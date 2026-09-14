"""RegressionService: run the frozen fixtures and compare to a baseline.

The frozen fixtures are the project's own evidence that a change did not break
what already worked. This service lists them, compares a results file against
the baseline, and reports what agreed, what disagreed and -- the part that keeps
getting lost -- what **did not run**.

The three are never merged. A fixture that did not run is not a fixture that
agreed and it is not one that failed, and a regression report whose numbers do
not add back to the number of fixtures it started with refuses to be published
rather than quietly dropping the difference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT, TOOLS, read_jsonl
from .gates import FALSE, NOT_ESTABLISHED, TRUE, read_gates
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.records import utc_now

__all__ = ["FixtureOutcome", "RegressionReport", "RegressionService",
           "REGRESSION_TOOL"]

#: The batch tool that replays the frozen experiments. Building its argument
#: list is this service's job and not a screen's: the interface must not
#: assemble a command, and two places that build it drift apart the first time
#: a flag changes.
REGRESSION_TOOL = "verify_store_in_abaqus.py"

SERVICE = "regression"

#: The three states a fixture can be in after a regression run, and there is no
#: fourth that means "probably fine".
AGREED = "agreed"
DISAGREED = "disagreed"
DID_NOT_RUN = "did_not_run"


@dataclass
class FixtureOutcome:
    fixture: str
    source_id: str
    state: str
    detail: str = ""
    baseline_stage: str = ""
    observed_stage: str = ""
    gates_that_did_not_hold: list[str] = field(default_factory=list)
    gates_never_established: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fixture": self.fixture, "source_id": self.source_id,
            "state": self.state, "detail": self.detail,
            "baseline_stage": self.baseline_stage,
            "observed_stage": self.observed_stage,
            "gates_that_did_not_hold": list(self.gates_that_did_not_hold),
            "gates_never_established": list(self.gates_never_established),
        }


@dataclass
class RegressionReport:
    baseline: str = ""
    results: str = ""
    outcomes: list[FixtureOutcome] = field(default_factory=list)

    @property
    def agreed(self) -> list[FixtureOutcome]:
        return [o for o in self.outcomes if o.state == AGREED]

    @property
    def disagreed(self) -> list[FixtureOutcome]:
        return [o for o in self.outcomes if o.state == DISAGREED]

    @property
    def did_not_run(self) -> list[FixtureOutcome]:
        return [o for o in self.outcomes if o.state == DID_NOT_RUN]

    @property
    def denominator_check(self) -> dict:
        parts = len(self.agreed) + len(self.disagreed) + len(self.did_not_run)
        return {"entries_in_baseline": len(self.outcomes), "sums_to": parts,
                "sums": parts == len(self.outcomes)}

    @property
    def passed(self) -> bool:
        """Only when every baseline entry ran and every one agreed.

        A run in which some fixtures did not run has not passed. It has not
        failed either -- it is incomplete, and :attr:`did_not_run` is how a
        caller tells the difference.
        """
        return bool(self.outcomes) and not self.disagreed and not self.did_not_run

    def as_dict(self) -> dict:
        return {
            "baseline": self.baseline, "results": self.results,
            "entries_in_baseline": len(self.outcomes),
            "agreed": [o.as_dict() for o in self.agreed],
            "disagreed": [o.as_dict() for o in self.disagreed],
            "did_not_run": [o.as_dict() for o in self.did_not_run],
            "counts": {"agreed": len(self.agreed),
                       "disagreed": len(self.disagreed),
                       "did_not_run": len(self.did_not_run)},
            "denominator_check": self.denominator_check,
            "passed": self.passed,
            "what_passed_means": (
                "every entry in the baseline ran and every one agreed. A run "
                "in which some entries did not run is incomplete, not passed."),
        }


class RegressionService:
    """Compare a run against the frozen baseline."""

    def __init__(self, *, repo_root: Path = REPO_ROOT,
                 baseline_path: Optional[Path] = None,
                 fixtures_dir: Optional[Path] = None) -> None:
        self.repo_root = Path(repo_root)
        self.baseline_path = Path(baseline_path or
                                  self.repo_root / "umat" / "baseline.json")
        self.fixtures_dir = Path(fixtures_dir or
                                 self.repo_root / "tests" / "fixtures" / "verified")

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def list_fixtures(self) -> ServiceResult:
        """Every frozen fixture on disk, with the baseline it belongs to."""
        result = ServiceResult(
            service=SERVICE, outcome="listed",
            provenance=self._provenance(fixtures=str(self.fixtures_dir),
                                        baseline=str(self.baseline_path)))
        fixtures = []
        for path in sorted(self.fixtures_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                result.add("fixture_unreadable",
                           f"{path}: {type(error).__name__}: {error}",
                           where=str(path), severity="warning")
                fixtures.append({"path": str(path), "readable": False})
                continue
            fixtures.append({
                "path": str(path), "readable": True,
                "schema": payload.get("schema", ""),
                "source_id": payload.get("source_id", ""),
                "source_sha256": payload.get("source_sha256", ""),
                "increments_carried": (payload.get("finite_history") or {})
                .get("increments_carried"),
            })
        result.data = {"fixtures": fixtures, "count": len(fixtures),
                       "fixtures_dir": str(self.fixtures_dir)}
        if not fixtures:
            result.outcome = "no_fixtures"
            result.add("no_fixtures_found",
                       f"no frozen fixtures under {self.fixtures_dir}; that is "
                       f"an empty directory, not a passing regression suite",
                       where=str(self.fixtures_dir), severity="warning")
        return result

    def compare_to_baseline(self, results_path: Path, *,
                            only: Optional[list[str]] = None) -> ServiceResult:
        """Compare a results file against the frozen baseline, entry by entry."""
        results_path = Path(results_path)
        result = ServiceResult(
            service=SERVICE, outcome="compared",
            provenance=self._provenance(baseline=str(self.baseline_path),
                                        results=str(results_path),
                                        only=only))
        if not self.baseline_path.is_file():
            result.add("baseline_missing",
                       f"{self.baseline_path} does not exist, so there is "
                       f"nothing to compare against. An absent baseline is not "
                       f"a baseline everything matches.",
                       where=str(self.baseline_path))
            result.outcome = "no_baseline"
            return result
        baseline = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        entries = list(baseline.get("entries") or [])

        observed: dict[str, dict] = {}
        for row in read_jsonl(results_path):
            if "unparseable" in row:
                result.add("unreadable_result_line",
                           "a line in the results file would not parse",
                           where=str(results_path), severity="warning")
                continue
            key = str(row.get("source") or "")
            if key:
                observed[key] = row

        report = RegressionReport(baseline=str(self.baseline_path),
                                  results=str(results_path))
        for entry in entries:
            source_id = str(entry.get("source") or "")
            if only and source_id not in only:
                continue
            expected_stage = str(entry.get("stage") or "")
            row = observed.get(source_id)
            if row is None:
                report.outcomes.append(FixtureOutcome(
                    fixture=str(entry.get("id") or source_id),
                    source_id=source_id, state=DID_NOT_RUN,
                    baseline_stage=expected_stage,
                    detail=(f"{source_id} is in the baseline and is not in "
                            f"{results_path.name}. It did not run; that is "
                            f"neither an agreement nor a disagreement.")))
                continue
            gates = read_gates(row)
            observed_stage = str(row.get("stage") or "")
            agreed = observed_stage == expected_stage
            report.outcomes.append(FixtureOutcome(
                fixture=str(entry.get("id") or source_id),
                source_id=source_id,
                state=AGREED if agreed else DISAGREED,
                baseline_stage=expected_stage,
                observed_stage=observed_stage,
                detail=("" if agreed else
                        f"the baseline has this entry at {expected_stage!r} "
                        f"and this run put it at {observed_stage!r}"),
                gates_that_did_not_hold=[r.gate for r in gates.readings
                                         if r.reading == FALSE],
                gates_never_established=[r.gate for r in gates.readings
                                         if r.reading == NOT_ESTABLISHED]))

        result.data = report
        check = report.denominator_check
        if not check["sums"]:
            result.add("denominator_does_not_sum",
                       f"the outcome counts add to {check['sums_to']} over "
                       f"{check['entries_in_baseline']} baseline entries; this "
                       f"report must not be published",
                       where=str(self.baseline_path))
        result.outcome = "passed" if report.passed else (
            "incomplete" if report.did_not_run and not report.disagreed
            else "failed")
        if report.did_not_run:
            result.add("fixtures_did_not_run",
                       f"{len(report.did_not_run)} baseline entr(ies) did not "
                       f"run in this results file, so this regression is "
                       f"incomplete rather than passed",
                       where=str(results_path), severity="warning")
        result.evidence_paths["baseline"] = str(self.baseline_path)
        result.evidence_paths["results"] = str(results_path)
        return result

    # -- running -----------------------------------------------------------

    def regression_command(self, *, work_dir: Path, results_dir: Path,
                           only: str = "", limit: int = 0, jobs: int = 1,
                           timeout: Optional[int] = None) -> list[str]:
        """The argv for a regression replay. Built here, never in a callback.

        A replay rather than a search: ``--mode regression --no-discovery``
        against the frozen baseline, so the run reproduces the recorded
        experiment instead of looking for a new one. ``--jobs`` defaults to 1
        because the licence pool is shared and contended.
        """
        import sys  # noqa: PLC0415

        command = [
            sys.executable, str(TOOLS / REGRESSION_TOOL),
            "--mode", "regression",
            "--no-discovery",
            "--baseline", str(self.baseline_path),
            "--work-dir", str(Path(work_dir)),
            "--results-dir", str(Path(results_dir)),
            "--jobs", str(int(jobs)),
        ]
        if only:
            command += ["--only", str(only)]
        if limit:
            command += ["--limit", str(int(limit))]
        if timeout:
            command += ["--timeout", str(int(timeout))]
        return command

    def submit_run(self, execution, *, work_dir: Path, results_dir: Path,
                   case_id: str = "regression", only: str = "",
                   limit: int = 0, jobs: int = 1,
                   timeout: Optional[int] = None) -> ServiceResult:
        """Start a regression replay as a tracked, cancellable job.

        ``execution`` is an :class:`~umat_oti.services.AbaqusExecutionService`.
        The replay is a local process this workflow owns, so it is spawned and
        tracked by its exact pid -- which is what makes it stoppable. The
        Abaqus jobs it launches are its own children inside the process group
        it was given; stopping it stops them, and nothing outside that group is
        ever signalled.
        """
        result = ServiceResult(
            service=SERVICE, outcome="submitted",
            provenance=self._provenance(work_dir=str(work_dir),
                                        results_dir=str(results_dir),
                                        only=only, jobs=jobs))
        tool = TOOLS / REGRESSION_TOOL
        if not tool.is_file():
            result.add("regression_tool_missing",
                       f"{tool} is not present, so a regression cannot be run. "
                       f"The replay rules are not reimplemented here.",
                       where=str(tool))
            result.outcome = "refused"
            return result
        if not self.baseline_path.is_file():
            result.add("baseline_missing",
                       f"{self.baseline_path} does not exist; a regression "
                       f"with no baseline would compare against nothing",
                       where=str(self.baseline_path))
            result.outcome = "refused"
            return result

        command = self.regression_command(work_dir=work_dir,
                                          results_dir=results_dir, only=only,
                                          limit=limit, jobs=jobs,
                                          timeout=timeout)
        submitted = execution.submit_local(
            case_id=case_id, command=command, kind="regression",
            source_paths=[self.baseline_path],
            metadata={"baseline": str(self.baseline_path),
                      "results_dir": str(results_dir),
                      "only": only, "jobs": jobs})
        result.data = submitted.data
        result.problems.extend(submitted.problems)
        result.ok = submitted.ok
        result.outcome = submitted.outcome
        result.evidence_paths.update(submitted.evidence_paths)
        return result

    def run_selected(self, source_ids: list[str], results_path: Path) -> ServiceResult:
        """Compare only these entries against the baseline."""
        return self.compare_to_baseline(results_path, only=source_ids)

    def run_all(self, results_path: Path) -> ServiceResult:
        """Compare every baseline entry against this results file."""
        return self.compare_to_baseline(results_path)
