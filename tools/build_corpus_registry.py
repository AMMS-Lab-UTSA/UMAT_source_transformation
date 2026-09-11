#!/usr/bin/env python3
"""One record per downloaded artefact, and a report a person can read.

The registry is the denominator. Every file the acquisition brought back is in
it exactly once, whether it transformed, whether it ran, whether it is even a
UMAT -- because a source that quietly stopped being attempted leaves no failing
row to notice, and a summary built from the rows a batch happened to produce
would never show it.

So the denominator is SEEDED FROM THE ACQUISITION INVENTORY and the batches are
joined onto it, never the other way round. Building it from the transform
report instead would have worked -- that report happens to carry all 391 rows
today -- and it would have gone on working silently on the day a run stopped
attempting a source, because a registry built from the attempts cannot show an
attempt that was never made. The inventory is 391 rows; the assertion that the
registry is too lives in
``tests/test_the_registry_is_the_denominator.py::test_the_registry_holds_every_one_of_the_391_discovered_sources``.

Each record carries a terminal state and who has to move next. Four of them are
final and external: nobody published the constants, the file is not a UMAT, it
does not compile as published, a module it needs was never published beside it.
One is final and verified. The rest are unfinished and OURS, named as precisely
as the evidence allows so the cluster a failure belongs to is visible -- because
that is what decides which fix is worth making, and because calling any of them
a terminal state would be relabelling our own limitation as somebody else's.

    tools/build_corpus_registry.py \
        --transform <run>/transform_batch.json \
        --abaqus <run>/results/store_verification.jsonl \
        --json paper_results/corpus/corpus_registry.json \
        --csv  paper_results/corpus/corpus_registry.csv \
        --markdown paper_results/corpus/CORPUS_VERIFICATION.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.abaqus.terminal_states import (EXTERNAL, FULLY_VERIFIED,  # noqa: E402
                                             INTERNAL, WAITS_FOR_INPUT,
                                             from_stage, from_transform_failure,
                                             kind_of)

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO.parent / "discovery_cache")

#: The acquisition inventory: one row per discovered source, written by the
#: discovery triage before anything was transformed. This is the denominator.
DEFAULT_INVENTORY = REPO / "paper_results/discovery/discovery_triage.csv"

#: Where the acquisition recorded, per repository, the 40-character commit it
#: read and the licence it read it under. The per-file URL is reconstructed
#: from that commit, which is why ``url_provenance`` says so on every record
#: rather than letting a derived URL pass for a recorded one.
DEFAULT_ACQUISITION = (REPO / "paper_results/corpus/companions.json",
                       REPO / "paper_results/corpus/companions_wave2.json")

#: The offline evidence about what each refused source is. Written by
#: ``--refusal-audit``; read back on every later build so the registry can be
#: rebuilt on a machine with no Fortran compiler and get the same answers.
DEFAULT_AUDIT = REPO / "paper_results/corpus/transform_refusal_audit.json"


@dataclass
class Record:
    """One acquired artefact, and everything established about it."""

    source_id: str
    repository: str = ""
    #: Where the file sits inside the acquisition cache, and where it came
    #: from. Held on every record, not only the ones that ran: a classification
    #: nobody can trace back to a commit and a path is an assertion.
    cache_path: str = ""
    acquisition_url: str = ""
    url_provenance: str = ""
    commit: str = ""
    license_spdx: str = ""
    sha256: str = ""
    bytes: Optional[int] = None
    source_form: str = ""
    is_umat: Optional[bool] = None
    entry_interface: str = ""
    entry_routine: str = ""
    entry_line: Optional[int] = None
    #: The line of the author's own file the entry point was read from,
    #: verbatim, and which piece of evidence decided the classification.
    entry_evidence: str = ""
    classification_basis: str = ""
    #: What a source the TRANSFORMER refused turned out to be, decided by
    #: parsing the file rather than by the refusal. See
    #: umat_oti.corpus.entry_routines.classify_refusal.
    refusal_class: str = ""
    refusal_class_confident: Optional[bool] = None
    duplicate_of: str = ""
    companion_files: str = ""
    terminal_state: str = "not_attempted"
    kind: str = "internal"
    reason: str = ""
    stage: str = ""
    #: Whether any batch produced a row for this source at all. A source the
    #: run never reached is not a source the run refused, and reading the
    #: second as the first invents a refusal nobody recorded.
    attempted: bool = False
    transformed: bool = False
    compiled: Optional[bool] = None
    ntens: Optional[int] = None
    ntens_provenance: str = ""
    element_type: str = ""
    formulation: str = ""
    kinematics: str = ""
    deck: str = ""
    material_provenance: str = ""
    props_count: Optional[int] = None
    nstatv: Optional[int] = None
    activated: Optional[bool] = None
    activation_amplitude: Optional[float] = None
    time_dependent: Optional[bool] = None
    response_character: str = ""
    worst_stress_relative: Optional[float] = None
    worst_state_relative: Optional[float] = None
    primal_increments: Optional[int] = None
    precision_control: Optional[bool] = None
    tangent_states_checked: Optional[int] = None
    tangent_states_agreeing: Optional[int] = None
    worst_tangent_relative: Optional[float] = None
    tangent_plateau: str = ""
    missing_companions: str = ""
    compile_defect: str = ""
    key: str = ""
    seconds: Optional[float] = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _rows(path: Optional[Path]) -> list:
    """Every record, one per entry: the last one written.

    The results file is append-only, so a resumed run that re-runs an entry
    appends a second record rather than editing the first. Keeping both would
    put a superseded verdict in the registry beside the one that replaced it.
    """
    if not path or not Path(path).is_file():
        return []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if Path(path).suffix == ".jsonl":
        latest: dict = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            latest[str(record.get("key") or record.get("source") or line)] = record
        return list(latest.values())
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload.get("entries") or payload.get("rows") or []
    return payload or []


# ---------------------------------------------------------------------------
# The denominator, and where each of its entries came from
# ---------------------------------------------------------------------------
def inventory(path: Optional[Path]) -> list:
    """Every source the acquisition discovered, in the order it recorded them.

    The discovery triage writes one row per discovered source before anything
    is transformed, so it is the only artefact in the chain that cannot have
    been shortened by a batch that skipped something. A CSV and not a line
    split: blocker columns hold embedded newlines, and the 391-row file is 856
    lines long because of them.
    """
    if not path or not Path(path).is_file():
        return []
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with Path(path).open(newline="", encoding="utf-8") as handle:
            return [str(row.get("source") or "").strip()
                    for row in csv.DictReader(handle)
                    if str(row.get("source") or "").strip()]
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else (
        payload.get("rows") or payload.get("sources") or [])
    return [str(row if isinstance(row, str) else
                (row.get("source") or row.get("source_id") or "")).strip()
            for row in rows]


def acquisition_provenance(paths=DEFAULT_ACQUISITION) -> dict:
    """Per repository: the commit it was read at, and under which licence.

    The acquisition pinned every repository to a 40-character commit and wrote
    a URL beside each file it fetched. Those URLs are for the COMPANION files,
    not for the UMAT sources, so the per-source URL here is reconstructed from
    the repository's commit and the file's path inside the cache. That is a
    derivation, and ``url_provenance`` says so on every record: a derived URL
    presented as a recorded one is a small lie that a reader cannot detect.

    The owner/repo slug is taken from a recorded URL wherever the acquisition
    left one -- 134 of the 136 repositories the corpus draws on -- and falls
    back to splitting the cache directory name at its first ``__``. That rule
    is not guessed: it agrees with the recorded slug on all 134.
    """
    found: dict[str, dict] = {}
    for path in paths or ():
        if not Path(path).is_file():
            continue
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            continue
        for entry in payload.get("repositories") or []:
            name = str(entry.get("repository") or "")
            if not name or name in found:
                continue
            slug = ""
            for fetched in entry.get("fetched") or []:
                match = re.match(r"https://github\.com/([^/]+/[^/]+)/blob/",
                                 str(fetched.get("url") or ""))
                if match:
                    slug = match.group(1)
                    break
            found[name] = {
                "commit": str(entry.get("commit") or ""),
                "slug": slug or name.replace("__", "/", 1),
                "slug_provenance": ("recorded in an acquisition URL" if slug
                                    else "derived from the cache directory name"),
                "license_spdx": str(entry.get("license_spdx") or ""),
            }
    return found


def _acquisition_url(source_id: str, provenance: dict) -> tuple:
    """The URL this file was acquired from, and how that URL was arrived at."""
    repo_dir = source_id.split("/", 1)[0]
    rest = source_id.split("/", 1)[1] if "/" in source_id else ""
    entry = (provenance or {}).get(repo_dir)
    if not entry or not entry.get("commit"):
        return "", "no commit was recorded for this repository"
    quoted = "/".join(quote(part) for part in rest.split("/"))
    return (f"https://github.com/{entry['slug']}/blob/{entry['commit']}/{quoted}",
            f"reconstructed from the commit the acquisition pinned "
            f"({entry['commit'][:12]}), whose owner/repo was "
            f"{entry['slug_provenance']}")


def _line_identity(path: Path) -> str:
    """A digest of the file's lines, ignoring how they were newline-terminated.

    Only trailing whitespace and the CR of a CRLF are removed. Nothing that
    changes a COLUMN is touched, because in fixed-form Fortran a column carries
    meaning: collapsing runs of spaces made a file whose continuation markers
    sit in column 9 -- which no compiler accepts -- come out identical to one
    whose markers sit in column 6, and quietly filed a corrupt source as a
    duplicate of a working one.
    """
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in text.replace("\r\n", "\n")
             .replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def duplicate_map(cache: Optional[Path], source_ids) -> dict:
    """Which acquired sources are second copies, and of what.

    The first source_id in sort order is the one kept; the rest name it. Two
    files that are line-for-line identical carry one answer between them, and
    counting that answer twice inflates every rate computed from the corpus.
    """
    if not cache or not Path(cache).is_dir():
        return {}
    groups: dict = defaultdict(list)
    for source_id in source_ids:
        path = Path(cache) / source_id
        if path.is_file():
            groups[_line_identity(path)].append(source_id)
    duplicates: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        canonical = sorted(members)[0]
        for member in sorted(members)[1:]:
            duplicates[member] = canonical
    return duplicates


# ---------------------------------------------------------------------------
# Does the author's own text build? Asked offline, without Abaqus.
# ---------------------------------------------------------------------------
#: ifort diagnostics that mean the compiler could not PARSE the text it was
#: given. They are the only ones this audit will call a defect in the file,
#: because a missing module cannot make a parser find ``&`` where an
#: identifier belongs, and cannot put an ENDDO where no DO was opened. Every
#: semantic diagnostic -- an undeclared name, a kind parameter that is not
#: constant, an argument of the wrong type -- is exactly what an unresolved
#: USE produces, so none of them may be read as the file's fault.
SYNTAX_DIAGNOSTICS = frozenset((
    "5082",   # syntax error
    "5078",   # unrecognised token
    "5118",   # first statement may not be a continuation
    "5143",   # missing mandatory item
    "5144",   # invalid attribute
    "5149",   # illegal character in the statement label field
    "5192",   # invalid statement
    "5195",   # continuation character illegal in this column in fixed form
    "5276",   # unbalanced parentheses
    "5274",
    "5287",
    "6099",   # ENDDO with no DO
    "6236",   # specification statement in the executable section
    "6317",   # ENDIF with no IF THEN
    "6343",   # invalid statement after a logical IF
    "6418",   # this name has already been assigned a data type
    "6222",   # IMPLICIT positioned wrongly in the scoping unit
    "6818",   # the statement after CONTAINS is not a procedure
))

#: The include the corpus writes as ``INCLUDE 'ABA_PARAM.INC'``. Its real
#: contents are read from the Abaqus installation when there is one, because a
#: stub that omits ``implicit real*8(a-h,o-z)`` changes the type of every
#: dummy argument and turns working files into type-mismatch errors.
ABA_PARAM_FALLBACK = ("      implicit real*8(a-h,o-z)\n"
                      "      parameter (nprecd=2)\n")
ABA_PARAM_SPELLINGS = ("ABA_PARAM.INC", "aba_param.inc", "ABA_PARAM.inc",
                       "Aba_param.inc", "aba_param.INC", "ABA_PARAM_DP.INC",
                       "aba_param_dp.inc")

#: Modules the compiler provides. ``resolve`` reports them as missing because
#: nothing in the repository defines them, which is true and irrelevant.
INTRINSIC_MODULES = frozenset((
    "iso_fortran_env", "iso_c_binding", "ieee_arithmetic", "ieee_exceptions",
    "ieee_features", "omp_lib", "omp_lib_kinds", "mpi", "mpi_f08", "openacc",
))

_INCLUDE = re.compile(r"^[^!'\"\n]*?\binclude\s*['\"]([^'\"]+)['\"]",
                      re.IGNORECASE | re.MULTILINE)


def _fortran_compiler() -> str:
    """A front end that reports diagnostic NUMBERS, or nothing.

    gfortran is not a substitute. Its diagnostics carry no numbers, so a
    syntax error cannot be told apart from an unresolved USE, and this audit
    would have to guess which of the two it was looking at. It returns "" and
    every verdict from the audit comes back unsettled, which is the honest
    answer for a machine that cannot ask the question.
    """
    for candidate in ("ifort", "ifx"):
        found = shutil.which(candidate)
        if found:
            return found
    for root in sorted(Path("/opt/intel/oneapi/compiler").glob("*/linux/bin*"),
                       reverse=True):
        for candidate in ("intel64/ifort", "ifort", "ifx"):
            if (root / candidate).is_file():
                return str(root / candidate)
    return ""


def _abaqus_header_dir() -> Optional[Path]:
    """Abaqus's own include directory, if this machine has one.

    Reading a header file off the disk is not running Abaqus: no process is
    started and no licence token is drawn.
    """
    for root in sorted(Path("/usr/SIMULIA").glob("*/*/linux_a64/code/include"),
                       reverse=True):
        if root.is_dir():
            return root
    return None


def _compile_once(source: Path, form: str, companions, include_dirs,
                  shims: dict, preprocess: bool, compiler: str) -> dict:
    """One ifort syntax pass over the author's file and its companions."""
    import subprocess
    import tempfile

    header_dir = _abaqus_header_dir()
    aba_param = ABA_PARAM_FALLBACK
    if header_dir and (header_dir / "aba_param.inc").is_file():
        aba_param = (header_dir / "aba_param.inc").read_text(errors="replace")
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        for name in ABA_PARAM_SPELLINGS:
            (scratch / name).write_text(aba_param, encoding="utf-8")
        for header in (header_dir.glob("*.hdr") if header_dir else ()):
            shutil.copyfile(header, scratch / header.name)
        for wanted, present in shims.items():
            try:
                shutil.copyfile(present, scratch / wanted)
            except OSError:
                pass
        suffix = ".f90" if form == "free" else ".f"
        units = []
        for index, companion in enumerate(companions):
            target = scratch / f"companion{index:02d}{suffix}"
            shutil.copyfile(companion, target)
            units.append(str(target))
        probe = scratch / f"probe{suffix}"
        shutil.copyfile(source, probe)
        units.append(str(probe))
        command = [compiler, "-syntax-only",
                   "-free" if form == "free" else "-fixed",
                   "-extend-source", "132", "-module", str(scratch),
                   "-I", str(scratch)]
        if header_dir:
            command += ["-I", str(header_dir)]
        if preprocess:
            command.append("-fpp")
        for directory in include_dirs:
            command += ["-I", str(directory)]
        command += units
        try:
            done = subprocess.run(command, capture_output=True, text=True,
                                  cwd=str(scratch), timeout=300)
        except Exception:                          # noqa: BLE001
            return {"ran": False, "ok": False, "own": []}
        output = ((done.stderr or "") + (done.stdout or "")).replace(
            str(scratch), "<probe>")
        # Diagnostics against the author's own file, and against the Abaqus
        # header AS THIS FILE INCLUDES IT -- a second IMPLICIT inside
        # aba_param.inc is caused by the source putting IMPLICIT NONE above
        # the INCLUDE, so it belongs to the source. Diagnostics against a
        # companion unit are that companion's and are left out.
        own = [{"line": int(line), "code": code, "message": message.strip(),
                "in": "the published source" if unit == "probe"
                      else "Abaqus's own aba_param.inc, as this source "
                           "includes it"}
               for unit, line, code, message in re.findall(
                   r"<probe>/(probe|ABA_PARAM\.INC|aba_param\.inc)"
                   r"[^(]*\((\d+)\): error #(\d+): ([^\n]*)", output)]
        return {"ran": True, "ok": done.returncode == 0, "own": own,
                "output": output[:4000]}


