"""Browser tests run when asked for: ``pytest -m gui tests/gui``.

A browser test starts a Streamlit server and a headless Chromium, builds real
objects and writes screenshots into docs/screenshots. That is a deliberate act,
so tests marked ``gui`` are *deselected* (not skipped) unless the marker
expression names ``gui`` -- the same arrangement as ``corpus_pass``. The
AppTest variants in this directory carry no ``gui`` marker and run in the
ordinary offline suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def pytest_collection_modifyitems(config, items):
    if "gui" in (config.getoption("-m") or ""):
        return
    selected, deselected = [], []
    for item in items:
        (deselected if item.get_closest_marker("gui") else selected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
