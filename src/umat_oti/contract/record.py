"""The canonical contract record: one UMAT, everything the other side needs.

This is the single object that crosses between UMAT_source_transformation and
Residual_Assembler. Before it, each side read ad-hoc keys out of the other's
JSON; a key renamed on one side surfaced on the other as a wrong number three
layers away.

The sections, and why each is its own section
---------------------------------------------
``identity``
    Cache path plus source SHA-256. Never a basename. See :mod:`.identity`.
``transform_fingerprint``
    The digest of the transform code the record was produced at. A consumer
    must be able to refuse a record or a fixture produced at a different one.
``terminal``
    The final answer and its owner, EXTERNAL or INTERNAL. See :mod:`.terminal`.
``evidence``
    The six gates and the seventh field, three-state. See :mod:`.gates`.
``material``
    The property values AND their provenance, together, because a value with
    no provenance is indistinguishable from an invented one and "do not invent
    arbitrary material constants" is a standing rule of this project. The
    provenance says which deck, which ``*MATERIAL`` block, how many constants,
    and whether the state count came from a ``*DEPVAR`` or was inferred.
``interface``
    ``ntens``, ``ndi``, ``nshr``, ``nstatv``, ``nprops``, ``unsymmetric``.
    Counts, not opinions.
``convention``
    The tensor convention: the Voigt component order and whether shear is
    engineering or tensorial. Carried explicitly because a consumer assembling
    a residual with the wrong shear convention gets an answer that is wrong by
    a factor of two in three components and right everywhere else, which is
    the hardest kind of wrong to notice.
``kinematics``
    Small strain or finite, with the deck line that said so.
``formulation``
    The element family, the element the deck ran, the element the verification
    ran, and whether the source and the deck agreed about it.
``derivatives``
    What the generated build can differentiate, and whether it was verified.
``fixtures``
    Which regression fixtures were frozen from this entry. See :mod:`.fixtures`.

What is deliberately absent: a single ``ok`` or ``passed`` field. Every
distinction above was bought with debugging, and one boolean over the top of
them would be a summary that hides them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from . import version as _version
from .gates import EvidenceGates, read_gates
from .identity import UmatIdentity
from .terminal import TerminalState, from_record as _terminal_from_record
from .tristate import NOT_ESTABLISHED, Tri, read

__all__ = ["ContractRecord", "MaterialProperties", "Interface",
           "StoreAdaptation", "adapt_store_records",
           "TensorConvention", "Kinematics", "Formulation",
           "DerivativeCapability", "from_store_record", "RecordError",
           "VOIGT_3D", "ENGINEERING_SHEAR"]


class RecordError(ValueError):
    """A record that cannot be carried across the contract boundary."""


#: The Abaqus UMAT component order for a three-dimensional continuum, with
#: ENGINEERING shear on the off-diagonals. Spelled out rather than assumed.
VOIGT_3D = ("11", "22", "33", "12", "13", "23")
ENGINEERING_SHEAR = "engineering"
TENSORIAL_SHEAR = "tensorial"


# ---------------------------------------------------------------------------
# material properties, never without their provenance
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MaterialProperties:
    """The PROPS vector and where every number in it came from.

    ``provenance`` is required and non-empty. A property list with no
    provenance is refused rather than carried, because the one thing that
    distinguishes a constant somebody published from a constant somebody
    invented is the record of where it was read.
    """

    props: tuple = ()
    provenance: str = ""
    deck: str = ""
    material_block: str = ""
    constants_declared: Optional[int] = None
    #: TRUE where the state count came from a ``*DEPVAR`` in the deck, FALSE
    #: where it was inferred from the source, NOT ESTABLISHED where neither
    #: happened. Three-state, because "inferred" and "unknown" are different
    #: and an inferred count is a weaker claim than a declared one.
    nstatv_from_depvar: Tri = NOT_ESTABLISHED
    searched: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.props)

    def require_provenance(self) -> None:
        if not self.provenance.strip():
            raise RecordError(
                f"{self.count} material constant(s) are carried with no "
                f"provenance. A value with no provenance is indistinguishable "
                f"from an invented one, and this project does not invent "
                f"material constants. Provenance must name the deck, the "
                f"*MATERIAL block, how many constants it declared, and "
                f"whether the state count came from a *DEPVAR.")

    def as_dict(self) -> dict:
        return {"props": list(self.props), "count": self.count,
                "provenance": self.provenance, "deck": self.deck,
                "material_block": self.material_block,
                "constants_declared": self.constants_declared,
                "nstatv_from_depvar": self.nstatv_from_depvar.state,
                "searched": dict(self.searched)}


# ---------------------------------------------------------------------------
# counts, convention, kinematics, formulation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Interface:
    """The UMAT's argument sizes. ``None`` means not established."""

    ntens: Optional[int] = None
    ndi: Optional[int] = None
    nshr: Optional[int] = None
    nstatv: Optional[int] = None
    nprops: Optional[int] = None
    unsymmetric: Tri = NOT_ESTABLISHED

    def consistent(self) -> tuple:
        """``(ok, reason)`` -- ntens must be ndi + nshr where all three exist."""
        if None in (self.ntens, self.ndi, self.nshr):
            return (True, "")
        if self.ntens != self.ndi + self.nshr:
            return (False, f"ntens={self.ntens} but ndi+nshr="
                           f"{self.ndi}+{self.nshr}={self.ndi + self.nshr}")
        return (True, "")

    def as_dict(self) -> dict:
        return {"ntens": self.ntens, "ndi": self.ndi, "nshr": self.nshr,
                "nstatv": self.nstatv, "nprops": self.nprops,
                "unsymmetric": self.unsymmetric.state}


