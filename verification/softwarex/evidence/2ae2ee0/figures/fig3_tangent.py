"""Figure 3 (Model A consistent tangent) from archived 2ae2ee0 data.

Builder: Ada, 2026-10-27. Run with the Anaconda interpreter in isolated mode:

  C:/Users/vfn333/AppData/Local/anaconda3/python.exe -I fig3_tangent.py WORKSPACE_ROOT

Data: evidence/2ae2ee0/rounds/tangent/results/table2_ddsdde_illustrative.csv, written
by UMAT-OTI tools/run_tangent_round.py at 2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc
(byte-identical to the file committed at 8e12548). Nothing is computed here except a
unit conversion (MPa -> GPa) and the selection of three DDSDDE entries; the plotted
relative differences are the file's `relative_error` column.

Design (writing guide section 4; IR-13): markers only, so no line crosses a regime
change; UMAT-OTI filled, closed form open; log-scale relative-difference strip with
the 1e-9 tolerance as a labelled line; exact agreement (relative error 0) drawn on a
labelled floor; Voigt/Abaqus labels; "plastic" inside the band; legend below the
axes; panel letters; Okabe-Ito colours as listed in the writing guide.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

COMMIT = "2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc"
DATA = "evidence/2ae2ee0/rounds/tangent/results/table2_ddsdde_illustrative.csv"
OUT = "evidence/2ae2ee0/figures"
NAME = "figure3_tangent"
BLUE, VERMILLION, GREEN, PURPLE = "#1F4E9C", "#D55E00", "#009E73", "#CC79A7"
GREY = "#555555"
BAND = "#E6E6E6"
TOL = 1e-9
FLOOR = 1e-17  # where an exact (zero) relative difference is drawn

PANELS = [
    ((1, 1), r"DDSDDE(1,1) $=\partial\Delta\sigma_{11}/\partial\Delta\varepsilon_{11}$"),
    ((1, 2), r"DDSDDE(1,2) $=\partial\Delta\sigma_{11}/\partial\Delta\varepsilon_{22}$"),
    ((4, 4), r"DDSDDE(4,4) $=\partial\Delta\sigma_{12}/\partial\Delta\gamma_{12}$"),
]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 7.5, "axes.labelsize": 7.5,
    "axes.titlesize": 7.5, "xtick.labelsize": 7.0, "ytick.labelsize": 7.0,
    "legend.fontsize": 7.0, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
    "ytick.major.width": 0.6, "pdf.fonttype": 42, "ps.fonttype": 42,
})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    data_path = root / DATA
    rows = list(csv.DictReader(data_path.open(newline="", encoding="utf-8")))
    branch: dict[int, str] = {}
    entries: dict[tuple[int, int], dict[int, tuple[float, float, float]]] = defaultdict(dict)
    worst = 0.0
    n_resolved = 0
    for r in rows:
        inc = int(r["increment"])
        branch[inc] = r["branch"]
        entries[(int(r["row"]), int(r["column"]))][inc] = (
            float(r["oti"]), float(r["analytic_reference"]), float(r["relative_error"]))
        if r["judged_by"] == "relative":
            n_resolved += 1
            worst = max(worst, float(r["relative_error"]))
    states = sorted(branch)
    plastic = [s for s in states if branch[s] == "plastic"]

    fig = plt.figure(figsize=(6.3, 3.05))
    gs = fig.add_gridspec(2, 3, height_ratios=[2.3, 1.0], hspace=0.12, wspace=0.42,
                          left=0.085, right=0.99, top=0.86, bottom=0.25)
    for k, (key, title) in enumerate(PANELS):
        ax = fig.add_subplot(gs[0, k])
        ax_err = fig.add_subplot(gs[1, k], sharex=ax)
        for a in (ax, ax_err):
            a.axvspan(min(plastic) - 0.5, max(plastic) + 0.5, color=BAND, lw=0, zorder=0)
            for s in ("top", "right"):
                a.spines[s].set_visible(False)
            a.tick_params(length=2.2, pad=1.6)
        oti = [entries[key][s][0] / 1e3 for s in states]
        ref = [entries[key][s][1] / 1e3 for s in states]
        err = [entries[key][s][2] for s in states]
        ax.plot(states, oti, ls="none", marker="o", ms=2.6, color=BLUE, zorder=3)
        ax.plot(states, ref, ls="none", marker="o", ms=5.6, mfc="none", mec=VERMILLION,
                mew=0.8, zorder=4)
        lo, hi = min(oti + ref), max(oti + ref)
        pad = 0.18 * (hi - lo)
        ax.set_ylim(lo - pad, hi + 0.55 * pad + 0.10 * (hi - lo))
        ax.text(0.5 * (min(plastic) + max(plastic)), hi + 0.30 * pad + 0.05 * (hi - lo),
                "plastic", ha="center", va="center", fontsize=6.8, color=GREY)
        ax.set_title(f"({'abc'[k]}) " + title, loc="left", pad=3, fontsize=7.0)
        plt.setp(ax.get_xticklabels(), visible=False)
        if k == 0:
            ax.set_ylabel("tangent entry (GPa)")
        # relative-difference strip
        shown = [e if e > 0 else FLOOR for e in err]
        exact = [s for s, e in zip(states, err) if e == 0]
        nonzero = [(s, e) for s, e in zip(states, err) if e > 0]
        ax_err.plot([s for s, _ in nonzero], [e for _, e in nonzero], ls="none", marker="D",
                    ms=2.6, color=GREEN, zorder=3)
        ax_err.plot(exact, [FLOOR] * len(exact), ls="none", marker="|", ms=5.0,
                    color=GREEN, mew=0.9, zorder=3)
        ax_err.axhline(TOL, color=GREY, lw=0.7, ls=(0, (3, 1.5)), zorder=1)
        ax_err.set_yscale("log")
        ax_err.set_ylim(3e-18, 1e-7)
        ax_err.set_yticks([1e-17, 1e-13, 1e-9])
        ax_err.set_yticklabels(["0", r"$10^{-13}$", r"$10^{-9}$"])
        ax_err.text(states[-1] + 0.4, TOL * 1.8, "tolerance", ha="right", va="bottom",
                    fontsize=6.3, color=GREY)
        ax_err.set_xticks([1, 3, 5, 7, 9, 11, 13, 15])
        ax_err.set_xlim(0.3, 15.7)
        ax_err.set_xlabel("evaluation state")
        if k == 0:
            ax_err.set_ylabel("rel. diff. (–)")
        del shown
    handles = [
        Line2D([], [], ls="none", marker="o", ms=2.6, color=BLUE, label="UMAT-OTI"),
        Line2D([], [], ls="none", marker="o", ms=5.6, mfc="none", mec=VERMILLION, mew=0.8,
               label="closed form (j2_reference.py)"),
        Line2D([], [], ls="none", marker="D", ms=2.6, color=GREEN,
               label="|UMAT-OTI − closed form| / |closed form|"),
        Line2D([], [], ls="none", marker="|", ms=5.0, mew=0.9, color=GREEN,
               label="exactly equal (drawn at 0)"),
        Patch(facecolor=BAND, edgecolor="none", label="plastic states 7–13"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 0.0), handlelength=1.6, columnspacing=1.4)
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{NAME}.pdf")
    fig.savefig(out / f"{NAME}.png", dpi=600)
    plt.close(fig)

    script = Path(__file__).resolve()
    prov = {
        "figure": NAME,
        "manuscript_location": "tex/sections/03-example.tex, Figure fig:tangent (V11 Figure 3)",
        "umat_oti_commit": COMMIT,
        "data": [{"path": DATA, "sha256": sha256(data_path), "rows": len(rows)}],
        "data_producer": "UMAT-OTI tools/run_tangent_round.py via refreeze/scripts/run_rounds.sh 2ae2ee0 "
                         "(Windows 11, GNU Fortran 16.1.0, local regeneration; not the Linux freeze)",
        "script": {"path": f"{OUT}/{script.name}", "sha256": sha256(script)},
        "outputs": {f"{NAME}.pdf": sha256(out / f"{NAME}.pdf"),
                    f"{NAME}.png": sha256(out / f"{NAME}.png")},
        "conditions": {
            "model": "Model A, UMATs/UMATs/generic_ps/j2_props.f (provenance: content clean, "
                     "responsible author open, Q-64)",
            "entries_plotted": ["DDSDDE(1,1)", "DDSDDE(1,2)", "DDSDDE(4,4)"],
            "states": states, "plastic_states": plastic,
            "unit_conversion": "CSV values in MPa divided by 1000 to GPa",
            "reference": "analytic_reference column: closed-form consistent tangent "
                         "(src/umat_oti/validation/j2_reference.py)",
            "relative_difference": "relative_error column of the CSV, unchanged",
            "tolerance_line": TOL,
            "zero_floor_drawn_at": FLOOR,
        },
        "numbers_consistent_with_text": {
            "resolved_entries_all_540": n_resolved,
            "worst_relative_difference_all_resolved": worst,
            "ledger": "L21 (540/354/186, 2.188e-15)",
        },
        "environment": {"python": sys.version.split()[0], "matplotlib": matplotlib.__version__,
                        "platform": platform.platform()},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / f"{NAME}.provenance.json").write_text(json.dumps(prov, indent=1) + "\n",
                                                  encoding="utf-8", newline="\n")
    print(json.dumps(prov["numbers_consistent_with_text"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
