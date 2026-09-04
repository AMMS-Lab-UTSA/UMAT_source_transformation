"""Where the offline gate puts the material point, and why it is not one point.

COORDS is not a knob. Nineteen sources in this corpus read it as a physical
position in their own mesh and evaluate a growth field there, so a single
"generic point of the unit cube" is a claim about geometry that most decks in
the corpus contradict.

The concrete failure this file exists for. The gate drove every source from
(0.3, 0.7, 0.5). The nineteen Jeff97 BodyForce/PureGravity sources model a
plate 0.01 m thick lying in the x-y plane, so Y=0.7 is seventy plate
thicknesses above their own mesh. Each computes a growth stretch
G11 = Lambda1z0(X) + Y*Lambda1z1(X), which at that point is -4.05, forms the
elastic tensor Ae = F.G^-1 from it, and evaluates DETAe**(-5/3) on a negative
determinant -- NaN, in BOTH builds. Nineteen rows of the gate report said
`both_builds_non_finite`, which is not evidence about the transform at all:
it is evidence that the probe was standing outside the model.

What each test here pins, and what breaks if it regresses:

* The point comes from the paired deck's own *NODE block, so it is inside the
  mesh the author published. Regress it and those nineteen rows go back to
  comparing NaN with NaN and the gate loses them again.
* The guard the generic point was chosen for survives the move. Sources here
  divide by COORDS(1), by COORDS(2) and by COORDS(1)**2 - COORDS(2)**2, so a
  deck-derived point that is the origin, all-ones, or on the diagonal would
  trade one NaN for another.
* A source with no deck, and a deck with no *NODE block, keep the generic
  point exactly as before. This gate never invents geometry any more than it
  invents material constants.
* The row says which of the two it got, because a reader who cannot tell a
  deck-derived point from the generic one cannot tell what was measured.

Nothing here compiles anything: the probe point is resolved by pure functions
over a deck's text, precisely so that this can be checked without a compiler.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from verify_store_offline import (  # noqa: E402
    AGREED, DECK_COORDS, GENERIC_COORDS, ORIGINAL_UNAVAILABLE, PROBE_COORDS,
    Material, Options, build_report, check_entry, node_extents,
    partition_for_resume, previously_recorded, probe_coords_in, probe_entry,
    probe_of_record, probe_point,
)

#: A deck shaped like the one the nineteen Jeff97 rows are paired to: a plate
#: one metre long, 0.01 m thick, 0.001 m deep, meshed in a *Node block, with a
#: *Node Output block later on in the step definition. Trimmed to a handful of
#: nodes; the extents are the real deck's, measured from
#: Examples-In-Section-3/ArcDown/Th001/Beam-Gravity-C0-100MPa.inp, which has
#: 26165 nodes spanning x [0, 1], y [0, 0.00999999978], z [0, 0.00100000005].
PLATE_DECK = """\
*Heading
** Job name: Beam-Gravity-Umat
*Part, name=Plate
*Node
      1,          0.5, 0.00499999989,           0.
      2,           1., 0.00999999978, 0.00100000005
      3,          0.5,           0.,           0.
      4,           0.,           0., 0.00100000005
*Element, type=C3D8
 1, 1, 2, 3, 4
*End Part
*Material, name=neoHookean
*User Material, constants=1
100000000.,
*Depvar
9,
*Step
*Node Output, NSET=Plate-1.WholeRegion
 900., 900., 900.
