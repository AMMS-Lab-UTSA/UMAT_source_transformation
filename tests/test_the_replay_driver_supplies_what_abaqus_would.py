"""What the offline replay driver has to supply because Abaqus is not there.

A UMAT is written against a solver, not against a program. Two of the things
the solver does before and around a UMAT call were missing from the replay
driver, and both showed up as a *failure of the untransformed original* -- the
tell that the harness was at fault rather than the transform.

The first is SDVINI. Abaqus calls the author's own SDVINI to fill STATEV
before the first increment; the driver did not, so every model whose state
starts at anything other than zero was replayed from a state its author never
declared. Eight mholla growth sources read a growth stretch their SDVINI sets
to 1.0 and divide by it, so both builds returned NaN and the row was undecided.

The second is the utility library. ``STDB_ABQERR``, ``GET_THREAD_ID``,
``GETJOBNAME`` and ``GETVRM`` live in Abaqus, not in libgfortran, so a source
that calls one of them does not link at all -- which is not a result about the
model.

If any of this regresses: a model with an SDVINI is silently driven from zero
state again (NaN, or worse, a finite answer to a question nobody asked), a
recorded increment is replayed from the initial state instead of the state the
solver had reached, or a source that calls an Abaqus utility is recorded as a
build failure that reads like a defect in the transform.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from umat_oti.abaqus.replay import (
    STATE_FILE, build_replay, declared_start, defines_sdvini, driver_source,
    run_replay, write_state,
)

pytestmark = pytest.mark.fortran

#: The flags the offline gate compiles this corpus with: fixed-form lines run
#: past column 72, the dialect is three standards old, and warnings on a
#: thousand-line UMAT are noise. Repeated here rather than imported so that a
#: change in the gate's flags cannot quietly change what these tests compiled.
FLAGS = ("-ffixed-line-length-132", "-std=legacy", "-O2", "-w")

#: The cache lives outside the repository and its location belongs to whoever
#: ran discovery, so it is named rather than hardcoded.
CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
             or Path(__file__).resolve().parents[2] / "discovery_cache")

needs_gfortran = pytest.mark.skipif(shutil.which("gfortran") is None,
                                    reason="gfortran is required")
needs_cache = pytest.mark.skipif(not CACHE.is_dir(),
                                 reason="no discovery cache on this machine")

#: A UMAT in the shape this corpus is written in: fixed form, the Abaqus
#: argument list, and the implicit typing rule aba_param.inc carries. The
#: declarations of the body go in before the first executable statement,
#: because that is where Fortran puts them.
_UMAT_HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IMPLICIT REAL*8(A-H,O-Z)
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),
     2 PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
"""

_UMAT_ZERO = """      DO 10 I=1,NTENS
        STRESS(I)=0.0D0
   10 CONTINUE
"""

_UMAT_TAIL = """      RETURN
      END
"""

#: An author's SDVINI, in the shape the mholla growth sources ship it: a
#: fixed-form subroutine in the same file as the UMAT, setting the state a
#: virgin material point starts from.
_SDVINI = """      SUBROUTINE SDVINI(STATEV,COORDS,NSTATV,NCRDS,NOEL,NPT,LAYER,KSPT)
      IMPLICIT REAL*8(A-H,O-Z)
      DIMENSION STATEV(NSTATV),COORDS(NCRDS)
      STATEV(1)=2.5D0
      RETURN
      END
"""


def _source(body: str, *, declarations: str = "", sdvini: bool = False) -> str:
    return ((_SDVINI if sdvini else "") + _UMAT_HEAD + declarations
            + _UMAT_ZERO + body + _UMAT_TAIL)


def _replay(tmp_path: Path, text: str, *, state: dict | None = None):
    """Build and run one replay of a synthetic source. Returns (stress, why)."""
    source = tmp_path / "probe_umat.f"
    source.write_text(text, encoding="utf-8")
    entry = state if state is not None else declared_start(
        (1.0,), ntens=6, nstatv=3)
    write_state(entry, tmp_path / STATE_FILE)
    build = build_replay(source, tmp_path, name="MAT",
                         flags=(*FLAGS, f"-J{tmp_path}"))
    if not build.ok:
        return [], f"{build.reason}\n{build.log}"
    return run_replay(build, tmp_path, 0, 0.0)


