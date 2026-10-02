"""Where the corpus workspace is, for tests that read campaign evidence.

The checkout sits in the workspace beside discovery_cache/, corpus_run/,
corpus_campaign/ ...; $UMAT_OTI_WORKSPACE overrides that for a checkout
elsewhere. Tests that need workspace files skip when they are absent.
"""
from __future__ import annotations

import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("UMAT_OTI_WORKSPACE")
                 or Path(__file__).resolve().parents[2])