*End Step
"""


def growth_stretch(x: float, y: float) -> float:
    """G11 as the Jeff97 sources compute it, at unit total time.

    Transcribed from Examples-In-Section-3/HelixUp/Th01/PureGravity.for lines
    179-197: Lambda1z0 and Lambda1z1 are functions of X alone, the increment
    is (TIME(1)+DTIME)/TotalT = 1 for the gate's single unit-time increment,
    and G11 = 1 + (Lambda1z0 + Y*Lambda1z1 - 1). Negative G11 is what puts a
    negative determinant into DETAe**(-5.0/3.0) and makes the stress NaN.
    """
    lambda_1z0 = 3.0 * math.sqrt(1.0 + 16.0 * math.pi ** 2 * x ** 4) / 5.0
    lambda_1z1 = (-4.0 * math.pi * x * (3.0 + 16.0 * math.pi ** 2 * x ** 4)
                  / (1.0 + 16.0 * math.pi ** 2 * x ** 4))
    return lambda_1z0 + y * lambda_1z1


def _deck(tmp_path: Path, text: str = PLATE_DECK,
          name: str = "Th001/Beam-Gravity-C0-100MPa.inp") -> Path:
    """Write ``text`` as a deck under a cache-shaped path and return the cache."""
    cache = tmp_path / "cache"
    path = cache / "owner__repo" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return cache


def _material(deck: str = "owner__repo/Th001/Beam-Gravity-C0-100MPa.inp"
              ) -> Material:
    return Material(props=(1.0e8,), provenance=f"{deck}, *Material neoHookean",
                    nstatv=9, deck=deck)


class TestTheProbePointComesFromTheDecksOwnNodes:
    """The extents are published in the deck, so this invents no geometry."""

    def test_the_node_block_is_read_and_a_node_output_block_is_not(self, tmp_path):
        """*Node Output is a request for results, not geometry. Reading its
        numbers as coordinates would put the probe at (900, 900, 900), which is
        further outside the plate than the generic point ever was."""
        cache = _deck(tmp_path)
        extents = node_extents(cache / "owner__repo" / "Th001"
                               / "Beam-Gravity-C0-100MPa.inp")
        assert extents == ((0.0, 1.0), (0.0, 0.00999999978),
                           (0.0, 0.00100000005))

    def test_the_probe_lands_inside_the_plate_and_not_seventy_thicknesses_above(
            self, tmp_path):
        """The whole defect in one assertion: Y=0.7 in a plate 0.01 m thick.

        If this regresses the nineteen Jeff97 rows return to
        both_builds_non_finite -- two programs agreeing about NaN, which
        decides nothing and costs the corpus its largest recoverable block.
        """
        cache = _deck(tmp_path)
        point = probe_point(_material(), cache)
        x, y, z = point.coords
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 0.00999999978, "the probe is outside the plate"
        assert 0.0 <= z <= 0.00100000005
        assert point.provenance == DECK_COORDS
        assert point.deck.endswith("Beam-Gravity-C0-100MPa.inp")

    def test_the_growth_stretch_this_was_found_through_stops_being_negative(
            self, tmp_path):
        """The measurement, not a proxy for it: G11 at the two points."""
        assert growth_stretch(*PROBE_COORDS[:2]) < 0.0      # -4.05, then NaN
        point = probe_point(_material(), _deck(tmp_path))
        assert growth_stretch(*point.coords[:2]) > 0.0

    def test_the_state_handed_to_both_builds_carries_that_point(self, tmp_path):
        """COORDS reaches the model through the probe ENTRY record. A point
        resolved but not written into the state changes nothing at all."""
        point = probe_point(_material(), _deck(tmp_path))
        state = probe_entry(_material(), coords=point.coords)
        assert state["COORDS"][:3] == list(point.coords)
        assert state["COORDS"][3] == 1.0

    def test_a_subset_of_a_huge_mesh_is_still_inside_the_mesh(self, tmp_path):
        """The reader stops after a bounded number of node lines. That is safe
        for exactly one reason: the bounding box of a subset of the nodes is
        contained in the bounding box of all of them, so a point interpolated
        inside the subset is inside the mesh. It is never safe to relax this
        into "close enough" -- a point outside the mesh is the whole defect."""
        first = node_extents(_deck(tmp_path) / "owner__repo" / "Th001"
                             / "Beam-Gravity-C0-100MPa.inp", limit=2)
        assert first == ((0.5, 1.0), (0.00499999989, 0.00999999978),
                         (0.0, 0.00100000005))


class TestTheGuardTheGenericPointWasChosenFor:
    """Models here divide by COORDS(1), COORDS(2) and COORDS(1)**2-COORDS(2)**2.

    tests/test_abaqus_deck_and_probe.py asserts this of the shared driver's
    declared start. It has to hold of a deck-derived point too, or the fix
    trades a NaN from a negative determinant for a NaN from a zero divisor.
    """

    @pytest.mark.parametrize("extents", [
        ((0.0, 1.0), (0.0, 1.0), (0.0, 1.0)),           # the unit cube
        ((-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)),        # centred on the origin
        ((0.0, 1.0), (0.0, 3.0 / 7.0), (0.0, 1.0)),     # 0.3 == 0.7*3/7
        ((0.0, 1.0), (0.0, 0.01), (0.0, 0.001)),        # the Jeff97 plate
        ((-2.0, 2.0), (-2.0, 2.0), (0.0, 0.0)),         # flat in z
        ((5.0, 5.0), (0.0, 10.0), (0.0, 1.0)),          # flat in x
    ])
    def test_no_point_is_the_origin_the_diagonal_or_a_zero_divisor(self, extents):
        coords = probe_coords_in(extents)
        assert coords is not None
        x, y, z = coords
        assert list(coords) != [0.0, 0.0, 0.0]
        assert list(coords) != [1.0, 1.0, 1.0]
        assert x != 0.0 and y != 0.0
        assert x ** 2 != y ** 2

    @pytest.mark.parametrize("extents", [
        ((0.0, 1.0), (0.0, 1.0), (0.0, 1.0)),
        ((-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)),
        ((0.0, 1.0), (0.0, 0.01), (0.0, 0.001)),
        ((-2.0, 2.0), (-2.0, 2.0), (0.0, 0.0)),
    ])
    def test_every_coordinate_is_inside_its_own_extent(self, extents):
        """A point outside the mesh is the defect being fixed. A guard that
        escaped the extents to satisfy itself would reintroduce it."""
        coords = probe_coords_in(extents)
        for value, (low, high) in zip(coords, extents):
            assert low <= value <= high

    def test_a_mesh_with_no_room_for_a_legal_point_keeps_the_generic_one(self):
        """A degenerate mesh -- every node at x=0 -- offers no point this
        gate can divide by. Reporting the generic point is honest; inventing a
        coordinate the deck does not contain is not."""
        assert probe_coords_in(((0.0, 0.0), (0.0, 1.0), (0.0, 1.0))) is None


class TestASourceWithNoDeckIsDrivenExactlyAsBefore:
    """The gate reads geometry where an author published it, and nowhere else."""

    def test_a_material_with_no_deck_keeps_the_generic_point(self, tmp_path):
        point = probe_point(Material(props=(1.0,), provenance="a manifest"),
                            tmp_path / "cache")
        assert point.coords == PROBE_COORDS
        assert point.provenance == GENERIC_COORDS

    def test_a_deck_with_no_node_block_keeps_the_generic_point(self, tmp_path):
        cache = _deck(tmp_path, "*Heading\n*Material, name=m\n*Depvar\n9,\n")
        point = probe_point(_material(), cache)
        assert point.coords == PROBE_COORDS
        assert point.provenance == GENERIC_COORDS

    def test_a_deck_that_is_not_in_the_cache_keeps_the_generic_point(self, tmp_path):
        point = probe_point(_material("owner__repo/gone.inp"), tmp_path / "cache")
        assert point.coords == PROBE_COORDS
        assert point.provenance == GENERIC_COORDS

    def test_a_deck_named_by_basename_alone_is_refused(self, tmp_path):
        """A source's identity is its cache-relative path, never its basename,
        and a deck's is no different. A bare "Job-1.inp" resolved against the
        cache root would pair a mesh with whichever repository happened to
        have that filename -- the same mistake that once drove eighteen UMATs
        with another project's constants."""
        cache = _deck(tmp_path, name="Job-1.inp")
        (cache / "Job-1.inp").write_text(PLATE_DECK, encoding="utf-8")
        point = probe_point(_material("Job-1.inp"), cache)
        assert point.coords == PROBE_COORDS
        assert point.provenance == GENERIC_COORDS

    def test_a_deck_path_that_leaves_the_cache_is_refused(self, tmp_path):
        """probe_deck is written into a committed report, and a path out of
        the cache names this machine. tools/audit_repository_standards.py
        fails the build on one, and a deck outside the cache is not a file any
        author in this corpus published anyway."""
        cache = _deck(tmp_path)
        outside = tmp_path / "elsewhere.inp"
        outside.write_text(PLATE_DECK, encoding="utf-8")
        for named in ("../elsewhere.inp", str(outside)):
            point = probe_point(_material(named), cache)
            assert point.coords == PROBE_COORDS
            assert point.deck == ""


