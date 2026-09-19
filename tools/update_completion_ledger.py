#!/usr/bin/env python
"""Rewrite docs/COMPLETION_LEDGER.md from the evidence of one clean-clone run.

The ledger has one row per requirement. ``tools/ledger_rows.json`` (identical in
UMAT_source_transformation and Residual_Assembler) says, for every row, which
test node ids, clean-install gate checks and example steps demonstrate it, or
which external resource it needs, or what is missing. This script reads a
clean-clone run directory and sets each row's status from that evidence alone:

* ``PASS: reproduced from a clean installation`` -- every mapped test PASSED
  (a skip is not a pass) in the run's JUnit XML, every mapped gate check and
  example step succeeded, the gate step exited 0 and its report says passed;
* ``BLOCKED: <resource>`` -- the row needs a resource the run does not exercise;
* ``IMPLEMENTED - not yet reproduced from clean install`` -- the implementation
  exists but the run's evidence for the row is missing or failed;
* ``NOT STARTED`` -- nothing implements the row.

The run directory must hold ``summary.tsv``, ``ra_suite.xml``,
``umat_suite.xml``, ``ra_head.txt``, ``umat_head.txt``,
``usage/RA/usage_examples.json``, ``usage/UMAT/usage_examples.json`` and
``gate/report.json``, as the clean-clone script writes them. If any is missing
or unreadable the script refuses to run and changes nothing.

Usage, from the root of either repository::

    python tools/update_completion_ledger.py RUN_DIR
    python tools/update_completion_ledger.py RUN_DIR --out /tmp/ledger.md --report /tmp/rows.json

The output depends only on the run directory and the mapping file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "tools" / "ledger_rows.json"
LEDGER = ROOT / "docs" / "COMPLETION_LEDGER.md"

REPOSITORIES = {
    "UMAT": "UMAT_source_transformation",
    "RA": "Residual_Assembler",
}
GITHUB = "https://github.com/AMMS-Lab-UTSA/{name}/blob/main/{path}"

PASS = "PASS: reproduced from a clean installation"
IMPLEMENTED = "IMPLEMENTED - not yet reproduced from clean install"
NOT_STARTED = "NOT STARTED"
BLOCKED = "BLOCKED: "

#: Steps the clean-clone script records in summary.tsv. Each must be present;
#: its exit code is evidence, its absence means the run did not finish.
REQUIRED_STEPS = ("clone_ra", "clone_umat", "gate", "suite_ra", "suite_umat", "examples")

#: Files the run directory must hold.
REQUIRED_FILES = ("summary.tsv", "ra_suite.xml", "umat_suite.xml", "ra_head.txt",
                  "umat_head.txt", "usage/RA/usage_examples.json",
                  "usage/UMAT/usage_examples.json", "gate/report.json")

#: Pseudo gate checks that stand for a whole suite step exiting 0.
SUITE_STEPS = {"suite_ra": "suite_ra", "suite_umat": "suite_umat"}

#: What each named gate check means, for the preamble and --help.
GATE_CHECKS = {
    "branch_and_clean_trees": "both clones on main, clean, at the published heads",
    "base_python": "base Python >= 3.10 with ctypes, ssl and venv",
    "gfortran": "gfortran found and runs",
    "venv": "new empty virtual environment created",
    "wheels_built": "exactly two wheels built from the clean trees",
    "wheels_installed": "both wheels installed with their extras",
    "pip_check": "pip check reports consistent dependencies",
    "installed_probe": "packages import from site-packages with their data files",
    "provider_build": "umat-oti-provider build of the J2 contract",
    "presentation_request": "resasm request on a real ODB, analytic J2 derivatives",
    "source_denied_request": "same request with material-source reads denied",
    "gui_render": "both Streamlit apps render without exception",
    "gui_servers": "both Streamlit apps reach HTTP readiness",
    "cantilever_request": "resasm request on the full J2 cantilever",
    "cantilever_reequilibrate": "re-equilibrated cantilever obeys the homogeneity identity",
}


class Incomplete(Exception):
    """The run directory does not hold a finished clean-clone run."""


# --------------------------------------------------------------------------
# reading the run directory

def read_summary(path: Path) -> dict[str, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t")[:2] != ["step", "exit"]:
        raise Incomplete(f"{path.name}: header is not 'step<TAB>exit...'")
    steps: dict[str, int] = {}
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) < 2 or not re.fullmatch(r"-?\d+", cells[1]):
            raise Incomplete(f"{path.name}:{number}: unreadable line {line!r}")
        steps[cells[0]] = int(cells[1])
    missing = [name for name in REQUIRED_STEPS if name not in steps]
    if missing:
        raise Incomplete(f"{path.name}: steps not recorded: {', '.join(missing)}")
    return steps


def read_head(path: Path) -> str:
    head = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise Incomplete(f"{path.name}: not a full commit SHA: {head!r}")
    return head


def read_junit(path: Path) -> tuple[dict[tuple[str, str], str], str]:
    """Map (classname, name) to passed/failed/error/skipped; return the run date."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as error:
        raise Incomplete(f"{path.name}: not valid JUnit XML ({error})") from None
    cases: dict[tuple[str, str], str] = {}
    for case in tree.iter("testcase"):
        key = (case.get("classname") or "", case.get("name") or "")
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        # a node reported twice (e.g. a teardown error after a pass) keeps the worse outcome
        if cases.get(key, "passed") == "passed":
            cases[key] = outcome
    suites = [tree.getroot()] + list(tree.getroot().iter("testsuite"))
    stamps = sorted(s.get("timestamp", "")[:10] for s in suites if s.get("timestamp"))
    return cases, (stamps[-1] if stamps else "")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise Incomplete(f"{path}: not valid JSON ({error})") from None


