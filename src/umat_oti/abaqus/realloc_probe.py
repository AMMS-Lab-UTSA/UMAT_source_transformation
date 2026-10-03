"""Whether a user-subroutine object needs ``for_realloc_lhs`` (Vera B10).

Abaqus jobs compile with ``-assume norealloc_lhs`` (include_shim.environment_text)
because the Fortran runtime Abaqus 2021 loads does not define
``for_realloc_lhs``: an object referencing it builds and then cannot be loaded
(ahartloper UVCplanestress). The flag changes the code only where the source
assigns to an allocatable. So that a reader can tell which builds the flag
actually changed, each job records whether the object compiled WITHOUT it --
the installation's own ``compile_fortran`` flags -- references the symbol.

The probe is a separate ``ifort -c`` of the same bundle into a scratch folder;
nothing it writes is used by the job.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence

#: The installation's site environment file, read for ``compile_fortran``.
SITE_ENV = "/usr/SIMULIA/EstProducts/2021/linux_a64/SMA/site/lnx86_64.env"
SYMBOL = "for_realloc_lhs"

_BLOCK = re.compile(r"^compile_fortran\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def shipped_compile_flags(site_env: str | Path = SITE_ENV) -> Optional[list[str]]:
    """The literal flags of the site file's ``compile_fortran`` list, without
    the compiler, ``-c``, ``-V``, the source placeholder and the -I entries
    (the caller supplies its own include path). None when not readable."""
    try:
        text = Path(site_env).read_text(errors="replace")
    except OSError:
        return None
    block = _BLOCK.search(text)
    if block is None:
        return None
    flags: list[str] = []
    for line in block.group(1).splitlines():
        line = line.split("#", 1)[0]
        # '-I'+abaHomeInc is an expression, not a flag of its own
        line = re.sub(r"'-I'\s*\+\s*\w+", "", line)
        for match in _QUOTED.finditer(line):
            flag = match.group(1) if match.group(1) is not None else match.group(2)
            if flag in ("-c", "-V", "%P") or flag.startswith("-I"):
                continue
            flags.append(flag)
    return flags


def probe(source: Path, out_dir: Path, include_dirs: Sequence[Path] = (), *,
          compiler: str = "ifort", site_env: str | Path = SITE_ENV,
          timeout: int = 600) -> dict:
    """Compile ``source`` with the shipped flags (no ``-assume
    norealloc_lhs``) and report whether the object references the symbol."""
    record: dict = {"symbol": SYMBOL, "references_for_realloc_lhs": None,
                    "flags_origin": f"compile_fortran of {site_env}, without "
                                    "-assume norealloc_lhs"}
    flags = shipped_compile_flags(site_env)
    if flags is None:
        record["reason"] = f"no compile_fortran list in {site_env}"
        return record
    if shutil.which(compiler) is None or shutil.which("nm") is None:
        record["reason"] = f"{compiler} or nm is not on PATH"
        return record
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obj = out_dir / (Path(source).stem + "_noflag.o")
    command = [compiler, "-c", *flags, *[f"-I{Path(d)}" for d in include_dirs],
               str(Path(source).resolve()), "-o", str(obj)]
    record["command"] = command
    try:
        done = subprocess.run(command, cwd=str(out_dir), capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        record["reason"] = f"{type(error).__name__}: {error}"
        return record
    if done.returncode != 0 or not obj.is_file():
        record["reason"] = f"the no-flag compile failed (exit {done.returncode})"
        record["log"] = (done.stdout + done.stderr)[-2000:]
        return record
    symbols = subprocess.run(["nm", "-u", str(obj)], capture_output=True, text=True).stdout
    undefined = sorted({line.split()[-1] for line in symbols.splitlines() if line.strip()})
    record["references_for_realloc_lhs"] = SYMBOL in undefined
    record["object_sha256"] = hashlib.sha256(obj.read_bytes()).hexdigest()
    return record
