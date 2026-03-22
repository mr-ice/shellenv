"""Backup, archive, and restore operations for shell startup files.

This module provides multi-file tar.gz archive operations with embedded
manifests.  Individual single-file backups (used by the TUI) remain in
``tui.py``; this module handles the higher-level archive workflow.

Public API
----------
get_backup_dir()
    Return the backup directory path, creating it if needed.
filter_files(files, include, exclude)
    Filter file paths by include/exclude fnmatch patterns.
create_backup(files, family, backup_dir)
    Create a tar.gz archive of the given files with a manifest.
create_archive(files, family, backup_dir)
    Create a backup and remove the originals.
list_archives(backup_dir)
    List available archives sorted newest-first.
read_manifest(archive_path)
    Extract and parse the manifest from an archive.
find_archive(substring, backup_dir)
    Find a unique archive by filename substring.
restore_from_archive(archive_path, target_dir, include, exclude, force)
    Extract files from an archive to the target directory.
"""

from __future__ import annotations

import io
import json
import os
import re
import socket
import sys
import tarfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

ARCHIVE_GLOB = "shellenv-backup-*.tar.gz"
ARCHIVE_RE = re.compile(r"shellenv-backup-(\d{8}T\d{6}Z)\.tar\.gz")
_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Backup directory
# ---------------------------------------------------------------------------


def get_backup_dir() -> Path:
    """Return the backup directory, creating it if needed.

    Uses the ``SHELLENV_BACKUP_DIR`` environment variable when set,
    otherwise defaults to ``~/.cache/shellenv/backups``.

    Returns
    -------
    Path
        The backup directory (guaranteed to exist).
    """
    backup_dir = Path(
        os.environ.get("SHELLENV_BACKUP_DIR") or Path.home() / ".cache" / "shellenv" / "backups"
    )
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------


