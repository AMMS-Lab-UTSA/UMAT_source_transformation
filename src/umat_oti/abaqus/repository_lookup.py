"""Which of a source's callees, modules and includes are published in its repository.

THE RULE (B17 G3a, written before it was run; the same words are in the commit
and in corpus_campaign/batches/B17/lovelace/RULE_G3a.md):

    A callee that is not in the repository and not an Abaqus utility is
    external; one that is in the repository is resolved.

"The repository" is the acquisition's copy of the SAME repository the source
came from (``owner__repo`` under the discovery cache), the whole tree. A name is
in it when some file of it DECLARES that name -- ``SUBROUTINE``, ``FUNCTION``,
``ENTRY`` or ``MODULE`` -- or, for an ``INCLUDE``, when a file of that name
exists. Never by a guess, and never from another repository.

What is looked up, for a source and for every file its own lookups pull in
(transitively, because a module the entry uses may use another and an included
file may CALL a routine that is two files away):

* ``USE`` modules and ``INCLUDE`` / ``#include`` files that are not the
  compiler's, Fortran's or Abaqus's own (:mod:`umat_oti.abaqus.companions`);
* ``CALL`` targets, ``EXTERNAL`` names, and the callees the transformer's own
  refusal names ("reached external or undefined callee X", "requires source
  definitions for [..]", "passed to X", "delegates its whole body to X");
* not type-bound calls (``CALL obj%method``), which are not global routines.

What is never looked up, because it is not a published dependency: the Abaqus
utility routines and includes, Fortran's intrinsic subroutines and the vendor
timing library, and names the file itself declares. A routine from a numerical
library (BLAS, LAPACK) is not an Abaqus utility, so when the repository does not
publish it, it is external under the rule; it is reported under its own
heading so a reader can see how many sources that touches.

This module decides nothing about the gate. It answers "is it in the
repository?" and the registry decides what follows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from umat_oti.abaqus.companions import ABAQUS_INCLUDES, modules_defined, needs
from umat_oti.fortran.normalize import detect_source_form

__all__ = ["RULE", "ABAQUS_UTILITIES", "INTRINSIC_AND_VENDOR_CALLS", "LIBRARY_ROUTINES",
           "Lookup", "lookup", "names_in_refusal", "repository_index", "declared_names",
           "call_targets"]

RULE = ("A callee that is not in the repository and not an Abaqus utility is "
        "external; one that is in the repository is resolved.")

#: The Abaqus-supplied utility routines a user subroutine may call. These are
#: the solver's own, linked at run time; nothing in a repository defines them.
ABAQUS_UTILITIES = frozenset({
    "XIT", "XPLB_ABQERR", "XPLB_EXIT", "STDB_ABQERR", "STDB_ABQPRT",
    "GETOUTDIR", "GETJOBNAME", "GETNUMCPUS", "GETRANK", "GETNUMTHREADS",
    "GETTHREADID", "GET_THREAD_ID", "GETPARTINFO", "GETLOCALDIR", "GETCOMMANDLINE",
    "SINV", "SPRINC", "SPRIND", "ROTSIG", "GETVRM", "GETVRMAVGATINTPT",
    "GETNODETOELEMCONN", "MUTEXINIT", "MUTEXLOCK", "MUTEXUNLOCK",
    "MPI_GETSTATUS", "SIGINI", "SDVINI", "VGETVRM",
    # fil-file and output-database utilities Abaqus documents for user code
    "VGETOUTDIR", "VGETJOBNAME", "VGETRANK", "VGETNUMCPUS", "VGETPARTINFO",
    # documented Abaqus table-collection and Ptk event-series utilities (the
    # source includes Abaqus's own PtkUtilitySubs.hdr to call them), and the
    # routines declared in Abaqus 2021's SMAUsubs/PublicInterfaces/*.hdr
    "SETTABLECOLLECTION", "GETPARAMETERTABLE", "GETPROPERTYTABLE",
    "PTKGETDATAACCESS", "PTKGETNUMINTERSECTEDELEMENTS", "GETCOMMUNICATOR",
    "SMAASPNUMERICLIMITSINTMAX", "SMAASPNUMERICLIMITSINTMIN",
    "SMAASPNUMERICLIMITSSIGNANDBL", "SMAASPNUMERICLIMITSSIGNANFLT",
    "POSFIL", "DBFILE", "STDB_GETRANKSIZE", "FILEOUT", "FLUSHBUFFER",
})

#: Ptk routines called beside the confirmed ones that no Abaqus header or
#: reference this project holds declares (Vera, B17): neither resolved nor
#: external, so they never make a source external; reported as unconfirmed.
UNCONFIRMED_UTILITIES = frozenset({
    "PTKSETMESHANDEVENTSERIES", "PTKSETEVENTSERIESPROPERTIES", "PTKCOMPUTE",
    "GETEVENTSERIESSLICEPROPERTIES", "GETEVENTSERIESSLICELG"})

#: Fortran intrinsic subroutines and the vendor timing/OS library every
#: Fortran 90 compiler the corpus is built with supplies. Not repository code.
INTRINSIC_AND_VENDOR_CALLS = frozenset({
    "CPU_TIME", "DATE_AND_TIME", "SYSTEM_CLOCK", "RANDOM_NUMBER", "RANDOM_SEED",
    "GET_COMMAND", "GET_COMMAND_ARGUMENT", "GET_ENVIRONMENT_VARIABLE", "MVBITS",
    "MOVE_ALLOC", "EXECUTE_COMMAND_LINE", "EXIT", "ABORT", "FLUSH", "GETENV",
    "SYSTEM", "SLEEP", "DTIME", "ETIME", "SECOND", "TIMEF", "ITIME", "IDATE",
    "FDATE", "CLOCK", "TIME", "GETARG", "IARGC", "GETCWD", "CHDIR", "SIGNAL",
    "OMP_SET_NUM_THREADS", "OMP_SET_LOCK", "OMP_UNSET_LOCK", "OMP_INIT_LOCK",
    "OMP_DESTROY_LOCK", "OMP_GET_NUM_THREADS", "OMP_GET_THREAD_NUM",
    "MPI_INIT", "MPI_FINALIZE", "MPI_COMM_RANK", "MPI_COMM_SIZE", "MPI_BARRIER",
    "MPI_ABORT", "C_F_POINTER", "C_F_PROCPOINTER", "IEEE_GET_FLAG",
    "IEEE_SET_FLAG", "IEEE_GET_STATUS", "IEEE_SET_STATUS", "IEEE_SET_HALTING_MODE",
    "SHARE_VARIABLES",
})

#: BLAS / LAPACK style names. Not Abaqus utilities: external under the rule when
#: the repository does not publish them. Listed so they can be counted apart.
LIBRARY_ROUTINES = re.compile(
    r"^(?:[SDCZ](?:GE|SY|PO|GB|GT|TR|OR|SP|HE|PT|TB|PB|SB|GG|HP|TP|UN)[A-Z0-9]{2,3}"
    r"|[SDCZ](?:AXPY|COPY|DOT[CU]?|NRM2|SCAL|SWAP|ROT[G]?|ASUM|AMAX|NORM)|I[SDCZ]AMAX"
    r"|MKL_\w+|DFTI_\w+|LAP\w*|XERBLA)$")

_STRING = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")
_CALL = re.compile(r"(?<![A-Za-z0-9_%])call\s+([A-Za-z_]\w*)\s*(%?)", re.IGNORECASE)
_EXTERNAL = re.compile(r"^\s*external\b\s*(?:::)?\s*(.+)$", re.IGNORECASE)
_PROCEDURE_DECL = re.compile(r"^\s*procedure\s*\([^)]*\)[^:]*::\s*(.+)$", re.IGNORECASE)
_UNIT = re.compile(
    r"^\s*(?:\d+\s+)?(?:(?:recursive|pure|elemental|impure|module)\s+)*"
    r"(?:(?P<sub>subroutine|entry)\s+(?P<sname>[A-Za-z_]\w*)\s*(?:\((?P<sargs>[^)]*)\))?"
    r"|(?:[A-Za-z0-9_*()=,\s]*?\b)?function\s+(?P<fname>[A-Za-z_]\w*)\s*(?:\((?P<fargs>[^)]*)\))?)",
    re.IGNORECASE)
#: ``MODULE PROCEDURE name`` outside an interface block defines ``name`` (a
#: submodule's implementation of a module procedure).
_MODULE_PROCEDURE = re.compile(r"^\s*module\s+procedure\s+([A-Za-z_]\w*)", re.IGNORECASE)
#: ``INTERFACE name`` declares a generic name (a call to it resolves to one of
#: the module procedures listed inside); ``OPERATOR(..)``, ``ASSIGNMENT(=)`` and
#: the I/O generics are not callable names.
_GENERIC = re.compile(r"^\s*(?:abstract\s+)?interface\s+([A-Za-z_]\w*)\s*$", re.IGNORECASE)
_END_UNIT = re.compile(r"^\s*(?:\d+\s+)?end\s*(?:subroutine|function|procedure)\b", re.IGNORECASE)
_END = re.compile(r"^\s*(?:\d+\s+)?end\b", re.IGNORECASE)
_INTERFACE = re.compile(r"^\s*(?:abstract\s+)?interface\b", re.IGNORECASE)
_END_INTERFACE = re.compile(r"^\s*end\s*interface\b", re.IGNORECASE)
_FREEFORM = re.compile(r"^\s*!\s*(?:dir|dec)\$\s*(no)?freeform\b", re.IGNORECASE)


def _segments(text: str, form: str):
    """``(text, form)`` pieces of a file, split at ``!DIR$ FREEFORM`` switches.

    Intel's directive switches the rest of the file to free form (and
    ``NOFREEFORM`` back); a fixed-form UMAT followed by free-form helpers is
    one file of this corpus (thatliuyang UMAT_comp_failure.for). Line numbers
    are not needed here, so the pieces are simply concatenated by form.
    """
    current, buffer, pieces = form, [], []
    for line in text.splitlines():
        directive = _FREEFORM.match(line)
        if directive:
            if buffer:
                pieces.append(("\n".join(buffer), current))
                buffer = []
            current = "fixed" if directive.group(1) else "free"
            continue
        buffer.append(line)
    if buffer:
        pieces.append(("\n".join(buffer), current))
    return pieces


def _statements(text: str, form: str) -> Iterable[str]:
    """Logical statements (continuations joined, comments removed), strings blanked."""
    from umat_oti.fortran.parser import logical_lines_from_text
    for piece, piece_form in _segments(text, form):
        for logical in logical_lines_from_text(_STRING.sub("''", piece), piece_form):
            if logical.text.strip():
                yield logical.text


def _split_args(arguments: Optional[str]) -> tuple:
    return tuple(a.strip().upper() for a in (arguments or "").split(",")
                 if re.fullmatch(r"\s*[A-Za-z_]\w*\s*", a or ""))


def declared_names(text: str, form: str = "fixed") -> frozenset:
    """Upper-case names of the subprograms and modules this text defines.

    Procedures declared inside an ``INTERFACE`` block are declarations of
    something defined elsewhere, not definitions; ``MODULE PROCEDURE x``
    outside one is the definition of ``x``.
    """
    names = set(modules_defined(text))
    depth = 0
    for code in _statements(text, form):
        if _END_INTERFACE.match(code):
            depth = max(0, depth - 1)
            continue
        if _INTERFACE.match(code):
            generic = _GENERIC.match(code)
            if generic and generic.group(1).lower() not in ("operator", "assignment"):
                names.add(generic.group(1).upper())
            depth += 1
            continue
        if depth:
            continue
        module_procedure = _MODULE_PROCEDURE.match(code)
        if module_procedure:
            names.add(module_procedure.group(1).upper())
            continue
        if _END.match(code):
            continue
        found = _UNIT.match(code)
        if found:
            names.add((found.group("sname") or found.group("fname")).upper())
    return frozenset(names)


def call_targets(text: str, form: str = "fixed") -> tuple:
    """Upper-case CALL / EXTERNAL names, in order of first appearance.

    Left out: ``CALL obj%method(...)`` (type-bound, not a global routine); a
    name that is a dummy argument of the subprogram making the call, or a
    procedure pointer / dummy procedure the subprogram declares (the caller
    supplies the routine; nothing is looked up for it).
    """
    seen: dict = {}
    dummies: set = set()
    local_procedures: set = set()
    depth = 0
    for code in _statements(text, form):
        if _END_INTERFACE.match(code):
            depth = max(0, depth - 1)
            continue
        if _INTERFACE.match(code):
            depth += 1
            continue
        if depth:
            continue
        unit = _UNIT.match(code)
        if unit and not _END.match(code):
            dummies = set(_split_args(unit.group("sargs") or unit.group("fargs")))
            local_procedures = set()
            continue
        if _END_UNIT.match(code):
            dummies, local_procedures = set(), set()
            continue
        declared = _PROCEDURE_DECL.match(code)
        if declared:
            local_procedures.update(re.findall(r"[A-Za-z_]\w*", declared.group(1).split("=")[0]))
            local_procedures = {n.upper() for n in local_procedures}
        for match in _CALL.finditer(code):
            name = match.group(1).upper()
            if match.group(2) != "%" and name not in dummies and name not in local_procedures:
                seen.setdefault(name, None)
        external = _EXTERNAL.match(code)
        if external:
            for name in re.split(r"[,\s]+", external.group(1)):
                if re.fullmatch(r"[A-Za-z_]\w*", name or "") and name.upper() not in dummies:
                    seen.setdefault(name.upper(), None)
    return tuple(seen)


_REFUSAL_NAME_PATTERNS = (
    re.compile(r"requires source definitions for \[([^\]]*)\]"),
    re.compile(r"reached external or undefined callee ([A-Za-z_]\w*)"),
    re.compile(r"is passed to ([A-Za-z_]\w*)[ ,]"),
    re.compile(r"delegates its whole body to ([A-Za-z_]\w*)"),
)


def names_in_refusal(reason: str) -> tuple:
    """The callee names the transformer's refusal itself says it needed."""
    found: dict = {}
    for pattern in _REFUSAL_NAME_PATTERNS:
        for match in pattern.finditer(reason or ""):
            for name in re.findall(r"[A-Za-z_]\w+", match.group(1)):
                name = name.upper()
                # the transformer's own renamed copies are not the author's names
                found.setdefault(name[:-4] if name.endswith("_OTI") else name, None)
    return tuple(found)


