"""The controlled experiment was already on disk; it only had to be re-run.

After a verification run the work directory holds the probe's ENTRY record --
every argument Abaqus passed -- and the transformed build's generated source
beside the compiled OTI modules it links against. So one call can be replayed
outside Abaqus, from exactly those arguments, in either build, as often as a
bisection needs.

What that bought, measured on pass9:

* ``Worlthen/simplified_curing.for``: the replay returns NaN in the same nine
  components the pass9 probe recorded -- all six stresses and STATEV(1), (2),
  (4) -- with STATEV(3) finite in both and agreeing to 1.1e-15 of the state
  field, a double's last place on the one number that goes through ``exp``.
  Bisected inside, the operation
  is ``(cure/max_cure)**m`` at ``cure = 0``. Side by side on the shipped
  module: ``q**0.4d0`` returns a real part of 0.0, ``q**oti(0.4)`` returns NaN.
  The generated helper declares the author's ``double precision ... m`` as
  ``TYPE(ONUMM6N1)``, which is what sends it down the second path.
* ``RitioL/huang_umat_97.for``: the replay reproduces the solver's corrupted
  STATEV(25) bit for bit under the solver's own flags and returns the CORRECT
  value under ``-no-vec``, ``-O1``, ``-O0``, ``-check bounds``, or without
  ``-align array64byte`` / ``-auto`` / ``-fstack-protector-strong``. The flags
  had to match the job's own ``.com`` before that meant anything: built with a
  reasonable-looking subset it silently returned the right answer, which would
  have read as "the transform is fine here".
* ``awhelanUCD/HETVAL_lemaitreDamageNonLocal.f``: the replay reproduces the
  divergence at ``-O0`` too, which separates it from the above as a defect in
  what the source says rather than in what the compiler made of it.
"""
import math
import os
import pathlib
import shutil

import pytest

from umat_oti.abaqus import single_call as sc


def _corpus_run(name: str = "pass9"):
    root = pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or pathlib.Path.home() / "softwarex_work" / "corpus_run")
    where = root / name
    if not where.is_dir():
        pytest.skip(f"no corpus run at {where}; set UMAT_OTI_CORPUS_RUN")
    return where


# ---------------------------------------------------------------------------
# offline, no compiler
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.unit

STUBS_WITH_ROTSIG = """\
SUBROUTINE GETOUTDIR(PATH,NCHAR)
  CHARACTER(*) :: PATH
  PATH='.'
END SUBROUTINE GETOUTDIR
SUBROUTINE ROTSIG(S,R,O,L,NDI,NSHR)
  REAL(8) :: S(*),R(3,3),O(*)
  IF (NDI .GT. 0) THEN
    O(1) = S(1)
  END IF
END SUBROUTINE ROTSIG
SUBROUTINE XIT
  STOP 3
END SUBROUTINE XIT
"""


def test_a_stub_the_source_defines_itself_is_dropped_not_defined_twice():
    """awhelanUCD/HETVAL_lemaitreDamageNonLocal.f ships its own ROTSIG. Linking
    the stub block beside it gave `multiple definition of 'rotsig_'` and no
    replay at all -- a source excluded from the evidence for supplying more of
    Abaqus's interface than the others."""
    kept, dropped = sc.drop_stubs_defined_by(
        STUBS_WITH_ROTSIG,
        "      SUBROUTINE ROTSIG(S,R,O,L,NDI,NSHR)\n      RETURN\n      END\n")
    assert dropped == ["ROTSIG"]
    assert sc.routines_defined(kept) == {"GETOUTDIR", "XIT"}


def test_end_if_does_not_close_a_program_unit():
    """Written as `END\\s*\\w*`, the closing-line pattern matched `END IF`: the
    first one inside a stub ended the block, the rest was scanned as a new
    program unit, and ROTSIG was reported -- and removed -- twice."""
    kept, dropped = sc.drop_stubs_defined_by(STUBS_WITH_ROTSIG, "")
    assert dropped == []
    assert sc.routines_defined(kept) == {"GETOUTDIR", "ROTSIG", "XIT"}


def test_a_replay_that_did_not_reproduce_the_record_is_reported_as_such():
    """A bisection inside a replay proves nothing about the solver's run unless
    the replay IS the solver's run. That has to be checked, not assumed."""
    result = sc.CallResult(stress=[1.0, 2.0], state=[3.0], ok=True)
    good = sc.reproduces(result, {"STRESS": [1.0, 2.0], "STATEV": [3.0]})
    bad = sc.reproduces(result, {"STRESS": [1.0, 2.5], "STATEV": [3.0]})
    assert good["reproduced"] and good["worst"] == 0.0
    assert not bad["reproduced"]
    assert "not a replay of that call" in bad["reason"]