def offline_syntax_audit(cache: Path, source_ids, *, compiler: str = "") -> dict:
    """Whether each source builds as its author published it, decided offline.

    No Abaqus process is started. The file is handed to ifort with
    ``-syntax-only``, with the companions the repository does publish compiled
    ahead of it, with Abaqus's own ``aba_param.inc`` on the include path, and
    with both source forms tried -- because reading a free-form file as fixed
    produces a page of illegal-character diagnostics that say nothing about
    the file.

    Three outcomes, and the difference between them is the whole point:

    ``text_rejected`` true
        the parser could not read the author's text, under either form, with
        a diagnostic that no absent module could have caused.
    ``text_rejected`` false
        it compiled.
    ``text_rejected`` None
        it did not compile, but every diagnostic is one an unresolved USE
        would also produce. The audit has not settled anything, and says so.
    """
    from umat_oti.abaqus.companions import repository_files, resolve
    from umat_oti.fortran.normalize import detect_source_form

    compiler = compiler or _fortran_compiler()
    audited: dict[str, dict] = {}
    for source_id in source_ids:
        source = Path(cache) / source_id
        if not source.is_file():
            continue
        repo = Path(cache) / source_id.split("/", 1)[0]
        text = source.read_text(errors="replace")
        found = resolve(source, repository_files(source, cache))
        missing = [f"module {name}" for name in found.missing_modules
                   if name.lower() not in INTRINSIC_MODULES]
        missing += [f"include {name}" for name in found.missing_includes]
        directories = [source.parent, repo]
        directories += [d for d in sorted(repo.rglob("*")) if d.is_dir()][:60]
        shims: dict[str, Path] = {}
        for wanted in sorted(set(_INCLUDE.findall(text))):
            base = Path(wanted).name
            if base.lower().startswith("aba_param") or base.lower().endswith(".hdr"):
                continue
            if any((d / wanted).is_file() or (d / base).is_file()
                   for d in directories):
                continue
            elsewhere = [f for d in directories for f in d.iterdir()
                         if f.is_file() and f.name.lower() == base.lower()]
            if elsewhere:
                # Published, but spelled in another case. A case-only mismatch
                # is a property of the filesystem it is unpacked on, not a
                # file the author failed to publish.
                shims[base] = elsewhere[0]
            else:
                missing.append(f"include {wanted}")
        record = {"missing_externals": sorted(set(missing)),
                  "companions": [str(Path(c).relative_to(cache))
                                 for c in found.order],
                  "compiler": Path(compiler).name if compiler else ""}
        if not compiler:
            record.update(compiles=None, text_rejected=None, evidence="",
                          basis="no compiler that reports diagnostic numbers "
                                "was available, so nothing was asked")
            audited[source_id] = record
            continue
        preprocess = bool(re.search(r"^\s*#\s*(include|if|define)", text,
                                    re.MULTILINE))
        primary = detect_source_form(source, text)
        other = "free" if primary == "fixed" else "fixed"
        first = _compile_once(source, primary, found.order, directories, shims,
                              preprocess, compiler)
        second = ({"ran": False, "ok": False, "own": []} if first["ok"]
                  else _compile_once(source, other, found.order, directories,
                                     shims, preprocess, compiler))
        compiles = bool(first["ok"] or second["ok"])
        syntax = [] if compiles else [d for d in first["own"]
                                      if d["code"] in SYNTAX_DIAGNOSTICS]
        if compiles:
            rejected, evidence, basis = False, "", (
                f"ifort -syntax-only accepted the published text as "
                f"{primary if first['ok'] else other} form")
        elif syntax:
            first_defect = syntax[0]
            rejected = True
            evidence = (f"{first_defect['in']}, line {first_defect['line']}: "
                        f"{first_defect['message'][:200]}")
            basis = (f"ifort rejected the published text with "
                     f"{len(syntax)} parse diagnostic(s) under {primary} form")
        else:
            rejected, evidence = None, ""
            basis = ("the offline compile failed, but every diagnostic is one "
                     "an unresolved USE or INCLUDE would also produce, so it "
                     "settles nothing about the file")
        record.update(compiles=compiles, text_rejected=rejected,
                      evidence=evidence, basis=basis, source_form=primary)
        audited[source_id] = record
    return audited