_SUFFIXES = {".f", ".for", ".f90", ".f95", ".f03", ".f08", ".ftn", ".f77",
             ".inc", ".h", ".hdr", ".fi", ".fh", ".i"}


@dataclass
class RepositoryIndex:
    """What one repository declares: names to files, file names to files."""

    root: Path
    by_declared: dict = field(default_factory=dict)
    by_filename: dict = field(default_factory=dict)
    texts: dict = field(default_factory=dict)
    forms: dict = field(default_factory=dict)
    files: int = 0


_INDEXES: dict = {}


def repository_index(root: Path) -> RepositoryIndex:
    """Index every Fortran-ish file under ``root`` by what it declares."""
    root = Path(root)
    key = str(root.resolve())
    cached = _INDEXES.get(key)
    if cached is not None:
        return cached
    index = RepositoryIndex(root=root)
    for path in sorted(root.rglob("*")) if root.is_dir() else ():
        if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        form = detect_source_form(path, text)
        index.files += 1
        index.texts[path] = text
        index.forms[path] = form
        index.by_filename.setdefault(path.name.lower(), []).append(path)
        for name in declared_names(text, form):
            index.by_declared.setdefault(name, []).append(path)
    if len(_INDEXES) > 4:                          # pragma: no cover - bound
        _INDEXES.clear()
    _INDEXES[key] = index
    return index