def test_a_recorded_nan_is_reproduced_by_a_nan_not_failed_by_one():
    """simplified_curing's recorded result IS NaN, and NaN != NaN. A comparison
    that only asked "is the difference small" would call the one case this was
    built for a failure to reproduce."""
    nan = float("nan")
    result = sc.CallResult(stress=[nan] * 6, state=[nan, nan, 0.0124702757],
                           ok=True)
    verdict = sc.reproduces(
        result, {"STRESS": [nan] * 6, "STATEV": [nan, nan, 0.0124702757]})
    assert verdict["reproduced"]


def test_a_finite_result_does_not_reproduce_a_recorded_nan():
    nan = float("nan")
    verdict = sc.reproduces(sc.CallResult(stress=[0.0] * 6, ok=True),
                            {"STRESS": [nan] * 6})
    assert not verdict["reproduced"]
    assert "not finite" in verdict["reason"]


def test_the_replay_flags_are_the_solver_s_own():
    """A replay built without -axcore-avx2,avx and -align array64byte is a
    different binary from the one the solver ran. Measured: the
    crystal-plasticity replay built without them returns the CORRECT
    STATEV(25) where the solver's build returns -1.698e-30."""
    assert "-axcore-avx2,avx" in sc.ABAQUS_IFORT_FLAGS
    assert "array64byte" in sc.ABAQUS_IFORT_FLAGS
    assert "threaded" in sc.ABAQUS_IFORT_FLAGS
    assert "-fstack-protector-strong" in sc.ABAQUS_IFORT_FLAGS


def test_the_replay_does_not_call_sdvini():
    """replay.py calls the author's SDVINI over an all-zero state, which is
    right for a finite difference and wrong here. On simplified_curing it would
    have hidden the finding: the author's SDVINI seeds STATEV(1) = 1.d-15
    precisely to keep the model off the singular point the generated deck put
    it on."""
    executable = [line for line in sc.driver_source("X").splitlines()
                  if not line.lstrip().startswith("!")]
    assert not any("SDVINI" in line.upper() for line in executable)


def test_the_replay_writes_back_the_state_not_only_the_stress():
    """The crystal-plasticity divergence is entirely inside STATEV; a driver
    that reported only STRESS would have shown two identical calls."""
    source = sc.driver_source("X")
    assert "NSTATV " in source and "STATEV(I)" in source


# ---------------------------------------------------------------------------
# against the corpus, with a compiler
# ---------------------------------------------------------------------------
def _replay(key, call_index, tmp_path):
    from umat_oti.abaqus import call_isolation as ci
    from umat_oti.abaqus.replay import write_state

    if shutil.which("ifort") is None:
        pytest.skip("no ifort on PATH")
    work = _corpus_run() / "work" / key
    if not (work / "transformed" / "transformed_probe.txt").is_file():
        pytest.skip(f"no pass9 probe records for {key}")
    inputs = sc.transformed_build_inputs(work)
    if not inputs["present"]:
        pytest.skip(f"no generated source and objects kept for {key}")
    _, transformed = ci.read_pair(work)
    entry, recorded = ci.pair_calls(transformed)[call_index]
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    write_state(entry, tmp_path / sc.STATE_FILE)
    build = sc.build_call(inputs["source"], tmp_path, compiler="ifort",
                          objects=inputs["objects"],
                          module_dirs=inputs["module_dirs"],
                          flags=list(sc.ABAQUS_IFORT_FLAGS))
    assert build.ok, build.reason + build.log[-1500:]
    return sc.run_call(build, tmp_path), recorded, build


@pytest.mark.fortran
@pytest.mark.integration
def test_the_curing_model_returns_the_recorded_nan_when_replayed(tmp_path):
    """Not a NaN: THE NaN, in the same nine components.

    STRESS in all six, STATEV(1), (2) and (4), and STATEV(3) finite in both --
    1.2470275728981441E-02 as Abaqus recorded it, 1.2470275728981415E-02 in the
    replay. Those differ in the sixteenth digit, which is 1.1e-15 of the state
    field and inside REPLAY_SAME; the one number this call computes from a
    library function (exp) is the one that moves, and it moves by about a
    double's last place. Asserted at that tolerance rather than exactly,
    because claiming bit-equality here would be claiming something that is not
    true."""
    result, recorded, _ = _replay("a3f970a8788b998cd2fef291", 0, tmp_path)
    verdict = sc.reproduces(result, recorded)
    assert verdict["reproduced"], verdict["reason"]
    assert verdict["worst"] < 1e-14
    assert all(math.isnan(value) for value in result.stress)
    assert [index for index, value in enumerate(result.state)
            if math.isnan(value)] == [0, 1, 3]
    assert result.state[2] == pytest.approx(1.2470275728981441e-02, rel=1e-14)