@dataclass(frozen=True)
class TensorConvention:
    """How a stress or strain vector's components are ordered and scaled."""

    voigt_order: tuple = VOIGT_3D
    shear: str = ENGINEERING_SHEAR
    note: str = ""

    def as_dict(self) -> dict:
        return {"voigt_order": list(self.voigt_order), "shear": self.shear,
                "note": self.note}

    @classmethod
    def for_ntens(cls, ntens: Optional[int]) -> "TensorConvention":
        """The convention Abaqus uses for a given NTENS.

        6 is the three-dimensional continuum order; 4 is plane strain /
        axisymmetric (11, 22, 33, 12); 3 is plane stress (11, 22, 12). Shear
        is ENGINEERING in every one of them -- Abaqus passes DSTRAN with
        engineering shear, and a consumer that halves it gets a tangent that
        is wrong by two in the shear block and right elsewhere.
        """
        orders = {6: VOIGT_3D, 4: ("11", "22", "33", "12"),
                  3: ("11", "22", "12"), 2: ("11", "12")}
        if ntens not in orders:
            return cls(voigt_order=(), shear=ENGINEERING_SHEAR,
                       note=f"ntens={ntens!r}: component order not established")
        return cls(voigt_order=orders[ntens], shear=ENGINEERING_SHEAR,
                   note=f"Abaqus UMAT order for NTENS={ntens}, engineering "
                        f"shear on the off-diagonals")


@dataclass(frozen=True)
class Kinematics:
    """Small strain or finite, and the deck line that said so."""

    regime: str = ""
    provenance: str = ""
    note: str = ""

    #: The two values this contract recognises. Anything else is refused
    #: rather than guessed, because the seed of a derivative depends on it:
    #: a small-strain contract seeds DSTRAN, a finite-strain one must seed
    #: the deformation gradient, and guessing differentiates the wrong thing.
    SMALL = "small strain"
    FINITE = "finite"

    @property
    def finite_strain(self) -> bool:
        return self.regime == self.FINITE

    @property
    def established(self) -> bool:
        return self.regime in (self.SMALL, self.FINITE)

    def as_dict(self) -> dict:
        return {"regime": self.regime, "provenance": self.provenance,
                "note": self.note}


@dataclass(frozen=True)
class Formulation:
    """Which element family, and whether the source and the deck agreed."""

    family: str = ""
    element_verified_on: str = ""
    deck_elements: tuple = ()
    agreement: str = ""
    provenance: str = ""
    reason: str = ""

    def as_dict(self) -> dict:
        return {"family": self.family,
                "element_verified_on": self.element_verified_on,
                "deck_elements": list(self.deck_elements),
                "agreement": self.agreement, "provenance": self.provenance,
                "reason": self.reason}