@dataclass
class Lookup:
    """The answer for one source."""

    source: Path
    #: name -> repository-relative file that declares it, for what was found
    resolved: dict = field(default_factory=dict)
    #: names (as ``call X`` / ``module X`` / ``include X``) no file of the
    #: repository declares and no Abaqus facility supplies
    unpublished: tuple = ()
    #: the subset of ``unpublished`` that is a BLAS/LAPACK-style routine
    unpublished_library: tuple = ()
    #: unconfirmed Ptk names (see UNCONFIRMED_UTILITIES): not counted either way
    unconfirmed: tuple = ()
    #: files of the repository the lookups pulled in, in discovery order
    companions: tuple = ()
    files_searched: int = 0

    @property
    def verdict(self) -> str:
        """``external`` when anything is unpublished, else ``resolved``."""
        return "external" if self.unpublished else "resolved"

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "unpublished": list(self.unpublished),
                "unpublished_library": list(self.unpublished_library),
                "unconfirmed": list(self.unconfirmed),
                "resolved": dict(self.resolved), "companions": list(self.companions),
                "files_searched": self.files_searched, "rule": RULE}


#: Modules the compiler, Fortran or the MPI/OpenMP runtimes supply.
_COMPILER_MODULES = frozenset({
    "iso_c_binding", "iso_fortran_env", "ieee_arithmetic", "ieee_exceptions",
    "ieee_features", "omp_lib", "omp_lib_kinds", "mpi", "mpi_f08", "openacc",
    "ifport", "ifcore", "dfport", "dflib", "kernel32", "mkl95_lapack",
    "mkl95_blas", "mkl95_precision", "f95_precision", "lapack95", "blas95"})