def build(transform_report: Optional[Path], abaqus_report: Optional[Path],
          cache: Optional[Path], *, compile_check: bool = False,
          inventory_ids=None, provenance: Optional[dict] = None,
          audit: Optional[dict] = None) -> list:
    """Every acquired artefact, its terminal state, and the evidence for it.

    ``inventory_ids`` is the denominator and is seeded first, so a source the
    transform batch never produced a row for still gets a record -- as
    ``not_attempted``, which is an absence of a verdict and has to stay
    visible. A source that appears in a batch but not in the inventory is also
    kept, because dropping it would hide a disagreement between two artefacts
    that are supposed to describe the same corpus.
    """
    records: dict[str, Record] = {}

    def _seed(source_id: str) -> Record:
        record = records.get(source_id)
        if record is None:
            record = Record(
                source_id=source_id,
                repository=source_id.split("/")[0].replace("__", "/", 1),
                cache_path=source_id)
            if provenance:
                entry = provenance.get(source_id.split("/", 1)[0]) or {}
                record.commit = str(entry.get("commit") or "")
                record.license_spdx = str(entry.get("license_spdx") or "")
                url, why = _acquisition_url(source_id, provenance)
                record.acquisition_url, record.url_provenance = url, why
            records[source_id] = record
        return record

    for source_id in (inventory_ids or ()):
        if str(source_id).strip():
            _seed(str(source_id).strip())

    payload = json.loads(transform_report.read_text(encoding="utf-8")) \
        if transform_report and Path(transform_report).is_file() else {}
    for row in payload.get("rows", []):
        source_id = str(row.get("source") or row.get("source_id") or "")
        if not source_id:
            continue
        record = _seed(source_id)
        record.ntens = row.get("ntens")
        record.ntens_provenance = str(row.get("ntens_provenance") or "")
        record.kinematics = str(row.get("kinematics") or "")
        record.key = str(row.get("key") or "")
        outcome = str(row.get("outcome") or "")
        record.attempted = True
        record.transformed = outcome in ("transformed", "cached")
        record.compiled = row.get("compiled")
        if not record.transformed:
            record.reason = str(row.get("reason") or "")[:500]
    for row in payload.get("failures", []):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        record = _seed(source_id)
        record.attempted = True
        record.transformed = False
        record.reason = str(row.get("reason") or "")[:500]

    # What the file itself is, asked of the file rather than of the transform.
    duplicates = duplicate_map(cache, sorted(records)) if cache else {}
    if cache and Path(cache).is_dir():
        from umat_oti.abaqus.companions import repository_files, resolve
        from umat_oti.corpus.entry_routines import classify, classify_refusal
        from umat_oti.store.transform_store import file_digest

        for record in records.values():
            source = Path(cache) / record.source_id
            if not source.is_file():
                record.classification_basis = (
                    "the acquisition inventory names this source but the "
                    "cache does not hold it")
                continue
            text = source.read_text(errors="replace")
            record.bytes = len(text.encode())
            record.sha256 = file_digest(source)
            record.duplicate_of = duplicates.get(record.source_id, "")

            found = classify(text, path=source)
            record.source_form = found.source_form
            record.entry_interface = found.entry_interface
            record.entry_routine = found.entry_routine
            record.entry_line = found.entry_line or None
            record.entry_evidence = found.entry_text

            resolution = resolve(source, repository_files(source, cache))
            record.companion_files = "; ".join(
                str(Path(unit).relative_to(cache))
                for unit in resolution.order)[:500]
            evidence = (audit or {}).get(record.source_id) or {}
            missing = evidence.get("missing_externals")
            if missing is None:
                missing = ([f"module {n}" for n in resolution.missing_modules
                            if n.lower() not in INTRINSIC_MODULES]
                           + [f"include {n}" for n in resolution.missing_includes])
            record.missing_companions = "; ".join(missing)[:300]

            verdict = classify_refusal(
                found, duplicate_of=record.duplicate_of,
                missing_externals=tuple(missing),
                text_rejected=evidence.get("text_rejected"),
                compiler_evidence=str(evidence.get("evidence") or ""))
            # The refusal class answers "the transformer refused this -- what
            # was it?", so it is only recorded where there was a refusal. What
            # the file IS is recorded either way, because a transformed file
            # whose entry point is a UEL is just as wrong to count as a UMAT.
            if record.attempted and not record.transformed:
                record.refusal_class = verdict.refusal_class
                record.refusal_class_confident = verdict.confident
            record.is_umat = verdict.is_umat
            record.classification_basis = "; ".join(
                part for part in (verdict.basis,
                                  str(evidence.get("basis") or "")) if part)[:600]
            if verdict.evidence:
                record.entry_evidence = verdict.evidence

    # What Abaqus made of the ones that got that far. This overrides the
    # transform's verdict, because it is later and it is about a real run.
    for row in _rows(abaqus_report):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        record = _seed(source_id)
        record.key = str(row.get("key") or record.key)
        record.stage = str(row.get("stage") or "")
        verdict = from_stage(record.stage, str(row.get("reason") or "")[:500])
        record.terminal_state, record.kind = verdict.state, verdict.kind
        record.reason = verdict.reason
        record.transformed = True
        record.element_type = str(row.get("element_type") or "")
        record.ntens = row.get("ntens", record.ntens)
        record.kinematics = str(row.get("kinematics") or record.kinematics)
        record.deck = str(row.get("deck") or "")
        record.material_provenance = str(row.get("material_provenance") or "")
        record.props_count = row.get("props_count")
        record.nstatv = row.get("nstatv")
        formulation = row.get("formulation") or {}
        record.formulation = str(formulation.get("family") or "")
        discovery = row.get("discovery") or {}
        record.activation_amplitude = discovery.get("chosen_amplitude")
        record.activated = (discovery.get("outcome") == "activated"
                            if discovery.get("ran") else None)
        record.time_dependent = (discovery.get("time") or {}).get("time_dependent")
        primal = row.get("primal") or {}
        record.worst_stress_relative = primal.get("worst_stress_relative")
        record.worst_state_relative = primal.get("worst_state_relative")
        record.primal_increments = primal.get("increments")
        record.precision_control = (row.get("precision_control") or {}).get("agrees")
        tangent = row.get("tangent") or {}
        record.tangent_states_checked = tangent.get("states_checked")
        record.tangent_states_agreeing = tangent.get("states_agreeing")
        record.response_character = str(tangent.get("response_character") or "")
        comparison = tangent.get("comparison") or {}
        record.worst_tangent_relative = comparison.get("best_relative")
        stable = comparison.get("stable_range") or []
        record.tangent_plateau = (f"{min(stable):g}..{max(stable):g}"
                                  if len(stable) == 2 else "")
        classification = row.get("entry_classification") or {}
        if classification:
            record.is_umat = classification.get("kind") == "umat"
            record.entry_interface = str(
                classification.get("entry_interface") or record.entry_interface)
        diagnosis = row.get("original_diagnosis") or {}
        if diagnosis:
            record.compile_defect = "; ".join(
                (diagnosis.get("compile") or {}).get("defects") or [])[:300]
        record.seconds = row.get("seconds")

    # Everything Abaqus never saw. Its terminal state comes from what the file
    # is: a transform refusal is ours unless the file is one nobody could have
    # transformed, and the compile check is what tells those apart.
    for record in records.values():
        if record.stage:
            continue
        if record.is_umat is False:
            record.terminal_state, record.kind = "not_a_umat", "external"
            continue
        if record.transformed or not record.attempted:
            # It converted and the batch has not reached it, or no batch
            # produced a row for it at all. Not a verdict -- an absence of one,
            # and an absence that has to stay visible.
            record.terminal_state, record.kind = "not_attempted", "internal"
            continue
        # A transform refusal is NEVER what decides this. What the file is
        # decides it, and what the file is was read out of the file, so the
        # three inputs below all come from the refusal classification and the
        # refusal text is carried along only as the reason.
        #
        # `compiles` is False ONLY where the classification says the text is
        # rejected. An offline compile that merely failed is not the same
        # claim: six genuine UMATs failed it because a module they USE could
        # not be built here, and passing that through as compiles=False filed
        # all six as `incomplete_or_corrupt_source` -- an external verdict on
        # somebody's repository, resting on a gap in this probe.
        compiles = (audit or {}).get(record.source_id, {}).get("compiles")
        if compiles is None and compile_check and cache \
                and (Path(cache) / record.source_id).is_file():
            compiles = _compiles(Path(cache) / record.source_id, record)
        if record.refusal_class == "incomplete_or_corrupt_source":
            compiles = False
        elif record.refusal_class:
            compiles = True if compiles else None
        verdict = from_transform_failure(
            record.reason, compiles=compiles,
            companions_missing=(record.refusal_class ==
                                "missing_external_dependency"),
            is_umat=(record.is_umat if record.refusal_class
                     else _is_a_umat(cache, record.source_id)))
        record.terminal_state, record.kind = verdict.state, verdict.kind
    return sorted(records.values(), key=lambda r: r.source_id)


