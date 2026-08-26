"""The state machine behind the four-step interface, without any Streamlit.

Keeping it separate means the rules a user meets -- when a step is complete,
when Run may be pressed, which products the selected source can actually
produce -- are testable without a browser, and are the same rules whether they
are reached from the interface or from a script.

Nothing here computes a derivative or invents a material value. It decides what
may be asked for, and says why when something may not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from umat_oti.publication.status import status_word

#: The four steps, in order. The numbering is generated from this list, so it
#: cannot skip: a screenshot that shows "1, 3, 4" means a step was dropped, and
#: that is a defect rather than a layout choice.
STEPS: tuple[tuple[str, str], ...] = (
    ("Source", "Choose the UMAT subroutine to differentiate."),
    ("Material model", "Describe the material the subroutine expects."),
    ("Derivatives and loading", "Choose what to compute, and how to load it."),
    ("Run and results", "Run the pipeline and read the evidence."),
)

#: Plain-language name for each product, with the API name kept as secondary
#: text so a reader who knows Abaqus still recognises it.
PRODUCT_LABELS: dict[str, tuple[str, str]] = {
    "DDSDDE": ("Consistent tangent", "DDSDDE"),
    "DSIGMA_DP": ("Stress sensitivity to material parameters", "DSIGMA_DP"),
    "DSTATEV_DP": ("State sensitivity to material parameters", "DSTATEV_DP"),
    "HIGHER_ORDER_STRESS": ("Higher-order stress derivatives",
                            "orders 2 and above"),
    "INTERNAL_JACOBIAN": ("Internal Jacobian of the local solve", "FJAC / DF"),
}

#: Short names for tab strips, where five full names do not fit a narrow
#: window and overflow it sideways.
PRODUCT_TABS: dict[str, str] = {
    "DDSDDE": "Tangent",
    "DSIGMA_DP": "Stress sens.",
    "DSTATEV_DP": "State sens.",
    "HIGHER_ORDER_STRESS": "Higher order",
    "INTERNAL_JACOBIAN": "Internal Jac.",
}

#: What each product is for, for a reader who has not met it before.
PRODUCT_HELP: dict[str, str] = {
    "DDSDDE": "The derivative of stress with respect to the strain increment. "
              "Abaqus uses it to build the global stiffness matrix.",
    "DSIGMA_DP": "How the stress at a material point responds to each material "
                 "constant. Used for calibration and uncertainty work.",
    "DSTATEV_DP": "How each state variable responds to each material constant. "
                  "Needed because a history-dependent material carries that "
                  "dependence into the next increment.",
    "HIGHER_ORDER_STRESS": "Second and higher derivatives of stress with "
                           "respect to the strain increment: curvature rather "
                           "than slope.",
    "INTERNAL_JACOBIAN": "The derivative the model's own Newton iteration needs "
                         "to solve its local equation. Abaqus never sees it.",
}


@dataclass
class Requirement:
    """One reason a product cannot be produced from this request."""

    product: str
    status: str
    reason: str

    @property
    def word(self) -> str:
        return status_word(self.status)


@dataclass
class WizardState:
    """Everything the four steps collect, and what has been settled so far."""

    source_key: Optional[str] = None
    source_path: Optional[Any] = None
    dependency_roots: tuple[Any, ...] = ()
    analysis: dict = field(default_factory=dict)

    ntens: int = 6
    ndi: int = 3
    nshr: int = 3
    nstatv: int = 1
    props: tuple[float, ...] = ()
    parameters: tuple[tuple[str, int], ...] = ()
    state_names: tuple[str, ...] = ()
    field_origins: dict = field(default_factory=dict)

    products: tuple[str, ...] = ()
    higher_order_max: int = 4
    loading_label: str = ""

    def furthest_ready_step(self) -> int:
        """The last step whose inputs are complete, zero-indexed."""
        if not self.source_complete():
            return 0
        if not self.material_complete():
            return 1
        if not self.request_complete():
            return 2
        return 3

    def source_complete(self) -> bool:
        return self.source_path is not None and bool(self.analysis)

    def material_complete(self) -> bool:
        return not self.material_problems()

    def request_complete(self) -> bool:
        return bool(self.products) and not self.request_problems()

    # -- validation ------------------------------------------------------ #
    def source_problems(self) -> list[str]:
        problems: list[str] = []
        if self.source_path is None:
            problems.append("No source is selected. Choose an example or "
                            "upload a UMAT file.")
            return problems
        if not self.analysis:
            problems.append("The source has not been analysed yet.")
            return problems
        if self.analysis.get("dependency_error"):
            problems.append(f"Dependencies could not be resolved: "
                            f"{self.analysis['dependency_error']}")
        missing = self.analysis.get("missing_symbols") or []
        if missing:
            names = ", ".join(m["symbol"] for m in missing)
            problems.append(
                f"These helper routines are called but not found: {names}. "
                "Add the directory that holds them under Advanced settings.")
        ambiguous = self.analysis.get("ambiguous_symbols") or []
        if ambiguous:
            problems.append(
                "These helpers are defined differently in different files and "
                f"none is local: {', '.join(ambiguous)}. Choosing one would "
                "change the numerics, so the run is refused.")
        return problems

    def material_problems(self) -> list[str]:
        problems: list[str] = []
        if self.ntens <= 0:
            problems.append("NTENS must be at least 1.")
        if self.ndi + self.nshr != self.ntens:
            problems.append(
                f"NDI + NSHR must equal NTENS. You have {self.ndi} + "
                f"{self.nshr} = {self.ndi + self.nshr}, but NTENS is "
                f"{self.ntens}.")
        minimum = (self.analysis.get("dimensions") or {}).get("minimum_ntens")
        if minimum and self.ntens < int(minimum):
            problems.append(
                f"This source writes tensor index {minimum}, so NTENS must be "
                f"at least {minimum}. Running it with NTENS={self.ntens} would "
                "read or write outside the driver's arrays.")
        if not self.props:
            problems.append("No material properties are given. PROPS is the "
                            "vector the subroutine reads its constants from.")
        for name, index in self.parameters:
            if index < 1 or index > len(self.props):
                problems.append(
                    f"Parameter {name!r} points at PROPS index {index}, but "
                    f"only {len(self.props)} properties are given.")
        if len(self.state_names) > self.nstatv:
            problems.append(
                f"{len(self.state_names)} state variable names were given but "
                f"NSTATV is {self.nstatv}.")
        return problems

    def request_problems(self) -> list[str]:
        problems: list[str] = []
        if not self.products:
            problems.append("No derivative product is selected. Choose at "
                            "least one on this step.")
        if not self.loading_label:
            problems.append("No loading history is selected.")
        needs_parameters = {"DSIGMA_DP", "DSTATEV_DP"} & set(self.products)
        if needs_parameters and not self.parameters:
            problems.append(
                "Parameter sensitivities were requested but no material "
                "constant is marked for differentiation. Go back to the "
                "material step and tick at least one.")
        if "DSTATEV_DP" in self.products and self.nstatv < 1:
            problems.append(
                "State sensitivities were requested but the model declares no "
                "state variables (NSTATV is 0).")
        return problems

    def blocking_problems(self) -> list[str]:
        """Everything standing between this request and a run."""
        return (self.source_problems() + self.material_problems()
                + self.request_problems())

    def requirements(self) -> list[Requirement]:
        """Products that were asked for but cannot be produced, and why.

        Reported before the run rather than after it, so a user is not made to
        wait for a build in order to be told the request was never possible.
        """
        found: list[Requirement] = []
        solves = self.analysis.get("local_solves") or []
        if "INTERNAL_JACOBIAN" in self.products and not solves:
            found.append(Requirement(
                "INTERNAL_JACOBIAN", "unsupported",
                "This source integrates its law without a local Newton "
                "iteration, so it has no internal Jacobian to extract."))
        if "HIGHER_ORDER_STRESS" in self.products:
            found.append(Requirement(
                "HIGHER_ORDER_STRESS", "unsupported",
                "Stress derivatives of order two and above are produced by the "
                "contract pipeline, and are not yet wired into this request. "
                "Asking for them here reports unsupported rather than "
                "returning nothing."))
        return found

    def supported_products(self) -> tuple[str, ...]:
        blocked = {r.product for r in self.requirements()}
        return tuple(p for p in self.products if p not in blocked)


def step_titles() -> list[str]:
    """"1. Source", "2. Material model", ... generated, never written out."""
    return [f"{index}. {name}" for index, (name, _) in enumerate(STEPS, start=1)]
