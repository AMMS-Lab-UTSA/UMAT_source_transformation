"""The two OTI backends must agree about the awkward points.

``StaticFirstOrderBackend`` is the default (services.transformation), and the
generated otim95n1 module is the other path. A source built with one and not
the other would behave differently at exactly the points that are hardest to
notice: where a derivative goes non-finite while its value stays perfectly
well defined.

Every such site carries the same rule -- compute the partial, drop it when it
is not finite -- because Inf times a zero perturbation is NaN, and the NaN
does not stay in the derivative. It reaches the primal through the norms and
comparisons built on it, and a Newton solve then stops converging on a value
that was never in doubt. one viscoplastic UMAT reaches this three ways on its first plastic
increment: SQRT of a plastic strain still exactly zero, and a
kinematic-hardening term whose base the line above clamps to zero, by way of
both ``0**(b-1)`` and ``LOG(0)``.
"""

from __future__ import annotations

import re

from umat_oti.oti.otilib_static import StaticFirstOrderBackend

GUARD = "if (.not. (abs(c%e) < huge(1.0d0))) c%e = 0.0d0"


def _library_source() -> str:
    backend = StaticFirstOrderBackend()
    for attribute in ("library_source", "module_source", "runtime_source", "source"):
        value = getattr(backend, attribute, None)
        if callable(value):
            return value()
        if isinstance(value, str):
            return value
    raise AssertionError("no source accessor found on the static backend")


def test_the_static_backend_guards_every_unbounded_partial():
    source = _library_source()
    for routine in ("pow_oi", "pow_or", "sqrt_o", "log_o"):
        body = re.search(
            rf"function {routine}\(.*?end function {routine}", source, re.S)
        assert body, f"{routine} not found in the static backend"
        assert GUARD in body.group(0), f"{routine} has no finiteness guard"


def test_the_plain_divisions_are_left_alone():
    """The paired case. A division by zero makes the VALUE infinite too, just
    as it does in the untransformed source, and matching the original is the
    point -- guarding it would invent a derivative for a value that has none.
    """
    source = _library_source()
    body = re.search(r"function div_oo\(.*?end function div_oo", source, re.S)
    if body is None:
        body = re.search(r"c%e = \(a%e \* b%r - a%r \* b%e\) / \(b%r \* b%r\)\n(.*?)\n",
                         source, re.S)
        assert body and GUARD not in body.group(1)
        return
    assert GUARD not in body.group(0)