def _is_a_umat(cache: Optional[Path], source_id: str) -> Optional[bool]:
    """What this file presents to Abaqus, by parsing rather than by name.

    Asked of sources the transform refused, because a file whose entry point
    is a UEL was never this transformer's to convert and its refusal says
    nothing about the transformer.
    """
    if not cache or not source_id:
        return None
    path = Path(cache) / source_id
    if not path.is_file():
        return None
    try:
        from umat_oti.corpus.entry_routines import classify
        found = classify(path.read_text(errors="replace"), path=path)
    except Exception:                              # noqa: BLE001 - advisory
        return None
    # A file that parses as nothing may be a helper, or may be a file whose
    # text is too damaged to parse. Saying "not a UMAT" about the second is an
    # external verdict resting on no evidence, so an unreadable file gets no
    # answer here and the compile check gives it one.
    from umat_oti.corpus.entry_routines import NO_PROGRAM_UNIT
    if found.kind == NO_PROGRAM_UNIT:
        return None
    return bool(found.is_umat)


def _compiles(source: Path, record: Record) -> Optional[bool]:
    """Does the author's own file build with Abaqus's compile line?"""
    try:
        from umat_oti.abaqus.companions import repository_files, resolve
        from umat_oti.abaqus.support import compile_one
        import tempfile

        found = resolve(source, repository_files(source, source.parents[-2]))
        with tempfile.TemporaryDirectory() as scratch:
            check = compile_one(source, Path(scratch), form=record.source_form,
                                extra_sources=found.order)
        if check.ok:
            return True
        if check.missing_dependencies:
            record.missing_companions = (record.missing_companions
                                         or "; ".join(check.missing_dependencies))
            return None
        record.compile_defect = "; ".join(check.defects)[:300]
        # False only when the compiler rejected the TEXT. Anything else is a
        # compile that did not settle the question, and None says so.
        return False if check.source_is_malformed else None
    except Exception:                              # noqa: BLE001
        return None


