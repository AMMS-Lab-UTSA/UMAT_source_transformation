"""The discovery cache is read-only: the transform must work on a staged copy.

One cache file was rewritten in place (every line changed) when a throwaway
patch gave the companion retry the published file as its entry and the
argument-position rename, which edits the file it is handed, ran on it. Rule
(B20 RULES.md R12): a write whose resolved path is inside the cache root
(UMAT_OTI_DISCOVERY_CACHE, else discovery_cache beside the checkout) raises
DiscoveryCacheReadOnly. Planted error: the in-place rewrite aimed at a file in a
temp cache root must raise and leave the file untouched; the normal transform
of a cached source must leave its bytes alone.
"""
import hashlib
import sys
from pathlib import Path

import pytest

from umat_oti.core.cache_guard import DiscoveryCacheReadOnly, refuse_write_into_discovery_cache

sys.path.insert(0, str(Path(__file__).parent))
from test_a_umat_is_matched_to_abaqus_by_argument_position import FREE, _args  # noqa: E402


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "discovery_cache"
    (root / "owner__repo").mkdir(parents=True)
    monkeypatch.setenv("UMAT_OTI_DISCOVERY_CACHE", str(root))
    return root


def test_a_path_inside_the_cache_is_refused_and_one_outside_is_not(cache, tmp_path):
    with pytest.raises(DiscoveryCacheReadOnly, match="read-only"):
        refuse_write_into_discovery_cache(cache / "owner__repo" / "u.for")
    with pytest.raises(DiscoveryCacheReadOnly):
        refuse_write_into_discovery_cache(cache / "owner__repo" / ".." / "owner__repo" / "u.for")
    refuse_write_into_discovery_cache(tmp_path / "work" / "u.for")


def test_canary_the_in_place_rewrite_aimed_at_a_cache_file_raises_and_leaves_it_alone(cache):
    from umat_oti.app.engine import _match_interface_by_position

    source = cache / "owner__repo" / "u.f90"
    source.write_text(FREE % {"args": _args()})
    before = _sha(source)
    with pytest.raises(DiscoveryCacheReadOnly):
        _match_interface_by_position(source)
    assert _sha(source) == before


def test_the_rewrite_on_a_staged_copy_still_works(cache, tmp_path):
    from umat_oti.app.engine import _match_interface_by_position

    staged = tmp_path / "work" / "u.f90"
    staged.parent.mkdir()
    staged.write_text(FREE % {"args": _args()})
    assert _match_interface_by_position(staged)["applied"] is True


def test_the_normal_transform_of_a_cached_source_never_writes_it(cache, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import transform_all as ta

    source = cache / "owner__repo" / "u.f90"
    source.write_text(FREE % {"args": _args()})
    before = _sha(source)
    item = ta.WorkItem(source_id="owner__repo/u.f90", path=source, sha256=before, ntens=6)
    ta.transform_one(item, tmp_path / "work")
    assert _sha(source) == before
    assert not list(cache.rglob("*.orig")) and [p.name for p in cache.rglob("*") if p.is_file()] == ["u.f90"]