def load_run(run: Path) -> dict:
    if not run.is_dir():
        raise Incomplete(f"{run} is not a directory")
    missing = [name for name in REQUIRED_FILES if not (run / name).is_file()]
    if missing:
        raise Incomplete("missing from the run directory: " + ", ".join(missing))
    evidence = {"steps": read_summary(run / "summary.tsv"),
                "heads": {"RA": read_head(run / "ra_head.txt"),
                          "UMAT": read_head(run / "umat_head.txt")},
                "junit": {}, "examples": {}, "dates": []}
    for key, name in (("RA", "ra_suite.xml"), ("UMAT", "umat_suite.xml")):
        cases, date = read_junit(run / name)
        if not cases:
            raise Incomplete(f"{name}: no test cases")
        evidence["junit"][key] = cases
        if date:
            evidence["dates"].append(date)
    for key in ("RA", "UMAT"):
        payload = read_json(run / "usage" / key / "usage_examples.json")
        if payload.get("phase") != "examples" or not isinstance(payload.get("commands"), list):
            raise Incomplete(f"usage/{key}/usage_examples.json is not an examples-phase record")
        evidence["examples"][key] = payload["commands"]
    report = read_json(run / "gate" / "report.json")
    if not isinstance(report.get("commands"), list):
        raise Incomplete("gate/report.json has no command list")
    evidence["gate"] = report
    return evidence


# --------------------------------------------------------------------------
# judging evidence

def mangle(node: str) -> tuple[str, str]:
    """pytest's JUnit (classname, name) for a node id."""
    path, bracket, params = node.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def test_outcome(cases: dict[tuple[str, str], str], node: str) -> str:
    """passed, or why not. A node without [params] stands for all its parametrizations."""
    key = mangle(node)
    if key in cases:
        return cases[key]
    if "[" not in node:
        classname, name = key
        family = [outcome for (cls, case), outcome in cases.items()
                  if cls == classname and case.startswith(name + "[")]
        if family:
            bad = sorted(set(family) - {"passed"})
            return "passed" if not bad else "/".join(bad)
    return "absent"