def _refused_sources(transform_report: Optional[Path]) -> list:
    """The sources the transform batch refused, from the batch's own report."""
    if not transform_report or not Path(transform_report).is_file():
        return []
    payload = json.loads(Path(transform_report).read_text(encoding="utf-8"))
    refused = [str(row.get("source") or "")
               for row in payload.get("failures") or []]
    refused += [str(row.get("source") or "") for row in payload.get("rows") or []
                if str(row.get("outcome") or "") not in ("transformed", "cached")]
    return sorted({name for name in refused if name})


def summarise(records: list) -> dict:
    umats = [r for r in records if r.is_umat is not False]
    verified = [r for r in records if r.terminal_state == FULLY_VERIFIED]
    by_state = Counter(r.terminal_state for r in records)
    by_kind = Counter(r.kind for r in records)
    clusters = defaultdict(list)
    for record in records:
        if record.kind == "internal":
            clusters[record.terminal_state].append(record.source_id)
    refused = [r for r in records if r.refusal_class]
    by_refusal = Counter(r.refusal_class for r in refused)
    return {
        "acquired": len(records),
        "genuine_umats": len(umats),
        "fully_verified": len(verified),
        "transform_refused": len(refused),
        "refusals_by_class": dict(sorted(by_refusal.items(),
                                         key=lambda kv: -kv[1])),
        "refusals_not_confidently_classified": sorted(
            r.source_id for r in refused if r.refusal_class_confident is False),
        "refusals_with_no_entry_evidence": sorted(
            r.source_id for r in refused if not r.entry_evidence),
        "duplicate_sources": sorted(
            f"{r.source_id} == {r.duplicate_of}"
            for r in records if r.duplicate_of),
        "records_without_an_acquisition_url": sorted(
            r.source_id for r in records if not r.acquisition_url),
        "by_terminal_state": dict(sorted(by_state.items(), key=lambda kv: -kv[1])),
        "by_kind": dict(by_kind),
        "external_total": sum(by_state[s] for s in EXTERNAL) + by_state[WAITS_FOR_INPUT],
        "internal_total": sum(by_state[s] for s in INTERNAL),
        "internal_clusters": {state: len(names)
                              for state, names in sorted(
                                  clusters.items(), key=lambda kv: -len(kv[1]))},
        "verified_sources": [r.source_id for r in verified],
    }


