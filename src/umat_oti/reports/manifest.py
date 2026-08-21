"""Derivative manifest emitter.

The SoftwareX task requires a machine-readable manifest recording every
important detail of a transformation run so downstream consumers can match
generated outputs back to the exact source / parameter map that produced them.

The manifest is a JSON document with the following schema
(``schema: umat-oti-derivative-manifest/1``)::

    {
      "schema": "umat-oti-derivative-manifest/1",
      "generated_at": "<utc iso timestamp>",
      "umat_oti_version": "<pkg version>",
      "source": {
         "path": "<file>",
         "sha256": "<hex>",
         "git_commit": "<sha or null>",
         "entry_routine": "UMAT"
      },
      "dimensions": {"ntens": 6, "nstatv": 1, "nprops": 4},
      "parameters":       [ {"name": "E", "props_index": 1}, ... ],
      "state_variables":  [ {"name": "EQPLAS", "statev_index": 1}, ... ],
      "derivatives":      [ <one entry per DerivativeRequest> ],
      "direction_order":  { "convention": "canonical_graded_lex", ... },
      "convention": {
          "coefficient_vs_derivative": "coefficient_x_factorial=recovered_derivative",
          "recovery_factors": {...}
      },
      "compiler":         {"name": "...", "version": "..."},
      "warnings":         [...]
    }

Nothing here is guessed at run time. Every field either comes from the input
config or is computed deterministically from the source file.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional

from umat_oti import __version__ as _umat_oti_version
from umat_oti.core.derivative_request import DerivativeRequest


MANIFEST_SCHEMA = "umat-oti-derivative-manifest/1"


def sha256_of_file(path: Path | str) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    *,
    source_path: Path | str,
    entry_routine: str,
    ntens: int,
    nstatv: int,
    nprops: int,
    requests: Iterable[DerivativeRequest],
    parameters: Iterable[tuple[str, int]] = (),
    state_variables: Iterable[tuple[str, int]] = (),
    compiler_name: str = "",
    compiler_version: str = "",
    warnings: Iterable[str] = (),
    generated_at: Optional[str] = None,
    git_commit: Optional[str] = None,
    direction_count: Optional[int] = None,
) -> dict[str, Any]:
    """Assemble a manifest dict for a transformation run.

    All array orderings follow the canonical UMAT-OTI convention:

    * ``parameters`` and ``state_variables`` are ordered in the sequence
      supplied by the caller (which matches the ``DerivativeRequest`` seed
      ordering).
    * ``direction_order.convention`` is ``"canonical_graded_lex"`` — the
      same convention used by ``umat_oti.oti.oti_directions``, which enumerates
      directions graded by the largest basis index and lexicographic within
      the grade.
    * The coefficient-vs-derivative convention is spelled out explicitly:
      the OTI coefficient equals the recovered derivative divided by the
      product of factorials of the repeated direction multiplicities.
    """
    source_path = Path(source_path)
    generated_at = generated_at or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    git_commit = git_commit or _infer_git_commit(source_path)

    request_records = [_request_record(r) for r in requests]

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "umat_oti_version": _umat_oti_version,
        "source": {
            "path": str(source_path),
            "sha256": sha256_of_file(source_path) if source_path.is_file() else None,
            "git_commit": git_commit,
            "entry_routine": entry_routine.upper(),
        },
        "dimensions": {"ntens": ntens, "nstatv": nstatv, "nprops": nprops},
        "parameters": [
            {"name": name, "props_index": idx} for name, idx in parameters
        ],
        "state_variables": [
            {"name": name, "statev_index": idx} for name, idx in state_variables
        ],
        "derivatives": request_records,
        "direction_order": {
            "convention": "canonical_graded_lex",
            "reference": "umat_oti.oti.oti_directions",
            "direction_count": direction_count,
        },
        "convention": {
            "coefficient_vs_derivative": (
                "recovered_derivative = OTI_coefficient * product_of_factorials(direction_multiplicities)"
            ),
            "recovery_factors": _recovery_factors_table(request_records),
        },
        "compiler": {"name": compiler_name, "version": compiler_version},
        "warnings": list(warnings),
    }
    return manifest


def write_manifest(manifest: dict[str, Any], destination: Path | str) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return destination


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _request_record(request: DerivativeRequest) -> dict[str, Any]:
    record = request.to_dict()
    record["recovery_factor"] = _recovery_factor_for(request)
    return record


def _recovery_factor_for(request: DerivativeRequest) -> int:
    """Recovery factor for a request under the canonical convention.

    The generalised OTI direction convention represents a mixed
    :math:`k`-th derivative as ``OTI_coefficient * prod_i (m_i!)`` where
    :math:`m_i` is the multiplicity of direction :math:`i` in the derivative.
    For plain first-order requests (order == 1) the factor is 1; for a pure
    :math:`k`-th-order repeated derivative it is :math:`k!`; for mixed
    derivatives it is the product of the factorials of the multiplicities.

    Without a concrete direction assignment the *worst-case* recovery factor
    for a request of order ``k`` is ``k!``. That is what we report; it is
    the strictest scalar factor a downstream consumer needs to be aware of.
    """
    if request.order <= 1:
        return 1
    return math.factorial(request.order)


def _recovery_factors_table(request_records: list[dict[str, Any]]) -> dict[str, int]:
    return {r["id"]: r.get("recovery_factor", 1) for r in request_records}


def _infer_git_commit(source_path: Path) -> Optional[str]:
    if not source_path.is_file():
        return None
    if shutil.which("git") is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(source_path.parent), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


__all__ = [
    "MANIFEST_SCHEMA",
    "build_manifest",
    "sha256_of_file",
    "write_manifest",
]