class TestTheRowSaysWhereItsProbePointCameFrom:
    """A reader has to be able to tell the two apart without rerunning."""

    def test_the_record_carries_the_point_and_its_origin(self, tmp_path):
        """Driven through the real per-entry path, on an entry whose original
        is missing so that nothing is compiled: the probe is a declaration the
        gate makes about the run, not a result of one."""
        class _Entry:
            key = "k0"
            source_id = "owner__repo/u.for"
            source_sha256 = ""
            fingerprint = "fp0"
            metadata: dict = {}
            entry_source = Path("u_oti.for")
            directory = Path(".")

        cache = _deck(tmp_path)
        record = check_entry(_Entry(), _material(),
                             Options(cache=cache, work_root=tmp_path / "work"))
        assert record["outcome"] == ORIGINAL_UNAVAILABLE
        assert record["probe_coords_from"] == DECK_COORDS
        assert record["probe_coords"][1] < 0.01
        assert record["probe_deck"].endswith("Beam-Gravity-C0-100MPa.inp")
        assert not (tmp_path / "work").exists()

    def test_the_report_does_not_advertise_one_point_for_every_row(self, tmp_path):
        """The report used to print a single `coords` under `probe`. With the
        point resolved per source that line would be false for every
        deck-derived row, which is worse than no line at all."""
        report = build_report([], {"entries": 0}, Options())
        probe = report["probe"]
        assert probe["generic_coords"] == list(PROBE_COORDS)
        assert "probe_coords" in probe["coords_note"]


