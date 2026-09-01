"""What the tangent driver starts a material point from, and why it matters.

Every UMAT here is driven by a harness, not by Abaqus, so the harness declares
the conditions the point starts in: its state, its position, and the utilities
the solver would otherwise supply. Each of those had a default that looked
neutral and was not. Zero state is wrong for a model whose author ships an
SDVINI. The origin is wrong for a model that resolves a direction from
position -- there it is 0/0. And a missing Abaqus utility is a link failure,
not a result.

The tell in every case was the same: the *untransformed* build failed too. A
transformed build alone failing accuses the transform; both failing accuses
the conditions, and these tests pin the conditions.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.validation.actual_umat_higher_order_generic import (  # noqa: E402
    _abaqus_utility_stubs,
)
from umat_oti.validation.tangent_validation import (  # noqa: E402
    TangentCase, _driver_source, sdvini_initial_state,
)

SDVINI_SOURCE = """      SUBROUTINE SDVINI(STATEV,COORDS,NSTATV,NCRDS,NOEL,NPT,LAYER,KSPT)
      DIMENSION STATEV(NSTATV)
      statev(1)=1.0d0
      statev(2) = 1.d0
c     statev(3)=1.0d0
      statev(4)=2.5
      statev(5)=COORDS(1)
      RETURN
      END
      SUBROUTINE UMAT(STRESS)
      statev(6)=9.0d0
      RETURN
      END
"""


def _case(**kwargs) -> TangentCase:
    return TangentCase(name="probe", source_path=Path("probe.f"), props=(1.0,),
                       dstran_per_increment=(1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
                       n_increments=2, ntens=6, nstatv=6, **kwargs)


DRIVE = SimpleNamespace(drives_deformation_gradient=False, dfgrd1={})


class TestTheAuthorsOwnInitialState:
    """SDVINI is a declaration by the source's author, not a harness guess."""

    def test_live_assignments_are_read(self):
        assert sdvini_initial_state(SDVINI_SOURCE, 6)[:2] == (1.0, 1.0)

    def test_a_d_exponent_is_a_double(self):
        assert sdvini_initial_state("""      SUBROUTINE SDVINI(STATEV)
      statev(1)=2.5d-3
      END
""", 1) == (0.0025,)

    def test_a_commented_assignment_is_not_an_initial_value(self):
        # The author disabled it. Reading it anyway would start the model in a
        # state its author deliberately turned off.
        assert sdvini_initial_state(SDVINI_SOURCE, 6)[2] == 0.0

    def test_a_value_computed_from_coords_is_left_alone(self):
        # COORDS depends on where the point sits in a mesh this driver does
        # not have. Zero is honest here; a number would be invented.
        assert sdvini_initial_state(SDVINI_SOURCE, 6)[4] == 0.0

    def test_assignments_outside_sdvini_are_not_initial_state(self):
        # statev(6)=9.0d0 is in the UMAT, where it is an update, not a start.
        assert sdvini_initial_state(SDVINI_SOURCE, 6)[5] == 0.0

    def test_no_sdvini_means_no_claim(self):
        assert sdvini_initial_state("      SUBROUTINE UMAT(X)\n      END\n", 4) == (0.0,) * 4

    def test_an_index_past_nstatv_is_dropped_not_written(self):
        assert sdvini_initial_state("""      SUBROUTINE SDVINI(STATEV)
      statev(9)=1.0d0
      END
""", 2) == (0.0, 0.0)

    def test_the_driver_emits_only_the_non_zero_entries(self):
        source = _driver_source(_case(initial_statev=(1.0, 0.0, 2.5, 0, 0, 0)), DRIVE)
        emitted = [line.strip() for line in source.splitlines()
                   if line.strip().startswith("STATEV(")]
        assert emitted == ["STATEV(1) = 1.0_8", "STATEV(3) = 2.5_8"]

    def test_a_source_without_one_is_driven_exactly_as_before(self):
        # No SDVINI must not change one byte of the driver, or every result
        # already recorded for such a source silently becomes incomparable.
        with_state = _driver_source(_case(initial_statev=(1.0,)), DRIVE)
        without = _driver_source(_case(), DRIVE)
        assert with_state.replace("\n  STATEV(1) = 1.0_8", "") == without


class TestWhereTheMaterialPointSits:
    def test_the_declared_position_is_not_the_origin(self):
        # A model that reads a fibre direction off the position computes
        # COORDS(2)/SQRT(COORDS(1)**2+COORDS(2)**2). At the origin that is
        # 0/0, and the untransformed build returns NaN just as the
        # transformed one does -- which is the harness's fault, not the
        # transform's.
        assert all(value != 0.0 for value in _case().coords)

    def test_no_two_coordinates_cancel_to_a_zero_radius(self):
        x, y, z = _case().coords
        for a, b in ((x, y), (y, z), (x, z)):
            assert a * a + b * b > 0.0

    def test_the_driver_sets_every_component(self):
        source = _driver_source(_case(), DRIVE)
        for index, value in enumerate(_case().coords, start=1):
            assert f"COORDS({index})={value!r}_8" in source
        assert "COORDS=0.0_8" not in source


