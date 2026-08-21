"""Versioned material-driver contract shared with Residual Assembler.

This is the single source of truth for how a UMAT-OTI-generated material
driver hands point-wise constitutive derivatives to a downstream residual
assembler. The same payload is emitted by
``umat_oti.validation.parameter_sensitivity`` and consumed by
``residual_core.materials.umat_oti_driver`` on the Residual Assembler side.

Schema id: ``umat-oti-driver-contract/1.1``.

The design deliberately keeps this a small, plain-JSON payload with no
UMAT-OTI-specific Python types on the wire: any consumer that speaks JSON
can build a residual sensitivity from it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


CONTRACT_SCHEMA = "umat-oti-driver-contract/1.1"


@dataclass
class ParameterEntry:
    name: str
    props_index: int


@dataclass
class StateEntry:
    name: str
    statev_index: int


@dataclass
class DriverContract:
    """The versioned material-driver contract.

    Fields
    ------
    schema
        Contract schema id, must equal ``CONTRACT_SCHEMA``.
    driver_id
        Human-readable identifier for the driver (e.g. ``"j2_softwarex"``).
    ntens
        Number of independent stress components used in ``DSIGMA_DP``.
    nstatv
        Number of state variables used in ``DSTATEV_DP``.
    nprops
        Total PROPS length expected by the driver.
    parameters
        Ordered list of parameter descriptors. Order defines the column
        order of ``DSIGMA_DP`` and ``DSTATEV_DP``.
    state_variables
        Ordered list of exported state variables. Order defines the row
        order of ``DSTATEV_DP``.
    voigt_convention
        Voigt convention used for stress components. Currently only
        ``"engineering_shear"`` is supported (Abaqus default).
    compiler
        Free-text compiler / ABI descriptor. Used by Residual Assembler to
        cross-check compatibility before dlopen'ing a shared driver.
    coefficient_convention
        The recovery-factor convention used to produce the payload. Must
        match the manifest emitted alongside the driver.
    source_sha256
        SHA-256 of the transformed UMAT source (for provenance).
    driver_kind
        ``"python_callable"`` when the payload contains an in-memory
        driver hook (the residual assembler imports the module by name and
        calls ``callable_path``); ``"jsonl_stream"`` when the payload is a
        pre-computed increment stream (JSON-lines file at ``stream_path``).
    callable_path
        Dotted Python path used when ``driver_kind == "python_callable"``.
    stream_path
        File path used when ``driver_kind == "jsonl_stream"``. One line per
        increment; each line is an object with keys ``stress``, ``statev``,
        ``dsigma_dp``, ``dstatev_dp``, ``ddsdde``.
    """

    schema: str
    driver_id: str
    ntens: int
    nstatv: int
    nprops: int
    parameters: list[ParameterEntry]
    state_variables: list[StateEntry]
    voigt_convention: str = "engineering_shear"
    compiler: str = ""
    coefficient_convention: str = "recovered_derivative = OTI_coefficient * prod_factorials(direction_multiplicities)"
    source_sha256: str = ""
    driver_kind: str = "jsonl_stream"
    callable_path: str = ""
    stream_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "driver_id": self.driver_id,
            "ntens": self.ntens,
            "nstatv": self.nstatv,
            "nprops": self.nprops,
            "voigt_convention": self.voigt_convention,
            "compiler": self.compiler,
            "coefficient_convention": self.coefficient_convention,
            "source_sha256": self.source_sha256,
            "driver_kind": self.driver_kind,
            "callable_path": self.callable_path,
            "stream_path": self.stream_path,
            "parameters": [asdict(p) for p in self.parameters],
            "state_variables": [asdict(s) for s in self.state_variables],
        }

    def write(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return p

    @classmethod
    def read(cls, path: Path | str) -> "DriverContract":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != CONTRACT_SCHEMA:
            raise ValueError(
                f"driver contract schema mismatch: expected {CONTRACT_SCHEMA!r}, got {data.get('schema')!r}"
            )
        return cls(
            schema=data["schema"],
            driver_id=data.get("driver_id", ""),
            ntens=int(data["ntens"]),
            nstatv=int(data["nstatv"]),
            nprops=int(data["nprops"]),
            parameters=[ParameterEntry(**p) for p in data.get("parameters", [])],
            state_variables=[StateEntry(**s) for s in data.get("state_variables", [])],
            voigt_convention=data.get("voigt_convention", "engineering_shear"),
            compiler=data.get("compiler", ""),
            coefficient_convention=data.get(
                "coefficient_convention", DriverContract.coefficient_convention
            ),
            source_sha256=data.get("source_sha256", ""),
            driver_kind=data.get("driver_kind", "jsonl_stream"),
            callable_path=data.get("callable_path", ""),
            stream_path=data.get("stream_path", ""),
        )


def build_softwarex_j2_contract(*, stream_path: str = "j2_stream.jsonl") -> DriverContract:
    """Build the SoftwareX focused-case contract for the J2 driver."""
    return DriverContract(
        schema=CONTRACT_SCHEMA,
        driver_id="j2_softwarex",
        ntens=6,
        nstatv=1,
        nprops=4,
        parameters=[
            ParameterEntry(name="E", props_index=1),
            ParameterEntry(name="NU", props_index=2),
            ParameterEntry(name="SIGY0", props_index=3),
            ParameterEntry(name="H", props_index=4),
        ],
        state_variables=[StateEntry(name="EQPLAS", statev_index=1)],
        driver_kind="jsonl_stream",
        stream_path=stream_path,
    )


def write_j2_stream(records: list[dict[str, Any]], path: Path | str) -> Path:
    """Write a JSON-lines increment stream for the J2 driver.

    Each record must contain: ``stress``, ``statev``, ``dsigma_dp``,
    ``dstatev_dp``, and (optionally) ``ddsdde``. The reader on the Residual
    Assembler side asserts these keys before consuming the stream.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")
    return p


__all__ = [
    "CONTRACT_SCHEMA",
    "DriverContract",
    "ParameterEntry",
    "StateEntry",
    "build_softwarex_j2_contract",
    "write_j2_stream",
]
