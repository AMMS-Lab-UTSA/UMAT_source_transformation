"""Summarise the regenerated rounds per candidate against V11's committed values.

Reads evidence/<sha7>/rounds/{psweep,internal_jacobian,tangent}/results and the
V11 committed files at 8e12548 (read with `git show`, read-only). Writes
refreeze/rounds_comparison.json and prints a table. Ada, 2026-10-27.
Usage: python refreeze/scripts/compare_rounds.py <sha7> [...]
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
CLONE = WS / "refreeze" / "src" / "ust"


def git_show(commit: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(CLONE), "show", f"{commit}:{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def tangent_metrics(text: str | None) -> dict | None:
    if not text:
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    zeros = [r for r in rows if r.get("judged_by") == "structural_zero"]
    resolved = [r for r in rows if r.get("judged_by") != "structural_zero"]
    worst = max((float(r["relative_error"]) for r in resolved), default=None)
    return {"entries": len(rows), "structural_zeros": len(zeros), "resolved": len(resolved),
            "disagree": sum(1 for r in rows if r.get("agrees") not in ("True", "true")),
            "worst_relative": worst}


def psweep_metrics(text: str | None) -> dict | None:
    if not text:
        return None
    d = json.loads(text)
    f = d.get("funnel", {})
    return {k: f.get(k) for k in ("attempted", "transformed", "primal_parity",
                                  "derivatives_verified", "parameter_directions_declared",
                                  "parameter_directions_verified", "comparison_rows_total",
                                  "comparison_rows_agreeing")} | {
        "failure_taxonomy": d.get("failure_taxonomy")}


def ij_metrics(text: str | None) -> dict | None:
    if not text:
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        out.append({k: r[k] for k in r if k and any(
            s in k.lower() for s in ("source", "model", "id", "status", "verdict",
                                     "generated", "finite", "hand", "relative"))})
    return {"rows": len(rows), "detail": out}


def first(path: Path, names: list[str]) -> str | None:
    for n in names:
        p = path / n
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


def main(argv: list[str]) -> int:
    out: dict = {}
    v11 = "8e12548"
    out["V11_committed_at_8e12548"] = {
        "tangent": tangent_metrics(git_show(v11, "paper_results/actual_umat_higher_order/j2/table2_ddsdde_illustrative.csv")),
        "psweep": psweep_metrics(git_show(v11, "paper_results/parameter_sensitivity/parameter_sensitivity_round.json")),
        "internal_jacobian": ij_metrics(git_show(v11, "paper_results/internal_jacobians/table3_internal_jacobians.csv")),
    }
    for sha in argv:
        r = WS / "evidence" / sha / "rounds"
        out[sha] = {
            "tangent": tangent_metrics(first(r / "tangent" / "results", ["table2_ddsdde_illustrative.csv"])),
            "psweep": psweep_metrics(first(r / "psweep" / "results", ["parameter_sensitivity_round.json"])),
            "internal_jacobian": ij_metrics(first(r / "internal_jacobian" / "results", [
                "table3_internal_jacobians.csv", "table3_internal_constitutive_jacobians.csv"])),
        }
    (WS / "refreeze" / "rounds_comparison.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for k, v in out.items():
        t, p = v["tangent"], v["psweep"]
        print(f"{k:28s} tangent={t and (t['entries'], t['structural_zeros'], t['resolved'], t['disagree'], t['worst_relative'])} "
              f"psweep={p and (p['derivatives_verified'], p['attempted'], p['parameter_directions_verified'], p['parameter_directions_declared'], p['comparison_rows_agreeing'], p['comparison_rows_total'])} "
              f"ij_rows={v['internal_jacobian'] and v['internal_jacobian']['rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
