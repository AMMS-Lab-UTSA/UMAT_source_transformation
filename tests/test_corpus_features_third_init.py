"""D-12 with three init builds (Vera B2 item 2).

zero vs snan alone misses an uninitialised value used through a NaN guard
(``IF (XK.NE.XK) XK=0``), a comparison (``IF (XK.GT.0.5)``) and an INTEGER
(``IF (NC.GT.0)``, 0 and -77777 both <= 0): in Vera's toys those outputs were
bit-identical across the pair and the cells verified. The third build (+inf
reals, +77777 integers, logicals flipped vs the zero build) separates them, on
the harness side AND on the Abaqus-side init check; the clean toy is unchanged.
Toys: corpus_campaign/batches/B2/vera/toys (copied to fixtures).
"""
import shutil
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.fortran]

TOYS = Path(__file__).parent / "fixtures" / "corpus_features_b2_toys"
REPO = Path(__file__).resolve().parents[1]
DEFECTIVE = ("b2_nan_guard", "b4b_cmp_uninit", "b4c_int_uninit")


def test_one_shared_definition_of_the_init_builds():
    from umat_oti.abaqus import replay
    from umat_oti.corpus_features import harness
    assert harness.FINIT_BUILDS is replay.FINIT_BUILDS
    names = [n for n, _ in replay.FINIT_BUILDS]
    assert names == ["zero", "snan", "inf"]
    flags = dict(replay.FINIT_BUILDS)
    assert "-finit-real=inf" in flags["inf"] and "-finit-integer=77777" in flags["inf"]
    # logicals flipped vs the zero (reference) build
    assert "-finit-logical=false" in flags["zero"] and "-finit-logical=true" in flags["inf"]


@pytest.fixture(scope="module")
def harness_results(tmp_path_factory):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features.harness import CorpusEntry, run_entry
    from umat_oti.corpus_features.paths import internal_paths
    root = tmp_path_factory.mktemp("third_init")
    out = {}
    for name in DEFECTIVE + ("toy_clean",):
        store = root / "store" / name
        store.mkdir(parents=True)
        shutil.copy(TOYS / f"{name}.f", store / "umat.f")
        (store / "compile_order.txt").write_text("umat.f\n")
        entry = CorpusEntry(key=name, source_id=f"vera_toy/{name}",
                            original_source=TOYS / f"{name}.f", ntens=6, nstatv=2,
                            props=[2.0e5, 0.3], store_dir=store)
        path = internal_paths({"ndi": 3, "nshr": 3})[:1]
        out[name] = run_entry(entry, root / "work", paths=path,
                              features=("primal_stress_state", "ddsdde"))
    return out


@pytest.mark.parametrize("name", DEFECTIVE)
def test_harness_flags_what_zero_vs_snan_missed(harness_results, name):
    records = harness_results[name]
    assert all(not r.get("hidden_state_trips") for r in records), records[0].get("hidden_state_trips")
    assert "STRESS(1)" in records[0]["undefined_outputs"], records[0]["undefined_outputs"]
    assert all(r["stress_and_ddsdde_fully_defined"] is False for r in records)


def test_harness_clean_toy_unchanged(harness_results):
    records = harness_results["toy_clean"]
    assert all(r["undefined_outputs"] == [] for r in records)
    assert all(r["stress_and_ddsdde_fully_defined"] for r in records)
    by = {r["feature"]: r for r in records}
    assert by["ddsdde"]["status"] == "verified", by["ddsdde"]["reason"]
    assert by["primal_stress_state"]["status"] == "verified"


def _abaqus_side(tmp_path, name):
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import verify_store_in_abaqus as V
    include = tmp_path / "inc"
    include.mkdir()
    for inc in ("aba_param.inc", "ABA_PARAM.INC"):
        (include / inc).write_text("      implicit real*8(a-h,o-z)\n")
    source = tmp_path / f"{name}_probed.for"
    shutil.copy(TOYS / f"{name}.f", source)
    entry = {"NTENS": 6, "NSTATV": 2, "NPROPS": 2, "NDI": 3, "NSHR": 3,
             "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
             "STATEV0": [0.0, 0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
             "PROPS": [2.0e5, 0.3], "COORDS": [0.0, 0.0, 0.0, 1.0]}
    return V.init_variant_check(source, [entry, entry], tmp_path / "work", ntens=6,
                                include_dirs=[include])


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
@pytest.mark.parametrize("name", DEFECTIVE)
def test_abaqus_side_flags_what_zero_vs_snan_missed(tmp_path, name):
    check = _abaqus_side(tmp_path, name)
    assert check["established"], check
    # B17 G2a: the ifort set the solver is built with decides; the gfortran
    # zero/snan/inf set (these toys were made for) is the recorded secondary.
    gnu = check if check.get("decided_by") == "gfortran" else check["secondary"]
    assert gnu["init_variants"] == ["zero", "snan", "inf"]
    assert 1 in gnu["undefined"]["STRESS"], gnu["undefined"]
    assert any(d["init_variant"] == "inf" for d in gnu["undefined"]["details"])
    assert 1 in check["undefined"]["STRESS"], check["undefined"]   # and the primary agrees


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_abaqus_side_clean_toy_unchanged(tmp_path):
    check = _abaqus_side(tmp_path, "toy_clean")
    assert check["established"], check
    assert check["undefined"]["details"] == []