@pytest.mark.fortran
@pytest.mark.integration
def test_the_crystal_plasticity_slot_is_corrupted_by_the_build_not_the_algebra(
        tmp_path):
    """Under the solver's own flags the replay returns -1.6982275886200392e-30
    for STATEV(25), bit for bit what Abaqus recorded. Under -no-vec, the same
    source, the same objects and the same arguments return
    -73.4629074865463 -- the author's value."""
    result, recorded, _ = _replay("0d97f9db648d23a064062989", 4, tmp_path)
    assert sc.reproduces(result, recorded)["reproduced"]
    assert result.state[24] == -1.6982275886200392e-30

    from umat_oti.abaqus import call_isolation as ci
    from umat_oti.abaqus.replay import write_state
    work = _corpus_run() / "work" / "0d97f9db648d23a064062989"
    inputs = sc.transformed_build_inputs(work)
    _, transformed = ci.read_pair(work)
    entry, _unused = ci.pair_calls(transformed)[4]
    novec = tmp_path / "novec"
    novec.mkdir()
    write_state(entry, novec / sc.STATE_FILE)
    build = sc.build_call(inputs["source"], novec, compiler="ifort",
                          objects=inputs["objects"],
                          module_dirs=inputs["module_dirs"],
                          flags=list(sc.ABAQUS_IFORT_FLAGS) + ["-no-vec"])
    assert build.ok, build.reason
    assert sc.run_call(build, novec).state[24] == pytest.approx(
        -73.46290748654624, rel=1e-12)


@pytest.mark.fortran
@pytest.mark.integration
def test_the_lemaitre_divergence_survives_switching_optimisation_off(tmp_path):
    """Which is what separates it from the crystal-plasticity one. STATEV(3) is
    333.5668828923864 in the transformed build at every optimisation level
    tried, against 6.660008321683725e-04 in the author's -- a stress-sized
    number where a strain belongs. The generated source passes the REAL*8
    statev(1) to ROTSIG_OTI, whose first dummy is TYPE(ONUMM3N1) :: S(NDI+NSHR)."""
    result, recorded, _ = _replay("f425611a8d9036c13b6f1d58", 8, tmp_path)
    assert sc.reproduces(result, recorded)["reproduced"]
    assert result.state[2] == pytest.approx(333.5668828923864, rel=1e-12)

    from umat_oti.abaqus import call_isolation as ci
    from umat_oti.abaqus.replay import write_state
    work = _corpus_run() / "work" / "f425611a8d9036c13b6f1d58"
    inputs = sc.transformed_build_inputs(work)
    _, transformed = ci.read_pair(work)
    entry, _unused = ci.pair_calls(transformed)[8]
    unoptimised = tmp_path / "O0"
    unoptimised.mkdir()
    write_state(entry, unoptimised / sc.STATE_FILE)
    build = sc.build_call(inputs["source"], unoptimised, compiler="ifort",
                          objects=inputs["objects"],
                          module_dirs=inputs["module_dirs"],
                          flags=list(sc.ABAQUS_IFORT_FLAGS) + ["-O0"])
    assert build.ok, build.reason
    assert sc.run_call(build, unoptimised).state[2] == pytest.approx(
        333.5668828923864, rel=1e-12)


@pytest.mark.fortran
@pytest.mark.integration
def test_a_routine_that_saves_state_stops_replaying_in_isolation(tmp_path):
    """Growth-Robot.for carries a block of SAVEd variables. Its calls 0 and 1
    replay bit for bit; calls 2 and 3 do not, differing by 2.7e-02 of the
    stress field. That is the instrument reporting its own limit -- and it is
    also a measurement: a routine whose later calls need the earlier ones is
    carrying state between them."""
    early, recorded_early, _ = _replay("d916a87ff9b360fbe3c855b3", 0, tmp_path)
    assert sc.reproduces(early, recorded_early)["reproduced"]
    later, recorded_later, _ = _replay("d916a87ff9b360fbe3c855b3", 2,
                                       tmp_path / "later")
    assert not sc.reproduces(later, recorded_later)["reproduced"]
