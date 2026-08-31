"""Render the transformed-source report as a self-contained page.

The count on this page is the thing most likely to be misread, so the page is
built so that it cannot be read without its limits: what "transformed" means
sits above the number, not in a footnote, and the three conditions
verification actually needs are shown as a set with their real state rather
than as a decorative sequence.

Input is the JSON written by build_transformed_report.py. Regenerate rather
than hand-edit; the numbers move.
"""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _bar_rows(counter: dict[str, int], total: int, tone: str = "accent") -> str:
    out = []
    for label, count in counter.items():
        pct = (100.0 * count / total) if total else 0.0
        out.append(
            f'<div class="bar"><span class="bar-label">{_esc(label)}</span>'
            f'<span class="bar-track"><span class="bar-fill tone-{tone}"'
            f' style="width:{pct:.1f}%"></span></span>'
            f'<span class="bar-count">{count}</span></div>')
    return "\n".join(out)


def render(payload: dict[str, Any], blockers: dict[str, int],
           corpus: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["sources"]
    total = summary["transformed_sources"]
    with_vector = summary["with_a_material_vector"]

    table_rows = []
    for r in rows:
        vec = r["material_vector"]
        state = "has-vector" if vec else "no-vector"
        table_rows.append(
            "<tr data-repo=\"%s\" data-kin=\"%s\" data-lic=\"%s\" data-vec=\"%s\">"
            "<td class=\"c-src\"><span class=\"path\">%s</span></td>"
            "<td class=\"c-repo\">%s</td>"
            "<td class=\"c-lic\"><span class=\"tag\">%s</span></td>"
            "<td class=\"c-kin\">%s</td>"
            "<td class=\"c-num\">%s</td>"
            "<td class=\"c-num\">%s</td>"
            "<td class=\"c-vec\">%s</td></tr>" % (
                _esc(r["repository"]), _esc(r["kinematics"]),
                _esc(r["license_spdx"]), state,
                _esc(r["source"]), _esc(r["repository"]),
                _esc(r["license_spdx"] or "unrecorded"), _esc(r["kinematics"]),
                _esc(r["lines"]), _esc(r["helper_routines"]),
                (f'<span class="pill pill-ok">{_esc(vec)} constants</span>'
                 if vec else '<span class="pill pill-none">none recovered</span>')))

    repos = sorted({r["repository"] for r in rows if r["repository"]})
    repo_options = "\n".join(f'<option value="{_esc(x)}">{_esc(x)}</option>' for x in repos)
    by_repo = Counter(r["repository"] for r in rows if r["repository"])

    blocker_total = sum(blockers.values())
    return f"""<title>UMAT Transformation Ledger</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Serif:ital,wght@0,400;0,600;1,400&display=swap">
<style>
:root {{
  --paper:#f3f5f7; --panel:#ffffff; --ink:#16212b; --ink-soft:#5a6874;
  --ink-faint:#8b97a2; --rule:#d8dee4; --accent:#2d4f8b;
  --ok:#2c6a4f; --warn:#8a6a20; --stop:#8c4a34;
  --ok-bg:#e6efe9; --warn-bg:#f5eeda; --stop-bg:#f6e8e2;
  --shadow:0 1px 2px rgba(22,33,43,.06),0 8px 24px rgba(22,33,43,.05);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --paper:#10161b; --panel:#161f27; --ink:#e4eaef; --ink-soft:#93a1ad;
    --ink-faint:#6b7883; --rule:#253039; --accent:#7fa3de;
    --ok:#6cbb94; --warn:#d3ae5c; --stop:#d38a70;
    --ok-bg:#152420; --warn-bg:#241f14; --stop-bg:#241813;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }}
}}
:root[data-theme="dark"] {{
  --paper:#10161b; --panel:#161f27; --ink:#e4eaef; --ink-soft:#93a1ad;
  --ink-faint:#6b7883; --rule:#253039; --accent:#7fa3de;
  --ok:#6cbb94; --warn:#d3ae5c; --stop:#d38a70;
  --ok-bg:#152420; --warn-bg:#241f14; --stop-bg:#241813;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Serif",Georgia,serif; font-size:16.5px; line-height:1.62;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1180px; margin:0 auto; padding:0 clamp(18px,4vw,44px); }}
.prose {{ max-width:68ch; }}
h1,h2,h3,.eyebrow,.stat-n,th,.bar-label,.bar-count,.tag,.pill,button,select,input {{
  font-family:"IBM Plex Sans Condensed",system-ui,sans-serif;
}}
h1 {{ font-size:clamp(2.1rem,5vw,3.1rem); font-weight:700; line-height:1.06;
     letter-spacing:-.015em; margin:0 0 .5rem; text-wrap:balance; }}
h2 {{ font-size:clamp(1.35rem,2.6vw,1.7rem); font-weight:600; line-height:1.15;
     letter-spacing:-.008em; margin:0 0 .6rem; text-wrap:balance; }}
h3 {{ font-size:1.02rem; font-weight:600; margin:0 0 .35rem; }}
p {{ margin:0 0 1rem; }}
a {{ color:var(--accent); }}
.eyebrow {{ font-size:.72rem; font-weight:600; letter-spacing:.14em;
  text-transform:uppercase; color:var(--ink-faint); margin:0 0 .9rem; }}
header.masthead {{ border-bottom:1px solid var(--rule); padding:clamp(38px,7vw,72px) 0 30px; }}
.lede {{ font-size:1.12rem; color:var(--ink-soft); max-width:60ch; margin:0; }}
section {{ padding:clamp(30px,5vw,52px) 0; border-bottom:1px solid var(--rule); }}
section:last-of-type {{ border-bottom:0; }}

.caveat {{ background:var(--warn-bg); border:1px solid var(--rule);
  border-left:3px solid var(--warn); border-radius:3px;
  padding:20px 22px; margin:26px 0 0; max-width:70ch; }}
.caveat h3 {{ color:var(--warn); letter-spacing:.01em; }}
.caveat p {{ margin:0; color:var(--ink); }}
.caveat p + p {{ margin-top:.7rem; }}

.stats {{ display:grid; gap:1px; background:var(--rule);
  grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  border:1px solid var(--rule); border-radius:3px; overflow:hidden; margin-top:30px; }}
.stat {{ background:var(--panel); padding:18px 20px; }}
.stat-n {{ font-size:2.1rem; font-weight:700; line-height:1; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums; display:block; }}
.stat-l {{ font-size:.83rem; color:var(--ink-soft); margin-top:.35rem; display:block;
  font-family:"IBM Plex Sans Condensed",system-ui,sans-serif; }}

.cond {{ display:grid; gap:14px; margin-top:20px; max-width:72ch; }}
.cond-item {{ display:grid; grid-template-columns:auto 1fr; gap:14px;
  align-items:start; padding:15px 17px; background:var(--panel);
  border:1px solid var(--rule); border-radius:3px; }}
.mark {{ width:22px; height:22px; border-radius:50%; display:grid; place-items:center;
  font-family:"IBM Plex Mono",monospace; font-size:12px; font-weight:500; margin-top:2px; }}
.mark-yes {{ background:var(--ok-bg); color:var(--ok); border:1px solid var(--ok); }}
.mark-part {{ background:var(--warn-bg); color:var(--warn); border:1px solid var(--warn); }}
.mark-no {{ background:var(--stop-bg); color:var(--stop); border:1px solid var(--stop); }}
.cond-item p {{ margin:.2rem 0 0; font-size:.94rem; color:var(--ink-soft); }}

.bars {{ display:grid; gap:9px; margin-top:16px; max-width:62ch; }}
.bar {{ display:grid; grid-template-columns:minmax(0,14ch) 1fr auto; gap:12px; align-items:center; }}
.bar-label {{ font-size:.82rem; color:var(--ink-soft); overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }}
.bar-track {{ height:9px; background:var(--rule); border-radius:2px; overflow:hidden; }}
.bar-fill {{ display:block; height:100%; border-radius:2px; }}
.tone-accent {{ background:var(--accent); }}
.tone-stop {{ background:var(--stop); }}
.bar-count {{ font-family:"IBM Plex Mono",monospace; font-size:.82rem;
  font-variant-numeric:tabular-nums; color:var(--ink-soft); min-width:3.5ch; text-align:right; }}

.controls {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:22px 0 14px; }}
.controls label {{ font-family:"IBM Plex Sans Condensed",system-ui,sans-serif;
  font-size:.78rem; letter-spacing:.06em; text-transform:uppercase; color:var(--ink-faint); }}
select,input[type=search] {{ font-size:.9rem; padding:7px 10px; border:1px solid var(--rule);
  border-radius:3px; background:var(--panel); color:var(--ink); min-width:150px; }}
select:focus-visible,input:focus-visible,th button:focus-visible {{
  outline:2px solid var(--accent); outline-offset:2px; }}
.count-note {{ font-family:"IBM Plex Mono",monospace; font-size:.8rem; color:var(--ink-faint);
  margin-left:auto; font-variant-numeric:tabular-nums; }}

.tablewrap {{ overflow-x:auto; border:1px solid var(--rule); border-radius:3px;
  background:var(--panel); box-shadow:var(--shadow); }}
table {{ border-collapse:collapse; width:100%; font-size:.86rem; }}
th {{ text-align:left; font-size:.74rem; font-weight:600; letter-spacing:.08em;
  text-transform:uppercase; color:var(--ink-faint); padding:11px 13px;
  border-bottom:1px solid var(--rule); background:var(--panel);
  position:sticky; top:0; z-index:1; white-space:nowrap; }}
td {{ padding:9px 13px; border-bottom:1px solid var(--rule); vertical-align:top; }}
tr:last-child td {{ border-bottom:0; }}
.path {{ font-family:"IBM Plex Mono",monospace; font-size:.79rem; word-break:break-all;
  color:var(--ink); }}
.c-repo {{ color:var(--ink-soft); white-space:nowrap; }}
.c-num {{ font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums;
  text-align:right; color:var(--ink-soft); }}
.c-kin {{ color:var(--ink-soft); white-space:nowrap; }}
.tag {{ font-size:.72rem; padding:2px 7px; border:1px solid var(--rule); border-radius:2px;
  color:var(--ink-soft); white-space:nowrap; }}
.pill {{ font-size:.72rem; padding:2px 8px; border-radius:2px; white-space:nowrap;
  font-weight:500; }}
.pill-ok {{ background:var(--ok-bg); color:var(--ok); }}
.pill-none {{ background:transparent; color:var(--ink-faint); border:1px solid var(--rule); }}
footer {{ padding:34px 0 60px; color:var(--ink-faint); font-size:.85rem; }}
code {{ font-family:"IBM Plex Mono",monospace; font-size:.85em;
  background:var(--rule); padding:1px 5px; border-radius:2px; }}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none!important; transition:none!important; }} }}
</style>

<header class="masthead"><div class="wrap">
  <p class="eyebrow">UMAT&nbsp;&rarr;&nbsp;OTI source transformer &middot; discovered-corpus ledger</p>
  <h1>{total} externally authored UMATs, transformed and compiled</h1>
  <p class="lede">Every source below was written by someone else, found by search, cleared for
  licence, put through the transformer, and built with gfortran. This page records what that
  does &mdash; and does not &mdash; establish.</p>

  <div class="caveat">
    <h3>What &ldquo;transformed&rdquo; means here</h3>
    <p>It means the generated Fortran <strong>compiles</strong>. It is the strongest claim
    available for these sources and it is not a claim about a derivative.</p>
    <p>A UMAT is <em>verified</em> when its OTI tangent is compared against an independent
    reference over a loading path. That needs three things together, and compiling is one of
    them. No derivative on this page has been executed or compared against anything.</p>
  </div>

  <div class="stats">
    <div class="stat"><span class="stat-n">{total}</span><span class="stat-l">sources transformed &amp; compiled</span></div>
    <div class="stat"><span class="stat-n">{summary["repositories"]}</span><span class="stat-l">repositories of origin</span></div>
    <div class="stat"><span class="stat-n">{summary["total_lines"]:,}</span><span class="stat-l">lines of Fortran</span></div>
    <div class="stat"><span class="stat-n">{with_vector}</span><span class="stat-l">with a material vector</span></div>
    <div class="stat"><span class="stat-n">0</span><span class="stat-l">verified derivatives</span></div>
  </div>
</div></header>

<section><div class="wrap prose">
  <h2>The three conditions verification needs</h2>
  <p>Presented as a set rather than a sequence, because they are independent and
  each is either met or not. Two of the three are met for part of the corpus; the
  third has not been met for any source.</p>
  <div class="cond">
    <div class="cond-item"><span class="mark mark-yes">&#10003;</span><div>
      <h3>The source builds</h3>
      <p>Met for all {total}. The transformer emitted Fortran and gfortran accepted it,
      after the original source was compiled first so that a file broken upstream is not
      charged to the transformer.</p></div></div>
    <div class="cond-item"><span class="mark mark-part">&#8226;</span><div>
      <h3>A material vector is known</h3>
      <p>Met for {with_vector} of {total}. The constants are read out of an
      <code>.inp</code> deck the source&rsquo;s own author shipped, never invented, and each
      row names the deck and the <code>*Material</code> line it came from.</p></div></div>
    <div class="cond-item"><span class="mark mark-no">&#215;</span><div>
      <h3>A loading history is accepted</h3>
      <p>Met for none. Every proposal carries
      <code>accepted_by_reviewer: false</code>. A probe path can be suggested, but choosing
      one is a reviewer&rsquo;s decision, so no derivative here is verified.</p></div></div>
  </div>
</div></section>

<section><div class="wrap">
  <div class="prose">
    <h2>What the corpus is made of</h2>
    <p>Licences were read before anything was cached; a repository declaring none was refused
    rather than assumed. Kinematics matter because the published reference collection is
    entirely small-strain &mdash; the finite-strain majority here is new ground for the
    transformer.</p>
  </div>
  <div style="display:grid;gap:34px;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));margin-top:8px">
    <div><h3>Licence</h3>{_bar_rows(summary["by_licence"], total)}</div>
    <div><h3>Kinematics</h3>{_bar_rows(summary["by_kinematics"], total)}</div>
    <div><h3>Most-represented repositories</h3>{_bar_rows(dict(by_repo.most_common(6)), total)}</div>
  </div>
</div></section>

<section><div class="wrap">
  <div class="prose">
    <h2>Every transformed source</h2>
    <p>One row per source. <em>Helpers</em> counts the subroutines the file defines besides
    the material routine &mdash; a rough measure of how much the transformer had to follow.</p>
  </div>
  <div class="controls">
    <label for="f-repo">Repository</label>
    <select id="f-repo"><option value="">All</option>{repo_options}</select>
    <label for="f-kin">Kinematics</label>
    <select id="f-kin"><option value="">All</option><option value="finite">finite</option><option value="small strain">small strain</option></select>
    <label for="f-vec">Material vector</label>
    <select id="f-vec"><option value="">All</option><option value="has-vector">recovered</option><option value="no-vector">none</option></select>
    <input type="search" id="f-text" placeholder="Filter by path&hellip;" aria-label="Filter by path">
    <span class="count-note" id="shown">{total} of {total}</span>
  </div>
  <div class="tablewrap"><table>
    <thead><tr>
      <th scope="col">Source</th><th scope="col">Repository</th><th scope="col">Licence</th>
      <th scope="col">Kinematics</th><th scope="col">Lines</th><th scope="col">Helpers</th>
      <th scope="col">Material vector</th>
    </tr></thead>
    <tbody id="tb">
{chr(10).join(table_rows)}
    </tbody>
  </table></div>
</div></section>

<section><div class="wrap">
  <div class="prose">
    <h2>What did not transform, and why</h2>
    <p>{corpus.get("not_transformed", 0)} of the {corpus.get("sources", 0)} cached sources did not
    reach a compiling file. The taxonomy is the point: it names what the transformer cannot yet
    do, separately from what a source does to itself.</p>
  </div>
  <div class="bars" style="max-width:64ch">{_bar_rows(blockers, blocker_total, "stop")}</div>
</div></section>

<footer><div class="wrap prose">
  <p>Generated from <code>paper_results/discovery/transformed_sources.json</code>. Regenerate
  rather than edit &mdash; the numbers move. Nothing on this page asserts that any derivative
  is correct.</p>
</div></footer>

<script>
(function () {{
  var tb = document.getElementById('tb');
  var rows = Array.prototype.slice.call(tb.querySelectorAll('tr'));
  var shown = document.getElementById('shown');
  var f = {{ repo: document.getElementById('f-repo'), kin: document.getElementById('f-kin'),
             vec: document.getElementById('f-vec'), text: document.getElementById('f-text') }};
  function apply() {{
    var q = f.text.value.trim().toLowerCase(), n = 0;
    rows.forEach(function (row) {{
      var ok = (!f.repo.value || row.dataset.repo === f.repo.value)
            && (!f.kin.value || row.dataset.kin === f.kin.value)
            && (!f.vec.value || row.dataset.vec === f.vec.value)
            && (!q || row.textContent.toLowerCase().indexOf(q) !== -1);
      row.hidden = !ok;
      if (ok) n++;
    }});
    shown.textContent = n + ' of ' + rows.length;
    try {{ localStorage.setItem('umat-ledger-filter', JSON.stringify(
      {{ repo: f.repo.value, kin: f.kin.value, vec: f.vec.value, text: f.text.value }})); }}
    catch (e) {{ /* private window, blocked storage: filtering still works */ }}
  }}
  try {{
    var saved = JSON.parse(localStorage.getItem('umat-ledger-filter') || '{{}}');
    ['repo', 'kin', 'vec', 'text'].forEach(function (k) {{
      if (saved[k] && f[k]) f[k].value = saved[k];
    }});
  }} catch (e) {{ /* nothing remembered; the unfiltered table is correct */ }}
  Object.keys(f).forEach(function (k) {{
    f[k].addEventListener(k === 'text' ? 'input' : 'change', apply);
  }});
  apply();
}})();
</script>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path,
                        default=REPO_ROOT / "paper_results" / "discovery" / "transformed_sources.json")
    parser.add_argument("--triage", type=Path,
                        default=REPO_ROOT / "paper_results" / "discovery" / "discovery_triage.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    blockers: dict[str, int] = {}
    corpus: dict[str, Any] = {}
    if args.triage.is_file():
        triage = json.loads(args.triage.read_text(encoding="utf-8"))
        summary = triage.get("summary", triage)
        blockers = dict(summary.get("by_blocker_kind", {}))
        blockers.pop("none", None)
        corpus = {
            "sources": summary.get("sources", 0),
            "not_transformed": summary.get("sources", 0) - summary.get("transformed", 0),
        }
    args.out.write_text(render(payload, blockers, corpus), encoding="utf-8")
    print(f"  wrote {args.out} ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
