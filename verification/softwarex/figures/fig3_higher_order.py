"""Figure 3 (Model A resolved second- to fourth-order stress derivatives) from 2ae2ee0 data.

Round-9 derivative (Quill, 2026-10-28) of evidence/2ae2ee0/figures/fig4_higher_order.py (Ada), made in
tex/figures/ for the layout pass: LAYOUT ONLY. The figure is drawn at the article's text width
(390 pt = 5.42 in) so that it is included at 100 % instead of being shrunk to 86 %; font sizes are
raised (base and axis labels 7.5 pt, tick labels 7.0 pt, panel titles and in-panel derivative labels
7.0 pt, legend 7.5 pt); the legend uses four columns; output name and folder changed. Data, filters,
plotted columns and every number are unchanged.
Round 10 (Quill, 2026-10-28; Vera format round m3, m5), LAYOUT ONLY: in panels (d)-(f) the x-tick
labels are the index pairs 11, 22, 33, 12 (7.0 pt, were sigma_11 ... at 6.5 pt) under the axis label
"stress component sigma_ij", so that neighbouring labels no longer touch; this docstring now states
the sizes and legend columns the code uses (it said 3 columns and 7.5 pt titles).
Run from the workspace root with: python -I tex/figures/fig3_higher_order.py .

Original builder: Ada, 2026-10-27. Run with the Anaconda interpreter in isolated mode:

  C:/Users/vfn333/AppData/Local/anaconda3/python.exe -I fig4_higher_order.py WORKSPACE_ROOT

Data: evidence/2ae2ee0/rounds/higher_order_convergence/j2/convergence_rows.csv, written by
`python -m umat_oti.validation.higher_order_convergence_study --model j2` at
2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc (source of ledger L22; Table 4). Only rows with
branch == plastic and reference_classification == resolved are drawn (20/20/26). Plotted
values are the file's `oti_normalized` and `reference_normalized` columns; panel numbers
are the maximum of its `relative_error` column. Nothing else is computed.

Design (writing guide section 4; IR-14): every series identified by (direction pattern,
stress component); colour = stress component, consistent across panels; UMAT-OTI as
filled markers on a line, reference as open markers; the state-13-only entries are
expanded into their own row of panels (d)-(f) instead of overlapping markers; neutral
legend below the axes; panel letters.
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

COMMIT = "2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc"
DATA = "evidence/2ae2ee0/rounds/higher_order_convergence/j2/convergence_rows.csv"
OUT = "figures"
NAME = "figure3_higher_order"
COLOUR = {1: "#1F4E9C", 2: "#D55E00", 3: "#009E73", 4: "#CC79A7"}
COMP = {1: r"$\sigma_{11}$", 2: r"$\sigma_{22}$", 3: r"$\sigma_{33}$", 4: r"$\sigma_{12}$"}
TICK = {1: "11", 2: "22", 3: "33", 4: "12"}  # (d)-(f) x-tick labels (round 10, m3)
GREY = "#555555"
DERIV = {
    "1|2": r"$\partial^2\sigma/\partial\varepsilon_{1}\partial\varepsilon_{2}$",
    "1|1": r"$\partial^2\sigma/\partial\varepsilon_{1}^2$",
    "1|1|2": r"$\partial^3\sigma/\partial\varepsilon_{1}^2\partial\varepsilon_{2}$",
    "1|1|1": r"$\partial^3\sigma/\partial\varepsilon_{1}^3$",
    "1|1|2|2": r"$\partial^4\sigma/\partial\varepsilon_{1}^2\partial\varepsilon_{2}^2$",
    "1|1|1|1": r"$\partial^4\sigma/\partial\varepsilon_{1}^4$",
}
MIXED = {2: "1|2", 3: "1|1|2", 4: "1|1|2|2"}
REPEATED = {2: "1|1", 3: "1|1|1", 4: "1|1|1|1"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 7.5, "axes.labelsize": 7.5,
    "axes.titlesize": 7.5, "xtick.labelsize": 7.0, "ytick.labelsize": 7.0,
    "legend.fontsize": 7.5, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
    "ytick.major.width": 0.6, "pdf.fonttype": 42, "ps.fonttype": 42,
})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sci(x: float) -> str:
    m, e = f"{x:.2e}".split("e")
    return rf"${m}\times10^{{{int(e)}}}$"


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    data_path = root / DATA
    rows = [r for r in csv.DictReader(data_path.open(newline="", encoding="utf-8"))
            if r["branch"] == "plastic" and r["reference_classification"] == "resolved"]
    counts, worst = {}, {}
    for o in (2, 3, 4):
        sel = [r for r in rows if int(r["order"]) == o]
        counts[o] = len(sel)
        worst[o] = max(float(r["relative_error"]) for r in sel)

    fig = plt.figure(figsize=(5.42, 5.6))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.0], hspace=0.62, wspace=0.50,
                          left=0.105, right=0.985, top=0.88, bottom=0.19)
    for k, order in enumerate((2, 3, 4)):
        sel = [r for r in rows if int(r["order"]) == order]
        # (a)-(c): series with more than one state (mixed pattern, states 7-13)
        ax = fig.add_subplot(gs[0, k])
        series = defaultdict(list)
        for r in sel:
            series[(r["directions"], int(r["stress_component"]))].append(
                (int(r["increment"]), float(r["oti_normalized"]), float(r["reference_normalized"])))
        for (dirs, comp), pts in sorted(series.items()):
            if len(pts) < 2:
                continue
            pts.sort()
            x = [p[0] for p in pts]
            ax.plot(x, [p[1] for p in pts], color=COLOUR[comp], lw=0.9, marker="o", ms=2.4,
                    zorder=3)
            ax.plot(x, [p[2] for p in pts], ls="none", marker="o", ms=5.4, mfc="none",
                    mec=COLOUR[comp], mew=0.7, zorder=4)
        ax.axhline(0, color=GREY, lw=0.4, zorder=1)
        ax.set_xticks(range(7, 14))
        ax.set_xlim(6.5, 13.5)
        ax.set_xlabel("plastic evaluation state")
        ax.set_title(f"({'abc'[k]}) order {order}: {DERIV[MIXED[order]]}\n"
                     f"{counts[order]} resolved\nworst {sci(worst[order])}", fontsize=7.0,
                     loc="left", pad=3)
        if k == 0:
            ax.set_ylabel(r"normalised derivative $\hat{D}_n$ (–)")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(length=2.2, pad=1.6)

        # (d)-(f): every resolved entry at state 13, expanded by pattern and component
        bx = fig.add_subplot(gs[1, k])
        at13 = [r for r in sel if int(r["increment"]) == 13]
        labels, xpos = [], 0
        for g, dirs in enumerate((REPEATED[order], MIXED[order])):
            for comp in (1, 2, 3, 4):
                hit = [r for r in at13 if r["directions"] == dirs
                       and int(r["stress_component"]) == comp]
                if not hit:
                    continue
                r = hit[0]
                bx.plot([xpos], [float(r["oti_normalized"])], ls="none", marker="o", ms=2.4,
                        color=COLOUR[comp], zorder=3)
                bx.plot([xpos], [float(r["reference_normalized"])], ls="none", marker="o",
                        ms=5.4, mfc="none", mec=COLOUR[comp], mew=0.7, zorder=4)
                labels.append(TICK[comp])
                xpos += 1
            if g == 0:
                bx.axvline(xpos - 0.5, color=GREY, lw=0.4, ls=(0, (2, 2)))
                xpos_split = xpos
        bx.axhline(0, color=GREY, lw=0.4, zorder=1)
        bx.set_xticks(range(len(labels)))
        bx.set_xticklabels(labels, fontsize=7.0)
        bx.set_xlim(-0.6, len(labels) - 0.4)
        ylo, yhi = bx.get_ylim()
        bx.set_ylim(ylo, yhi + 0.30 * (yhi - ylo))
        bx.text((xpos_split - 1) / 2, yhi + 0.17 * (yhi - ylo), DERIV[REPEATED[order]],
                ha="center", va="center", fontsize=7.0)
        bx.text((xpos_split + len(labels) - 1) / 2, yhi + 0.17 * (yhi - ylo),
                DERIV[MIXED[order]], ha="center", va="center", fontsize=7.0)
        bx.set_title(f"({'def'[k]}) order {order},\nmultiaxial state 13", loc="left", pad=3,
                     fontsize=7.0)
        bx.set_xlabel(r"stress component $\sigma_{ij}$")
        if k == 0:
            bx.set_ylabel(r"normalised derivative $\hat{D}_n$ (–)")
        for s in ("top", "right"):
            bx.spines[s].set_visible(False)
        bx.tick_params(length=2.2, pad=1.6)

    handles = [Line2D([], [], color=COLOUR[c], lw=0.9, marker="o", ms=2.4, label=COMP[c])
               for c in (1, 2, 3, 4)]
    handles += [
        Line2D([], [], color=GREY, lw=0.9, marker="o", ms=2.4, label="UMAT-OTI"),
        Line2D([], [], ls="none", marker="o", ms=5.4, mfc="none", mec=GREY, mew=0.7,
               label="80-digit finite-difference reference (mpmath)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, 0.0), handlelength=1.6, columnspacing=1.1)
    fig.text(0.5, 0.085, r"$\hat{D}_n = (\partial^n\sigma/\partial\varepsilon^n)\,"
             r"\varepsilon_s^n/\sigma_s$, $\sigma_s = 250$ MPa, $\varepsilon_s = 10^{-3}$; "
             r"$\varepsilon_1, \varepsilon_2$ = DSTRAN components 1, 2",
             ha="center", fontsize=7.0, color=GREY)
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{NAME}.pdf")
    fig.savefig(out / f"{NAME}.png", dpi=600)
    plt.close(fig)

    script = Path(__file__).resolve()
    prov = {
        "figure": NAME,
        "manuscript_location": "tex/sections/03-example.tex, Figure fig:higher (build Figure 3; V11 Figure 4)",
        "derived_from": "evidence/2ae2ee0/figures/fig4_higher_order.py (Ada); round-9 layout-only change",
        "umat_oti_commit": COMMIT,
        "data": [{"path": DATA, "sha256": sha256(data_path)}],
        "data_producer": "python -m umat_oti.validation.higher_order_convergence_study --model j2 "
                         "(run in refreeze/wt/2ae2ee0; Windows 11, local regeneration; "
                         "convergence_rows.csv byte-identical to 8e12548)",
        "script": {"path": f"{OUT}/{script.name}", "sha256": sha256(script)},
        "outputs": {f"{NAME}.pdf": sha256(out / f"{NAME}.pdf"),
                    f"{NAME}.png": sha256(out / f"{NAME}.png")},
        "conditions": {
            "model": "Model A, j2_props.f (provenance: content clean, responsible author open, Q-64)",
            "row_filter": "branch == plastic and reference_classification == resolved",
            "normalisation": "D_hat_n = (d^n sigma/d eps^n) eps_s^n / sigma_s, sigma_s = 250 MPa, "
                             "eps_s = 1e-3 (convergence_evidence.json 'normalization')",
            "reference": "80-digit nine-point tensor-product finite difference (mpmath), "
                         "plateau over nine step factors, base step 2e-5",
            "directions": "DSTRAN components; '1|2' = d2/(d eps1 d eps2), etc.",
        },
        "numbers_consistent_with_text": {
            "resolved_per_order": counts,
            "max_relative_difference_per_order": worst,
            "ledger": "L22 / Table 4 (20/20/26; 5.119e-14, 2.956e-11, 2.563e-11)",
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
