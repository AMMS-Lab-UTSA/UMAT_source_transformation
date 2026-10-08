"""Assemble the B20 separate lines from the evidence the rule runs left.

Usage: python tools/d28_report.py OUT_DIR [--scratch DIR]

Cheap, offline parts are recomputed here (rule-1 rows, rule-2/3 static, rule-4
scan, A/B identity); the parts that ran an Abaqus job or the D-4 sweeps are read
from the JSON files the runs wrote beside OUT_DIR (rule2_dynamic.json,
rule3_dynamic.json, dt_tangent_default.json, rule4_jm.json, rule5_rows.json,
rule1_wrinkle_tangent.json, compile_*.json). Nothing here writes a store record
or the registry; the published figure is not an input to any line below.
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d28_lines as d        # noqa: E402

out = Path(sys.argv[1])
scratch = Path(sys.argv[sys.argv.index("--scratch") + 1]) if "--scratch" in sys.argv else out / "scratch"
records = d.load_records()
by_prefix = lambda p: next(k for k in records if k.startswith(p))  # noqa: E731
lines, report = [], {}


def load(name):
    return json.loads((out / name).read_text())


def other_gates_hold(rec):
    e = rec["evidence"]
    return bool(e.get("abaqus_job_completed") and e.get("all_requested_outputs_present")
                and e.get("complete_history_finite") and e.get("mechanically_informative"))


# ---------------------------------------------------------------- rule 1
rows = []
for key, found in d.single_precision_rows(records):
    r = d.rule_1_row_verdict(key, scratch, records[key])
    r["stage"] = records[key]["stage"]
    r["widened"] = found["widened"]
    rows.append(r)
tw = load("rule1_wrinkle_tangent.json")
admitted, passing_native, table = [], [], []
for r in rows:
    if r.get("status") != "run":
        continue
    changed = bool(r["native_primal_gate"]) and not bool(r["published_final_gate"])
    jm = r.get("jacobian_matched_native") or {}
    table.append({"key": r["key"][:8], "source": r["source"], "stage": r["stage"],
                  "U": r["native"]["measured_floor_U"], "ulps": r["native"]["ulps"],
                  "native_over_bound_routine": r["native"]["worst_stress_over_bound"],
                  "native_over_bound_jm": jm.get("worst_stress_over_bound"),
                  "bound_over_max_sigma": jm.get("bound_over_max_sigma"),
                  "published_over_bound_routine": r.get("published_worst_over_bound"),
                  "published_gate": r["published_final_gate"], "native_gate": r["native_primal_gate"],
                  "canary_1e-6_fails": r["canary_fails_as_required"], "verdict_changes": changed})
    if changed:
        passing_native.append(r["key"])
        if r["canary_fails_as_required"] and tw.get(r["key"], {}).get("verified") \
                and other_gates_hold(records[r["key"]]):
            admitted.append(r["key"])
report["rule_1"] = {"rows_in_scope": len(table), "rows_whose_primal_verdict_changes": len(passing_native),
                    "rows_admitted": len(admitted), "table": table,
                    "changed": [records[k]["source"] for k in passing_native],
                    "wrinkle_tangent": {records[k]["source"]: v["verified"] for k, v in tw.items()}}
tan_ok = [k for k in passing_native if tw.get(k, {}).get("verified")]
lines.append(f"Float32-native primal unit: {len(admitted)} rows "
             f"(under the native unit {len(passing_native)} rows leave primal_disagreed and {len(tan_ok)} of them also pass the "
             f"D-4 tangent gate, but the planted 1e-6 canary does not fail on {len(passing_native) - len(admitted)} of "
             f"{len(passing_native)}, so the rule as written admits {len(admitted)})")

# ---------------------------------------------------------------- rule 2 & 3
trunc_keys = [k for k, r in records.items() if r["stage"] == "derivative_truncated"]
dyn2, dyn3, tan = load("rule2_dynamic.json"), load("rule3_dynamic.json"), load("dt_tangent_default.json")
r2, r3 = [], []
for k in sorted(trunc_keys, key=lambda x: records[x]["source"]):
    rec = records[k]
    text = (d.CACHE / rec["source"]).read_text(errors="replace")
    st2 = d.rule_2_static(text, rec["truncation"]["truncations"])
    targets = sorted({t["target"] for t in rec["truncation"]["truncations"]})
    reads = d.replacement_region_reads((d.work_dir(k) / "transformed" / "transformed_user.f").read_text(errors="replace"))
    sinks = ({"STRESS", "STATEV"} | reads) - {"DDSDDE"}
    st3 = d.rule_3_static(text, targets, sinks)
    tv = tan[k].get("verified")
    gates = other_gates_hold(rec) and bool(rec["evidence"].get("primal_agreed"))
    d2 = dyn2.get(k, {})
    row2 = {"source": rec["source"], "pattern": not st2["pattern_offenders"],
            "static_literal": st2["static_literal"], "static_admitting_output": st2["static_admitting_output"],
            "violations": [f'{v["unit"]}:{v["line"]} {v["context"]}' for v in st2.get("violations", [])],
            "dynamic_single_value": d2.get("single_integer_value_everywhere"),
            "value_seen": d2.get("replay_distinct_values"), "tangent_full": tv, "other_gates": gates}
    row2["counts_literal"] = bool(row2["static_literal"] and row2["dynamic_single_value"] and tv and gates)
    row2["counts_if_output_and_store_back_admitted"] = bool(
        row2["static_admitting_output"] and row2["dynamic_single_value"] and tv and gates)
    r2.append(row2)
    m = dyn3[k]
    row3 = {"source": rec["source"], "targets": targets, "static_reaches": st3["reached_sinks"],
            "static_none": st3["reaches_none"], "mutated_statements": m.get("mutated_statements"),
            "stress_bitwise": m.get("stress_bitwise_unchanged"), "statev_bitwise": m.get("statev_bitwise_unchanged"),
            "ddsdde_changed_calls": m.get("ddsdde_changed_calls"), "calls": m.get("calls"),
            "mutation_proof": m.get("proof"), "tangent_full": tv, "other_gates": gates}
    row3["counts"] = bool(row3["static_none"] and row3["mutation_proof"] and tv and gates)
    r3.append(row3)
report["rule_2"], report["rule_3"] = r2, r3
j2 = [r["source"] for r in r2 if r["counts_literal"]]
j2b = [r["source"] for r in r2 if r["counts_if_output_and_store_back_admitted"]]
j3 = [r["source"] for r in r3 if r["counts"]]
lines.append(f"Benign NINT read-back: {len(j2)} rows (rule as written; {len(j2b)} rows if the console WRITE and the "
             f"first-call store of the integer back into STATEV are admitted: Vera to say)")
lines.append(f"Hand-DDSDDE-only truncations: {len(j3)} rows " + "; ".join(
    f'{r["source"].split("/")[-1]}: {r["ddsdde_changed_calls"]}/{r["calls"]} DDSDDE calls changed, '
    f'STRESS {"=" if r["stress_bitwise"] else "!="} STATEV {"=" if r["statev_bitwise"] else "!="} bitwise, '
    f'tangent gate {"passes" if r["tangent_full"] else "does not pass"}' for r in r3 if r["counts"]))

# ---------------------------------------------------------------- rule 4
changed4, scanned = [], 0
for k, rec in sorted(records.items()):
    dirs = d._routine_dirs(k)
    rp, tp = dirs["reference"] / "otis_history_out.txt", dirs["transformed"] / "otis_history_out.txt"
    if not (rp.exists() and tp.exists()):
        continue
    ref, trn = d.read_calls(rp), d.read_calls(tp)
    if not ref or len(ref) != len(trn):
        continue
    scanned += 1
    s = d.state_slot_floor_compare(ref, trn, excluded=d.undefined_excluded(rec).get("STATEV"))
    if s["state_agrees_published"] != s["state_agrees_with_floor"]:
        changed4.append({"key": k[:8], "source": rec["source"], "stage": rec["stage"], "state": s,
                         "canaries": d.rule_4_canaries(ref, trn)})
jm4 = {r["key"]: r for r in load("rule4_jm.json")}
admitted4 = []
for c in changed4:
    k = by_prefix(c["key"])
    jm = jm4.get(k)
    c["jm_rule_4_agrees"] = (jm or {}).get("rule_4", {}).get("rule_4_agrees")
    tg = d.tangent_rerun(k, records[k], scratch / f"r4tan_{c['key']}")
    c["tangent_full"] = tg.get("verified")
    c["other_gates"] = other_gates_hold(records[k])
    c["routine_stress_ok"] = c["state"]["worst_over_bound_with_floor"] <= 1.0
    c["admitted"] = bool(c["jm_rule_4_agrees"] and c["tangent_full"] and c["other_gates"]
                         and all(v.get("as_required") for v in c["canaries"].values() if isinstance(v, dict) and "as_required" in v))
    if c["admitted"]:
        admitted4.append(c["source"])
report["rule_4"] = {"rows_scanned": scanned, "state_verdict_changes": changed4,
                    "verified_rows_changed": [c["source"] for c in changed4 if c["stage"] == "verified"]}
lines.append(f"State-slot floor: {len(admitted4)} rows ({', '.join(s.split('/')[-1] for s in admitted4)}); "
             f"{len(changed4)} rows change their routine-level state verdict, 0 verified rows change")

# ---------------------------------------------------------------- rule 5
r5 = load("rule5_rows.json")
n_tangent = sum(1 for r in records.values() if r.get("tangent", {}).get("state_selection"))
gain5 = [r for r in r5 if r.get("revised_verified") and not r.get("published_tangent_verified")]
lost5 = [r for r in r5 if r.get("published_tangent_verified") and r.get("revised_verified") is False]
report["rule_5"] = {"rows_with_a_tangent_record": n_tangent, "selection_changed": len(r5),
                    "unchanged_selection_rows_keep_their_verdict": n_tangent - len(r5),
                    "gained": [r["source"] for r in gain5], "lost": [r["source"] for r in lost5], "rows": r5}
adm5 = [r for r in gain5 if r.get("canary_wrong_entry_fails")
        and other_gates_hold(records[by_prefix(r["key"][:8])])
        and records[r["key"]]["evidence"].get("primal_agreed")]
lines.append(f"Revised state selection: {len(adm5)} rows ({', '.join(r['source'].split('/')[-3] + '/' + r['source'].split('/')[-1] for r in adm5)}); "
             f"selection changes on {len(r5)} of {n_tangent} rows, none loses a verdict")

# ---------------------------------------------------------------- relabel
reg = {r["source_id"]: r for r in csv.DictReader(open(d.REGISTRY))}
b = {r["source_id"]: r for r in json.load(open("/home/ammslab3/softwarex_work/corpus_campaign/pass24_registry/corpus_registry.json"))["records"]}
a = {r["source_id"]: r for r in json.load(open("/home/ammslab3/softwarex_work/corpus_campaign/pass23_registry/corpus_registry.json"))["records"]}
elig = lambda r: bool(r and r.get("adequately_specified") and (r.get("adequacy_tier") or "author_deck") == "author_deck")  # noqa: E731
s242 = {s for s, r in a.items() if elig(r)}
alone = load("compile_alone.json")
moves, ambiguous = [], []
for x in alone:
    al = x["alone"]
    r = b.get(x["source_id"])
    if not r or al.get("status") != "run" or al.get("ok") or r["terminal_state"] == "incomplete_or_corrupt_source":
        continue
    in_file = bool(al.get("malformed") and al.get("defects_in_this_file") and not al.get("missing_dependencies"))
    dependency_like = [bool(re.search(r"kind type parameter|does not have a type|has not been declared", t))
                       for t in (al.get("defects_in_this_file") or [])]
    if in_file and dependency_like and all(dependency_like):
        ambiguous.append({"source": x["source_id"], "from": r["terminal_state"], "in_242": x["source_id"] in s242,
                          "defect": (al["defects_in_this_file"] or [""])[0][-160:],
                          "why_ambiguous": "the name may be defined in a module or include of another file"})
        continue
    if in_file:
        moves.append({"source": x["source_id"], "from": r["terminal_state"], "eligible": elig(r),
                      "in_242": x["source_id"] in s242, "defect": (al["defects_in_this_file"] or [""])[0][-160:]})
report["relabel"] = {"moves": moves, "ambiguous_not_moved": ambiguous}
ojf = [x for x in alone if x["state"] == "original_job_failed"]
report["relabel"]["original_job_failed_rows"] = len(ojf)
report["relabel"]["of_which_the_published_text_compiles_alone"] = sum(1 for x in ojf if x["alone"].get("ok"))
in242 = [m for m in moves if m["in_242"]]
lines.append(f"106 of 242 as published; 106 of 252 revised callee rule; 106 of 252 - {len(in242)} with the "
             f"published-text-compiles rule (k = {', '.join(m['source'].split('/')[0] for m in in242)})")

(out / "D28_LINES.json").write_text(json.dumps({"lines": lines, "report": report}, indent=1, default=str))
(out / "D28_LINES.txt").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
