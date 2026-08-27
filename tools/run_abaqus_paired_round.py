#!/usr/bin/env python3
"""Run the paired Abaqus validation over every source that declares a material.

The offline route compiles the original and transformed subroutines into two
standalone drivers and compares them at a material point. This route puts both
through Abaqus instead, on the same deck, and compares what Abaqus reports.
They fail differently: the offline route never exercises Abaqus's own interface
conventions, and this one cannot see a derivative family Abaqus does not
return.

Two things this round refuses to do:

* Invent a material. The constants come from the same contracts the offline
  round uses. A source that declares none is recorded as such and stays in the
  denominator; it is not given a plausible-looking vector so that it can be
  counted.
* Report a match that proves nothing. A law with a yield surface is driven past
  it, and the run is only admitted if the plastic state actually moved. A deck
  that stays elastic compares the elastic branch of both builds and says
  nothing about the rest, which is what the activation check is for.

    python tools/run_abaqus_paired_round.py --work-dir /tmp/abq_round
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.app.engine import validate_in_abaqus  # noqa: E402
from umat_oti.fortran.scanner import analyze_fortran_source  # noqa: E402
from umat_oti.validation.abaqus_runner import abaqus_available  # noqa: E402

CONTRACTS = REPO_ROOT / "parameter_sensitivity" / "contracts"
MODELS = REPO_ROOT / "parameter_sensitivity" / "models"
CORPUS_SNAPSHOT = REPO_ROOT / "parameter_sensitivity" / "corpus_snapshot.json"
DEFAULT_RESULTS = REPO_ROOT / "paper_results" / "abaqus_paired"

COLUMNS = (
    "model", "status", "material_constants_source", "nprops", "ntens", "nstatv",
    "load_case", "plasticity_expected", "plasticity_reached",
    "max_abs_difference", "max_rel_difference",
    "stress_pass", "statev_pass", "ddsdde_pass", "convergence_pass",
    "activation_pass", "environment_caveat", "blocker", "seconds",
)


def _corpus_candidates(snapshot_root: Path | None) -> dict[str, dict[str, Any]]:
    """Corpus sources that declare a material and live in one file.

    A multi-file source needs its dependency closure resolved and emitted
    before Abaqus can compile it, which is the corpus round's job, not this
    one. Those are reported as out of scope rather than skipped silently.
    """
    if not CORPUS_SNAPSHOT.is_file():
        return {}
    snapshot = json.loads(CORPUS_SNAPSHOT.read_text(encoding="utf-8"))
    root = snapshot_root or Path(
        snapshot.get("default_snapshot_root", "")).expanduser()
    found: dict[str, dict[str, Any]] = {}
    for candidate in snapshot.get("candidates", []):
        material = candidate.get("material") or {}
        props = material.get("props")
        if not props:
            continue
        source = None
        for base in (root, root / "permissive"):
            for repository in (candidate.get("repository") or "", ""):
                guess = Path(base) / repository / str(candidate.get("source", ""))
                if guess.is_file():
                    source = guess
                    break
            if source:
                break
        if source is None:
            continue
        found[candidate["id"]] = {
            "props": [float(v) for v in props],
            "ntens": int(candidate["ntens"]),
            "nstatv": int(candidate["nstatv"]),
            "source": source,
        }
    return found


def _declared(model: str) -> dict[str, Any] | None:
    path = CONTRACTS / f"{model}.json"
    if not path.is_file():
        return None
    contract = json.loads(path.read_text(encoding="utf-8"))
    driver = contract.get("material_point_driver") or {}
    props = driver.get("static_props")
    if not props:
        return None
    state = contract.get("state_variables") or []
    return {
        "props": [float(v) for v in props],
        "ntens": int(contract["ntens"]),
        "nstatv": len(state),
        "state_names": [str(s.get("name", "")).upper() for s in state],
    }


def _load_case_for(source: Path) -> tuple[str, bool]:
    """How hard to drive the deck, from the same signal that grades the result.

    The validation workspace decides whether to expect plasticity by scanning
    the source for a yield surface, a hardening law and a plastic strain. If
    this round picked the load case by any other rule the two could disagree,
    and they did: six models were driven with a 1e-4 elastic step while the
    activation check waited for a plastic state that the deck was never going
    to produce, and reported the source as failing. Asking the same question
    once means the deck and the check cannot part company.
    """
    indicators = analyze_fortran_source(Path(source)).get("plasticity_indicators") or {}
    if bool(indicators.get("is_plasticity_candidate")):
        return "single element plastic probe", True
    return "single element tension", False


def run_one(model: str, work_root: Path, abaqus_cmd: str,
            declared: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.time()
    row: dict[str, Any] = {name: "" for name in COLUMNS}
    row["model"] = model
    declared = declared if declared is not None else _declared(model)
    if declared is None:
        row.update(status="no_declared_material", blocker=(
            "the source declares no material vector, and this round will not "
            "invent one; it stays in the denominator unverified"))
        row["seconds"] = round(time.time() - started, 2)
        return row

    source = Path(declared.get("source") or (MODELS / model / "umat.for"))
    if not source.is_file():
        row.update(status="source_missing", blocker=f"no source at {source}")
        row["seconds"] = round(time.time() - started, 2)
        return row

    mode, expect_plastic = _load_case_for(source)
    row.update(nprops=len(declared["props"]), ntens=declared["ntens"],
               nstatv=declared["nstatv"], load_case=mode,
               plasticity_expected=expect_plastic)

    outcome = validate_in_abaqus(
        source_text=source.read_text(errors="replace"), name=model,
        seed="DSTRAN", output="STRESS", target="DDSDDE",
        ntens=declared["ntens"], order=1, abaqus_cmd=abaqus_cmd,
        test_mode=mode, work_root=str(work_root / model),
        material_props=declared["props"])

    stage = str(outcome.get("stage") or "")
    vdir = Path(str(outcome.get("vdir") or work_root / model))
    report = _read(vdir / "comparison_report.json")
    validation = _read(vdir / "validation_report.json")
    row["material_constants_source"] = validation.get("material_constants_source", "")
    caveats = report.get("warnings") or []
    row["environment_caveat"] = "; ".join(c[:120] for c in caveats)[:400]

    for key, column in (("stress_comparison", "stress_pass"),
                        ("state_variable_comparison", "statev_pass"),
                        ("ddsdde_comparison", "ddsdde_pass"),
                        ("convergence_comparison", "convergence_pass"),
                        ("activation_check", "activation_pass")):
        block = report.get(key)
        if isinstance(block, dict) and "pass" in block:
            row[column] = bool(block["pass"])
    activation = report.get("activation_check") or {}
    reached = (activation.get("original_plasticity_active"),
               activation.get("otis_plasticity_active"))
    if reached != (None, None):
        row["plasticity_reached"] = bool(reached[0]) and bool(reached[1])
    row["max_abs_difference"] = outcome.get("max_abs_diff", "")
    row["max_rel_difference"] = outcome.get("max_rel_diff", "")

    if report.get("status") == "passed" and outcome.get("ok"):
        row["status"] = "passed"
    elif _only_the_tangent_differs(row, source):
        # Both builds agree on what the material did -- same stress, same
        # state, same convergence -- and disagree only on the tangent they
        # hand back. That is what a source whose own DDSDDE is an elastic
        # predictor looks like once the transform replaces it with the
        # consistent one, and comparing the two against each other cannot say
        # which is right. This route reports the disagreement and declines to
        # adjudicate it; the offline route judges the generated tangent
        # against an independent reference instead.
        predictor, evidence = tangent_is_an_elastic_predictor(source)
        row["status"] = "tangent_not_comparable"
        row["blocker"] = (
            "the state the material reached and the convergence behaviour "
            "agree between the two builds; the returned tangents differ by "
            f"{row['max_rel_difference']} relative, and the converged stress "
            "follows the tangent Abaqus was given. The source leaves DDSDDE "
            f"at the elastic predictor ({evidence}), so replacing it is what "
            "the transform is for and the two tangents must differ. A paired "
            "run holds only those two and cannot say which is right; the "
            "offline route judges the generated tangent against an "
            "independent reference instead. Not counted as verified here.")
    else:
        row["status"] = report.get("status") or stage or "failed"
        row["blocker"] = (outcome.get("message")
                          or "; ".join(report.get("errors") or [])
                          or stage)[:400]
    row["seconds"] = round(time.time() - started, 2)
    return row


#: A yield test, in the vocabulary these sources use for one.
_YIELD_CONDITION = re.compile(
    r"\b(SMISES|SEQUIV|FBAR|SYIEL|SYIELD|YIELD|PHI|FTRIAL)\b", re.IGNORECASE)


def tangent_is_an_elastic_predictor(source: Path) -> tuple[bool, str]:
    """Does the source leave DDSDDE at the elastic predictor when it yields?

    A model that never touches DDSDDE inside its yield branch returns the same
    stiffness whether or not the increment was plastic. That is a predictor,
    not a consistent tangent, and replacing it is the whole purpose of the
    transform -- so the two builds must return different tangents, and a
    comparison between them cannot say which is right. Read off the source
    rather than assumed, because getting this wrong in the other direction
    would excuse a genuine disagreement.
    """
    lines = Path(source).read_text(errors="replace").splitlines()
    depth = 0
    inside_yield = False
    total = 0
    inside = 0
    for raw in lines:
        if raw[:1] in "Cc*!":
            continue
        statement = raw[6:] if len(raw) > 6 else ""
        upper = statement.upper()
        if re.search(r"\bIF\s*\(.*\)\s*THEN\s*$", upper):
            depth += 1
            if depth == 1 and _YIELD_CONDITION.search(upper):
                inside_yield = True
        elif re.match(r"\s*END\s*IF\b", upper):
            depth -= 1
            if depth <= 0:
                inside_yield = False
        if re.match(r"\s*DDSDDE\s*\(", upper):
            total += 1
            if inside_yield:
                inside += 1
    evidence = (f"{total} assignments to DDSDDE, {inside} of them inside a "
                f"yield branch")
    return (total > 0 and inside == 0), evidence


def _only_the_tangent_differs(row: dict[str, Any], source: Path | None = None) -> bool:
    """The two builds disagree only because of a tangent they had to disagree on.

    The state the material reached and the convergence behaviour must agree --
    those are what the paired run can actually adjudicate. The stress is
    allowed to differ here, and only here: Abaqus drives equilibrium with the
    tangent the subroutine returns, so two builds returning different tangents
    take different iterate paths and land on slightly different converged
    stresses. That is a consequence of the tangent difference, not independent
    evidence of one. It is admitted only when the source is shown to leave
    DDSDDE at the elastic predictor; without that evidence a stress
    disagreement stays a failure.
    """
    if row.get("ddsdde_pass") is not False:
        return False
    if any(row.get(name) is False for name in ("statev_pass", "convergence_pass",
                                               "activation_pass")):
        return False
    if row.get("stress_pass") is False:
        if source is None:
            return False
        predictor, _ = tangent_is_an_elastic_predictor(source)
        return predictor
    return True


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--abaqus", default="/usr/bin/abaqus")
    parser.add_argument("--model", action="append", default=None,
                        help="run only these models (repeatable)")
    parser.add_argument("--corpus", action="store_true",
                        help="also run the pinned corpus sources that declare "
                             "a material and live in a single file")
    parser.add_argument("--snapshot-root", type=Path, default=None)
    args = parser.parse_args(argv)

    if not abaqus_available(args.abaqus):
        print(f"Abaqus not found at {args.abaqus}; nothing was run and nothing "
              "is recorded as verified.")
        return 2

    benchmark = sorted(p.stem for p in CONTRACTS.glob("*.json"))
    corpus = _corpus_candidates(args.snapshot_root) if args.corpus else {}
    models = benchmark + sorted(corpus)
    if args.model:
        models = [m for m in models if m in set(args.model)]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, model in enumerate(models, start=1):
        print(f"[abaqus {index}/{len(models)}] {model}", flush=True)
        row = run_one(model, args.work_dir, args.abaqus, corpus.get(model))
        print(f"    {row['status']}  rel={row['max_rel_difference']}  "
              f"plastic={row['plasticity_reached']}  {row['seconds']}s", flush=True)
        rows.append(row)

    passed = [r for r in rows if r["status"] == "passed"]
    tangent_only = [r for r in rows if r["status"] == "tangent_not_comparable"]
    summary = {
        "sources": len(rows),
        "passed": len(passed),
        "tangent_not_comparable": len(tangent_only),
        "not_passed": len(rows) - len(passed),
        "declared_material": sum(1 for r in rows if r["material_constants_source"].startswith("declared")),
        "plasticity_expected": sum(1 for r in rows if r["plasticity_expected"] is True),
        "plasticity_reached": sum(1 for r in rows if r["plasticity_reached"] is True),
        "with_environment_caveat": sum(1 for r in rows if r["environment_caveat"]),
        "worst_relative_difference": max(
            (float(r["max_rel_difference"]) for r in rows
             if isinstance(r["max_rel_difference"], (int, float))), default=None),
    }
    print(json.dumps(summary, indent=2))
    for row in rows:
        if row["status"] != "passed":
            print(f"  not passed: {row['model']}: {row['blocker'][:150]}")

    if args.results_dir:
        args.results_dir.mkdir(parents=True, exist_ok=True)
        csv_path = args.results_dir / "abaqus_paired_round.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        (args.results_dir / "abaqus_paired_round.json").write_text(
            json.dumps({"summary": summary, "rows": rows}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
