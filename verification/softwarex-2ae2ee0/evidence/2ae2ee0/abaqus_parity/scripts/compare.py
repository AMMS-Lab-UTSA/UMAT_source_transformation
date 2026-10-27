"""Compare each original/OTI job pair increment by increment (Ada, 2026-10-27).

Usage (from the workspace root):
    refreeze/venv/2ae2ee0/Scripts/python.exe evidence/2ae2ee0/abaqus_parity/scripts/compare.py

Sources (all full double precision unless noted):
  jobs/<job>/<job>_calls.txt  one record per UMAT call (wrapper): inputs STRAN/DSTRAN, outputs STRESS,
                              STATEV(1), DDSDDE. The converged value of an increment is the LAST call for
                              that (KSTEP, KINC, NOEL, NPT).
  jobs/<job>/<job>.fin        `abaqus ascfil` translation of the .fil (*NODE FILE U, RF; *EL FILE S, SDV),
                              written with 16 significant digits.
  jobs/<job>/<job>.sta        attempts and equilibrium iterations per increment.

Writes:
  comparison_increments.csv   one row per job pair and increment
  comparison_summary.csv      one row per job pair
Differences are a - b with a = orig and b = oti. "rel" = max|a-b| / max|b| over the quantity in that scope
(matrix max-norm, N1). Per-call checks also confirm that both builds received identical STRAN/DSTRAN at every call.
"""

from __future__ import annotations

import csv
import re
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("modelA", "r1")
CASES = ("ext", "shear", "mixed", "uniax")


