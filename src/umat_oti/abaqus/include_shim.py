"""A directory where an Abaqus header answers to its name in any case.

Abaqus compiles user subroutines with ``-fpp``, so a source may carry a
preprocessor ``#include`` beside the Fortran ``INCLUDE`` statement. The two are
resolved by different machinery, and only one of them is case-insensitive about
it: ``INCLUDE 'ABA_PARAM.INC'`` works in every verified entry we have, while

    #INCLUDE <SMAASPUSERSUBROUTINES.HDR>

-- written that way at lines 848 and 1233 of ``UMAT_KLP_RK5_hybrid.f`` --
cannot be found on a case-sensitive filesystem, because Abaqus ships the file as
``SMAAspUserSubroutines.hdr`` and no uppercase variant exists anywhere in the
installation. The preprocessor does not find it, the build fails before Abaqus
writes anything at all, and the entry is recorded as though the author's code
were at fault.

The author's code is not at fault. Uppercase is how ``#INCLUDE`` is spelled in
fixed-form Fortran written to be read, it is what the compiler this source was
written for accepted, and the same file compiles with return code 0, unmodified,
against a directory that offers each shipped header under its own name and under
its uppercase name. So that is what this builds. The source is never touched;
only the search path the compiler is given grows.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

# Where Abaqus keeps the headers a user subroutine may include. Both are real
# directories in a 2021 installation and they do not hold the same files, so a
# shim built from one alone still leaves includes unresolved.
PUBLIC_INTERFACES = (
    "/usr/SIMULIA/EstProducts/2021/SMAUsubs/PublicInterfaces",
    "/usr/SIMULIA/EstProducts/2021/linux_a64/code/include",
)
SHIM_DIRECTORY = "include_any_case"
ENVIRONMENT_FILE = "abaqus_v6.env"


def header_directories(roots: Sequence[str] = ()) -> list[Path]:
    """The shipped header directories that exist on this machine.

    ``UMAT_OTI_ABAQUS_HEADERS`` overrides the search, so a machine with Abaqus
    somewhere else -- or a test with a directory of its own -- is not a machine
    where this silently does nothing. Several paths may be given, separated the
    way a PATH is.
    """
    named = os.environ.get("UMAT_OTI_ABAQUS_HEADERS")
    wanted = tuple(roots) or (tuple(named.split(os.pathsep)) if named
                              else PUBLIC_INTERFACES)
    return [Path(one) for one in wanted if one and Path(one).is_dir()]


def build(work_dir: Path, roots: Sequence[str] = ()) -> Path | None:
    """Link every shipped header under its own name and its uppercase name.

    Returns the directory, or None when no shipped headers were found -- in
    which case the caller adds no ``-I`` and the build behaves exactly as it
    did before, rather than pointing the compiler at an empty directory and
    changing which of two identically named headers wins.
    """
    directories = header_directories(roots)
    if not directories:
        return None

    shim = Path(work_dir) / SHIM_DIRECTORY
    shim.mkdir(parents=True, exist_ok=True)
    for directory in directories:
        for header in sorted(directory.iterdir()):
            if not header.is_file():
                continue
            for name in (header.name, header.name.upper()):
                link = shim / name
                # The first directory listed wins a name the second repeats,
                # which is the order the shipped -I flags already establish.
                if not link.exists() and not link.is_symlink():
                    link.symlink_to(header.resolve())
    return shim


def environment_text(shim: Path) -> str:
    """An Abaqus environment file that adds the shim to the compile line.

    Abaqus reads ``abaqus_v6.env`` from the directory the job is launched in,
    after the site file, and executes it as Python -- so ``compile_fortran`` is
    already bound to the shipped list. ``%P`` is the placeholder for the source
    file and ifort wants it last, so the flag goes in ahead of it rather than on
    the end.
    """
    quoted = repr(f"-I{Path(shim).resolve()}")
    return (
        "# Added by umat_oti: let a #INCLUDE written in uppercase resolve.\n"
        "# The shipped -I directories are kept and still searched; this one\n"
        "# only offers the same headers under a second spelling.\n"
        "try:\n"
        "    compile_fortran = (list(compile_fortran[:-1])\n"
        f"                       + [{quoted}]\n"
        "                       + list(compile_fortran[-1:]))\n"
        "except NameError:\n"
        "    pass\n"
    )


def install(work_dir: Path, roots: Sequence[str] = ()) -> Path | None:
    """Build the shim and write the environment file that points at it.

    An ``abaqus_v6.env`` already in the directory is appended to, never
    replaced: it may carry a caller's own settings, and dropping those to fix an
    include path would trade one silent build difference for another.
    """
    shim = build(work_dir, roots)
    if shim is None:
        return None

    where = Path(work_dir) / ENVIRONMENT_FILE
    existing = where.read_text(encoding="utf-8", errors="replace") if where.exists() else ""
    if f"-I{shim.resolve()}" in existing:
        return shim
    joined = (existing + "\n" if existing and not existing.endswith("\n") else existing)
    where.write_text(joined + environment_text(shim), encoding="utf-8")
    return shim
