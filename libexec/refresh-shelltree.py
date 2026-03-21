#!/usr/bin/env python3
"""Re-create the shelltree directory with random files."""

import random
import shutil
import string
from pathlib import Path

shutil.rmtree("shelltree", ignore_errors=True)
root = Path("shelltree")
bash = root / "bash"
zsh = root / "zsh"
tcsh = root / "tcsh"

bash.mkdir(parents=True, exist_ok=True)
zsh.mkdir(parents=True, exist_ok=True)
tcsh.mkdir(parents=True, exist_ok=True)

bash_profile = random.choice([".bash_profile", ".bash_login", ".profile"])


def create_random_files(path: Path, file: str):
    """Create random files for testing discovery of startup files."""
    # choose between 0 and 4 additional files, weighted toward 0 and 1
    for _ in range(random.choice([0] * 6 + [1] * 8 + [2] * 3 + [3] * 2 + [4])):
        tag = "".join(random.choices(string.ascii_letters, k=3))
        with open(path / f"{file}-{tag}", "w") as f:
            f.write(f"# {file}-{tag}\n")
            f.write(":\n")


for file in [
    ".bashrc",
    ".bash_logout",
] + [bash_profile]:
    with open(bash / file, "w") as f:
        f.write(f"# {file}\n")
        f.write(f"for f in ~/{file}-*; do\n")
        f.write("    source $f\n")
        f.write("done\n")

    create_random_files(bash, file)

for file in [
    ".zshenv",
    ".zshrc",
    ".zprofile",
    ".zlogin",
    ".zlogout",
]:
    with open(zsh / file, "w") as f:
        f.write(f"# {file}\n")
        f.write("export NULL_GLOB=1\n")
        f.write(f"for f in ~/{file}-*; do\n")
        f.write("    source $f\n")
        f.write("done\n")

    create_random_files(zsh, file)

with open(zsh / ".zshrc", "a") as f:
    f.write("# also test this mechanic\n")
    f.write("if [ -f $HOME/.zshlib/all ]; then\n")
    f.write("    source $HOME/.zshlib/all\n")
    f.write("fi\n")

zshlib = zsh / ".zshlib"
zshlib.mkdir(parents=True, exist_ok=True)
with open(zshlib / "all", "w") as f:
    f.write("# .zshlib/all from michael's home directory\n")
    f.write("for f in $HOME/.zshlib/*; do\n")
    f.write("    case ${f} in\n")
    f.write("        */all) continue;;")
    f.write("        *) source $f;;")
    f.write("    esac\n")
    f.write("done\n")

with open(zshlib / "mkcd", "w") as f:
    f.write("# .zshlib/mkcd from michael's home directory\n")
    f.write("function mkcd () {\n")
    f.write("    mkdir -p $1\n")
    f.write("    cd $1\n")
    f.write("}\n")

with open(zshlib / "py", "w") as f:
    f.write("# .zshlib/py from michael's home directory\n")
    f.write("py() {\n")
    f.write('    python3 "$@"\n')
    f.write("}\n")

for file in [
    ".tcshrc",
    ".cshrc",
    ".login",
]:
    with open(tcsh / file, "w") as f:
        f.write(f"# {file}\n")
        # tcsh expands globs before running ls; use nonomatch so an empty glob is not an error.
        f.write("set nonomatch\n")
        f.write(f"foreach _f ($HOME/{file}-*)\n")
        f.write("    if (-f $_f) source $_f\n")
        f.write("end\n")
        f.write("unset nonomatch\n")

    create_random_files(tcsh, file)