def gate_checks(report: dict) -> dict[str, bool]:
    commands = report.get("commands", [])

    def ran(predicate) -> bool:
        chosen = [c for c in commands if predicate([str(a) for a in c.get("argv", [])])]
        return bool(chosen) and all(c.get("returncode") == 0 for c in chosen)

    def probe(text):
        return lambda a: "-c" in a[:-1] and text in a[a.index("-c") + 1]

    repositories = report.get("repositories") or {}
    presentation = report.get("presentation") or {}
    errors = presentation.get("analytic_errors") or {}
    servers = report.get("servers") or {}
    gui = report.get("gui") or {}
    cantilever = report.get("cantilever") or {}
    origins = (report.get("installed") or {}).get("origins") or {}
    bound = cantilever.get("homogeneity_bound")
    residual = cantilever.get("homogeneity_residual")
    return {
        "branch_and_clean_trees": report.get("final_branch_clean_clone") is True
            and len(repositories) == 2
            and all(not str(r.get("status", "")).strip() for r in repositories.values())
            and ran(lambda a: a[:1] == ["git"] and "status" in a),
        "base_python": ran(probe("import ctypes, ssl, venv")),
        "gfortran": ran(lambda a: a == ["gfortran", "--version"]),
        "venv": ran(lambda a: "-m" in a and "venv" in a and a.index("venv") == a.index("-m") + 1),
        "wheels_built": len(report.get("wheels") or {}) == 2 and ran(lambda a: "pip" in a and "wheel" in a),
        "wheels_installed": ran(lambda a: "pip" in a and "install" in a and any(".whl" in x for x in a)),
        "pip_check": ran(lambda a: a[-2:] == ["pip", "check"]),
        "installed_probe": len(origins) >= 7 and bool((report.get("installed") or {}).get("resources")),
        "provider_build": ran(lambda a: a[:1] and a[0].endswith("umat-oti-provider") and a[1:2] == ["build"]),
        "presentation_request": len(errors) == 3 and all(abs(v) < 2e-5 for v in errors.values())
            and len(presentation.get("outputs") or []) == 3,
        "source_denied_request": presentation.get("source_denied_outputs_identical") is True,
        "gui_render": len(gui) == 2,
        "gui_servers": len(servers) == 2 and all(s.get("ready") is True for s in servers.values()),
        "cantilever_request": "request_seconds" in cantilever,
        "cantilever_reequilibrate": isinstance(bound, (int, float)) and isinstance(residual, (int, float))
            and residual <= bound and (cantilever.get("plastic_increments") or 0) > 0,
    }


def example_passed(records: list[dict], name: str) -> str:
    chosen = [r for r in records if r.get("name") == name]
    if not chosen:
        return "absent"
    record = chosen[-1]
    if record.get("returncode") != 0:
        return f"exit {record.get('returncode')}"
    if "verification" in record and not (record["verification"] or {}).get("passed"):
        return "verification failed"
    if "proof" in record and not ((record["proof"] or {}).get("data") or {}).get("passed"):
        return "proof failed"
    return "passed"


def judge(row: dict, evidence: dict) -> tuple[str, list[str]]:
    """Status and the reasons it is not PASS."""
    if row["class"] == "b":
        return BLOCKED + row["blocked_by"], []
    problems: list[str] = []
    if row["class"] == "c":
        problems.append("not demonstrated: " + row["missing"])
    else:
        for test in row["tests"]:
            outcome = test_outcome(evidence["junit"][test["repo"]], test["node"])
            if outcome != "passed":
                problems.append(f"{test['repo']} {test['node']}: {outcome}")
        gate_ok = evidence["steps"]["gate"] == 0 and evidence["gate"].get("passed") is True
        checks = gate_checks(evidence["gate"])
        for name in row["gate"]:
            if name in SUITE_STEPS:
                if evidence["steps"][SUITE_STEPS[name]] != 0:
                    problems.append(f"{name} exited {evidence['steps'][SUITE_STEPS[name]]}")
            elif not gate_ok:
                problems.append(f"gate {name}: gate did not pass")
            elif not checks[name]:
                problems.append(f"gate {name}: check not satisfied")
        for step in row["examples"]:
            repo, name = step.split(":", 1)
            if evidence["steps"]["examples"] != 0:
                outcome = example_passed(evidence["examples"][repo], name)
                problems.append(f"example {step}: phase exited {evidence['steps']['examples']}"
                                + ("" if outcome == "passed" else f", step {outcome}"))
                continue
            outcome = example_passed(evidence["examples"][repo], name)
            if outcome != "passed":
                problems.append(f"example {step}: {outcome}")
    if not problems:
        return PASS, []
    return (IMPLEMENTED if row["implementation"] else NOT_STARTED), problems