class TestAResumeDoesNotServeAMeasurementFromAnotherPoint:
    """The probe point is not in the store key, and it has to be in the resume.

    The store key fingerprints the transform code. Where the material point
    goes depends on the deck paired to the source, which that key knows
    nothing about, so nothing in it changes when the point moves. The nineteen
    rows this file exists for are `both_builds_non_finite`, which is not in
    RECONSIDERED -- so without this check every later `--resume` would serve
    their NaNs verbatim and the fix above would never reach a report.
    """

    class _Entry:
        def __init__(self, key="k1", source_id="owner__repo/u.for"):
            self.key = key
            self.source_id = source_id

    def test_a_row_driven_from_a_point_this_run_has_moved_is_run_again(self):
        previous = previously_recorded({"entries": [
            {"key": "k1", "outcome": AGREED, "probe_coords": [0.3, 0.7, 0.5]}]})
        todo, reused = partition_for_resume(
            [self._Entry()], previous, probe_at=lambda entry: (0.3, 0.007, 0.0005))
        assert [entry.key for entry in todo] == ["k1"] and reused == []

    def test_a_row_driven_from_the_same_point_is_still_reused(self):
        """The check has to be about the point, not about being cautious: a
        resume that re-ran everything would cost the batch its whole reason
        for existing."""
        previous = previously_recorded({"entries": [
            {"key": "k1", "outcome": AGREED, "probe_coords": [0.3, 0.007, 5e-4]}]})
        todo, reused = partition_for_resume(
            [self._Entry()], previous, probe_at=lambda entry: (0.3, 0.007, 5e-4))
        assert todo == [] and reused[0]["reused_from_previous_run"] is True

    def test_a_row_written_before_the_point_was_recorded_reads_as_the_generic_one(
            self):
        """Not a guess: the generic point was the only point the gate could
        use when those rows were written, so a row with no probe_coords is
        reusable exactly when this run would also use the generic point."""
        assert probe_of_record({"outcome": AGREED}) == list(PROBE_COORDS)
        previous = previously_recorded({"entries": [
            {"key": "k1", "outcome": AGREED}]})
        todo, reused = partition_for_resume(
            [self._Entry()], previous, probe_at=lambda entry: PROBE_COORDS)
        assert todo == [] and len(reused) == 1

    def test_the_old_two_argument_call_still_reuses_every_decided_row(self):
        """A caller that cannot say where the probe goes gets the behaviour it
        had before, rather than a silent full re-run."""
        previous = previously_recorded({"entries": [
            {"key": "k1", "outcome": AGREED, "probe_coords": [1.0, 2.0, 3.0]}]})
        todo, reused = partition_for_resume([self._Entry()], previous)
        assert todo == [] and len(reused) == 1
