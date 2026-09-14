"""The DOUBLE COMPLEX refusal is ours, and the classification has to say so.

Nine corpus sources -- all genuine UMATs, all from the abaqus_ufl/CoupFE
complex-step lineage -- are refused because the OTI algebra is generated over
the reals and a DOUBLE COMPLEX quantity on the stress path has no shadow type
to be promoted to. Nothing is missing from those files. The reasoning is
written out in docs/development/COMPLEX_STRESS_PATH.md; this pins the two
things a later edit could quietly get wrong.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import _complex_type_blockers  # noqa: E402

DECISION = Path(__file__).resolve().parents[1] / "docs/development/COMPLEX_STRESS_PATH.md"


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


def test_the_decision_is_written_down_and_labelled_internal():
    """The document exists, says internal, and forbids the relabelling.

    Written as a test because the failure mode is administrative: the nine are
    an attractive thing to move into an external bucket, and the only guard
    against that is a statement somebody has to delete on purpose.
    """
    assert DECISION.is_file(), f"missing {DECISION.name}"
    text = DECISION.read_text(encoding="utf-8")
    assert re.search(r"internal limitation of this transform", text, re.I)
    assert "genuine_umat" in text
    assert "missing_external_dependency" in text
    # The compiler's own words, kept so the claim is not an assertion.
    assert "Cannot convert COMPLEX(8) to TYPE(onumm6n1)" in text