def markdown(records: list, summary: dict) -> str:
    lines = [
        "# Corpus verification",
        "",
        f"{summary['acquired']} acquired artefacts, of which "
        f"{summary['genuine_umats']} present a UMAT interface to Abaqus.",
        "",
        f"**{summary['fully_verified']} fully verified.**",
        "",
        "`fully_verified` means the source transformed and compiled, Abaqus ran",
        "the ORIGINAL, Abaqus ran the CONVERTED build on the same deck, their",
        "stress and state histories agreed over the whole path, and the OTI",
        "tangent agreed with a finite difference of the original at several",
        "states along it. Compiling is not working and running is not verified.",
        "",
        "## Finished, and unfinished",
        "",
        "| | entries |",
        "| --- | ---: |",
        f"| verified | {summary['by_kind'].get('verified', 0)} |",
        f"| blocked outside this repository | {summary['external_total']} |",
        f"| work remaining here | {summary['internal_total']} |",
        "",
        "## Every terminal state",
        "",
        "| terminal state | whose move | entries |",
        "| --- | --- | ---: |",
    ]
    for state, count in summary["by_terminal_state"].items():
        lines.append(f"| `{state}` | {kind_of(state)} | {count} |")
    lines += ["", "## What is left here, by cluster", "",
              "Each of these is a limitation of this pipeline, not of the "
              "corpus. They are listed largest first because that is the "
              "order they are worth fixing in.", "",
              "| cluster | entries |", "| --- | ---: |"]
    for state, count in summary["internal_clusters"].items():
        lines.append(f"| `{state}` | {count} |")

    if summary.get("transform_refused"):
        lines += ["", "## What the transformer refused, and what those files are",
                  "",
                  f"{summary['transform_refused']} sources were refused by the "
                  "transformer. A REFUSAL IS A FACT ABOUT THE TRANSFORMER. Each "
                  "of these was then classified by parsing the file itself -- "
                  "its Abaqus entry point, its digest against every other "
                  "acquired source, and an offline compile of the author's own "
                  "text -- and the classification below rests on that evidence "
                  "and never on the refusal.", "",
                  "| what the file is | entries |", "| --- | ---: |"]
        for name, count in summary.get("refusals_by_class", {}).items():
            lines.append(f"| `{name}` | {count} |")
        unsure = summary.get("refusals_not_confidently_classified") or []
        lines += ["",
                  f"{len(unsure)} of them are held at `genuine_umat` because "
                  "the offline compile did not settle whether the published "
                  "text builds. That is the safe direction: it counts the work "
                  "as ours."]

    lines += ["", "## Every entry", "",
              "| source | terminal state | element | primal | tangent | states |",
              "| --- | --- | --- | ---: | ---: | --- |"]
    for record in records:
        primal = ("" if record.worst_stress_relative is None
                  else f"{record.worst_stress_relative:.2e}")
        tangent = ("" if record.worst_tangent_relative is None
                   else f"{record.worst_tangent_relative:.2e}")
        states = ("" if record.tangent_states_checked is None
                  else f"{record.tangent_states_agreeing}/{record.tangent_states_checked}")
        lines.append(
            f"| {record.source_id[-70:]} | `{record.terminal_state}` | "
            f"{record.element_type} | {primal} | {tangent} | {states} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transform", type=Path, required=True)
    parser.add_argument("--abaqus", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--json", dest="json_path", type=Path,
                        default=REPO / "paper_results/corpus/corpus_registry.json")
    parser.add_argument("--csv", dest="csv_path", type=Path,
                        default=REPO / "paper_results/corpus/corpus_registry.csv")
    parser.add_argument("--markdown", type=Path,
                        default=REPO / "paper_results/corpus/CORPUS_VERIFICATION.md")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY,
                        help="the acquisition inventory, one row per "
                             "discovered source. This is the denominator: the "
                             "registry is seeded from it and the batches are "
                             "joined onto it, so a source no batch produced a "
                             "row for still gets a record")
    parser.add_argument("--acquisition", type=Path, action="append",
                        dest="acquisition", default=None,
                        help="acquisition manifests carrying the commit each "
                             "repository was read at (default: the two "
                             "companion manifests)")
    parser.add_argument("--refusal-audit", type=Path, default=DEFAULT_AUDIT,
                        help="offline evidence about what each refused source "
                             "is; read if present, rewritten by --audit-refusals")
    parser.add_argument("--audit-refusals", action="store_true",
                        help="compile every refused source offline with "
                             "ifort -syntax-only and write the evidence to "
                             "--refusal-audit. No Abaqus process is started "
                             "and no licence token is drawn")
    parser.add_argument("--compile-check", action="store_true",
                        help="compile every unreached source with Abaqus's own "
                             "compile line, so a transform refusal on a file "
                             "that does not build is recorded as the file's "
                             "problem rather than as ours")
    args = parser.parse_args(argv)

    inventory_ids = inventory(args.inventory)
    provenance = acquisition_provenance(args.acquisition or DEFAULT_ACQUISITION)

    audit: dict = {}
    if args.refusal_audit and Path(args.refusal_audit).is_file():
        audit = json.loads(Path(args.refusal_audit).read_text(
            encoding="utf-8")).get("sources") or {}
    if args.audit_refusals:
        refused = _refused_sources(args.transform)
        print(f"  auditing {len(refused)} refused sources offline "
              f"(ifort -syntax-only; no Abaqus)", flush=True)
        audit = offline_syntax_audit(args.cache_dir, refused)
        Path(args.refusal_audit).parent.mkdir(parents=True, exist_ok=True)
        Path(args.refusal_audit).write_text(json.dumps({
            "schema": "umat-oti/transform-refusal-audit/1",
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "what_this_is": (
                "for each source the transformer refused: whether the author's "
                "own text is accepted by ifort -syntax-only, what it USEs or "
                "INCLUDEs that was never published beside it, and which "
                "companion units the repository does publish. No Abaqus "
                "process was started. A refusal is not evidence for any of "
                "these; this file is."),
            "sources": audit}, indent=1) + "\n", encoding="utf-8")
        print(f"  wrote {args.refusal_audit}")

    records = build(args.transform, args.abaqus, args.cache_dir,
                    compile_check=args.compile_check,
                    inventory_ids=inventory_ids, provenance=provenance,
                    audit=audit)
    summary = summarise(records)
    summary["inventory"] = {
        "path": str(args.inventory),
        "discovered_sources": len(inventory_ids),
        "in_the_registry": len(records),
        "in_a_batch_but_not_the_inventory": sorted(
            {r.source_id for r in records} - set(inventory_ids)),
        "in_the_inventory_but_in_no_batch": sorted(
            set(inventory_ids) - {r.source_id for r in records}),
    }

    payload = {
        "schema": "umat-oti/corpus-registry/1",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "what_counts_as_verified": (
            "only fully_verified, and it is reached by a source that "
            "transformed, compiled, ran in Abaqus as the original, ran as the "
            "converted build on the same deck, agreed with itself over the "
            "whole stress and state history, and whose OTI tangent agreed with "
            "a finite difference of the original at several smooth states"),
        "terminal_states": {
            "verified": [FULLY_VERIFIED],
            "external": list(EXTERNAL) + [WAITS_FOR_INPUT],
            "internal": list(INTERNAL),
        },
        "summary": summary,
        "records": [r.as_dict() for r in records],
    }
    for path, text in ((args.json_path, json.dumps(payload, indent=1) + "\n"),
                       (args.markdown, markdown(records, summary))):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")
    with open(args.csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].as_dict())
                                if records else ["source_id"])
        writer.writeheader()
        for record in records:
            writer.writerow(record.as_dict())

    print(f"  {summary['acquired']} artefacts, {summary['genuine_umats']} UMATs, "
          f"{summary['fully_verified']} fully verified")
    if summary.get("refusals_by_class"):
        print(f"  {summary['transform_refused']} refused by the transformer; "
              f"what those files are:")
        for name, count in summary["refusals_by_class"].items():
            print(f"    {name:<34} {count:>4}")
    for state, count in summary["by_terminal_state"].items():
        print(f"    {state:<34} {count:>4}  ({kind_of(state)})")
    print(f"  wrote {args.json_path}")
    print(f"  wrote {args.csv_path}")
    print(f"  wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
