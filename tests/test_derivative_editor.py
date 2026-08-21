from __future__ import annotations

import pytest

from umat_oti.app.derivative_editor import build_unified_config, request_editor_rows
from umat_oti.core.derivative_request import DerivativeRequestError, load_project_derivative_requests


def test_editor_builds_all_unified_request_kinds():
    config = {"project": {"name": "gui-case"}, "source": {"selected_umat_file": "/tmp/umat.for"}}
    rows = [
        {"id": "tangent", "kind": "material_tangent", "target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1},
        {"id": "local", "kind": "local_jacobian", "target": "FJAC", "seed": "DGAMMA", "response": "RESID", "order": 1, "scope": "NEWTON"},
        {"id": "higher", "kind": "higher_order", "target": "DDSDDE3", "seed": "DSTRAN", "response": "STRESS", "order": 3},
        {"id": "stress_p", "kind": "parameter_sensitivity", "target": "DSIGMA_DP", "seed": "E, NU", "response": "STRESS", "order": 1},
        {"id": "state_p", "kind": "state_sensitivity", "target": "DSTATEV_DP", "seed": "E, EQPLAS", "response": "STATEV", "order": 1},
    ]

    updated = build_unified_config(
        config,
        rows,
        [{"name": "E", "props_index": 1, "value": 210000.0}, {"name": "NU", "props_index": 2, "value": 0.3}],
        [{"name": "EQPLAS", "statev_index": 1}],
    )
    requests = load_project_derivative_requests(updated)

    assert updated["schema_version"] == "1.1"
    assert [request.kind for request in requests] == [row["kind"] for row in rows]
    assert requests[3].parameter_map == (("E", 1), ("NU", 2))
    assert requests[4].parameter_map == (("E", 1),)
    assert requests[4].state_map == (("EQPLAS", 1),)
    assert request_editor_rows(updated)[2]["seed"] == "DSTRAN"


def test_editor_rejects_duplicate_request_ids():
    rows = [
        {"id": "same", "kind": "material_tangent", "target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1},
        {"id": "same", "kind": "higher_order", "target": "DDSDDE2", "seed": "DSTRAN", "response": "STRESS", "order": 2},
    ]

    with pytest.raises(DerivativeRequestError, match="duplicate derivative-request id"):
        build_unified_config({}, rows, [], [])
