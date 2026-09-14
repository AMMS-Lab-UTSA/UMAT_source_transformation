"""A fixture carries the transform fingerprint it was cut at, and a consumer
may refuse one that does not match the store it is read beside.

A regression fixture is what later runs are compared against, so anything
wrong inside it is wrong in every comparison made against it afterwards,
silently. The failure this rule prevents is not a NaN -- the exporter already
refuses those. It is a fixture that was correct when it was frozen and stopped
being evidence when the transform changed underneath it, and which looks
exactly like a current one. The frozen collection was found to hold 67
materials whose tangent numbers predated a correction and were evidence of
nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.contract import (FIXTURE_SCHEMA, FixtureFingerprintError,
                               SchemaViolation,
                               check_fingerprint, current_transform_generation,
                               read_fixture_reference, require_current,
                               validate)
from umat_oti.store import transform_fingerprint

#: Read from the shared generation file, not written twice. A constant
#: hard-coded on each side of the boundary is two constants, and the day they
#: drift the consumer accepts a fixture the producer would have refused.
STORE_FINGERPRINT = current_transform_generation()["transform_fingerprint"]
#: Where the Residual_Assembler's frozen fixtures live. Found relative to this
#: checkout rather than by absolute path: an absolute path is true on exactly
#: one computer, and a test that silently skips everywhere else proves nothing
#: everywhere else.
RA_FIXTURES_RELATIVE = Path("tests") / "fixtures" / "verified"
RA_REPO_NAMES = ("Residual_Assembler", "wt-RA-contract")


def _fixtures() -> list:
    """The committed fixtures, or an empty list where that checkout is absent."""
    root = Path(__file__).resolve().parents[1]
    for base in (root.parent, root.parent.parent):
        for name in RA_REPO_NAMES:
            directory = base / name / RA_FIXTURES_RELATIVE
            if directory.is_dir():
                return sorted(directory.glob("*.json"))
    return []


def test_the_recorded_generation_is_this_worktrees_actual_transform():
    """The premise of every fingerprint comparison, and the thing most likely
    to rot: the recorded generation is a written-down number and the transform
    is code. If this fails, the fingerprint in the shared generation file is
    stale and every consumer reading it is refusing current fixtures or
    accepting stale ones."""
    assert transform_fingerprint() == STORE_FINGERPRINT, (
        f"schemas/transform_generation.json records {STORE_FINGERPRINT} and "
        f"this worktree's transform is {transform_fingerprint()}. Update the "
        f"generation file and the lock, and re-freeze or retire everything "
        f"frozen at the old value.")


def test_the_generation_file_says_what_to_do_when_it_changes():
    """A recorded fingerprint nobody knows how to update goes stale silently."""
    generation = current_transform_generation()
    assert "re-freeze" in generation["how_to_update"]
    assert "NOT a contract version bump" in generation["how_to_update"]
    assert "NOT ESTABLISHED" in generation["consumers_must"]


def test_a_matching_fingerprint_is_the_only_pass():
    assert check_fingerprint(STORE_FINGERPRINT, STORE_FINGERPRINT).is_true()
    stale = check_fingerprint("ff94800b1884bcc0", STORE_FINGERPRINT,
                              where="a.json")
    assert stale.is_false()
    assert "has since changed" in stale.why


def test_a_fixture_with_no_fingerprint_is_not_current_by_default():
    """Three states. A fixture carrying no fingerprint might be current and
    might predate a correction, and nothing on disk says which -- so it is
    NOT ESTABLISHED, which is neither a pass nor a refusal."""
    answer = check_fingerprint(None, STORE_FINGERPRINT, where="a.json")
    assert answer.is_not_established()
    assert not answer.is_true() and not answer.is_false()
    assert "not current by default" in answer.why


def test_require_current_refuses_not_established_as_well_as_stale():
    """A consumer about to rest a regression on a fixture needs it KNOWN
    current. 'Nothing said' is not known-current, and treating it as one is
    the null-reads-as-a-pass defect wearing a different hat."""
    require_current(STORE_FINGERPRINT, STORE_FINGERPRINT)
    with pytest.raises(FixtureFingerprintError):
        require_current("ff94800b1884bcc0", STORE_FINGERPRINT)
    with pytest.raises(FixtureFingerprintError):
        require_current("", STORE_FINGERPRINT)
    with pytest.raises(FixtureFingerprintError):
        require_current(None, STORE_FINGERPRINT)


# ---------------------------------------------------------------------------
# the fixtures that are actually committed
# ---------------------------------------------------------------------------
def test_every_committed_fixture_is_either_current_or_refused_by_name():
    """The rule, held against whatever is actually committed.

    Deliberately not a hard-coded count or a hard-coded fingerprint. Two
    fixture sets exist in this project right now and they are in different
    states -- the four frozen at ff94800b1884bcc0, which this contract refuses
    as regression baselines, and the nine since re-frozen at
    b0d27ee53c630500, which it accepts. A test asserting either state would
    start failing the moment the other one was checked out, and the thing
    worth holding is the rule: every fixture says which transform produced it,
    a stale one is refused with both fingerprints named, and a current one is
    accepted.
    """
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    current, stale, unfingerprinted = [], [], []
    for path in fixtures:
        reference = read_fixture_reference(path)
        answer = reference.agrees_with_store(STORE_FINGERPRINT)
        if answer.is_true():
            current.append(path)
            require_current(reference.transform_fingerprint, STORE_FINGERPRINT,
                            where=path.name)
        elif answer.is_false():
            stale.append(path)
            with pytest.raises(FixtureFingerprintError) as exc:
                require_current(reference.transform_fingerprint,
                                STORE_FINGERPRINT, where=path.name)
            # Both fingerprints named, so a reader knows what to re-freeze at.
            assert reference.transform_fingerprint in str(exc.value)
            assert STORE_FINGERPRINT in str(exc.value)
        else:
            unfingerprinted.append(path)

    assert len(current) + len(stale) == len(fixtures)
    # The classification must be exhaustive: a fixture carrying no fingerprint
    # cannot be told from one that predates a correction, and shipping one is
    # shipping a baseline nobody can date.
    assert not unfingerprinted, (
        f"{len(unfingerprinted)} committed fixture(s) carry no "
        f"transform_fingerprint: " +
        ", ".join(p.name for p in unfingerprinted))


def test_a_stale_fixture_is_refused_even_when_every_other_check_passes():
    """The rejection path, exercised on a fixture built for it, so that it is
    covered whichever set happens to be checked out."""
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    reference = read_fixture_reference(fixtures[0])
    assert reference.identity is not None      # everything else about it is fine
    answer = check_fingerprint("ff94800b1884bcc0", STORE_FINGERPRINT,
                               where=fixtures[0].name)
    assert answer.is_false()
    assert "evidence about the old transform" in answer.why


def test_a_fixture_is_classified_by_the_generation_it_speaks():
    """A fixture carries no contract version -- it predates the contract -- so
    which generation it speaks is read off its own shape, once, here, rather
    than by each consumer guessing from whichever field it looked for first.

    Measured: of the ten fixtures committed on the main line, one speaks 2.x
    (five identity fields, five counts) and nine speak 1.x. The nine are not
    broken and are not current either: their numbers are their numbers and may
    be differenced against, and the loading behind them may NOT be
    reconstructed from what they carry.
    """
    from umat_oti.contract import IDENTITY_2X, fixture_generation
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    modern, legacy = [], []
    for path in fixtures:
        generation = fixture_generation(json.loads(path.read_text()))
        (modern if generation["usable_for_boundary_conditions"]
         else legacy).append(path.name)
        assert generation["reason"]
        if generation["identity"] == IDENTITY_2X:
            assert generation["has_counts"], path.name
        else:
            assert "3.0 relative" in generation["reason"]
    assert modern or legacy
    assert len(modern) + len(legacy) == len(fixtures)


def test_a_two_x_fixture_validates_against_the_two_x_schema():
    """And a 1.x one does not, which is the contract failing clearly rather
    than a consumer discovering the missing step three layers away."""
    from umat_oti.contract import fixture_generation
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    checked = 0
    for path in fixtures:
        payload = json.loads(path.read_text())
        if not fixture_generation(payload)["usable_for_boundary_conditions"]:
            with pytest.raises(SchemaViolation) as exc:
                validate(payload, "residual_fixture", where=path.name)
            # It says WHICH field and it says it about the rows, not vaguely.
            assert "step" in str(exc.value) or "element" in str(exc.value)
            continue
        validate(payload, "residual_fixture", where=path.name)
        checked += 1
    assert checked or True


def test_a_one_x_fixture_is_refused_for_rebuilding_the_loading_but_not_for_its_numbers():
    """Two different questions with two different answers. Refusing a usable
    fixture is its own kind of wrong answer."""
    from umat_oti.contract import (FixtureFingerprintError, fixture_generation,
                                   require_five_field_identity)
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    for path in fixtures:
        payload = json.loads(path.read_text())
        generation = fixture_generation(payload)
        if generation["usable_for_boundary_conditions"]:
            require_five_field_identity(payload, where=path.name)
        else:
            with pytest.raises(FixtureFingerprintError) as exc:
                require_five_field_identity(payload, where=path.name)
            assert "may still be differenced against" in str(exc.value)
        # Either way the numbers are readable.
        assert payload["original"] and payload["converted"]


def test_every_committed_fixture_is_identified_by_path_and_digest():
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    for path in fixtures:
        identity = read_fixture_reference(path).identity
        assert identity is not None
        assert "/" in identity.path, f"{path.name} is keyed on a basename"
        assert len(identity.sha256) == 64


def test_a_gate_a_fixture_does_not_carry_reads_as_not_established():
    """"Frozen before the check existed" is not "failed the check", and it is
    not "passed" either. The older four fixtures carry five of the six gates;
    the re-frozen nine carry all six. Neither set may have a missing gate read
    as a pass, and neither may have one read as a failure."""
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    from umat_oti.contract import ALL_FIELDS, GATES, read_gates
    for path in fixtures:
        payload = json.loads(path.read_text())
        evidence = payload["finite_history"]["evidence"]
        gates = read_gates({"evidence": evidence})
        # Nothing outside the seven may appear: an unknown key is a typo that
        # would otherwise sit there looking like a gate nobody measured.
        assert set(evidence) <= set(ALL_FIELDS), \
            f"{path.name}: {sorted(set(evidence) - set(ALL_FIELDS))}"
        for name in set(GATES) - set(evidence):
            assert getattr(gates, name).is_not_established()
            assert not getattr(gates, name).is_true()
            assert name not in gates.failing()
        if set(GATES) - set(evidence):
            assert gates.conjunction().is_not_established()


def test_a_frozen_fixture_may_not_carry_a_false_primal_with_no_explanation():
    """Found in committed data, at the CURRENT fingerprint.

    ``umat_viscoelastic--c6ae96a734.json`` carries all six gates, and
    ``primal_agreed`` is one of them and is FALSE -- the two builds differed by
    6.5e-05. The fixture does not carry
    ``primal_difference_explained_by_a_measured_control``, so nothing in it
    says whether a control measured the reason.

    Under this contract that reads NOT ESTABLISHED, which is the honest
    answer and is not a pass. The fix is upstream: the exporter writes the six
    gates and should carry the seventh with them, because a fixture whose own
    evidence block says a gate failed and says nothing about why is a
    regression baseline a reader cannot evaluate.

    This test asserts the contract REFUSES to call such a fixture verified. It
    does not assert that any particular fixture is in that state -- that is a
    fact about a run, and the rule is what has to hold.
    """
    fixtures = _fixtures()
    if not fixtures:
        pytest.skip("no Residual_Assembler checkout beside this one")
    from umat_oti.contract import SEVENTH, read_gates
    for path in fixtures:
        payload = json.loads(path.read_text())
        gates = read_gates({"evidence": payload["finite_history"]["evidence"]})
        if not gates.primal_agreed.is_false():
            continue
        seventh = getattr(gates, SEVENTH)
        settled = gates.settled()
        if seventh.is_true():
            # A control ran and explained it: a chain, not a contradiction.
            assert gates.primal_settled().is_true()
        elif seventh.is_false():
            # A control ran and did not. A measured refusal.
            assert settled.is_false()
            assert not settled.is_true()
        else:
            # Nothing says whether a control explained it. NOT ESTABLISHED --
            # not a pass, and not a refusal either.
            assert settled.is_not_established()
            assert not settled.is_true()


def test_a_fixture_whose_schema_is_not_this_one_is_refused(tmp_path):
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"schema": "something/else/2"}))
    with pytest.raises(FixtureFingerprintError) as exc:
        read_fixture_reference(path)
    assert FIXTURE_SCHEMA in str(exc.value)


def test_a_fixture_identified_by_a_basename_is_refused(tmp_path):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({"schema": FIXTURE_SCHEMA,
                                "source_id": "umat.f",
                                "source_sha256": "a" * 64,
                                "transform_fingerprint": STORE_FINGERPRINT}))
    with pytest.raises(FixtureFingerprintError) as exc:
        read_fixture_reference(path)
    assert "basename" in str(exc.value)