@dataclass(frozen=True)
class DerivativeCapability:
    """What the generated build can differentiate, and whether it was checked.

    ``verified`` is the ``derivatives_verified`` gate restated here so a
    consumer reading the derivative section does not have to reach into the
    evidence block -- it is the SAME three-state value, not a second opinion.
    """

    seed: str = ""
    responses: tuple = ()
    order: Optional[int] = None
    verified: Tri = NOT_ESTABLISHED
    states_checked: Optional[int] = None
    states_agreeing: Optional[int] = None
    states_unmeasured: Optional[int] = None
    driven_through: str = ""
    reason: str = ""

    def as_dict(self) -> dict:
        return {"seed": self.seed, "responses": list(self.responses),
                "order": self.order, "verified": self.verified.state,
                "states_checked": self.states_checked,
                "states_agreeing": self.states_agreeing,
                "states_unmeasured": self.states_unmeasured,
                "driven_through": self.driven_through, "reason": self.reason}


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContractRecord:
    """Everything one verified (or unverified) UMAT publishes to the other side."""

    identity: UmatIdentity
    transform_fingerprint: str
    terminal: TerminalState
    evidence: EvidenceGates
    material: MaterialProperties
    interface: Interface
    convention: TensorConvention
    kinematics: Kinematics
    formulation: Formulation
    derivatives: DerivativeCapability
    manifest: dict = field(default_factory=dict)
    fixtures: tuple = ()
    warnings: tuple = ()
    contract_version: str = _version.CONTRACT_VERSION

    def as_dict(self) -> dict:
        return {
            "contract_version": self.contract_version,
            "identity": self.identity.as_dict(),
            "transform_fingerprint": self.transform_fingerprint,
            "terminal": self.terminal.as_dict(),
            "evidence": self.evidence.as_dict(),
            "material": self.material.as_dict(),
            "interface": self.interface.as_dict(),
            "convention": self.convention.as_dict(),
            "kinematics": self.kinematics.as_dict(),
            "formulation": self.formulation.as_dict(),
            "derivatives": self.derivatives.as_dict(),
            "manifest": dict(self.manifest),
            "fixtures": [f if isinstance(f, dict) else f.as_dict()
                         for f in self.fixtures],
            "warnings": list(self.warnings),
        }

    def usable_by_the_residual_assembler(self) -> tuple:
        """``(Tri, reason)`` -- may the assembler drive itself from this entry?

        Three-state on purpose. TRUE needs a verified terminal state, all six
        gates measured true, and an established tensor convention. FALSE is a
        measured refusal. NOT ESTABLISHED is what an entry that nobody
        finished measuring gets, and it is not a refusal -- the difference
        matters because a refusal is a finding and an unmeasured entry is a
        queue item.
        """
        if not self.terminal.verified:
            return (Tri(False), f"terminal state is {self.terminal.state!r} "
                                f"({self.terminal.owner}), not fully_verified")
        # The SETTLED six, not the raw ones: a primal that disagreed and whose
        # difference a control measured and explained is a chain, not a
        # contradiction. The raw conjunction stays available and unmoved for
        # the reader asking whether the two builds produced the same numbers.
        settled = self.evidence.settled()
        if settled.is_false():
            primal = self.evidence.primal_settled()
            failing = [n for n in self.evidence.failing() if n != "primal_agreed"]
            if primal.is_false():
                failing.append(f"primal_agreed ({primal.why})")
            return (Tri(False), f"gates measured false: {', '.join(failing)}")
        if settled.is_not_established():
            unmeasured = [n for n in self.evidence.not_established()
                          if n != "primal_agreed"]
            primal = self.evidence.primal_settled()
            if primal.is_not_established():
                unmeasured.append(f"primal_agreed ({primal.why})")
            return (NOT_ESTABLISHED,
                    f"gates never measured: {', '.join(unmeasured)}")
        if not self.convention.voigt_order:
            return (NOT_ESTABLISHED, self.convention.note or
                    "the tensor component order is not established")
        return (Tri(True), "")


