"""The DOUBLE COMPLEX refusal is ours, and the classification has to say so.

Nine corpus sources -- all genuine UMATs, all from the abaqus_ufl/CoupFE
complex-step lineage -- are refused because the OTI algebra is generated over
the reals and a DOUBLE COMPLEX quantity on the stress path has no shadow type
to be promoted to. Nothing is missing from those files. This pins that the
refusal names the transform, not the file, as what lacks the form.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import _complex_type_blockers  # noqa: E402

def test_the_blocker_names_the_transform_and_not_the_file():
    """The message has to say the OTI type is what lacks the form.

    A refusal that read "this source uses an unsupported construct" would be
    the same refusal with the cause moved onto somebody else's file, and the
    corpus counts read the cause.
    """
    config = {"variable_roles": {"PZ": {"detected type": "double complex"}}}
    roles = {"seed": set(), "promote": {"PZ"}, "keep_real": set()}
    blockers = _complex_type_blockers(config, roles)
    assert blockers, "a promoted DOUBLE COMPLEX variable must be refused"
    message = " ".join(blockers).lower()
    assert "oti type is built over the reals" in message
    assert "not supported" in message