# --------------------------------------------------------------------------
# rendering

def link(here: str, repo: str, path: str, text: str | None = None) -> str:
    """A link that resolves from docs/ of repository `here`."""
    if repo == here:
        return f"[{text or path}](../{path})"
    name = REPOSITORIES[repo]
    return f"[{text or name + '/' + path}]({GITHUB.format(name=name, path=path)})"


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_tests(here: str, row: dict) -> str:
    parts: list[str] = []
    files: dict[tuple[str, str], int] = {}
    for test in row["tests"]:
        key = (test["repo"], test["node"].split("::", 1)[0])
        files[key] = files.get(key, 0) + 1
    for (repo, path), count in files.items():
        parts.append(link(here, repo, path) + (f" ({count} tests)" if count > 1 else ""))
    gate = [name for name in row["gate"] if name not in SUITE_STEPS]
    if gate:
        parts.append(link(here, "RA", "scripts/clean_install_gate.py", "gate: " + ", ".join(gate)))
    suites = [name for name in row["gate"] if name in SUITE_STEPS]
    if suites:
        parts.append("whole suite: " + ", ".join(
            "Residual_Assembler offline" if name == "suite_ra" else "UMAT_source_transformation"
            for name in suites))
    if row["examples"]:
        parts.append(link(here, "RA", "scripts/audit_recovery_usage.py",
                          "examples: " + ", ".join(step.split(":", 1)[1] for step in row["examples"])))
    if row["class"] == "c":
        parts.append("not demonstrated: missing " + row["missing"])
    return "; ".join(parts) if parts else "none"


def render_command(row: dict) -> str:
    return "; ".join(f"in {REPOSITORIES[item['repo']]}: `{item['command']}`" for item in row["reproduce"])