# ---------------------------------------------------------------------------
# adapter: a store-verification row -> a contract record
# ---------------------------------------------------------------------------
def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _kinematics(row: Mapping[str, Any]) -> Kinematics:
    raw = str(row.get("kinematics") or "").strip()
    mapped = {"": "", "small strain": Kinematics.SMALL,
              "small_strain": Kinematics.SMALL, "finite": Kinematics.FINITE,
              "finite strain": Kinematics.FINITE}
    if raw not in mapped:
        raise RecordError(
            f"kinematics {raw!r} is neither {Kinematics.SMALL!r} nor "
            f"{Kinematics.FINITE!r}. The seed of every derivative depends on "
            f"which it is -- small strain seeds DSTRAN, finite strain must "
            f"seed the deformation gradient -- so guessing here "
            f"differentiates the wrong quantity. Refusing.")
    return Kinematics(regime=mapped[raw],
                      provenance=str(row.get("kinematics_provenance") or ""),
                      note=str(row.get("kinematics_note") or ""))


def _formulation(row: Mapping[str, Any]) -> Formulation:
    block = row.get("formulation")
    if not isinstance(block, Mapping):
        return Formulation(element_verified_on=str(row.get("element_type") or ""))
    return Formulation(
        family=str(block.get("family") or ""),
        element_verified_on=str(block.get("element")
                                or row.get("element_type") or ""),
        deck_elements=tuple(str(e) for e in (block.get("deck_elements") or [])),
        agreement=str(block.get("agreement") or ""),
        provenance=str(block.get("provenance") or ""),
        reason=str(block.get("reason") or ""))


def _material(row: Mapping[str, Any], manifest: Mapping[str, Any]) -> MaterialProperties:
    props = manifest.get("props") if isinstance(manifest, Mapping) else None
    values = tuple(props) if isinstance(props, (list, tuple)) else ()
    provenance = str(row.get("material_provenance")
                     or (manifest.get("material_provenance")
                         if isinstance(manifest, Mapping) else "") or "")
    depvar: Tri = NOT_ESTABLISHED
    if provenance:
        lowered = provenance.lower()
        if "*depvar" in lowered:
            depvar = Tri(True, "the paired deck declares a *DEPVAR")
        else:
            depvar = Tri(False, "no *DEPVAR in the provenance; the state "
                                "count was inferred rather than declared")
    searched = row.get("searched_for_material_data")
    return MaterialProperties(
        props=values, provenance=provenance,
        deck=str(row.get("deck") or ""),
        material_block=str(row.get("material_block") or ""),
        constants_declared=_int_or_none(row.get("props_count")),
        nstatv_from_depvar=depvar,
        searched=dict(searched) if isinstance(searched, Mapping) else {})


def _derivatives(row: Mapping[str, Any], gates: EvidenceGates,
                 kinematics: Kinematics) -> DerivativeCapability:
    tangent = row.get("tangent")
    tangent = tangent if isinstance(tangent, Mapping) else {}
    seed = ("DSTRAN" if kinematics.regime == Kinematics.SMALL
            else "DFGRD1" if kinematics.finite_strain else "")
    return DerivativeCapability(
        seed=seed,
        responses=("STRESS", "STATEV") if seed else (),
        order=1 if seed else None,
        verified=gates.derivatives_verified,
        states_checked=_int_or_none(tangent.get("states_checked")),
        states_agreeing=_int_or_none(tangent.get("states_agreeing")),
        states_unmeasured=_int_or_none(tangent.get("states_unmeasured")),
        driven_through=str(tangent.get("driven_through") or ""),
        reason=str(tangent.get("reason") or ""))


