"""R1 verification (task T4): newly generated evidence, Ada, 2026-10-27.

Verifies the UMAT-OTI transformation of the replacement model
``evidence/replacement-models/j2_voce_newton/umat_j2_voce.f`` (R1) at one
UMAT-OTI commit, against references that do not share code with UMAT-OTI:

* primal parity: transformed build vs untransformed build (Fortran, gfortran);
* tangent DDSDDE: README Eq. T evaluated in numpy at the converged state, the
  original routine's hand-coded DDSDDE, central finite differences of the
  untransformed build with a step sweep, and complex-step differentiation of an
  independent Python implementation of the README specification;
* parameter sensitivities (from ``umat-oti check``'s provider): closed form for
  monotone uniaxial strain (implicit relation, scalar root), complex step of
  the Python implementation over the whole history, and central FD of the
  untransformed build over the whole history with a relative-step sweep;
* internal Jacobian: UMAT-OTI's probe vs the hand-coded -3G - H';
* derivative of a truncated Newton iteration: variants with exactly k Newton
  steps, OTI tangent vs Eq. T at the converged solution and vs the k-step
  derivative of the Python implementation;
* hydrostatic increments (deviator exactly zero): NaN/Inf check.

Usage (from the manuscript workspace root, with the candidate venv's python):
    python refreeze/scripts/r1/r1_verify.py --commit 2ae2ee0
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

WS = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
R1_SOURCE = WS / "evidence" / "replacement-models" / "j2_voce_newton" / "umat_j2_voce.f"
STUB = "      IMPLICIT REAL*8(A-H,O-Z)\n"
PROPS = [200000.0, 0.3, 250.0, 1000.0, 150.0, 20.0]
PNAMES = ["YMOD", "PNU", "SIGY0", "HLIN", "QSAT", "BSAT"]
STRAIN_STEPS = [1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9, 1e-10]
PROP_STEPS = [1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9]
NEWTON_COUNTS = [1, 2, 3, 4, 5, 6, 8, 12]


# ----------------------------------------------------------------------------
# Independent Python implementation of the README specification
# ----------------------------------------------------------------------------
def py_umat(props, stress, ep, dstran, *, tolr=1e-12, maxit=50, fixed_iters=None):
    """One R1 increment in Python (works with complex arrays for complex step).

    Returns (stress_new, ep_new, info). ``fixed_iters`` forces exactly that many
    Newton updates (no convergence test), mirroring the k-step variants.
    """
    E, nu, sy0, H, Q, b = props
    G = E / (2 * (1 + nu))
    K = E / (3 * (1 - 2 * nu))
    lam = K - 2 * G / 3
    dev = dstran[0] + dstran[1] + dstran[2]
    st = np.array(stress, dtype=complex if np.iscomplexobj(np.asarray(dstran))
                  or any(isinstance(p, complex) for p in props)
                  or np.iscomplexobj(np.asarray(stress)) or isinstance(ep, complex)
                  else float)
    tr = st.copy()
    for i in range(3):
        tr[i] = st[i] + lam * dev + 2 * G * dstran[i]
    for i in range(3, 6):
        tr[i] = st[i] + G * dstran[i]
    p = (tr[0] + tr[1] + tr[2]) / 3
    s = tr.copy()
    s[:3] = tr[:3] - p
    snorm2 = s[0] ** 2 + s[1] ** 2 + s[2] ** 2 + 2 * (s[3] ** 2 + s[4] ** 2 + s[5] ** 2)
    snorm = np.sqrt(snorm2)
    q = math.sqrt(1.5) * snorm
    syn = sy0 + H * ep + Q * (1 - np.exp(-b * ep))
    info = {"plastic": False, "iterations": 0}
    if np.real(q - syn) <= 0:
        return tr, ep, info
    dg = 0.0 * q
    its = 0
    n = fixed_iters if fixed_iters is not None else maxit
    for _ in range(n):
        epk = ep + dg
        syk = sy0 + H * epk + Q * (1 - np.exp(-b * epk))
        hpk = H + Q * b * np.exp(-b * epk)
        res = q - 3 * G * dg - syk
        dres = -3 * G - hpk
        dg = dg - res / dres
        its += 1
        if fixed_iters is None and abs(np.real(res)) <= tolr * np.real(sy0):
            break
    fact = 1 - 3 * G * dg / q
    out = s * fact
    out[:3] = out[:3] + p
    info.update(plastic=True, iterations=its, dgam=dg, qtr=q, n=s / snorm,
                hp_new=H + Q * b * np.exp(-b * (ep + dg)), G=G, K=K)
    return out, ep + dg, info


def eq_t(info, props):
    """README Eq. T (Voigt, engineering shear), from a converged real state."""
    E, nu = props[0], props[1]
    G = E / (2 * (1 + nu))
    K = E / (3 * (1 - 2 * nu))
    D = np.zeros((6, 6))
    idev = np.zeros((6, 6))
    for i in range(3):
        for j in range(3):
            idev[i, j] = (1.0 if i == j else 0.0) - 1.0 / 3.0
    for i in range(3, 6):
        idev[i, i] = 0.5
    one = np.array([1, 1, 1, 0, 0, 0], dtype=float)
    D += K * np.outer(one, one)
    if not info["plastic"]:
        D += 2 * G * idev
        return D
    dg, q, n, hp = (float(np.real(info[k])) if k != "n" else np.real(info[k])
                    for k in ("dgam", "qtr", "n", "hp_new"))
    D += 2 * G * (1 - 3 * G * dg / q) * idev
    D -= 6 * G * G * (1 / (3 * G + hp) - dg / q) * np.outer(n, n)
    return D


def py_path(props, path, **kw):
    st = np.zeros(6)
    ep = 0.0
    hist = []
    for de in path:
        st, ep, info = py_umat(props, st, ep, np.asarray(de), **kw)
        hist.append((np.array(st), ep, info))
    return hist


def cs_tangent(props, stress, ep, de, h=1e-30, **kw):
    """Complex-step DDSDDE of the Python implementation from a given state."""
    D = np.zeros((6, 6))
    for j in range(6):
        d = np.array(de, dtype=complex)
        d[j] += 1j * h
        out, _, _ = py_umat(props, np.array(stress, dtype=complex), complex(ep), d, **kw)
        D[:, j] = np.imag(out) / h
    return D


def cs_props(props, path, h=1e-30):
    """Complex-step total derivatives of stress and EP over the history."""
    n = len(path)
    ds = np.zeros((n, 6, 6))
    dq = np.zeros((n, 6))
    for k in range(6):
        p = [complex(v) for v in props]
        p[k] += 1j * h
        st = np.zeros(6, dtype=complex)
        ep = 0j
        for i, de in enumerate(path):
            st, ep, _ = py_umat(p, st, ep, np.asarray(de, dtype=complex))
            ds[i, :, k] = np.imag(st) / h
            dq[i, k] = np.imag(ep) / h
    return ds, dq


def closed_form_uniaxial(props, eps):
    """Monotone uniaxial strain: EP solves 2G eps - 3G EP - SY(EP) = 0.

    Returns (sigma11, sigma22, EP, dsigma11/dp, dsigma22/dp, dEP/dp) or None
    when elastic. Exact for the discrete radial return along a fixed direction
    (the trial deviator stays parallel to the plastic flow direction).
    """
    E, nu, sy0, H, Q, b = props
    G = E / (2 * (1 + nu))
    K = E / (3 * (1 - 2 * nu))
    if 2 * G * eps <= sy0:
        return None
    x = 0.0
    for _ in range(200):
        r = 2 * G * eps - 3 * G * x - (sy0 + H * x + Q * (1 - math.exp(-b * x)))
        dr = -3 * G - (H + Q * b * math.exp(-b * x))
        dx = -r / dr
        x += dx
        if abs(dx) < 1e-18:
            break
    hp = H + Q * b * math.exp(-b * x)
    den = 3 * G + hp
    dG = np.array([1 / (2 * (1 + nu)), -E / (2 * (1 + nu) ** 2), 0, 0, 0, 0])
    dK = np.array([1 / (3 * (1 - 2 * nu)), 2 * E / (3 * (1 - 2 * nu) ** 2), 0, 0, 0, 0])
    dsy = np.array([0, 0, 1, x, 1 - math.exp(-b * x), Q * x * math.exp(-b * x)])
    dx_dp = (dG * (2 * eps - 3 * x) - dsy) / den
    s11 = K * eps + 2 * G * (2 * eps / 3 - x)
    s22 = K * eps + 2 * G * (-eps / 3 + x / 2)
    d11 = dK * eps + 2 * dG * (2 * eps / 3 - x) - 2 * G * dx_dp
    d22 = dK * eps + 2 * dG * (-eps / 3 + x / 2) + G * dx_dp
    return s11, s22, x, d11, d22, dx_dp


# ----------------------------------------------------------------------------
# Fortran builds and runs
# ----------------------------------------------------------------------------
def sh(cmd, cwd, log):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(map(str, cmd)) + "\n")
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
        fh.write(r.stdout + r.stderr + f"exit {r.returncode}\n")
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {cmd}\n{r.stderr[-2000:]}")
    return r


def build_original(src: Path, out: Path, log: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "ABA_PARAM.INC").write_text(STUB)
    shutil.copy2(src, out / "umat.f")
    sh(["gfortran", "-O1", "-std=legacy", "-ffixed-form", "-I.", "-c", "umat.f", "-o", "umat.o"], out, log)
    sh(["gfortran", "-O1", "-c", SCRIPTS / "r1_driver.f90", "-o", "drv.o"], out, log)
    sh(["gfortran", "-O1", "drv.o", "umat.o", "-o", "r1_drv.exe"], out, log)
    return out / "r1_drv.exe"


def build_transformed(jac_dir: Path, out: Path, log: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    objs = [jac_dir / n for n in ("master_parameters.o", "real_utils.o")]
    objs += sorted(jac_dir.glob("otim*.o")) + [jac_dir / "oti_intrinsics.o",
                                                jac_dir / "transformed_umat.o"]
    sh(["gfortran", "-O1", "-c", SCRIPTS / "r1_driver.f90", "-o", "drv.o"], out, log)
    sh(["gfortran", "-O1", "drv.o", *objs, "-o", "r1_drv.exe"], out, log)
    return out / "r1_drv.exe"


def transform_jacobian(src: Path, out: Path, py: str, repo: Path, log: Path) -> Path:
    sh([py, repo / "umat-oti", "jacobian", src, "--ntens", "6", "--out", out, "--compile"],
       repo, log)
    return out


def run_driver(exe: Path, workdir: Path, path, mode=0, steps=(1.0,), props=PROPS, nstatv=1):
    workdir.mkdir(parents=True, exist_ok=True)
    lines = [str(len(props)), " ".join(repr(float(p)) for p in props), str(nstatv),
             str(len(path))]
    lines += [" ".join(repr(float(v)) for v in de) for de in path]
    lines += [str(mode), str(len(steps)), " ".join(repr(float(s)) for s in steps)]
    (workdir / "r1_in.txt").write_text("\n".join(lines) + "\n")
    r = subprocess.run([str(exe)], cwd=workdir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"driver failed: {r.stderr[-1000:]}")
    res = {"STRESS": {}, "STATEV": {}, "DDSDDE": {}, "PNEWDT": {}, "FDTAN": {}, "FDPROP": {}}
    for line in (workdir / "r1_out.txt").read_text().splitlines():
        t = line.split()
        tag = t[0]
        if tag == "HEADER":
            continue
        inc = int(t[1])
        vals = [float(v) for v in t[2:]]
        if tag == "FDTAN":
            res["FDTAN"].setdefault(inc, {})[vals[0]] = np.array(vals[1:]).reshape(6, 6)
        elif tag == "FDPROP":
            k, step = int(vals[0]), vals[1]
            res["FDPROP"].setdefault(step, {}).setdefault(k, {})[inc] = np.array(vals[2:])
        elif tag == "DDSDDE":
            res["DDSDDE"][inc] = np.array(vals).reshape(6, 6)
        else:
            res[tag][inc] = np.array(vals)
    return res


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def mat_rel(a, b):
    """max |a-b| / max |b| (entrywise max over the matrix; scale of b)."""
    scale = float(np.max(np.abs(b)))
    return float(np.max(np.abs(a - b))) / scale if scale > 0 else float(np.max(np.abs(a - b)))


def finite(a) -> bool:
    return bool(np.all(np.isfinite(a)))


def paths(check_path):
    uni = [[2e-4, 0, 0, 0, 0, 0]] * 30
    a = [2e-4, -1e-4, -0.5e-4, 3e-4, 1e-4, -2e-4]
    b = [-1e-4, 2e-4, 0.0, -2e-4, 3e-4, 1e-4]
    multi = [a] * 8 + [b] * 8 + [[-0.5 * v for v in b]] * 4 + [[1e-4, 1e-4, 1e-4, 0, 0, 0]] * 3
    hydro = [[1e-3, 1e-3, 1e-3, 0, 0, 0]] * 3 + [[-2e-3, -2e-3, -2e-3, 0, 0, 0]] * 2
    large = [[5e-3, -1e-3, 0, 4e-3, 0, 0]] * 4
    return {"uniaxial_strain": uni, "multiaxial_nonproportional": multi,
            "large_increment_multiaxial": large,
            "hydrostatic": hydro, "check_path": check_path}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", required=True)
    args = ap.parse_args()
    ev = WS / "evidence" / args.commit / "r1"
    repo = WS / "refreeze" / "wt" / args.commit
    py = sys.executable
    work = ev / "verify"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    log = work / "build.log"
    report: dict = {
        "label": "NEWLY GENERATED EVIDENCE (Ada, 2026-10-27); builder output, not independently reviewed",
        "umat_oti_commit": subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                          capture_output=True, text=True).stdout.strip(),
        "r1_source": str(R1_SOURCE.relative_to(WS)),
        "r1_sha256": hashlib.sha256(R1_SOURCE.read_bytes()).hexdigest(),
        "props": dict(zip(PNAMES, PROPS)),
        "platform": "Windows 11, MinGW-w64 GNU Fortran 16.1.0, refreeze POSIX shim (see refreeze/MANIFEST.md)",
    }
    pkg = json.loads((ev / "check" / "sensitivities" / "package.json").read_text())
    P = paths(pkg["check_path"]["increments"])

    orig = build_original(R1_SOURCE, work / "build_original", log)
    trans = build_transformed(ev / "check" / "jacobian", work / "build_transformed", log)

    # ---- primal parity, tangent, hydrostatic ------------------------------
    tangent_rows = []
    summary_paths = {}
    for name, path in P.items():
        ro = run_driver(orig, work / "run" / f"{name}_orig", path, mode=1, steps=STRAIN_STEPS)
        rt = run_driver(trans, work / "run" / f"{name}_oti", path, mode=0)
        hist = py_path(PROPS, path)
        worst_parity = 0.0
        worst_py = 0.0
        all_finite = True
        st_prev = np.zeros(6)
        ep_prev = 0.0
        best = {"oti_vs_eqT": 0.0, "oti_vs_hand": 0.0, "oti_vs_cs": 0.0, "oti_vs_fd_best": 0.0,
                "hand_vs_eqT": 0.0}
        plastic_incs = 0
        for inc in range(1, len(path) + 1):
            so, st_ = ro["STRESS"][inc], rt["STRESS"][inc]
            svo, svt = ro["STATEV"][inc], rt["STATEV"][inc]
            scale = max(float(np.max(np.abs(so))), 1.0)
            par = max(float(np.max(np.abs(so - st_))) / scale,
                      float(abs(svo[0] - svt[0])) / max(abs(svo[0]), 1e-30) if svo[0] != 0 else float(abs(svt[0])))
            worst_parity = max(worst_parity, par)
            pst, pep, info = hist[inc - 1]
            worst_py = max(worst_py, float(np.max(np.abs(np.real(pst) - so))) / scale)
            Dt = rt["DDSDDE"][inc]
            Dh = ro["DDSDDE"][inc]
            all_finite &= finite(Dt) and finite(st_) and finite(svt)
            Deq = eq_t({k: v for k, v in info.items()}, PROPS)
            Dcs = cs_tangent(PROPS, st_prev, ep_prev, np.asarray(path[inc - 1]))
            fd = ro["FDTAN"].get(inc, {})
            fd_err = {h: mat_rel(Dt, M) for h, M in fd.items()}
            hbest = min(fd_err, key=fd_err.get) if fd_err else None
            row = {
                "path": name, "increment": inc, "branch": "plastic" if info["plastic"] else "elastic",
                "newton_iterations_py": info["iterations"],
                "primal_parity_rel": par,
                "oti_vs_eqT": mat_rel(Dt, Deq), "oti_vs_hand": mat_rel(Dt, Dh),
                "oti_vs_cs_python": mat_rel(Dt, Dcs), "hand_vs_eqT": mat_rel(Dh, Deq),
                "fd_best_step": hbest, "oti_vs_fd_best": fd_err.get(hbest) if hbest else None,
                **{f"oti_vs_fd_h{h:.0e}": e for h, e in fd_err.items()},
                "oti_finite": finite(Dt),
            }
            tangent_rows.append(row)
            plastic_incs += info["plastic"]
            for k_, key in (("oti_vs_eqT", "oti_vs_eqT"), ("oti_vs_hand", "oti_vs_hand"),
                            ("oti_vs_cs", "oti_vs_cs_python"), ("hand_vs_eqT", "hand_vs_eqT")):
                best[k_] = max(best[k_], row[key])
            if row["oti_vs_fd_best"] is not None:
                best["oti_vs_fd_best"] = max(best["oti_vs_fd_best"], row["oti_vs_fd_best"])
            st_prev, ep_prev = np.real(pst), float(np.real(pep))
        summary_paths[name] = {"increments": len(path), "plastic_increments": plastic_incs,
                               "worst_primal_parity_rel": worst_parity,
                               "worst_python_vs_fortran_primal_rel": worst_py,
                               "all_transformed_outputs_finite": all_finite,
                               "worst_tangent": best}
    report["tangent_and_primal"] = summary_paths
    with open(ev / "r1_tangent_rows.csv", "w", newline="") as fh:
        keys = sorted({k for r in tangent_rows for k in r}, key=lambda k: (k not in tangent_rows[0], k))
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(tangent_rows)

    # ---- parameter sensitivities on the check path -------------------------
    oti = {}
    with open(ev / "check" / "sensitivities" / "verification" / "verification_entries.csv") as fh:
        for r in csv.DictReader(fh):
            oti[(r["array"], r["column"], int(r["increment"]), int(r["component"]))] = float(r["oti"])
    cpath = P["check_path"]
    ds_cs, dq_cs = cs_props(PROPS, cpath)
    rfd = run_driver(orig, work / "run" / "check_path_propfd", cpath, mode=2, steps=PROP_STEPS)
    eps = 0.0
    ps_rows = []
    worst = {"closed_form": 0.0, "complex_step": 0.0, "fd_best": 0.0}
    for inc in range(1, len(cpath) + 1):
        eps += cpath[inc - 1][0]
        monotone = all(cpath[i][0] > 0 for i in range(inc))
        cf = closed_form_uniaxial(PROPS, eps) if monotone else None
        for k, pn in enumerate(PNAMES):
            for comp in range(1, 7):
                key = ("DSIGMA_DP", pn, inc, comp)
                if key not in oti:
                    continue
                v = oti[key]
                ref_cs = ds_cs[inc - 1, comp - 1, k]
                fds = {s: rfd["FDPROP"][s][k + 1][inc][comp - 1] for s in PROP_STEPS}
                sc = max(abs(ref_cs), 1e-12 * max(abs(x) for x in ds_cs[inc - 1, :, k]) + 1e-300)
                e_fd = {s: abs(v - f) / sc for s, f in fds.items()}
                sbest = min(e_fd, key=e_fd.get)
                row = {"array": "DSIGMA_DP", "param": pn, "increment": inc, "component": comp,
                       "oti": v, "complex_step": ref_cs, "rel_vs_cs": abs(v - ref_cs) / sc,
                       "fd_best_step": sbest, "rel_vs_fd_best": e_fd[sbest]}
                if cf is not None and comp in (1, 2):
                    ref = cf[3][k] if comp == 1 else cf[4][k]
                    row["closed_form"] = ref
                    row["rel_vs_closed_form"] = abs(v - ref) / max(abs(ref), 1e-300) if ref != 0 else abs(v)
                    worst["closed_form"] = max(worst["closed_form"], row["rel_vs_closed_form"])
                worst["complex_step"] = max(worst["complex_step"], row["rel_vs_cs"])
                worst["fd_best"] = max(worst["fd_best"], row["rel_vs_fd_best"])
                ps_rows.append(row)
            key = ("DSTATEV_DP", pn, inc, 1)
            if key in oti:
                v = oti[key]
                ref_cs = dq_cs[inc - 1, k]
                row = {"array": "DSTATEV_DP", "param": pn, "increment": inc, "component": 1,
                       "oti": v, "complex_step": ref_cs,
                       "rel_vs_cs": abs(v - ref_cs) / max(abs(ref_cs), 1e-300) if ref_cs != 0 else abs(v)}
                fds = {s: rfd["FDPROP"][s][k + 1][inc][6] for s in PROP_STEPS}
                e_fd = {s: abs(v - f) / max(abs(ref_cs), 1e-300) if ref_cs != 0 else abs(v - f)
                        for s, f in fds.items()}
                sbest = min(e_fd, key=e_fd.get)
                row.update(fd_best_step=sbest, rel_vs_fd_best=e_fd[sbest])
                if cf is not None:
                    ref = cf[5][k]
                    row["closed_form"] = ref
                    row["rel_vs_closed_form"] = abs(v - ref) / max(abs(ref), 1e-300)
                    worst["closed_form"] = max(worst["closed_form"], row["rel_vs_closed_form"])
                worst["complex_step"] = max(worst["complex_step"], row["rel_vs_cs"])
                worst["fd_best"] = max(worst["fd_best"], row["rel_vs_fd_best"])
                ps_rows.append(row)
    with open(ev / "r1_parameter_rows.csv", "w", newline="") as fh:
        keys = ["array", "param", "increment", "component", "oti", "closed_form",
                "rel_vs_closed_form", "complex_step", "rel_vs_cs", "fd_best_step", "rel_vs_fd_best"]
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(ps_rows)
    report["parameter_sensitivities"] = {
        "path": pkg["check_path"]["description"],
        "entries_compared": len(ps_rows),
        "closed_form_entries": sum(1 for r in ps_rows if "closed_form" in r),
        "worst_relative": worst,
        "note": ("relative errors use the complex-step value as scale; entries whose "
                 "reference is exactly zero report the absolute OTI value"),
    }

    # ---- truncated Newton: exactly k Newton updates ------------------------
    src = R1_SOURCE.read_text()
    trunc = []
    for k in NEWTON_COUNTS:
        vsrc = src.replace("TOLR=1.D-12, MAXIT=50", f"TOLR=-1.D0, MAXIT={k}")
        assert vsrc != src
        vdir = work / f"newton_k{k}"
        vdir.mkdir(parents=True)
        vfile = vdir / f"umat_j2_voce_k{k}.f"
        vfile.write_text(vsrc)
        transform_jacobian(vfile, vdir / "oti", py, repo, log)
        tv = build_transformed(vdir / "oti", vdir / "build_oti", log)
        for name in ("uniaxial_strain", "multiaxial_nonproportional",
                     "large_increment_multiaxial"):
            path = P[name]
            rt = run_driver(tv, vdir / f"run_{name}", path, mode=0)
            hist_conv = py_path(PROPS, path)
            hist_k = py_path(PROPS, path, fixed_iters=k)
            e_eq, e_csk = 0.0, 0.0
            st_prev, ep_prev = np.zeros(6), 0.0
            for inc in range(1, len(path) + 1):
                _, _, info = hist_conv[inc - 1]
                if not info["plastic"]:
                    st_prev, ep_prev = np.real(hist_k[inc - 1][0]), float(np.real(hist_k[inc - 1][1]))
                    continue
                Dt = rt["DDSDDE"][inc]
                e_eq = max(e_eq, mat_rel(Dt, eq_t(info, PROPS)))
                Dk = cs_tangent(PROPS, st_prev, ep_prev, np.asarray(path[inc - 1]), fixed_iters=k)
                e_csk = max(e_csk, mat_rel(Dt, Dk))
                st_prev, ep_prev = np.real(hist_k[inc - 1][0]), float(np.real(hist_k[inc - 1][1]))
            trunc.append({"newton_updates": k, "path": name,
                          "worst_oti_vs_eqT_at_converged": e_eq,
                          "worst_oti_vs_cs_of_same_k_step_python": e_csk})
    report["truncated_newton"] = trunc
    its = [r["newton_iterations_py"] for r in tangent_rows if r["branch"] == "plastic"]
    report["newton_iterations_used_by_R1_tolerance_rule"] = {
        "min": min(its), "max": max(its),
        "note": "counted in the Python implementation, same update-then-test rule as the Fortran"}

    # ---- internal Jacobian -------------------------------------------------
    try:
        sys.path.insert(0, str(repo / "src"))
        from umat_oti.validation.internal_jacobian_validation import (
            InternalJacobianCase, verify_internal_jacobian)
        case = InternalJacobianCase(
            model="r1_j2_voce", source_path=R1_SOURCE, props=tuple(PROPS),
            dstran_per_increment=(2e-4, 0, 0, 0, 0, 0), n_increments=30,
            ntens=6, nstatv=1, ndi=3, nshr=3, state_names=("EP",))
        rec = verify_internal_jacobian(case, work / "internal_jacobian")
        (ev / "r1_internal_jacobian_record.json").write_text(json.dumps(rec, indent=1, default=str))
        ext = rec.get("extracted") or {}
        gamma = rec.get("converged_iterate")
        tgt = rec.get("target_increment")
        hist = py_path(PROPS, [[2e-4, 0, 0, 0, 0, 0]] * 30)
        ij = {"stages": {k: v.get("status") if isinstance(v, dict) else v
                         for k, v in (rec.get("stages") or {}).items()},
              "target_increment": tgt, "converged_iterate_DGAM": gamma,
              "extracted": ext, "hand_coded_jacobian_reported": rec.get("hand_coded_jacobian")}
        if tgt and gamma is not None:
            ep_n = float(np.real(hist[tgt - 2][1])) if tgt > 1 else 0.0
            E, nu, sy0, H, Q, b = PROPS
            G = E / (2 * (1 + nu))
            exact = -3 * G - (H + Q * b * math.exp(-b * (ep_n + gamma)))
            ij["closed_form_minus3G_minus_Hprime"] = exact
            val = ext.get("value", ext.get("oti"))
            if isinstance(val, (int, float)):
                ij["rel_oti_vs_closed_form"] = abs(val - exact) / abs(exact)
        report["internal_jacobian"] = ij
    except Exception as exc:  # recorded, not hidden
        report["internal_jacobian"] = {"error": repr(exc)[:800]}

    (ev / "r1_report.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