class TestTheAuthorsOwnSdviniIsRun:
    """Abaqus runs SDVINI before the first increment; so must the replay.

    Reading the constants out of SDVINI would be a second implementation of the
    author's declaration. Calling it runs the author's own code, which is also
    the only thing that gets a state variable set from COORDS or NOEL right.
    """

    def test_a_defined_sdvini_is_found(self):
        assert defines_sdvini(_SDVINI + _UMAT_HEAD) is True

    def test_a_source_without_one_is_not_claimed_to_have_one(self):
        """Emitting the call for a source with no SDVINI would fail the link."""
        assert defines_sdvini(_UMAT_HEAD) is False

    def test_a_commented_out_sdvini_is_not_a_definition(self):
        """Fixed form puts comments in column 1; a comment defines no symbol."""
        assert defines_sdvini(
            "c     subroutine sdvini(statev,coords,nstatv,ncrds)\n") is False

    def test_calling_sdvini_is_not_defining_it(self):
        assert defines_sdvini(
            "      CALL SDVINI(STATEV,COORDS,NSTATV,3,1,1,1,1)\n") is False

    def test_the_call_is_emitted_only_when_it_can_link(self):
        assert "CALL SDVINI(" in driver_source("MAT", initialise_state=True)
        assert "CALL SDVINI(" not in driver_source("MAT")

    @needs_gfortran
    def test_the_state_the_author_declared_is_what_the_umat_reads(self, tmp_path):
        """Before this, umat_iso_stretch.f read 0.0 for a stretch of 1.0.

        It then divided by it: NaN out of the ORIGINAL build, which is the
        source saying the harness handed it a state it was never written for.
        """
        stress, why = _replay(tmp_path, _source(
            "      STRESS(1)=STATEV(1)\n", sdvini=True))
        assert stress, why
        assert stress[0] == pytest.approx(2.5)

    @needs_gfortran
    def test_a_recorded_state_is_not_overwritten_by_it(self, tmp_path):
        """A replay of a recorded increment must start where the solver was.

        SDVINI is what a *virgin* point starts from. An ENTRY record from the
        probe carries the state the solver had already reached, and running
        SDVINI over it would replay a different increment from the one
        recorded -- silently, and with a plausible-looking answer.
        """
        state = declared_start((1.0,), ntens=6, nstatv=3,
                               initial_statev=(7.0, 0.0, 0.0))
        stress, why = _replay(tmp_path, _source(
            "      STRESS(1)=STATEV(1)\n", sdvini=True), state=state)
        assert stress, why
        assert stress[0] == pytest.approx(7.0)

    @needs_gfortran
    def test_a_source_without_an_sdvini_still_links_and_runs(self, tmp_path):
        """The call must not be emitted where there is nothing to call."""
        stress, why = _replay(tmp_path, _source("      STRESS(1)=1.5D0\n"))
        assert stress, why
        assert stress[0] == pytest.approx(1.5)

    @needs_gfortran
    @needs_cache
    @pytest.mark.regression
    def test_a_growth_model_from_the_corpus_stops_returning_nan(self, tmp_path):
        """mholla/growth umat_iso_stretch.f, the case this fix was found on.

        Its SDVINI sets statev(1..3)=1.0 and its UMAT divides by statev(1).
        Replayed from zero state it returned NaN in all six components, from
        both builds; the offline gate recorded it as non_finite_response.
        """
        source = CACHE / "mholla__growth" / "umats" / "umat_iso_stretch.f"
        if not source.is_file():
            pytest.skip("that source is not in this cache")
        # The material constants of the author's own deck, cube_1_C3D8_noload.inp
        # (*User Material, constants=6): nothing here is invented.
        props = (0.577, 0.385, 0.0, 1.0, 0.0, 0.2)
        state = declared_start(props, ntens=6, nstatv=3)
        # This source computes its stress from DFGRD1 and never reads DSTRAN,
        # so the increment has to be carried by the gradient: at the identity
        # it reports the stress of a body that was never deformed, which is
        # zero, and a finite zero would prove no more than the NaN did.
        state["DFGRD1"] = [1.0 + 1.0e-4, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        write_state(state, tmp_path / STATE_FILE)
        build = build_replay(source, tmp_path, name="MAT",
                             flags=(*FLAGS, f"-J{tmp_path}"))
        assert build.ok, f"{build.reason}\n{build.log}"
        stress, why = run_replay(build, tmp_path, 0, 0.0)
        assert stress, why
        assert all(value == value for value in stress), (
            f"the replayed stress is still not finite: {stress}")
        assert any(value != 0.0 for value in stress)


class TestTheUtilitiesTheSolverWouldProvide:
    """Abaqus's utility library is not libgfortran's, and a link is not a result."""

    @pytest.mark.parametrize("name", ["GETOUTDIR", "XIT", "GETJOBNAME",
                                      "STDB_ABQERR", "GET_THREAD_ID", "GETVRM"])
    def test_the_driver_carries_a_definition(self, name):
        """Six cache files call one of these; without a body they do not link.

        A definition, not a mention: the symbol has to be introduced by
        SUBROUTINE or FUNCTION or the linker still has nothing to resolve.
        """
        text = driver_source("MAT")
        assert any(line in text for line in
                   (f"SUBROUTINE {name}(", f"SUBROUTINE {name}\n",
                    f"FUNCTION {name}(", f"FUNCTION {name}\n"))

    @needs_gfortran
    def test_the_thread_id_a_umat_reads_is_the_master_thread(self, tmp_path):
        """GET_THREAD_ID must come back as 0, in the type the caller assumes.

        Abaqus declares it INTEGER in SMAASPUSERSUBROUTINES.HDR, which is a
        preprocessor include gfortran does not process in a fixed-form .f. The
        caller therefore types it by the implicit rule these sources carry --
        REAL*8(A-H,O-Z), and G is in A-H -- and reads the result out of the
        floating-point register. Measured on UMAT_KLP_RK5_hybrid.f: gfortran
        emits `call get_thread_id_; cvttsd2sil %xmm0,%eax`. An INTEGER stub
        returns in %eax, leaving the caller reading whatever was in %xmm0, and
        a thread id that is not 0 silently skips the input checks the author
        guarded with IF (MYTHREADID.EQ.0).
        """
        stress, why = _replay(tmp_path, _source(
            "      MYID=GET_THREAD_ID()\n      STRESS(1)=MYID\n"))
        assert stress, why
        assert stress[0] == pytest.approx(0.0)

    @needs_gfortran
    def test_a_fatal_diagnostic_stops_the_run(self, tmp_path):
        """STDB_ABQERR(-3,...) is Abaqus terminating the analysis at once.

        A silent stub would let the increment the author refused to compute
        flow into the evidence as though it had been computed.
        """
        stress, why = _replay(tmp_path, _source(
            "      INTV(1)=0\n      REALV(1)=0.D0\n      CHARV(1)=''\n"
            "      CALL STDB_ABQERR(-3,'MODEL REFUSED THIS INPUT',\n"
            "     1 INTV,REALV,CHARV)\n"
            "      STRESS(1)=1.0D0\n",
            declarations="      DIMENSION INTV(1),REALV(1)\n"
                         "      CHARACTER*8 CHARV(1)\n"))
        assert not stress
        assert "MODEL REFUSED THIS INPUT" in why

    @needs_gfortran
    def test_a_warning_does_not_stop_the_run(self, tmp_path):
        """-1 is a warning in Abaqus; treating it as fatal would lose the row."""
        stress, why = _replay(tmp_path, _source(
            "      INTV(1)=0\n      REALV(1)=0.D0\n      CHARV(1)=''\n"
            "      CALL STDB_ABQERR(-1,'JUST A WARNING',INTV,REALV,CHARV)\n"
            "      STRESS(1)=1.0D0\n",
            declarations="      DIMENSION INTV(1),REALV(1)\n"
                         "      CHARACTER*8 CHARV(1)\n"))
        assert stress, why
        assert stress[0] == pytest.approx(1.0)

    @needs_gfortran
    def test_a_job_name_is_supplied_and_its_length_agrees(self, tmp_path):
        """Sources open files named after the job; a blank name opens nothing."""
        stress, why = _replay(tmp_path, _source(
            "      CALL GETJOBNAME(JOBNAME,LENJOB)\n"
            "      STRESS(1)=LENJOB\n"
            "      STRESS(2)=LEN_TRIM(JOBNAME)\n",
            declarations="      CHARACTER*80 JOBNAME\n"))
        assert stress, why
        assert stress[0] > 0
        assert stress[1] == pytest.approx(stress[0])

    @needs_gfortran
    def test_reading_the_results_database_stops_rather_than_inventing_data(
            self, tmp_path):
        """GETVRM asks Abaqus for output values. There is no Abaqus here.

        It is stubbed so that UMAT_KLP_RK5_hybrid.f links -- its UVARM calls
        GETVRM and is never entered by this driver -- but a UMAT that actually
        calls it would be handed values from a results database that does not
        exist. Returning zeros would be inventing state.
        """
        stress, why = _replay(tmp_path, _source(
            "      CALL GETVRM('S',ARRAY,JARRAY,FLGRAY,JRCD,JMAC,JMATYP,\n"
            "     1 MATLAYO,LACCFLA)\n"
            "      STRESS(1)=ARRAY(1)\n",
            declarations="      DIMENSION ARRAY(15),JARRAY(15),JMAC(1),"
                         "JMATYP(1)\n      CHARACTER*3 FLGRAY(15)\n"))
        assert not stress
        assert "GETVRM" in why

    @needs_gfortran
    @needs_cache
    @pytest.mark.regression
    def test_the_corpus_source_that_would_not_link_now_links(self, tmp_path):
        """UMAT_KLP_RK5_hybrid.f: undefined get_thread_id_ and stdb_abqerr_.

        Both builds failed the same way, which accuses the harness and not the
        transform. The offline gate recorded it as original_build_failed.
        """
        source = (CACHE / "victorlefevre__UMAT_Lefevre_Sozio_Lopez-Pamies"
                  / "Examples" / "C3D8H" / "UT kappa_mu=1"
                  / "UMAT_KLP_RK5_hybrid.f")
        if not source.is_file():
            pytest.skip("that source is not in this cache")
        write_state(declared_start((1.0,) * 6, ntens=6, nstatv=6),
                    tmp_path / STATE_FILE)
        build = build_replay(source, tmp_path, name="MAT",
                             flags=(*FLAGS, f"-J{tmp_path}"))
        assert build.ok, f"{build.reason}\n{build.log}"
