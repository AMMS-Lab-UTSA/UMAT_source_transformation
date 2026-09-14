"""Identity is the path within the cache plus the source digest.

Eighteen corpus sources were said to share a basename. Measured on the frozen
237-entry store it is worse than that: 23 basenames name more than one source
file, covering 108 of the 237 entries, and ``BodyForce-Growth-2Stages.for``
alone names 26 different files. A consumer keyed on ``Path(source).name``
merges 26 materials -- different constants, different verdicts -- into
whichever one it read last.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umat_oti.contract import IdentityError, UmatIdentity, refuse_basename_keying

#: The frozen store this contract is validated against. Located relative to
#: the checkout rather than written as an absolute path: an absolute one is
#: true on exactly one computer, and a test that silently skips everywhere
#: else is a test that proves nothing everywhere else. ``UMAT_OTI_STORE``
#: overrides it for a checkout laid out differently.
STORE_ENV = "UMAT_OTI_STORE"
STORE_RELATIVE = Path("corpus_run") / "pass11" / "results" / \
    "store_verification.jsonl"


def store_path() -> Path | None:
    """The store, or ``None`` when this machine does not have it."""
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override) if Path(override).is_file() else None
    root = Path(__file__).resolve().parents[1]
    for base in (root, root.parent, root.parent.parent):
        candidate = base / STORE_RELATIVE
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def rows() -> list:
    store = store_path()
    if store is None:
        pytest.skip(f"the frozen store ({STORE_RELATIVE}) is not on this "
                    f"machine; set {STORE_ENV} to point at one")
    return [json.loads(line) for line in store.read_text().splitlines() if line]


def test_a_bare_basename_is_refused_as_an_identity():
    with pytest.raises(IdentityError) as exc:
        UmatIdentity.of("umat.f", "0" * 64)
    assert "basename" in str(exc.value)
    assert "26" in str(exc.value)      # the message carries the measurement


def test_an_absolute_path_is_refused_because_it_is_not_portable():
    with pytest.raises(IdentityError) as exc:
        UmatIdentity.of("/scratch/cache/repo/umat.f", "a" * 64)
    assert "absolute" in str(exc.value)


def test_a_path_without_a_digest_says_which_file_not_which_bytes():
    with pytest.raises(IdentityError) as exc:
        UmatIdentity.of("repo__x/umat.f", None)
    assert "SHA-256" in str(exc.value)
    with pytest.raises(IdentityError):
        UmatIdentity.of("repo__x/umat.f", "not-a-digest")


def test_the_real_store_confirms_the_basename_collision(rows):
    """The reason this rule exists, measured rather than asserted."""
    message = refuse_basename_keying(row["source"] for row in rows)
    assert message is not None, "no collisions -- the premise would be stale"
    assert "basename" in message
    names = {}
    for row in rows:
        names.setdefault(row["source"].rsplit("/", 1)[-1], set()).add(row["source"])
    clashing = {n: g for n, g in names.items() if len(g) > 1}
    assert len(clashing) == 23
    assert sum(len(g) for g in clashing.values()) == 108
    assert len(clashing["BodyForce-Growth-2Stages.for"]) == 26


def test_path_and_digest_together_are_unique_and_neither_alone_is(rows):
    paths = [row["source"] for row in rows]
    digests = [row["source_sha256"] for row in rows]
    assert len(set(paths)) == len(rows) == 237
    # The digest alone is NOT an identity either: the same file published at
    # two paths shares one. Eight entries do.
    assert len(set(digests)) == 229
    together = {(p, d) for p, d in zip(paths, digests)}
    assert len(together) == 237


def test_every_real_store_row_yields_a_legal_identity(rows):
    for row in rows:
        identity = UmatIdentity.from_record(row)
        assert "/" in identity.path
        assert len(identity.sha256) == 64


def test_the_cache_spelling_of_a_repository_is_not_the_record_spelling(rows):
    """``Owner__name`` in the cache path, ``Owner/name`` in the field. Two
    renderings of one fact; a consumer comparing them directly gets a
    mismatch on every entry, so the contract names both."""
    identity = UmatIdentity.from_record(rows[0])
    assert "__" in identity.cache_repository
    assert identity.cache_repository != identity.repository
    assert identity.cache_repository == identity.repository.replace("/", "__")


def test_matching_is_by_both_halves():
    one = UmatIdentity.of("repo__a/src/umat.f", "a" * 64)
    same_name_other_file = UmatIdentity.of("repo__b/src/umat.f", "a" * 64)
    same_file_changed = UmatIdentity.of("repo__a/src/umat.f", "b" * 64)
    assert one.same_source_as(UmatIdentity.of("repo__a/src/umat.f", "a" * 64))
    assert not one.same_source_as(same_name_other_file)
    assert not one.same_source_as(same_file_changed)
    assert one.basename == same_name_other_file.basename   # and it means nothing