class TestUtilitiesTheSolverWouldSupply:
    def test_the_thread_locks_are_defined(self):
        stubs = _abaqus_utility_stubs()
        for name in ("MUTEXINIT", "MUTEXLOCK", "MUTEXUNLOCK"):
            assert f"SUBROUTINE {name}(" in stubs

    def test_the_thread_locks_do_nothing_and_that_is_exact(self):
        # One thread, one material point: a lock is uncontended by
        # construction, so an empty body is the behaviour, not a stand-in for
        # it. Contrast XIT, which must still abort.
        stubs = _abaqus_utility_stubs()
        body = stubs.split("SUBROUTINE MUTEXLOCK(ID)")[1].split("END SUBROUTINE")[0]
        assert "STOP" not in body and "WRITE" not in body

    def test_an_abort_is_still_an_abort(self):
        assert "STOP 3" in _abaqus_utility_stubs()


class TestBothBuildsStartFromTheSamePlace:
    """The reference is only a reference if it is driven the same way.

    Setting the position on the OTI driver alone made the two builds disagree
    by 100% on a growth model -- not because the transform was wrong, but
    because one build's material point was at the origin and the other's was
    not. A difference introduced by the harness is indistinguishable, in the
    output, from a difference introduced by the transformation.
    """

    def _reference(self, **kwargs):
        from umat_oti.validation.parameter_sensitivity_validation import (  # noqa: PLC0415
            driver_source,
        )
        return driver_source(ntens=6, nstatv=4, nprops=2, **kwargs)

    def test_the_reference_takes_the_same_position(self):
        source = self._reference(coords=(1.0, 1.0, 1.0))
        for index in (1, 2, 3):
            assert f"COORDS({index})=1.0_8" in source

    def test_the_reference_takes_the_same_initial_state(self):
        source = self._reference(initial_statev=(1.0, 0.0, 2.5, 0.0))
        assert "STATEV(1)=1.0_8" in source
        assert "STATEV(3)=2.5_8" in source
        assert "STATEV(2)=" not in source

    def test_a_state_index_past_nstatv_is_not_written(self):
        # It would be out of bounds in the reference's own declaration.
        source = self._reference(initial_statev=(0.0,) * 4 + (7.0,))
        assert "STATEV(5)=" not in source

    def test_the_default_reference_is_unchanged(self):
        # Table 6's evidence is built by this driver and is committed
        # byte-identical; a caller that sets nothing must get what it got.
        source = self._reference()
        assert "COORDS(1)=" not in source
        assert "STATEV(1)=" not in source
        assert "COORDS=0.0_8" in source

    def test_the_reference_links_against_the_same_utilities(self):
        # It failed to link for ten sources that call Abaqus's thread locks,
        # and a link failure was being read as a transformation failure.
        source = self._reference()
        for name in ("MUTEXINIT", "MUTEXLOCK", "MUTEXUNLOCK"):
            assert f"SUBROUTINE {name}(" in source


class TestASourceThatNeedsFilesNobodyShipped:
    """Several UMATs read their own inputs from the author's own disk.

    Growth targets, fitted coefficients, tabulated curves -- read at run time
    from ``T:\\Abaqus-Temp\\...``. The repository holds the subroutine and not
    the data, so the model cannot run here and could not run under Abaqus on
    any machine but its author's. Reporting the raw Fortran runtime error
    leaves a reader thinking the transform broke it.
    """

    def _reason(self, stderr: str) -> str:
        from umat_oti.validation.tangent_validation import (  # noqa: PLC0415
            _missing_data_file_reason,
        )
        return _missing_data_file_reason(stderr)

    def test_the_missing_file_is_named(self):
        reason = self._reason(
            "At line 349 of file G.for (unit = 301) Fortran runtime error: "
            "Cannot open file 'T:\\Abaqus-Temp\\Lambda10St1.csv': No such file")
        assert "Lambda10St1.csv" in reason
        assert "repository does not ship" in reason

    def test_it_does_not_blame_the_transform(self):
        reason = self._reason("Fortran runtime error: Cannot open file 'x.csv'")
        assert "Nothing was transformed incorrectly" in reason

    def test_another_runtime_failure_is_left_alone(self):
        # A segmentation fault is not an absent data file and must not be
        # excused as one.
        assert self._reason("Program received signal SIGSEGV") == ""
        assert self._reason("") == ""
