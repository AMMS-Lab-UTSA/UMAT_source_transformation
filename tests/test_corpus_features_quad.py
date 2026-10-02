"""Quad-precision FD reference of the ORIGINAL (lead request after Curie-G B2, cluster F).

The quad build promotes the original's double precision to REAL(16) and leaves
its binary32 quantities and every literal exactly as written, so it evaluates
the same function with less rounding. It must reproduce a closed-form
derivative far below what the double reference can (independence check), and
the value under test (a double computation) keeps its own round-off scale in
the tolerance -- an exact zero computed in double is not "wrong" against the
1e-22 a quad FD of rounded inputs gives.
"""
import shutil
from pathlib import Path

import numpy as np
import pytest

from umat_oti.corpus_features import drivers as dv
from umat_oti.corpus_features import fd


def test_quadify_promotes_double_and_keeps_binary32_and_literals():
    src = ("      IMPLICIT REAL*8(A-H,O-Z)\n"
           "      DOUBLE PRECISION X\n"
           "      REAL(8) Z\n"
           "      REAL(KIND=8) W\n"
           "      REAL Y, ENU\n"
           "      REAL*4 V\n"
           "      ENU=0.4999\n"
           "      X=DSQRT(DBLE(Y))*1.0D0+DEXP(Z)+0.1D0\n")
    q = dv.quadify(src)
    assert "IMPLICIT REAL*16(A-H,O-Z)" in q
    assert "REAL*16 X" in q and "REAL(16) Z" in q and "REAL(16) W" in q
    assert "REAL Y, ENU" in q and "REAL*4 V" in q          # binary32 stays binary32
    assert "ENU=0.4999" in q and "1.0D0" in q and "0.1D0" in q   # literals as written
    assert "SQRT(QEXT(Y))" in q and "EXP(Z)" in q


def test_the_value_under_test_keeps_its_own_roundoff_scale_under_a_quad_reference():
    # quad FD of a cancelled output: 2.2e-22 (rounded inputs), double value 0
    est = [np.array([2e-5, 2.2455e-22]) for _ in fd.DEFAULT_LADDER]
    steps = [2100.0 * r for r in fd.DEFAULT_LADDER]
    v = fd.judge_column(np.array([2e-5, -4.2e-22]), est, list(range(6)), fd.DEFAULT_LADDER,
                        steps=steps, magnitude=np.array([4.2, 4.7e-17]), eps=fd.EPS_QUAD)
    assert v.status == "verified", v.codes
    # ...but a real error is still caught at quad resolution
    v = fd.judge_column(np.array([2e-5 * (1 + 1e-9), 0.0]), est, list(range(6)), fd.DEFAULT_LADDER,
                        steps=steps, magnitude=np.array([4.2, 4.7e-17]), eps=fd.EPS_QUAD,
                        rtol=1e-10)
    assert v.status == "failed"


@pytest.mark.slow
@pytest.mark.fortran
def test_the_quad_reference_reproduces_closed_form_elasticity(tmp_path):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cf_integration", Path(__file__).with_name("test_corpus_features_integration.py"))
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    from umat_oti.corpus_features.harness import CorpusEntry, build_all
    from umat_oti.corpus_features.independence import check_iso_elastic
    from umat_oti.corpus_features.paths import internal_paths, kinematics_for
    source = tmp_path / "tiny.f"
    source.write_text(T.TINY_UMAT)
    entry = CorpusEntry(key="tiny", source_id="t", original_source=source, ntens=6, nstatv=1,
                        props=[2.0e5, 0.3])
    builds = build_all(entry, tmp_path / "w", want_store=False, want_lifted=False)
    assert builds.original_quad.ok, builds.original_quad.log[-2000:]
    path = internal_paths(entry.as_mapping())[1]
    kin = kinematics_for(path, 3, 3)
    incs = [(d, f0, f1, r, i.dtime, i.temp, i.dtemp) for (d, f0, f1, r), i in zip(kin, path.increments)]
    ladder = tuple(10.0 ** -k for k in range(2, 13))
    double = check_iso_elastic(builds.original, tmp_path / "d", props=entry.props, ntens=6, ndi=3,
                               nshr=3, increments=incs, ladder=ladder)
    quad = check_iso_elastic(builds.original_quad, tmp_path / "q", props=entry.props, ntens=6, ndi=3,
                             nshr=3, increments=incs, ladder=ladder, quad=True)
    assert double["status"] == "verified" and quad["status"] == "verified", quad
    assert quad["worst_rel"] < 1e-12 < double["worst_rel"]
    assert quad["min_plateau"] >= 6


def test_a_total_derivative_keeps_the_roundoff_of_the_history_it_was_carried_through():
    # measured (abaci cyclic, increment 50): response back at ~0, quad FD 2e-34,
    # OTI total derivative 4.8e-18 = double round-off carried through 50 increments
    est = [np.array([2.1e-34]) for _ in fd.DEFAULT_LADDER]
    steps = [2.0e3 * r for r in fd.DEFAULT_LADDER]          # PROPS(1) ~ 2e5
    kw = dict(steps=steps, magnitude=np.array([1e-30]), eps=fd.EPS_QUAD)
    bare = fd.judge_column(np.array([4.77e-18]), est, list(range(6)), fd.DEFAULT_LADDER, **kw)
    assert bare.status == "failed"                           # judged below double resolution
    # B2c: the carried term is capped at 1e-3 of the column's derivative scale
    # over the PATH (dsigma/dE ~ strain ~ 1.5e-3 earlier on the abaci path);
    # without a path scale the column's own ~0 reference cannot open it
    kw["value_magnitude"] = np.array([50 * 300.0])
    uncapped = fd.judge_column(np.array([4.77e-18]), est, list(range(6)), fd.DEFAULT_LADDER, **kw)
    assert uncapped.status != "verified"
    carried = fd.judge_column(np.array([4.77e-18]), est, list(range(6)), fd.DEFAULT_LADDER,
                              derivative_scale=1.5e-3, **kw)
    assert carried.status == "verified"
    # a real error at the history scale is still caught
    wrong = fd.judge_column(np.array([1e-12]), est, list(range(6)), fd.DEFAULT_LADDER,
                            derivative_scale=1.5e-3, **kw)
    assert wrong.status == "failed"
