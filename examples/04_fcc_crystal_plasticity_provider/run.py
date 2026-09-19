#!/usr/bin/env python
"""Example 4: read the FCC crystal-plasticity provider package.

Run from the repository root on the --out directory of
``python -m umat_oti.provider.collaborator``:

    python examples/04_fcc_crystal_plasticity_provider/run.py \
        --package umat_oti_workspace/examples/04_fcc/package

This is the package reader of Example 3 (``examples/03_j2_parameter_sensitivities/run.py``)
with defaults suited to the crystal: it tabulates the shear stress S12 and the
growth of the first slip resistance, SDV1. Every option of that script works
here too (``--component``, ``--state``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

READER = Path(__file__).resolve().parents[1] / "03_j2_parameter_sensitivities" / "run.py"


def main(argv=None) -> int:
    sys.dont_write_bytecode = True  # leave no __pycache__ in the examples folder
    spec = importlib.util.spec_from_file_location("provider_package_reader", READER)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader.main(argv, default_component=4, default_state=1)


if __name__ == "__main__":
    sys.exit(main())