def filter_files(
    files: list[str],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Filter absolute file paths by include/exclude glob patterns.

    Patterns are matched against the **basename** of each path using
    :func:`fnmatch.fnmatch`.

    Parameters
    ----------
    files : list[str]
        Absolute paths to candidate files.
    include : list[str] or None
        If provided, only files whose basename matches at least one
        pattern are kept.
    exclude : list[str] or None
        Files whose basename matches any pattern are removed.
        Applied after *include*.

    Returns
    -------
    list[str]
        Filtered list of absolute paths.
    """
    result = list(files)
    if include:
        result = [f for f in result if any(fnmatch(os.path.basename(f), pat) for pat in include)]
    if exclude:
        result = [
            f for f in result if not any(fnmatch(os.path.basename(f), pat) for pat in exclude)
        ]
    return result


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class BackupManifest:
    """Metadata stored inside each archive.

    Attributes
    ----------
    timestamp : str
        UTC timestamp in ``YYYYMMDDTHHMMSSZ`` format.
    family : str
        Shell family that was detected or specified.
    files : list[str]
        Paths relative to the home directory stored in the archive.
    hostname : str
        Machine hostname at time of backup.
    version : str
        shellenv version string.
    """

    timestamp: str
    family: str
    files: list[str]
    hostname: str
    version: str


def _manifest_to_bytes(manifest: BackupManifest) -> bytes:
    """Serialize a manifest to UTF-8 JSON bytes."""
    return json.dumps(asdict(manifest), indent=2).encode("utf-8")


def _manifest_from_bytes(data: bytes) -> BackupManifest:
    """Deserialize a manifest from JSON bytes."""
    d: dict[str, Any] = json.loads(data)
    return BackupManifest(
        timestamp=d["timestamp"],
        family=d["family"],
        files=d["files"],
        hostname=d["hostname"],
        version=d["version"],
    )


# ---------------------------------------------------------------------------
# Archive helpers
# ---------------------------------------------------------------------------


def _archive_filename(timestamp: str) -> str:
    """Return the archive filename for a given timestamp string."""
    return f"shellenv-backup-{timestamp}.tar.gz"


def _make_timestamp() -> str:
    """Return a UTC timestamp string for archive naming."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _validate_tar_member(name: str) -> bool:
    """Return True if a tar member name is safe (no traversal)."""
    if os.path.isabs(name):
        return False
    if ".." in name.split(os.sep):
        return False
    # Also check with forward slashes for cross-platform safety
    if ".." in name.split("/"):
        return False
    return True


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def create_backup(
    files: list[str],
    family: str,
    backup_dir: Path | None = None,
) -> Path:
    """Create a tar.gz archive of the given files.

    Files are stored with paths relative to ``$HOME``.  A
    ``manifest.json`` with metadata is embedded in the archive.

    Parameters
    ----------
    files : list[str]
        Absolute paths to files to back up.  Each must exist.
    family : str
        Shell family string for the manifest.
    backup_dir : Path or None
        Override backup directory.  Defaults to :func:`get_backup_dir`.

    Returns
    -------
    Path
        Path to the created archive.

    Raises
    ------
    ValueError
        If *files* is empty.
    FileNotFoundError
        If any file in *files* does not exist.
    """
    if not files:
        raise ValueError("no files to back up")

    for f in files:
        if not os.path.exists(f):
            raise FileNotFoundError(f"file not found: {f}")

    if backup_dir is None:
        backup_dir = get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    home = str(Path.home())
    timestamp = _make_timestamp()
    archive_path = backup_dir / _archive_filename(timestamp)

    rel_files: list[str] = []
    with tarfile.open(archive_path, "w:gz") as tar:
        for filepath in files:
            if filepath.startswith(home):
                arcname = os.path.relpath(filepath, home)
            else:
                arcname = os.path.basename(filepath)
            rel_files.append(arcname)
            tar.add(filepath, arcname=arcname)

        # Add manifest
        manifest = BackupManifest(
            timestamp=timestamp,
            family=family,
            files=rel_files,
            hostname=socket.gethostname(),
            version=_VERSION,
        )
        manifest_bytes = _manifest_to_bytes(manifest)
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

    return archive_path


def create_archive(
    files: list[str],
    family: str,
    backup_dir: Path | None = None,
) -> Path:
    """Back up files and then remove the originals.

    Parameters
    ----------
    files : list[str]
        Absolute paths to files to archive.
    family : str
        Shell family string for the manifest.
    backup_dir : Path or None
        Override backup directory.

    Returns
    -------
    Path
        Path to the created archive.

    Raises
    ------
    ValueError
        If *files* is empty.
    FileNotFoundError
        If any file does not exist.
    """
    archive_path = create_backup(files, family, backup_dir=backup_dir)

    for filepath in files:
        try:
            os.remove(filepath)
        except OSError as exc:
            print(f"warning: could not remove {filepath}: {exc}", file=sys.stderr)

    return archive_path


# ---------------------------------------------------------------------------
# Listing and lookup
# ---------------------------------------------------------------------------


def list_archives(backup_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Return available archives sorted newest-first.

    Parameters
    ----------
    backup_dir : Path or None
        Override backup directory.

    Returns
    -------
    list[tuple[str, Path]]
        Each tuple is ``(timestamp_str, archive_path)``.
    """
    if backup_dir is None:
        backup_dir = get_backup_dir()
    if not backup_dir.exists():
        return []

    results: list[tuple[str, Path]] = []
    for p in backup_dir.glob(ARCHIVE_GLOB):
        m = ARCHIVE_RE.match(p.name)
        if m:
            results.append((m.group(1), p))

    results.sort(key=lambda x: x[0], reverse=True)
    return results


def read_manifest(archive_path: Path) -> BackupManifest:
    """Extract and parse the manifest from an archive.

    Parameters
    ----------
    archive_path : Path
        Path to the tar.gz archive.

    Returns
    -------
    BackupManifest
        The parsed manifest.

    Raises
    ------
    KeyError
        If ``manifest.json`` is not in the archive.
    FileNotFoundError
        If *archive_path* does not exist.
    """
    with tarfile.open(archive_path, "r:gz") as tar:
        member = tar.getmember("manifest.json")
        f = tar.extractfile(member)
        if f is None:
            raise KeyError("manifest.json is not a regular file")
        return _manifest_from_bytes(f.read())


def find_archive(
    substring: str,
    backup_dir: Path | None = None,
) -> Path | None:
    """Find a unique archive whose filename contains *substring*.

    Parameters
    ----------
    substring : str
        Substring to match against archive filenames.
    backup_dir : Path or None
        Override backup directory.

    Returns
    -------
    Path or None
        The unique matching archive path, or ``None`` if no match.

    Raises
    ------
    ValueError
        If multiple archives match (message includes the matches).
    """
    archives = list_archives(backup_dir)
    matches = [(ts, p) for ts, p in archives if substring in p.name]

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0][1]
    names = [p.name for _, p in matches]
    raise ValueError(f"ambiguous match — {len(matches)} archives match '{substring}': {names}")


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore_from_archive(
    archive_path: Path,
    target_dir: Path | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    force: bool = False,
) -> list[str]:
    """Extract files from an archive to *target_dir*.

    Parameters
    ----------
    archive_path : Path
        Path to the tar.gz archive.
    target_dir : Path or None
        Base directory for extraction.  Defaults to ``Path.home()``.
    include : list[str] or None
        If set, only restore files matching these fnmatch patterns.
    exclude : list[str] or None
        Skip files matching these fnmatch patterns.
    force : bool
        If False, skip files that already exist at the target.
        If True, overwrite existing files.

    Returns
    -------
    list[str]
        Absolute paths of files that were restored.

    Raises
    ------
    FileNotFoundError
        If *archive_path* does not exist.
    ValueError
        If the archive contains unsafe member paths.
    """
    if not archive_path.exists():
        raise FileNotFoundError(f"archive not found: {archive_path}")

    if target_dir is None:
        target_dir = Path.home()

    manifest = read_manifest(archive_path)

    # Apply include/exclude filtering on the manifest file list
    candidates = filter_files(
        [str(target_dir / f) for f in manifest.files],
        include=include,
        exclude=exclude,
    )
    # Convert back to relative names for extraction
    candidate_rel = {os.path.relpath(c, target_dir) for c in candidates}

    restored: list[str] = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name == "manifest.json":
                continue
            if not _validate_tar_member(member.name):
                raise ValueError(f"unsafe archive member: {member.name!r}")
            if member.name not in candidate_rel:
                continue

            dest = target_dir / member.name
            if dest.exists() and not force:
                print(f"skipped (exists): {dest}", file=sys.stderr)
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                if src is not None:
                    dest.write_bytes(src.read())
            restored.append(str(dest))

    return restored
