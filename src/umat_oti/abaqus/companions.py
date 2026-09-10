"""Which other files a UMAT has to be compiled with, and whether they exist.

``abaqus job=... user=...`` compiles one file. A UMAT that opens with
``use Tensor`` or ``include 'ttb/ttb_library.f'`` is not one file, and handing
Abaqus only the entry source produces a compile that aborts before the analysis
starts -- no ``.sta``, no ``.msg``, no ``.odb``. The ladder read that as the
ORIGINAL failing to run, which names this harness rather than what happened.

What happened is one of two different things, and they are different findings:

* the companion is in the corpus cache beside the source, and nothing was
  compiling it. That is work to do here, and this module is the work: the
  units are ordered so a module is built before its users and handed to the
  job as one compilation unit, which is what Abaqus does with ``user=``.
* the companion was never published, or was published and not acquired. Then
  the entry is blocked on something outside this repository, and the record
  has to name the module or the file so a reader can go and look.

Resolution is by what a file DECLARES, never by its name. ``umat_module`` may
live in ``helpers.f90``; ``Tensor`` lives in ``ttb/ttb_library.f``. Matching on
filename would pair the wrong files and the link would then fail somewhere
less obvious.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

#: A ``USE`` statement. Fortran allows ``USE, INTRINSIC ::`` and a rename list;
#: only the module name is wanted. Anchored to the start of a statement so
#: ``because`` and ``house`` inside an expression are not module names.
_USE = re.compile(r"^\s*use\s*(?:,\s*(?:non_)?intrinsic\s*)?(?:::)?\s*"
                  r"([A-Za-z_]\w*)", re.IGNORECASE)

#: A Fortran ``INCLUDE`` line and the preprocessor's ``#include``. Abaqus
#: compiles with ``-fpp``, so both reach the file.
_INCLUDE = re.compile(r"""^\s*(?:\#\s*)?include\s*['"<]([^'">]+)['">]""",
                      re.IGNORECASE)

#: A module definition. ``MODULE PROCEDURE`` inside an interface block is not
#: one, and neither is ``END MODULE``.
_MODULE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)\s*(?:!.*)?$", re.IGNORECASE)

#: Modules Abaqus itself provides. Asking the corpus for them finds nothing and
#: reports a blocker that is not one.
ABAQUS_MODULES = frozenset()

#: Includes Abaqus itself provides, matched case-insensitively because half the
#: corpus writes ABA_PARAM.INC and the file on disk is aba_param.inc.
ABAQUS_INCLUDES = frozenset({
    "aba_param.inc", "aba_evs_param.inc", "aba_globalvar.inc",
    "aba_tcs_param.inc", "aba_ptk_enums.inc", "aba_phcon_param.inc",
    "smaaspusersubroutines.hdr", "smaaspuserarrays.hdr",
    "smaaspuserutilities.hdr", "smaasusersubroutines.hdr",
    "smaaspnumericlimits.hdr", "vaba_param.inc",
})


@dataclass(frozen=True)
class Needs:
    """What one source asks for beyond itself."""

    modules: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"modules": list(self.modules), "includes": list(self.includes)}


