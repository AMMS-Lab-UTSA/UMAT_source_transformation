"""Driver point from the source's own Abaqus experiment (pass18 COORDS fix).

The routine-level driver ran every source at COORDS = 0, NOEL = NPT = 1; a
position-dependent growth law (Jeff97 circular plate/shell, mholla BMMB24)
is non-finite there, so 17 sources that passed the Abaqus primal gate were
routine-level ``inconclusive``. The harness now takes NOEL, NPT and COORDS
from the first call recorded by the probe of the generated original deck.
Toy: growth rate ~ (1 + NPT/10) / r -- non-finite at COORDS = 0, verified at
the recorded point.
"""
import shutil
from pathlib import Path

import pytest

TOY = Path(__file__).parent / "fixtures" / "corpus_features_position_toy" / "growth_over_r.f"

# Format of corpus_run/pass18/work/<key>/original/original_probe.txt
PROBE = """ENTRY original        3        2        1        1   0.00000000000000000E+000
SHAPE        6        1        3        3        3
DTIME        1
   0.10000000000000000E+000
COORDS        4
   0.78867513459481287E+000   0.21132486540518503E+000   0.21132486540518503E+000   0.10000000000000002E+001
ENTRY original        3        3        1        1   0.00000000000000000E+000
COORDS        4
   0.78867513459481287E+000   0.78867513459481287E+000   0.21132486540518503E+000   0.10000000000000002E+001
"""


def _experiment(root: Path, key: str) -> Path:
    original = root / key / "original"
    original.mkdir(parents=True)
    (original / "original_probe.txt").write_text(PROBE)
    return root


def test_driver_point_is_the_first_recorded_call(tmp_path):
    from umat_oti.corpus_features import harness
    root = _experiment(tmp_path / "work", "k")
    point = harness.experiment_driver_point("k", root)
    assert (point["noel"], point["npt"]) == (3, 2)
    assert point["coords"] == pytest.approx([0.78867513459481287, 0.21132486540518503,
                                             0.21132486540518503], abs=0, rel=1e-15)
    assert "line 1" in point["provenance"] and "element 3, point 2" in point["provenance"]
    missing = harness.experiment_driver_point("absent", root)
    assert missing["coords"] == [0.0, 0.0, 0.0] and (missing["noel"], missing["npt"]) == (1, 1)
    assert "no recorded Abaqus call" in missing["provenance"]


def test_config_carries_the_point_and_reads_legacy_configs(tmp_path):
    from umat_oti.corpus_features import drivers as dv
    config = dv.RunConfig(ntens=6, nstatv=1, nprops=3, ndi=3, nshr=3, props=[1.0, 0.3, 0.0],
                          statev0=[0.0], cmname="T", increments=[], coords=(0.5, 0.25, 0.0),
                          noel=7, npt=4)
    line = config.write(tmp_path).read_text().splitlines()[4]
    assert line.split() == ["0.5", "0.25", "0.0", "7", "4"]
    # a frozen config (COORDS only) falls back to NOEL = NPT = 1 in the driver
    assert "NOEL0=1; NPT0=1" in dv._READ_CONFIG and "IOSTAT=IOS) (COORDS0(I),I=1,3),NOEL0,NPT0" \
        in dv._READ_CONFIG


@pytest.mark.slow
@pytest.mark.fortran
def test_position_dependent_toy_verifies_at_the_recorded_point(tmp_path):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features import harness
    from umat_oti.corpus_features.harness import CorpusEntry, run_entry
    from umat_oti.corpus_features.paths import internal_paths
    root = _experiment(tmp_path / "experiment", "toy_r")
    store = tmp_path / "store"
    store.mkdir()
    shutil.copy(TOY, store / "umat.f")
    (store / "compile_order.txt").write_text("umat.f\n")
    path = internal_paths({"ndi": 3, "nshr": 3})[:1]
    out = {}
    for label, point in (("zero", None), ("recorded", harness.experiment_driver_point("toy_r", root))):
        entry = CorpusEntry(key="toy_r", source_id="gauss_toy/growth_over_r", original_source=TOY,
                            ntens=6, nstatv=1, props=[2.0e5, 0.3, 1.0e-3], store_dir=store)
        if point is not None:
            entry.driver_point = point
        records = run_entry(entry, tmp_path / label, paths=path,
                            features=("primal_stress_state", "ddsdde"))
        out[label] = {r["feature"]: r for r in records}
        for r in records:
            assert r["driver_point"] == entry.driver_point
            assert r["build_info"]["driver_point"]["NOEL"] == entry.driver_point["noel"]
    zero = out["zero"]["primal_stress_state"]
    assert zero["status"] == "inconclusive" and "not finite" in zero["reason"], zero["reason"]
    rec = out["recorded"]
    assert rec["primal_stress_state"]["status"] == "verified", rec["primal_stress_state"]["reason"]
    assert rec["ddsdde"]["status"] == "verified", rec["ddsdde"]["reason"]
    assert rec["primal_stress_state"]["driver_point"]["npt"] == 2