def read_calls(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        f = line.split()
        if not f:
            continue
        ints = [int(x) for x in f[:4]]
        v = [float(x) for x in f[4:]]
        out.append({"key": tuple(ints), "time": v[0:4], "stran": v[4:10], "dstran": v[10:16],
                    "stress": v[16:22], "statev": v[22:23], "ddsdde": v[23:59]})
    return out


def fin_tokens(path: Path):
    """Tokens of an ASCII results file: (type, value)."""
    s = "".join(path.read_text().splitlines())
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == " ":  # block padding
            i += 1
        elif c == "*":
            yield ("*", None)
            i += 1
        elif c == "I":
            w = int(s[i + 1:i + 3])
            yield ("I", int(s[i + 3:i + 3 + w]))
            i += 3 + w
        elif c == "D":
            yield ("D", float(s[i + 1:i + 23].replace("D", "E")))
            i += 23
        elif c == "A":
            yield ("A", s[i + 1:i + 9])
            i += 9
        else:
            raise ValueError(f"{path}: unexpected {c!r} at {i}")


def read_fin(path: Path) -> "OrderedDict[tuple, dict]":
    """Per (step, inc): {'U': {node: [3]}, 'RF': {...}, 'S': {(el,ip): [6]}, 'SDV': {...}}."""
    recs, cur = [], None
    for t, v in fin_tokens(path):
        if t == "*":
            if cur:
                recs.append(cur)
            cur = []
        elif cur is not None:
            cur.append(v)
    if cur:
        recs.append(cur)
    data: "OrderedDict[tuple, dict]" = OrderedDict()
    inc, elkey = None, None
    for r in recs:
        key = r[1]
        if key == 2000:
            inc = (int(r[7]), int(r[8]))
            data[inc] = {"U": {}, "RF": {}, "S": {}, "SDV": {}, "time": float(r[2])}
        elif inc is None:
            continue
        elif key == 1:
            elkey = (int(r[2]), int(r[3]))
        elif key == 11:
            data[inc]["S"][elkey] = [float(x) for x in r[2:8]]
        elif key == 5:
            data[inc]["SDV"][elkey] = [float(x) for x in r[2:]]
        elif key == 101:
            data[inc]["U"][int(r[2])] = [float(x) for x in r[3:6]]
        elif key == 104:
            data[inc]["RF"][int(r[2])] = [float(x) for x in r[3:6]]
    return data


def read_sta(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^\s+(\d+)\s+(\d+)\s+(\d+U?)\s+(\d+)\s+(\d+)\s+(\d+)\s", line)
        if m:
            out[(int(m[1]), int(m[2]))] = {"att": m[3], "sdi": int(m[4]), "equil": int(m[5]), "total": int(m[6])}
    return out


def diff(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """(max abs diff, max |b|, N1 relative)."""
    d = max((abs(x - y) for x, y in zip(a, b)), default=0.0)
    s = max((abs(y) for y in b), default=0.0)
    return d, s, (d / s if s > 0 else (0.0 if d == 0 else float("inf")))


def flat(dct: dict) -> list[float]:
    return [x for k in sorted(dct) for x in dct[k]]


def main() -> int:
    rows, summary = [], []
    for model in MODELS:
        for case in CASES:
            ja, jb = f"{model}_{case}_orig", f"{model}_{case}_oti"
            ca = read_calls(ROOT / "jobs" / ja / f"{ja}_calls.txt")
            cb = read_calls(ROOT / "jobs" / jb / f"{jb}_calls.txt")
            same_seq = [c["key"] for c in ca] == [c["key"] for c in cb]
            # per-call (all calls, including non-final iterations), only meaningful if sequences match
            call_inputs_identical = same_seq and all(x["stran"] == y["stran"] and x["dstran"] == y["dstran"]
                                                     for x, y in zip(ca, cb))
            call_stress = max((diff(x["stress"], y["stress"])[0] for x, y in zip(ca, cb)), default=0.0) if same_seq else None
            call_input = (max((diff(x["stran"] + x["dstran"], y["stran"] + y["dstran"])[0] for x, y in zip(ca, cb)),
                              default=0.0) if same_seq else None)
            call_input_ndiff = (sum(1 for x, y in zip(ca, cb) if x["stran"] + x["dstran"] != y["stran"] + y["dstran"])
                                if same_seq else None)
            call_dd = max((diff(x["ddsdde"], y["ddsdde"])[0] for x, y in zip(ca, cb)), default=0.0) if same_seq else None
            # calls whose DDSDDE differs by more than 1e-6 relative (e.g. a different elastic/plastic branch)
            call_dd_branch = (sum(1 for x, y in zip(ca, cb) if diff(x["ddsdde"], y["ddsdde"])[2] > 1e-6)
                              if same_seq else None)
            # converged = last call per (step, inc, el, ip)
            la, lb = OrderedDict(), OrderedDict()
            for c in ca:
                la[c["key"]] = c
            for c in cb:
                lb[c["key"]] = c
            fa = read_fin(ROOT / "jobs" / ja / f"{ja}.fin")
            fb = read_fin(ROOT / "jobs" / jb / f"{jb}.fin")
            sa = read_sta(ROOT / "jobs" / ja / f"{ja}.sta")
            sb = read_sta(ROOT / "jobs" / jb / f"{jb}.sta")
            incs = sorted({k[:2] for k in la} | {k[:2] for k in lb} | set(fa) | set(fb) | set(sa) | set(sb))
            calls_a = {i: sum(1 for c in ca if c["key"][:2] == i) for i in incs}
            calls_b = {i: sum(1 for c in cb if c["key"][:2] == i) for i in incs}
            agg = {q: [0.0, 0.0] for q in ("stress", "statev", "ddsdde", "fil_S", "fil_SDV", "U", "RF")}
            worst = {q: "" for q in agg}
            maxpeq = 0.0
            for inc in incs:
                ka = [k for k in la if k[:2] == inc]
                kb = [k for k in lb if k[:2] == inc]
                row = {"model": model, "case": case, "step": inc[0], "inc": inc[1],
                       "time_total": fa.get(inc, {}).get("time", ""),
                       "ip_keys_match": ka == kb}
                vals = {}
                if ka == kb and ka:
                    for q in ("stress", "statev", "ddsdde"):
                        vals[q] = diff([x for k in ka for x in la[k][q]], [x for k in kb for x in lb[k][q]])
                    row["eqplas_max_orig"] = max(la[k]["statev"][0] for k in ka)
                    maxpeq = max(maxpeq, row["eqplas_max_orig"])
                    row["plastic_in_inc_orig"] = any(
                        la[k]["statev"][0] > (la[(k[0], k[1] - 1, k[2], k[3])]["statev"][0]
                                              if (k[0], k[1] - 1, k[2], k[3]) in la else -1) for k in ka) if inc[1] > 1 else ""
                if inc in fa and inc in fb:
                    vals["fil_S"] = diff(flat(fa[inc]["S"]), flat(fb[inc]["S"]))
                    vals["fil_SDV"] = diff(flat(fa[inc]["SDV"]), flat(fb[inc]["SDV"]))
                    vals["U"] = diff(flat(fa[inc]["U"]), flat(fb[inc]["U"]))
                    vals["RF"] = diff(flat(fa[inc]["RF"]), flat(fb[inc]["RF"]))
                for q, (d, s, r) in vals.items():
                    row[f"{q}_maxabs"] = d
                    row[f"{q}_maxref"] = s
                    row[f"{q}_rel"] = r
                    if d > agg[q][0] or (d == agg[q][0] and r > agg[q][1]):
                        agg[q] = [d, r]
                        worst[q] = f"{inc[0]}.{inc[1]}"
                for side, st, cn in (("orig", sa, calls_a), ("oti", sb, calls_b)):
                    e = st.get(inc, {})
                    row[f"att_{side}"] = e.get("att", "")
                    row[f"equil_iters_{side}"] = e.get("equil", "")
                    row[f"umat_calls_{side}"] = cn[inc]
                rows.append(row)
            it_a = sum(v["equil"] for v in sa.values())
            it_b = sum(v["equil"] for v in sb.values())
            summary.append({
                "model": model, "case": case, "increments_orig": len(sa), "increments_oti": len(sb),
                "cutbacks_orig": sum(1 for v in sa.values() if "U" in v["att"] or v["att"] != "1"),
                "cutbacks_oti": sum(1 for v in sb.values() if "U" in v["att"] or v["att"] != "1"),
                "equil_iters_total_orig": it_a, "equil_iters_total_oti": it_b,
                "equil_iters_max_orig": max(v["equil"] for v in sa.values()),
                "equil_iters_max_oti": max(v["equil"] for v in sb.values()),
                "umat_calls_orig": len(ca), "umat_calls_oti": len(cb),
                "call_sequence_identical": same_seq, "call_inputs_identical": call_inputs_identical,
                "allcalls_stress_maxabs": call_stress,
                "allcalls_input_maxabs": call_input, "allcalls_input_calls_not_bitwise": call_input_ndiff,
                "allcalls_ddsdde_maxabs": call_dd, "allcalls_ddsdde_calls_rel_gt_1e-6": call_dd_branch,
                "increments_with_different_equil_iters": sum(1 for k in set(sa) | set(sb)
                                                             if sa.get(k, {}).get("equil") != sb.get(k, {}).get("equil")),
                "eqplas_final_max": maxpeq,
                **{f"{q}_maxabs": agg[q][0] for q in agg}, **{f"{q}_rel_at_maxabs": agg[q][1] for q in agg},
                **{f"{q}_worst_inc": worst[q] for q in agg},
            })
    for name, data in (("comparison_increments.csv", rows), ("comparison_summary.csv", summary)):
        keys = []
        for r in data:
            keys += [k for k in r if k not in keys]
        with open(ROOT / name, "w", newline="\n", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    for s in summary:
        print({k: (f"{v:.3g}" if isinstance(v, float) else v) for k, v in s.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