def from_store_record(row: Mapping[str, Any], *,
                      fixtures: tuple = ()) -> ContractRecord:
    """Translate one ``store_verification.jsonl`` row into a contract record.

    Refuses rather than guesses: an unmappable stage, an identity that is a
    bare basename, an unrecognised kinematics value, and material constants
    with no provenance are each a refusal with the reason. Nothing is
    defaulted into a pass.
    """
    if not isinstance(row, Mapping):
        raise RecordError(f"a store row must be an object; got "
                          f"{type(row).__name__}")
    identity = UmatIdentity.from_record(row)
    fingerprint = str(row.get("fingerprint") or "")
    if not fingerprint:
        raise RecordError(
            f"{identity}: the row declares no transform fingerprint, so a "
            f"consumer cannot tell whether its numbers predate a correction "
            f"to the transform. Refusing to carry it.")
    terminal = _terminal_from_record(row)
    gates = read_gates(row)
    ok, why = gates.seventh_is_consistent()
    if not ok:
        raise RecordError(f"{identity}: {why}")
    manifest = row.get("manifest")
    manifest = dict(manifest) if isinstance(manifest, Mapping) else {}
    kinematics = _kinematics(row)
    material = _material(row, manifest)
    if material.props and not material.provenance.strip():
        material.require_provenance()
    ntens = _int_or_none(row.get("ntens"))
    interface = Interface(
        ntens=ntens,
        ndi=_int_or_none(manifest.get("ndi")),
        nshr=_int_or_none(manifest.get("nshr")),
        nstatv=_int_or_none(row.get("nstatv")),
        nprops=_int_or_none(manifest.get("nprops")
                            if manifest.get("nprops") is not None
                            else row.get("props_count")),
        unsymmetric=read(row, "unsymmetric"))
    consistent, reason = interface.consistent()
    if not consistent:
        raise RecordError(f"{identity}: {reason}. A component count that does "
                          f"not add up means a consumer sizing an array from "
                          f"one of them and indexing it from another.")
    return ContractRecord(
        identity=identity,
        transform_fingerprint=fingerprint,
        terminal=terminal,
        evidence=gates,
        material=material,
        interface=interface,
        convention=TensorConvention.for_ntens(ntens),
        kinematics=kinematics,
        formulation=_formulation(row),
        derivatives=_derivatives(row, gates, kinematics),
        manifest=manifest,
        fixtures=tuple(fixtures),
        warnings=tuple(str(w) for w in (row.get("warnings") or [])))


@dataclass(frozen=True)
class StoreAdaptation:
    """Every row of a store accounted for: translated, or refused with a reason.

    Two outputs and no third. A row is either a :class:`ContractRecord` or a
    conforming error envelope naming why it could not become one -- nothing is
    dropped, and nothing is defaulted into a record that would read as a
    verdict it never earned.

    Measured on the frozen 237-entry store: 234 translate, and 3 are refused
    with ``contract.untranslatable_stage`` because
    ``arguments_diverged_before_the_routine`` has no owner in
    ``terminal_states.FROM_STAGE``. Silently answering ``not_attempted`` for
    those three -- which is what ``from_stage`` does -- would assert that this
    project never tried, about three entries that ran.
    """

    records: tuple = ()
    errors: tuple = ()

    @property
    def total(self) -> int:
        return len(self.records) + len(self.errors)

    def describe(self) -> str:
        by_code: dict = {}
        for error in self.errors:
            by_code[error["code"]] = by_code.get(error["code"], 0) + 1
        detail = ("; ".join(f"{n} {code}" for code, n in sorted(by_code.items()))
                  or "none refused")
        return (f"{len(self.records)} of {self.total} rows translated into "
                f"contract records; {detail}")


def adapt_store_records(rows: Any, *, fixtures: Mapping[str, tuple] = None
                        ) -> "StoreAdaptation":
    """Translate a whole store, accounting for every row either way."""
    from .errors import ContractError  # local: errors imports terminal, not record

    frozen = dict(fixtures or {})
    records: list = []
    errors: list = []
    for index, row in enumerate(rows):
        where = ""
        try:
            identity = UmatIdentity.from_record(row) \
                if isinstance(row, Mapping) else None
            where = str(identity) if identity else f"row {index}"
        except Exception:            # noqa: BLE001 - reported below as an error
            identity, where = None, f"row {index}"
        try:
            records.append(from_store_record(
                row, fixtures=frozen.get(where, ())))
        except Exception as exc:      # noqa: BLE001 - every refusal is reported
            code = ("contract.untranslatable_stage"
                    if exc.__class__.__name__ == "TerminalStateError"
                    else "contract.identity_not_unique"
                    if exc.__class__.__name__ == "IdentityError"
                    else "contract.schema_violation")
            errors.append(ContractError(
                code=code, owner="CONTRACT", message=str(exc), terminal=False,
                identity=identity,
                detail={"row_index": index,
                        "stage": (row.get("stage")
                                  if isinstance(row, Mapping) else None)},
                contract_version=_version.CONTRACT_VERSION).as_dict())
    return StoreAdaptation(records=tuple(records), errors=tuple(errors))