def render(here: str, mapping: dict, evidence: dict, statuses: list[tuple[dict, str]]) -> str:
    counts = Counter("BLOCKED" if status.startswith(BLOCKED) else status for _, status in statuses)
    date = max(evidence["dates"]) if evidence["dates"] else "unknown date"
    total = len(statuses)
    lines = [
        "# Completion ledger",
        "",
        "One row per requirement of the implementation directive of 2026-09-18, shared by",
        "UMAT_source_transformation and Residual_Assembler (the two copies differ only in",
        "link paths).",
        "",
        "## Status vocabulary",
        "",
        f"- `{PASS}`: every test, gate check and example step mapped to the row succeeded",
        "  in the clean-clone run below. This is the only completed status.",
        f"- `{IMPLEMENTED}`: the implementation exists, but the clean-clone run did not",
        "  demonstrate the row: a mapped test failed, was skipped or did not run, a mapped",
        "  check or step failed, or no existing test or command demonstrates it yet (the",
        "  Test column then says what is missing).",
        "- `BLOCKED: <resource>`: demonstrating the row needs the named external resource,",
        "  which the clean-clone run does not exercise.",
        f"- `{NOT_STARTED}`: nothing implements the row.",
        "",
        "## How the statuses were computed",
        "",
        "Statuses are computed, not edited by hand. A clean-clone run cloned the published",
        "`main` branches into a new directory:",
        "",
        f"- Residual_Assembler `{evidence['heads']['RA']}`",
        f"- UMAT_source_transformation `{evidence['heads']['UMAT']}`",
        f"- run date {date}",
        "",
        "It ran the clean-install gate (Residual_Assembler `scripts/clean_install_gate.py`:",
        "wheels, a new virtual environment, the provider build, `resasm request` on a real",
        "ODB against analytic J2 derivatives, the denied-source rerun, both GUIs, the",
        "cantilever request and re-equilibration), the UMAT_source_transformation test suite",
        "and the Residual_Assembler offline suite (`-m \"not abaqus and not arc and not",
        "network\"`) as JUnit XML, and the worked examples",
        "(`scripts/audit_recovery_usage.py --phase examples`).",
        "",
        "`tools/ledger_rows.json` maps every row to the test node ids, gate checks and example",
        "steps that demonstrate it, or to the external resource it needs.",
        "`tools/update_completion_ledger.py` read the run directory and set each status: a",
        "row is PASS only when every mapped test passed (a skipped test does not count), every",
        "mapped gate check and example step succeeded, and the gate as a whole passed. The",
        "Reproduction command column gives the commands to run from a clean clone of `main`,",
        "at the root of the repository named.",
        "",
        f"Counts: {total} requirements; {counts.get(PASS, 0)} PASS; "
        f"{counts.get(IMPLEMENTED, 0)} IMPLEMENTED; {counts.get('BLOCKED', 0)} BLOCKED; "
        f"{counts.get(NOT_STARTED, 0)} NOT STARTED.",
        "",
        "| ID | Requirement | Repository | Implementation | Test | Reproduction command | Status |",
        "| -- | ----------- | ---------- | -------------- | ---- | -------------------- | ------ |",
    ]
    for row, status in statuses:
        implementation = "; ".join(link(here, item["repo"], item["path"]) for item in row["implementation"]) or "none"
        lines.append("| " + " | ".join(cell(value) for value in (
            row["id"], row["requirement"], row["repository"], implementation,
            render_tests(here, row), render_command(row), status)) + " |")
    lines += ["", f"Rows: {total}", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------

def this_repository() -> str:
    if (ROOT / "src" / "umat_oti").is_dir():
        return "UMAT"
    if (ROOT / "residual_core").is_dir():
        return "RA"
    raise SystemExit(f"{ROOT} is neither UMAT_source_transformation nor Residual_Assembler")


def load_mapping(path: Path) -> dict:
    mapping = json.loads(path.read_text(encoding="utf-8"))
    rows = mapping.get("rows", [])
    ids = [row["id"] for row in rows]
    problems = []
    if len(set(ids)) != len(ids):
        problems.append("duplicate row ids")
    for row in rows:
        kind = row.get("class")
        if kind not in ("a", "b", "c"):
            problems.append(f"{row['id']}: class {kind!r}")
        elif kind == "a" and not (row["tests"] or row["gate"] or row["examples"]):
            problems.append(f"{row['id']}: class a with no evidence mapped")
        elif kind == "b" and not row.get("blocked_by"):
            problems.append(f"{row['id']}: class b without blocked_by")
        elif kind == "c" and not row.get("missing"):
            problems.append(f"{row['id']}: class c without missing")
        for name in row["gate"]:
            if name not in GATE_CHECKS and name not in SUITE_STEPS:
                problems.append(f"{row['id']}: unknown gate check {name}")
        for step in row["examples"]:
            if step.split(":", 1)[0] not in REPOSITORIES:
                problems.append(f"{row['id']}: example step {step} names no repository")
        for test in row["tests"]:
            if test["repo"] not in REPOSITORIES:
                problems.append(f"{row['id']}: test repository {test['repo']}")
    if len(rows) != mapping.get("requirements"):
        problems.append(f"{len(rows)} rows, expected {mapping.get('requirements')}")
    if problems:
        raise SystemExit("invalid mapping " + str(path) + ":\n  " + "\n  ".join(problems))
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path, help="clean-clone run directory")
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--out", type=Path, default=LEDGER,
                        help="where to write the ledger (default: docs/COMPLETION_LEDGER.md)")
    parser.add_argument("--report", type=Path,
                        help="also write each row's status and unmet evidence as JSON")
    args = parser.parse_args(argv)
    here = this_repository()
    mapping = load_mapping(args.mapping)
    try:
        evidence = load_run(args.run)
    except (Incomplete, OSError) as error:
        print(f"refusing: {args.run} is not a complete clean-clone run: {error}", file=sys.stderr)
        return 2
    statuses, unmet = [], {}
    for row in mapping["rows"]:
        status, problems = judge(row, evidence)
        statuses.append((row, status))
        unmet[row["id"]] = {"status": status, "unmet": problems}
    args.out.write_text(render(here, mapping, evidence, statuses), encoding="utf-8")
    if args.report:
        args.report.write_text(json.dumps({"heads": evidence["heads"], "rows": unmet},
                                          indent=1, sort_keys=True) + "\n", encoding="utf-8")
    counts = Counter("BLOCKED" if s.startswith(BLOCKED) else s for _, s in statuses)
    print(f"wrote {args.out}: " + "; ".join(f"{count} {name}" for name, count in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