def lookup(source: Path, cache_root: Path, *, reason: str = "",
           depth: int = 12) -> Lookup:
    """Apply the rule to ``source`` (a file under ``cache_root/owner__repo``).

    ``reason`` is the transformer's refusal text, if any: the callee names it
    reports are looked up as well as the CALL statements the file contains.
    """
    source, cache_root = Path(source), Path(cache_root)
    relative = source.resolve().relative_to(cache_root.resolve())
    index = repository_index(cache_root / relative.parts[0])

    def text_of(path: Path):
        if path not in index.texts:
            try:
                index.texts[path] = path.read_text(errors="replace")
            except OSError:
                return None
            index.forms[path] = detect_source_form(path, index.texts[path])
        return index.texts[path]

    if text_of(source) is None:
        return Lookup(source=source)
    result = Lookup(source=source, files_searched=index.files)
    defined: set = set()
    closure = [source]
    seen = {source.resolve()}
    files: list = [(source, 0)]
    names: dict = {n: None for n in names_in_refusal(reason)}
    asked: set = set()
    unpublished: dict = {}
    unconfirmed: dict = {}

    def rel(path: Path) -> str:
        return str(path.relative_to(cache_root))

    def pull(label: str, name: str, candidates: Sequence[Path], level: int) -> None:
        if (label, name) in asked:
            return
        asked.add((label, name))
        if not candidates:
            unpublished.setdefault(f"{label} {name}", None)
            return
        result.resolved.setdefault(f"{label} {name}", rel(candidates[0]))
        for path in candidates:
            if path.resolve() not in seen:
                seen.add(path.resolve())
                closure.append(path)
                files.append((path, level + 1))

    while files or names:
        while files:
            path, level = files.pop(0)
            body = text_of(path)
            if body is None or level > depth:
                continue
            form = index.forms[path]
            defined.update(declared_names(body, form))
            wants = needs(body)
            for module in wants.modules:
                if module.lower() in _COMPILER_MODULES:
                    continue
                pull("module", module,
                     [p for p in index.by_declared.get(module.upper(), ())
                      if module.upper() in modules_defined(text_of(p) or "")], level)
            for include in wants.includes:
                base = Path(include).name.lower()
                if base in ABAQUS_INCLUDES:
                    continue
                near = sorted(index.by_filename.get(base, ()),
                              key=lambda p: (0 if p.parent == path.parent else 1,
                                             len(p.parts), str(p)))
                pull("include", include, near[:1], level)
            for name in call_targets(body, form):
                names.setdefault(name, None)
        for name in list(names):
            del names[name]
            if (name in ABAQUS_UTILITIES or name in INTRINSIC_AND_VENDOR_CALLS
                    or name.startswith("SMA")):
                continue
            if name in defined:
                continue
            if name in UNCONFIRMED_UTILITIES:
                unconfirmed.setdefault(name, None)
                continue
            pull("call", name, list(index.by_declared.get(name, ())), 0)
    # a routine some later file of the closure defined is defined for this source
    for key in list(unpublished):
        label, _, name = key.partition(" ")
        if label == "call" and name in defined:
            del unpublished[key]
    # BLAS/LAPACK are a library, not an Abaqus utility and not a repository
    # routine: neither resolved nor external (RULE_G3a item 2, Vera B17). A
    # rule that treated them as unavailable would be a new rule made after
    # seeing which sources it removes; it is not implemented.
    library = {key: None for key in unpublished
               if key.startswith("call ") and LIBRARY_ROUTINES.match(key.split(" ", 1)[1])}
    result.unpublished_library = tuple(library)
    result.unconfirmed = tuple(unconfirmed)
    result.unpublished = tuple(key for key in unpublished if key not in library)
    result.companions = tuple(rel(p) for p in closure[1:])
    return result
