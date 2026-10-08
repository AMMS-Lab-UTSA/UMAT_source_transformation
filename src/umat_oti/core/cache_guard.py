"""The discovery cache holds the published sources as acquired; nothing may write into it.

A transform works on a staged copy. A rewrite that edits a source in place (the
argument-position rename edits the file it was handed) must never be handed a
cache path: one cache file was rewritten that way. The root is
``UMAT_OTI_DISCOVERY_CACHE`` when set, else ``discovery_cache`` beside the
checkout.
"""
from __future__ import annotations

import os
from pathlib import Path


class DiscoveryCacheReadOnly(RuntimeError):
    """A write was aimed at the discovery cache."""


def cache_root() -> Path:
    configured = os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
    return Path(configured) if configured else Path(__file__).resolve().parents[3].parent / "discovery_cache"


def refuse_write_into_discovery_cache(path: Path | str) -> None:
    """Raise when ``path`` resolves inside the discovery cache root."""
    target = Path(path).expanduser().resolve()
    root = cache_root().expanduser().resolve()
    if target == root or root in target.parents:
        raise DiscoveryCacheReadOnly(
            "the discovery cache is read-only: the transform must work on a staged copy "
            f"(refused a write to {target.name} inside {root.name})")
