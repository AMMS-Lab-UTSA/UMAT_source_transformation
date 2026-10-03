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
import re
from pathlib import Path
from typing import Callable, Optional, Sequence

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
        "# -assume norealloc_lhs: ifort 2021 otherwise emits calls to\n"
        "# for_realloc_lhs for an allocatable assignment, which the Fortran\n"
        "# runtime Abaqus 2021 loads does not define; the library then fails\n"
        "# to load and the job dies before its first increment (measured on\n"
        "# ahartloper UVCplanestress). A source with no allocatable assignment\n"
        "# compiles to the same code either way.\n"
        "try:\n"
        "    compile_fortran = (list(compile_fortran[:-1])\n"
        f"                       + [{quoted}, '-assume', 'norealloc_lhs']\n"
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


#: ``INCLUDE 'name'`` (Fortran) and ``#include "name"`` / ``<name>`` (fpp).
_INCLUDE_STATEMENT = re.compile(
    r"^\s*(?:\d+\s+)?INCLUDE\s+['\"]([^'\"]+)['\"]"
    r"|^\s*#\s*include\s+[\"<]([^\">]+)[\">]",
    re.IGNORECASE | re.MULTILINE)


def included_names(text: str) -> list[str]:
    """Every file a source INCLUDEs, as spelled, first occurrence first."""
    names = []
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if line[:1] in "cC*" or stripped.startswith("!"):
            continue
        found = _INCLUDE_STATEMENT.match(line)
        if found:
            name = found.group(1) or found.group(2)
            if name not in names:
                names.append(name)
    return names


def _find(name: str, directory: Path) -> tuple[Path | None, str]:
    """``name`` resolved against ``directory``: exactly, or case-insensitively
    when exactly one entry of its folder matches (what a case-insensitive
    filesystem -- the author's, by the evidence -- would have opened)."""
    candidate = Path(directory) / name
    if candidate.is_file():
        return candidate, "exact"
    folder = candidate.parent
    if not folder.is_dir():
        return None, ""
    matches = [entry for entry in folder.iterdir()
               if entry.is_file() and entry.name.lower() == candidate.name.lower()]
    if len(matches) == 1:
        return matches[0], "case-insensitive"
    return None, "ambiguous" if matches else ""


#: The Abaqus parameter header, in every casing: never staged from beside a
#: source -- the build installs the installation's (or the quad stub), and a
#: link here would let that write go through to the author's file.
_ABAQUS_HEADER = "aba_param.inc"


def _refusal(name: str) -> str:
    """Why an INCLUDE name is not staged, or "" when it may be."""
    spelled = Path(name)
    if spelled.is_absolute() or name.startswith("~"):
        return "absolute include path: names a file outside the source tree, not staged"
    if ".." in spelled.parts:
        return "include path climbs out of its directory (..), not staged"
    return ""


def _sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def stage_includes(text: str, search: Sequence[Path], shim: Path, *,
                   convert: Optional[Callable[[str], str]] = None,
                   conversion: str = "") -> list[dict]:
    """Make every file the source INCLUDEs resolvable from the job.

    Abaqus compiles the user file in a scratch directory of its own, so an
    INCLUDE that names a file beside the author's source (``INCLUDE
    './UMAT_MODEL.f'``, davidmorin V_UMAT) is not found there; and on Linux
    ``INCLUDE 'PARAM_UMAT.INC'`` does not open ``param_umat.inc``
    (jpsferreira), which the author's filesystem did. Each name is looked up
    in ``search`` in order (the ORIGINAL source's directory first): exactly,
    then case-insensitively when one file matches; the file is linked into
    ``shim`` (already on the compiler's -I path) under the name as spelled.
    Shipped Abaqus headers already in the shim are left alone, and so is
    ``aba_param.inc`` (the build installs it). An absolute name or one with
    ``..`` is refused (Vera B10 condition B). Files the staged files include
    are staged too, looked up beside them first.

    ``convert`` (Vera B10 condition A): a staged file is not linked but
    written through ``convert`` -- the quad replay promotes an include as it
    promotes the source, so the reference is not mixed-precision. Each
    record carries the sha256 of the author's file and of what was staged.
    """
    staged: list[dict] = []
    seen: set[str] = set()
    pending = [(text, list(search))]
    while pending:
        current, directories = pending.pop(0)
        for name in included_names(current):
            if name in seen:
                continue
            seen.add(name)
            spelled = Path(name)
            if spelled.name.lower() == _ABAQUS_HEADER:
                continue
            refused = _refusal(name)
            if refused:
                staged.append({"include": name, "found": False, "refused": True,
                               "reason": refused})
                continue
            target = Path(shim) / (spelled.name if str(spelled.parent) in (".", "")
                                   else spelled)
            if target.is_symlink() and str(target.resolve()).startswith(tuple(
                    str(d) for d in header_directories())):
                continue                                   # a shipped header
            found, how = None, ""
            for directory in directories:
                found, how = _find(name, Path(directory))
                if found is not None:
                    break
            if found is None:
                staged.append({"include": name, "found": False, "reason": how or "not found"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            data = found.read_bytes()
            record = {"include": name, "found": True, "from": str(found), "match": how,
                      "sha256": _sha256(data)}
            if convert is not None:
                converted = convert(data.decode("utf-8", errors="replace"))
                target.write_text(converted, encoding="utf-8")
                record.update(staged_as="converted copy", conversion=conversion or "converted",
                              staged_sha256=_sha256(converted.encode("utf-8")))
            else:
                target.symlink_to(found.resolve())
                record.update(staged_as="link", staged_sha256=record["sha256"])
            staged.append(record)
            pending.append((data.decode("utf-8", errors="replace"),
                            [found.parent, *directories]))
    return staged
