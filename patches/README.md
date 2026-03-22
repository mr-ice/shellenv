# Patches for shellenv

## tcsh TCSH_XTRACEFD

Shell tracing for tcsh requires a patched tcsh that supports `TCSH_XTRACEFD` (analogous to bash's `BASH_XTRACEFD`). The full tcsh source tree is not checked in; only the patch and build instructions are.

### tcsh source

- **URL**: [tcsh source](https://github.com/tcsh-org/tcsh)
- **Patches**:
  - `tcsh-TCSH_XTRACEFD.patch` (required)
  - `tcsh-closem-preserve-xtracefd.patch` (required: otherwise `closem()` closes the xtrace fd)
  - `tcsh-xtrace-filepath.patch` (adds path/filename to trace output, like zsh)
  - `tcsh-allow-l-with-args.patch` (required so `-l` works with `-c` / `-i`)
  - `tcsh-sourcetrace.patch` (emits `+timestamp /path <sourcetrace>` when a file is sourced)

### Build patched tcsh

From the shellenv repo (clones into `tcsh-src/tcsh-git/`, patches, builds, copies binary to `tcsh-src/tcsh`):

```bash
cd /path/to/shellenv
make tcsh-src/tcsh
```

Manual build:

```bash
git clone https://github.com/tcsh-org/tcsh.git tcsh-src
cd tcsh-src
patch -p1 < /path/to/shellenv/patches/tcsh-TCSH_XTRACEFD.patch
patch -p1 < /path/to/shellenv/patches/tcsh-closem-preserve-xtracefd.patch
patch -p1 < /path/to/shellenv/patches/tcsh-xtrace-filepath.patch
patch -p1 < /path/to/shellenv/patches/tcsh-allow-l-with-args.patch
patch -p1 < /path/to/shellenv/patches/tcsh-sourcetrace.patch
./configure && make
```

The resulting `tcsh` binary is built in the source directory. Point shellenv at it via:

- `SHELLENV_TCSH_PATH=/path/to/tcsh-src/tcsh`
- Or pass `--shell-path` when running discover/trace for tcsh

## bash source trace (zsh SOURCE_TRACE analog)

Discovery needs to know **each file** bash reads (`source`, `.`, and startup files).
Stock bash only shows that indirectly via xtrace. This patch always emits one
line per file read through `_evalfile()`, in the same stream as xtrace (stderr
or `BASH_XTRACEFD`), shaped like shellenv’s parser expects:

`+0.000000 /absolute/path/to/file:1 <sourcetrace>`

There is no runtime toggle; use this binary only for tracing/discovery if you prefer.

- **URL**: [bash-5.2 tarball](https://ftp.gnu.org/gnu/bash/bash-5.2.tar.gz) (or git savannah bash)
- **Patch**: `bash-sourcetrace.patch`

### Build patched bash

From the shellenv repo (downloads `bash-$(BASH_VERSION).tar.gz`, unpacks under `bash-src/`, patches, builds, copies the binary to `bash-src/bash`):

```bash
cd /path/to/shellenv
make bash-src/bash
```

Manual build:

```bash
wget https://ftp.gnu.org/gnu/bash/bash-5.2.tar.gz
tar xzf bash-5.2.tar.gz && cd bash-5.2
patch -p1 < /path/to/shellenv/patches/bash-sourcetrace.patch
./configure && make
```

The `bash` binary is produced in the build tree (often `./bash`). Point shellenv at it via:

- `SHELLENV_BASH_PATH=/path/to/bash-5.2/bash`
- Or install/copy the binary to `bash-src/bash` at the shellenv project root
- Or pass `--shell-path` for trace commands

Optional: you can also apply `bash-xtrace-fileline.patch` if you want the default
PS4 to include file:line when `PS4` is not set from the environment.

### bash xtrace file:line (optional)

- **Patch**: `bash-xtrace-fileline.patch`

```bash
cd bash-5.2
patch -p1 < /path/to/shellenv/patches/bash-xtrace-fileline.patch
./configure && make
```

This changes the default PS4 to `+${BASH_SOURCE}:${LINENO}` so trace output includes path and line number when not overridden.
