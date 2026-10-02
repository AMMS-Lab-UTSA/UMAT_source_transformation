"""Independence check: does the FD reference reproduce a KNOWN derivative?

Before an FD reference of the original routine is allowed to judge an OTI
derivative, it is itself judged against a closed form on a routine whose
response is known exactly: linear isotropic elasticity,

    sigma_{n+1} = sigma_n + C(E, nu) : d_eps,   C = lambda 1(x)1 + 2 mu I
    (Voigt, engineering shear: the shear block is mu * gamma),

so that, with ``eps_n`` the accumulated strain,

    local   d sigma_{n+1} / dp = (dC/dp) : d_eps_n          (sigma_n held fixed)
    total   d sigma_n     / dp = (dC/dp) : eps_n            (strain history held fixed)

    dlambda/dE = nu / ((1+nu)(1-2nu)),        dmu/dE = 1 / (2(1+nu))
    dlambda/dnu = E (1+2nu^2) / ((1+nu)^2 (1-2nu)^2),   dmu/dnu = -E / (2(1+nu)^2)

The check uses the same driver, ladder and plateau rule as the harness, and
the closed form shares no code with either the routine or the OTI build.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from umat_oti.corpus_features import drivers as dv
from umat_oti.corpus_features import fd


def iso_elastic_dC(e: float, nu: float, ndi: int, nshr: int, wrt: str) -> np.ndarray:
    if wrt == "E":
        dlam = nu / ((1 + nu) * (1 - 2 * nu))
        dmu = 1.0 / (2 * (1 + nu))
    elif wrt == "nu":
        dlam = e * (1 + 2 * nu * nu) / ((1 + nu) ** 2 * (1 - 2 * nu) ** 2)
        dmu = -e / (2 * (1 + nu) ** 2)
    else:
        raise ValueError(wrt)
    n = ndi + nshr
    d = np.zeros((n, n))
    d[:ndi, :ndi] = dlam
    for i in range(ndi):
        d[i, i] += 2 * dmu
    for i in range(ndi, n):
        d[i, i] = dmu
    return d


def check_iso_elastic(build: dv.Build, work: Path, *, props: Sequence[float], ntens: int,
                      ndi: int, nshr: int, increments: list, ladder=fd.DEFAULT_LADDER,
                      rtol: float = fd.DEFAULT_RTOL,
                      cmname: str = "MATERIAL", oti=None, quad: bool = False) -> dict:
    """Judge the FD reference (and optionally OTI values) against the closed form.

    ``oti`` (optional) maps (mode, wrt, increment) -> OTI column, to report how
    far the OTI build sits from the closed form as well. ``quad``: ``build`` is
    the quad-precision reference build (drivers.quadify); the ladder is formed
    from its REAL(16) differences and judged with eps = 2^-112.
    """
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    e, nu = float(props[0]), float(props[1])
    config = dv.RunConfig(ntens=ntens, nstatv=1, nprops=len(props), ndi=ndi, nshr=nshr,
                          props=list(props), statev0=[0.0], cmname=cmname,
                          increments=increments)
    config.write(work)
    perts, where = [], {}
    for mode in ("local", "total"):
        for i, name in ((1, "E"), (2, "nu")):
            scale = fd.step_scale(props[i - 1], floor=1e-6)
            for k, h in enumerate(ladder):
                perts.append(dv.Perturbation(mode, "props", i, h * scale))
                where[(mode, name, k)] = len(perts)
    dv.write_perturbations(work, perts)
    ok, message = dv.run_program(build, work)
    if not ok:
        return {"status": "not_attempted", "reason": message}
    out = dv.parse_real_output(work / dv.REAL_OUT, ntens, 1)
    dstran = np.array([d for d, *_ in increments], float)
    eps = np.cumsum(dstran, axis=0)
    result = {"what": "FD of the ORIGINAL routine vs closed-form isotropic elasticity",
              "reference_precision": "quad" if quad else "double",
              "rule": f"entrywise, FD-only plateau >= {fd.MIN_PLATEAU}, rtol={rtol}, "
                      "atol = round-off scale 8 eps F / h_(3)",
              "columns": 0, "verified": 0, "worst_rel": 0.0, "min_plateau": None,
              "oti_vs_closed_form_worst_rel": None, "per_column": []}
    for mode in ("local", "total"):
        for name in ("E", "nu"):
            dC = iso_elastic_dC(e, nu, ndi, nshr, name)
            for n in range(1, len(increments) + 1):
                closed = dC @ (dstran[n - 1] if mode == "local" else eps[n - 1])
                plus, minus, steps = [], [], []
                for k in range(len(ladder)):
                    ip = where[(mode, name, k)]
                    table = out.local if mode == "local" else out.total
                    key_p = (n, ip, 1) if mode == "local" else (ip, 1, n)
                    key_m = (n, ip, -1) if mode == "local" else (ip, -1, n)
                    plus.append(table[key_p][0]); minus.append(table[key_m][0])
                    steps.append(perts[ip - 1].step)
                incoming = out.base[n - 1]["stress"] if n > 1 else np.zeros(ntens)
                if quad:
                    dtable = out.local_delta if mode == "local" else out.total_delta
                    mag = np.abs(out.base[n]["stress"])
                    for arr in plus + minus:
                        mag = np.maximum(mag, np.abs(arr))
                    column = fd.classify_and_reference(
                        [dtable[(n, where[(mode, name, k)], 1) if mode == "local"
                                else (where[(mode, name, k)], 1, n)][0] for k in range(len(ladder))],
                        [dtable[(n, where[(mode, name, k)], -1) if mode == "local"
                                else (where[(mode, name, k)], -1, n)][0] for k in range(len(ladder))],
                        np.zeros(ntens), steps, magnitude=mag, eps=fd.EPS_QUAD)
                else:
                    column = fd.classify_and_reference(plus, minus, out.base[n]["stress"], steps)
                magnitude = np.maximum(column.magnitude, np.abs(incoming))
                verdict = fd.judge_column(closed, column.estimates, column.usable, ladder,
                                          steps=column.steps, magnitude=magnitude, rtol=rtol,
                                          eps=fd.EPS_QUAD if quad else fd.EPS)
                result["columns"] += 1
                result["verified"] += verdict.status == "verified"
                result["worst_rel"] = max(result["worst_rel"], verdict.max_rel)
                result["entries"] = result.get("entries", 0) + verdict.compared
                result["entries_unresolved"] = result.get("entries_unresolved", 0) + verdict.unresolved
                if verdict.min_plateau and (result["min_plateau"] is None or
                                            verdict.min_plateau < result["min_plateau"]):
                    result["min_plateau"] = verdict.min_plateau
                entry = {"mode": mode, "wrt": name, "increment": n, "status": verdict.status,
                         "max_rel": verdict.max_rel, "min_plateau": verdict.min_plateau,
                         "order": column.order}
                if oti is not None and (mode, name, n) in oti:
                    o = np.asarray(oti[(mode, name, n)], float)
                    scale = max(float(np.max(np.abs(closed))), 1e-300)
                    rel = float(np.max(np.abs(o - closed))) / scale
                    entry["oti_vs_closed_form_rel"] = rel
                    result["oti_vs_closed_form_worst_rel"] = max(
                        result["oti_vs_closed_form_worst_rel"] or 0.0, rel)
                result["per_column"].append(entry)
    result["status"] = "verified" if result["verified"] == result["columns"] else "failed"
    return result