def _statements(text: str) -> Iterable[str]:
    """Lines that could carry a statement, comments and strings aside.

    Fixed and free form both. A fixed-form comment marker is in column 1; a
    free-form one is the first non-blank character.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] == "!" or line[0] in "cC*":
            continue
        yield line


def modules_defined(text: str) -> tuple[str, ...]:
    """The modules this source defines, upper-cased.

    Line by line, over the lines that could carry a statement. Running the
    pattern over the whole text needs re.MULTILINE to mean anything, and
    without it ``findall`` matched nothing at all -- so every module in the
    corpus looked undefined and every source that used one looked externally
    blocked.
    """
    found = set()
    for line in _statements(text):
        match = _MODULE.match(line.rstrip())
        if match:
            found.add(match.group(1).upper())
    return tuple(sorted(found))


def needs(text: str) -> Needs:
    """The modules and include files this source cannot compile without.

    A module DEFINED in the same file is not a need: many sources carry their
    own module above the UMAT that uses it.
    """
    defined = set(modules_defined(text))
    modules, includes = [], []
    for line in _statements(text):
        found = _USE.match(line)
        if found:
            name = found.group(1)
            if (name.upper() not in defined
                    and name.upper() not in {m.upper() for m in ABAQUS_MODULES}
                    and name.upper() not in {m.upper() for m in modules}):
                modules.append(name)
            continue
        found = _INCLUDE.match(line)
        if found:
            name = found.group(1).strip()
            if (Path(name).name.lower() not in ABAQUS_INCLUDES
                    and name not in includes):
                includes.append(name)
    return Needs(tuple(modules), tuple(includes))


@dataclass
class Resolution:
    """Which companions were found, in what order, and what was not found."""

    #: Files to compile before the entry source, dependencies first.
    order: tuple[Path, ...] = ()
    #: Include files to place beside the entry source, by the name it asks for.
    include_files: dict = field(default_factory=dict)
    #: Modules nothing in the search set defines.
    missing_modules: tuple[str, ...] = ()
    #: Include files nothing in the search set provides.
    missing_includes: tuple[str, ...] = ()
    #: What was searched, for the record.
    searched: int = 0

    @property
    def complete(self) -> bool:
        return not (self.missing_modules or self.missing_includes)

    def as_dict(self) -> dict:
        return {"order": [str(p) for p in self.order],
                "include_files": {k: str(v) for k, v in self.include_files.items()},
                "missing_modules": list(self.missing_modules),
                "missing_includes": list(self.missing_includes),
                "searched": self.searched}

    def reason(self) -> str:
        if self.complete:
            return (f"every companion is in the cache: {len(self.order)} unit(s) "
                    f"to compile first and {len(self.include_files)} include "
                    f"file(s) to place beside the source"
                    if (self.order or self.include_files)
                    else "this source needs no companion")
        missing = ([f"module {name}" for name in self.missing_modules]
                   + [f"include file {name}" for name in self.missing_includes])
        return (f"{', '.join(missing)} is not in the {self.searched} file(s) "
                f"this source's repository published to the cache, so the "
                f"source cannot be compiled as its author compiled it")


def resolve(entry: Path, candidates: Sequence[Path],
            *, depth: int = 8) -> Resolution:
    """Everything ``entry`` needs, found among ``candidates`` by what they declare.

    Transitive: a module the entry uses may itself use another. ``depth``
    bounds the walk, because a cycle between two modules is a thing authors
    write and this must terminate rather than diagnose it.
    """
    candidates = [Path(path) for path in candidates
                  if Path(path).resolve() != Path(entry).resolve()]
    texts: dict[Path, str] = {}
    for path in candidates:
        try:
            texts[path] = path.read_text(errors="replace")
        except OSError:
            continue

    provides: dict[str, Path] = {}
    for path, text in texts.items():
        for name in modules_defined(text):
            provides.setdefault(name, path)

    by_name: dict[str, Path] = {}
    for path in texts:
        by_name.setdefault(path.name.lower(), path)

    entry_text = Path(entry).read_text(errors="replace")
    ordered: list[Path] = []
    includes: dict[str, Path] = {}
    missing_modules: list[str] = []
    missing_includes: list[str] = []
    seen_files: set[Path] = set()
    seen_modules: set[str] = set()

    def walk(text: str, level: int) -> None:
        if level > depth:
            return
        wanted = needs(text)
        for name in wanted.modules:
            key = name.upper()
            if key in seen_modules:
                continue
            seen_modules.add(key)
            provider = provides.get(key)
            if provider is None:
                missing_modules.append(name)
                continue
            if provider in seen_files:
                continue
            seen_files.add(provider)
            walk(texts[provider], level + 1)      # dependencies first
            ordered.append(provider)
        for name in wanted.includes:
            if name in includes or name in missing_includes:
                continue
            found = by_name.get(Path(name).name.lower())
            if found is None:
                missing_includes.append(name)
                continue
            includes[name] = found
            walk(texts[found], level + 1)

    walk(entry_text, 0)
    # A file pulled in by INCLUDE is compiled as part of whatever includes it.
    # ttb_library.f is both: umat_nh_ttb.f includes it at file scope AND uses
    # the module it defines. Compiling it separately as well defines that
    # module twice and the link fails on every symbol in it.
    included = {path.resolve() for path in includes.values()}
    ordered = [path for path in ordered if path.resolve() not in included]
    return Resolution(tuple(ordered), includes, tuple(missing_modules),
                      tuple(missing_includes), len(candidates))


def repository_files(source: Path, cache_root: Path,
                     suffixes: Sequence[str] = (".f", ".for", ".f90", ".f95",
                                                ".f03", ".f08", ".ftn", ".inc",
                                                ".h", ".hdr", ".fi")
                     ) -> tuple[Path, ...]:
    """Every compilable or includable file the source's own repository cached.

    Scoped to the repository, which is the first path component under the cache
    root. A module named ``utils`` exists in more than one repository in this
    corpus, and compiling somebody else's is worse than not compiling one.
    """
    source, cache_root = Path(source), Path(cache_root)
    try:
        relative = source.resolve().relative_to(Path(cache_root).resolve())
    except ValueError:
        return ()
    if not relative.parts:
        return ()
    root = Path(cache_root) / relative.parts[0]
    wanted = {s.lower() for s in suffixes}
    return tuple(sorted(path for path in root.rglob("*")
                        if path.is_file() and path.suffix.lower() in wanted))
