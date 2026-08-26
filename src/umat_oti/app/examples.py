"""Example projects the interface can populate itself from.

A first-time user should not have to know a model's property vector to run
anything, and inventing one would be worse than asking. Each example ships a
committed contract, so every field the interface fills in has a file behind it
and can say so.

Nothing here computes a material value. Values are read from the contract or
they are absent, and an absent value is shown as absent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS = REPO_ROOT / "parameter_sensitivity" / "models"
CONTRACTS = REPO_ROOT / "parameter_sensitivity" / "contracts"

#: Where a field's value came from. The interface shows these differently, so a
#: reader can tell a measured input from a typed one at a glance.
INFERRED = "inferred"
USER = "entered"
UNAVAILABLE = "unavailable"


@dataclass
class Parameter:
    """One material constant, and whether a derivative is wanted for it."""

    name: str
    props_index: int
    value: Optional[float]
    differentiate: bool = True


@dataclass
class Example:
    """A committed example project, with everything the interface can prefill."""

    key: str
    source: Path
    contract_path: Optional[Path] = None
    ntens: Optional[int] = None
    ndi: Optional[int] = None
    nshr: Optional[int] = None
    nstatv: Optional[int] = None
    parameters: list[Parameter] = field(default_factory=list)
    state_names: list[str] = field(default_factory=list)
    dstran_per_increment: tuple[float, ...] = ()
    n_increments: int = 0
    loading_provenance: str = ""
    kinematics: str = ""

    @property
    def props(self) -> tuple[float, ...]:
        """PROPS in index order, as far as the contract defines it."""
        if not self.parameters:
            return ()
        size = max(p.props_index for p in self.parameters)
        values = [0.0] * size
        for parameter in self.parameters:
            if parameter.value is not None:
                values[parameter.props_index - 1] = float(parameter.value)
        return tuple(values)

    @property
    def has_contract(self) -> bool:
        return self.contract_path is not None

    def provenance(self) -> str:
        if self.contract_path is None:
            return ("no committed contract for this source, so nothing was "
                    "prefilled; the dimensions and properties are yours to give")
        return f"prefilled from {self.contract_path.relative_to(REPO_ROOT)}"


def _read_contract(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_example(key: str, source: Path) -> Example:
    """Everything a committed contract can tell the interface about a source."""
    example = Example(key=key, source=source)
    contract_path = CONTRACTS / f"{key}.json"
    if not contract_path.is_file():
        return example
    try:
        contract = _read_contract(contract_path)
    except (OSError, json.JSONDecodeError):
        # A contract that cannot be read prefills nothing. It must not prefill
        # something plausible.
        return example

    example.contract_path = contract_path
    example.ntens = contract.get("ntens")
    driver = contract.get("material_point_driver") or {}
    example.nstatv = driver.get("nstatv")
    example.dstran_per_increment = tuple(driver.get("dstran_per_increment") or ())
    example.n_increments = int(driver.get("n_increments") or 0)
    example.loading_provenance = str(driver.get("_source") or "")
    example.kinematics = str((contract.get("provenance") or {}).get("kinematics") or "")

    if example.ntens:
        # Abaqus splits NTENS into direct and shear components. Three direct
        # components is the only split these small-strain examples use, and it
        # is stated rather than guessed at.
        example.ndi = min(3, example.ntens)
        example.nshr = example.ntens - example.ndi

    static = driver.get("static_props") or []
    for entry in contract.get("parameters") or []:
        index = int(entry["props_index"])
        value = entry.get("value")
        if value is None and index <= len(static):
            value = static[index - 1]
        example.parameters.append(
            Parameter(name=str(entry["name"]), props_index=index,
                      value=None if value is None else float(value)))

    example.state_names = [str(s["name"]) for s in
                           sorted(contract.get("state_variables") or [],
                                  key=lambda s: int(s["statev_index"]))]
    return example


def discover() -> dict[str, Example]:
    """Every example project in the repository, with its contract if it has one."""
    if not MODELS.is_dir():
        return {}
    found: dict[str, Example] = {}
    for directory in sorted(MODELS.iterdir()):
        source = directory / "umat.for"
        if source.is_file():
            found[directory.name] = load_example(directory.name, source)
    return found


def describe(example: Example) -> str:
    """A one-line description a non-specialist can read."""
    if not example.has_contract:
        return "no committed contract; nothing prefilled"
    pieces = []
    if example.ntens:
        pieces.append(f"{example.ntens} stress components")
    if example.nstatv is not None:
        pieces.append(f"{example.nstatv} state variable"
                      + ("s" if example.nstatv != 1 else ""))
    if example.parameters:
        pieces.append(f"{len(example.parameters)} material constants")
    if example.kinematics:
        pieces.append(example.kinematics.replace("_", " "))
    return ", ".join(pieces)
