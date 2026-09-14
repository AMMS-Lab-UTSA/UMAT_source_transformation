"""Why two builds of one model disagree -- as hypotheses, with their status.

The previous version of this module returned a *name* for each disagreement:
``iterative_solver_different_iterate``, ``round_off_scale``,
``branch_divergence_sign_flip``. Those names were read off the summary numbers
and a regular-expression search of the source, and they were reported in the
same field, in the same tone, as a measurement. They were not measurements.
"The worst pair has opposite signs and the source contains a DO WHILE" does
not establish that two valid internal solves converged to different iterates.
It is consistent with that. It is equally consistent with one output being
written wrongly, with an argument being passed wrongly, and with a constant
being read at the wrong precision -- and on this corpus the last kind of thing
is what the data actually shows.

So nothing here returns a diagnosis. Each entry gets one or more
:class:`Hypothesis` objects, and each hypothesis carries

    claim                  what it asserts about the mechanism
    predicts               what would have to be true if it held
    supporting_evidence    measurements consistent with it
    contradicting_evidence measurements it forbids, that were seen anyway
    confirmation_status    confirmed / refuted / needs_abaqus /
                           needs_more_evidence / untested
    confirmed_root_cause   set ONLY by confirm(), which requires a
                           reproduction record
    what_would_confirm     the experiment that would settle it
    what_would_refute      the observation that would kill it

Two rules this module enforces rather than documents:

**No classifier path can set ``confirmed_root_cause``.** ``classify`` returns
hypotheses at ``needs_more_evidence`` or ``needs_abaqus`` unless a measured
:class:`~umat_oti.abaqus.call_isolation.Isolation` contradicts them, in which
case it returns ``refuted`` with the contradicting measurement attached. The
only way to reach ``confirmed`` is :meth:`Hypothesis.confirm`, which demands a
:class:`Reproduction` saying what was held fixed, what was varied, and what was
observed.

**``round_off_scale`` is not a pass.** It is a hypothesis about a mechanism --
that the difference is last-place rounding grown along the path -- and it makes
a prediction that can fail: the first call at which the builds part must differ
by about one unit in the last place, and the growth from there must be
consistent with the number of increments. A small worst-case number is not
evidence for it and is never grounds for widening a tolerance.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# status vocabulary
# ---------------------------------------------------------------------------
#: A controlled reproduction was performed, and it showed the mechanism the
#: hypothesis claims. Requires a Reproduction record. Nothing else sets this.
CONFIRMED = "confirmed"
#: A measurement showed something the hypothesis forbids.
REFUTED = "refuted"
#: The measurement that would settle it needs a solver run that has not been
#: made. A request belongs in the Abaqus queue.
NEEDS_ABAQUS = "needs_abaqus"
#: The measurement that would settle it can be made from data already on disk,
#: and has not been -- or the evidence is mixed.
NEEDS_MORE_EVIDENCE = "needs_more_evidence"
#: Raised as a possibility, nothing measured about it yet.
UNTESTED = "untested"
#: The entry cannot carry a claim about the transform, whatever its hypotheses
#: say: something about the run makes the comparison meaningless.
NOT_EVIDENCE = "not_evidence_about_the_transform"

_OPEN_STATUSES = (NEEDS_ABAQUS, NEEDS_MORE_EVIDENCE, UNTESTED)


# ---------------------------------------------------------------------------
# hypothesis names
# ---------------------------------------------------------------------------
#: The transformed build returned a value that is not a number. This is an
#: observation, not a mechanism: it says the comparison established nothing
#: about the model, and leaves open why.
NON_FINITE = "transformed_returned_non_finite"
#: Two valid internal solves of the author's own iteration converged to
#: different iterates because the residual was summed in a different order.
ITERATIVE_SOLVER = "iterative_solver_different_iterate"
#: A conditional inside the routine took a different branch in the two builds.
BRANCH_DIVERGENCE = "branch_divergence"
#: One output component is written with a wrong value while the rest of the
#: call is reproduced. Distinguishable from every "whole solve moved"
#: hypothesis by how many outputs move.
SINGLE_OUTPUT_SLOT = "single_output_slot_corrupted"
#: A constant, a modulus or an argument reaches the routine at a different
#: precision in the two builds, so the first call already differs by far more
#: than double rounding and by about single-precision epsilon.
REDUCED_PRECISION_INPUT = "reduced_precision_constant_or_argument"
#: The two builds agree to the last representable bit at the first call, and
#: the reported difference is that rounding carried along the path.
ROUND_OFF_GROWTH = "round_off_grown_along_path"
#: The routine keeps something between calls -- a SAVE, a COMMON, a file read
#: once -- whose lifetime differs between the builds.
DATA_OR_LIFETIME = "data_read_or_save_lifetime"
#: Most of what was compared is too small a fraction of the response to carry
#: a claim either way.
NEAR_ZERO = "near_zero_normalisation"
#: The transformed routine returns a materially different answer for the very
#: first call of the analysis, from the same arguments. Nothing about the path,
#: the solver or accumulated state can be responsible: there is no path yet.
DIFFERENT_FUNCTION = "transformed_computes_a_different_function"
#: Nothing above fits.
UNCLASSIFIED = "unclassified"


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------
#: Where a piece of evidence came from. ``source_text`` is the weakest: it says
#: a construct exists, never that it ran.
FROM_PROBE = "probe_history"
FROM_ISOLATION = "controlled_single_call_comparison"
FROM_JOB_RECORDS = "abaqus_job_records"
FROM_SOURCE_TEXT = "source_text"
FROM_REPRODUCTION = "controlled_reproduction"

#: Evidence read off source text can support a hypothesis and can never
#: confirm one. A Newton loop in the file is not a Newton loop that ran.
_NEVER_CONFIRMING = (FROM_SOURCE_TEXT,)


@dataclass(frozen=True)
class Evidence:
    """One measurement or observation, with where it came from."""

    statement: str
    origin: str = FROM_PROBE

    @property
    def is_measurement(self) -> bool:
        return self.origin not in _NEVER_CONFIRMING

    def as_dict(self) -> dict:
        return {"statement": self.statement, "origin": self.origin,
                "is_measurement": self.is_measurement}


@dataclass(frozen=True)
class Reproduction:
    """What was held fixed, what was varied, and what came out.

    A hypothesis cannot be confirmed without one. The fields are deliberately
    awkward to fill in from a summary: if "held_fixed" cannot be written down,
    the experiment was not controlled and the result does not confirm anything.
    """

    held_fixed: str
    varied: str
    observed: str
    where: str = ""
    repeatable: bool = False

    def as_dict(self) -> dict:
        return {"held_fixed": self.held_fixed, "varied": self.varied,
                "observed": self.observed, "where": self.where,
                "repeatable": self.repeatable}


@dataclass
class Hypothesis:
    """One proposed mechanism, and everything known for and against it."""

    name: str
    claim: str
    predicts: tuple = ()
    what_would_confirm: str = ""
    what_would_refute: str = ""
    supporting_evidence: list = field(default_factory=list)
    contradicting_evidence: list = field(default_factory=list)
    confirmation_status: str = UNTESTED
    confirmed_root_cause: Optional[str] = None
    reproduction: Optional[Reproduction] = None

    # -- the only two transitions that reach a verdict --------------------
    def confirm(self, root_cause: str, reproduction: Reproduction) -> "Hypothesis":
        """Record that a controlled reproduction showed this mechanism.

        Refuses on three grounds, each of which had to be refused at some
        point while this corpus was being read:

        * a hypothesis already refuted cannot be confirmed;
        * a reproduction with nothing held fixed is not an experiment;
        * evidence read off source text cannot be the whole case.
        """
        if self.confirmation_status == REFUTED:
            against = (self.contradicting_evidence[0].statement
                       if self.contradicting_evidence else "?")
            raise ValueError(
                f"{self.name} has contradicting evidence ({against}); a "
                f"reproduction cannot confirm a hypothesis that has already "
                f"been refuted -- withdraw the refutation explicitly or state "
                f"a different hypothesis")
        if not reproduction.held_fixed.strip():
            raise ValueError(
                f"{self.name} cannot be confirmed by a reproduction that names "
                f"nothing it held fixed: without that the two observations "
                f"differ in an unknown number of ways")
        if not any(item.is_measurement for item in self.supporting_evidence):
            raise ValueError(
                f"{self.name} has no supporting evidence that is a "
                f"measurement; a construct found in the source is consistent "
                f"with the hypothesis and does not establish it")
        self.confirmation_status = CONFIRMED
        self.confirmed_root_cause = root_cause
        self.reproduction = reproduction
        self.supporting_evidence.append(
            Evidence(reproduction.observed, FROM_REPRODUCTION))
        return self

    def refute(self, evidence: Evidence) -> "Hypothesis":
        """Record a measurement the hypothesis forbids."""
        self.contradicting_evidence.append(evidence)
        self.confirmation_status = REFUTED
        self.confirmed_root_cause = None
        return self

    # -- accumulating evidence without reaching a verdict ------------------
    def support(self, evidence: Evidence) -> "Hypothesis":
        self.supporting_evidence.append(evidence)
        if self.confirmation_status == UNTESTED:
            self.confirmation_status = NEEDS_MORE_EVIDENCE
        return self

    def needs_abaqus(self, why: str) -> "Hypothesis":
        if self.confirmation_status in (UNTESTED, NEEDS_MORE_EVIDENCE):
            self.confirmation_status = NEEDS_ABAQUS
            self.what_would_confirm = why or self.what_would_confirm
        return self

    @property
    def open(self) -> bool:
        return self.confirmation_status in _OPEN_STATUSES

    def as_dict(self) -> dict:
        return {
            "hypothesis": self.name,
            "claim": self.claim,
            "predicts": list(self.predicts),
            "supporting_evidence": [e.as_dict() for e in self.supporting_evidence],
            "contradicting_evidence": [e.as_dict()
                                       for e in self.contradicting_evidence],
            "confirmation_status": self.confirmation_status,
            "confirmed_root_cause": self.confirmed_root_cause,
            "reproduction": self.reproduction.as_dict() if self.reproduction else None,
            "what_would_confirm": self.what_would_confirm,
            "what_would_refute": self.what_would_refute,
        }


@dataclass
class Signature:
    """Every hypothesis raised for one disagreement, and where it stands."""

    magnitude: float = 0.0
    where: str = ""
    hypotheses: list = field(default_factory=list)
    #: Facts that stop the entry being evidence about the transform at all.
    #: Ten of the forty-two pass9 disagreements are the HelixUp family, and in
    #: every one of them the ORIGINAL build's own probe record goes non-finite
    #: at call 83 -- the author's code, on the deck we generated, returns NaN
    #: for all six stress components at increment 2. The transformed build gets
    #: there at call 73. Which of two builds reached NaN first is not a
    #: measurement of a transform, and no hypothesis below should be read as
    #: one while this list is non-empty.
    blocking_observations: list = field(default_factory=list)

    @property
    def confirmed(self) -> list:
        return [h for h in self.hypotheses
                if h.confirmation_status == CONFIRMED]

    @property
    def refuted(self) -> list:
        return [h for h in self.hypotheses if h.confirmation_status == REFUTED]

    @property
    def open(self) -> list:
        return [h for h in self.hypotheses if h.open]

    @property
    def informative(self) -> bool:
        """Can this entry carry a claim about the transform at all?"""
        return not self.blocking_observations

    @property
    def status(self) -> str:
        """The status of the entry: what is known, not what is suspected."""
        if self.blocking_observations:
            return NOT_EVIDENCE
        if self.confirmed:
            return CONFIRMED
        if not self.hypotheses:
            return UNTESTED
        if all(h.confirmation_status == REFUTED for h in self.hypotheses):
            return REFUTED
        if any(h.confirmation_status == NEEDS_ABAQUS for h in self.open):
            return NEEDS_ABAQUS
        return NEEDS_MORE_EVIDENCE

    def as_dict(self) -> dict:
        return {"magnitude": self.magnitude, "where": self.where,
                "status": self.status, "informative": self.informative,
                "blocking_observations": [e.as_dict()
                                          for e in self.blocking_observations],
                "hypotheses": [h.as_dict() for h in self.hypotheses]}


# ---------------------------------------------------------------------------
# thresholds, each one a statement about what a number can mean
# ---------------------------------------------------------------------------
#: Two values of opposite sign whose magnitudes agree this closely are not one
#: number computed twice. It raises a hypothesis; it settles nothing.
SIGN_FLIP_CLOSENESS = 0.25

#: One unit in the last place of a double, as a relative difference. A first
#: divergence at or below a few of these is what ROUND_OFF_GROWTH predicts.
LAST_PLACE = 2.3e-16

#: Single precision's epsilon. A first divergence near this, from bit-identical
#: inputs, is what REDUCED_PRECISION_INPUT predicts and round-off does not.
SINGLE_PRECISION_EPSILON = 1.2e-7

#: Constructs whose presence makes a mechanism possible. Searched in the
#: ORIGINAL source. Evidence from here is tagged FROM_SOURCE_TEXT and can
#: never be part of a confirmation.
_ITERATION = re.compile(
    r"newton|raphson|\bdo\s+while\b|\bconverg|\btoler|\bnitr\b|\bmaxit",
    re.IGNORECASE)
_BRANCH_ON_STATE = re.compile(
    r"IF\s*\([^)]*\b(STATEV|STRESS|DSTRAN)\b", re.IGNORECASE)
_FILE_IO = re.compile(r"^\s*(OPEN|READ)\s*\(", re.IGNORECASE | re.MULTILINE)
_SAVED = re.compile(r"^\s*(SAVE|COMMON)\b", re.IGNORECASE | re.MULTILINE)


# ---------------------------------------------------------------------------
# an untransformed actual argument at an OTI-typed dummy
# ---------------------------------------------------------------------------
#: The generated unit calls helpers whose dummies are declared by
#: ``implicit type(ONUMM<m>N<n>) (a-h,o-z)`` and ``implicit integer (i-n)``.
#: The caller's own untransformed variables are typed by ABA_PARAM.INC's
#: ``IMPLICIT REAL*8(A-H,O-Z)``. Where the transform leaves a variable
#: untransformed and still routes it into a helper, an 8-byte REAL is passed to
#: a dummy that is several times that size -- five doubles for ONUMM4N1 -- and
#: the callee's first store to it runs off the end of the caller's frame.
#: There is no explicit interface anywhere in the generated code, so neither
#: the compiler nor ``-check bounds`` says anything about it.
#:
#: Measured on ``RitioL/PolyFatigueCrackSim``: ``CALL LUDCMP_OTI(WORKST_OTI,
#: NSLPTL, ND, INDX, DDCMP)`` writes 40 bytes into the 8 that DDCMP occupies,
#: and that 32-byte overrun is the whole of the STATEV(25) corruption. Adding
#: ``TYPE(ONUMM4N1) :: DDCMP`` and changing nothing else repairs it at the
#: solver's own flags with vectorisation on.
_CALL_TO_A_HELPER = re.compile(r"\s*CALL\s+(\w+_OTI)\s*\((.*)\)\s*$",
                               re.IGNORECASE)
#: A name ABA_PARAM.INC types INTEGER. Its counterpart dummy is typed INTEGER
#: by the helper's own ``implicit integer (i-n)``, so the two agree.
_IMPLICIT_INTEGER = "IJKLMN"


@dataclass(frozen=True)
class MistypedArgument:
    """One actual argument whose type cannot match the dummy it reaches."""

    line: int
    callee: str
    position: int
    actual: str

    def describe(self) -> str:
        return (f"line {self.line}: {self.callee} receives {self.actual} at "
                f"argument {self.position}, which no declaration in the "
                f"generated unit gives an OTI type, so it is REAL*8 by "
                f"ABA_PARAM.INC while the dummy is the OTI derived type")


def _statements_of_fixed_form(source_text: str):
    """Fixed-form lines with their continuations joined, comments dropped.

    Yields ``(statement, line_number)`` where the line number is that of the
    statement's FIRST line, which is the one a traceback names.
    """
    statements: list = []
    numbers: list = []
    for index, line in enumerate(source_text.splitlines()):
        if not line.strip() or line[:1] in "Cc*!":
            continue
        body = line[6:] if len(line) > 6 else ""
        continued = len(line) > 5 and line[5] not in (" ", "0")
        if continued and statements:
            statements[-1] += body
        else:
            statements.append(body)
            numbers.append(index + 1)
    return list(zip(statements, numbers))


def _arguments_of(text: str) -> list:
    """Split an argument list on commas that are not inside a subscript."""
    out: list = []
    depth = 0
    current = ""
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            out.append(current.strip())
            current = ""
        else:
            current += character
    if current.strip():
        out.append(current.strip())
    return out


def mistyped_oti_arguments(source_text: str) -> list:
    """Actual arguments the generated unit hands to an OTI dummy untransformed.

    Source-text evidence, and only that: it says the construct is written, not
    that the call ran or that any output moved. Confirming one takes what
    confirmed DDCMP -- declare the variable with the callee's type, change
    nothing else, rebuild at the solver's flags, and see the output move.

    Deliberately conservative. An argument is reported only when it is a bare
    variable or array element whose name ABA_PARAM.INC types REAL, which the
    transform did not rename to ``_OTI``. Expressions are skipped, because an
    expression of OTI operands has the OTI type whatever its leading name
    looks like, and names in ``I``-``N`` are skipped, because the helper types
    those dummies INTEGER by the same first-letter rule and the two agree.
    """
    found: list = []
    for statement, number in _statements_of_fixed_form(source_text):
        match = _CALL_TO_A_HELPER.match(statement.strip())
        if match is None:
            continue
        callee = match.group(1).upper()
        for position, actual in enumerate(_arguments_of(match.group(2)), 1):
            name = re.match(r"([A-Za-z]\w*)", actual)
            if name is None:
                continue
            base = name.group(1).upper()
            if base.endswith("_OTI"):
                continue
            if base[0] in _IMPLICIT_INTEGER:
                continue
            if re.search(r"[-+*/]", actual):
                continue
            found.append(MistypedArgument(number, callee, position, actual))
    return found


# ---------------------------------------------------------------------------
# a constant the author wrote at single precision
# ---------------------------------------------------------------------------
#: ``1./3.`` is a quotient of two DEFAULT REAL literals, so Fortran evaluates
#: it in single precision and then widens the single-precision result. It is
#: not 1/3 to double precision: it is 0.3333333432674408, which differs from
#: 0.33333333333333331 by 9.93e-09 relative. ``ABA_PARAM.INC``'s
#: ``IMPLICIT REAL*8`` does not change this -- implicit typing types VARIABLES,
#: never literal constants -- and Abaqus does not compile user subroutines with
#: ``-r8``, so nothing rescues it.
#:
#: The transform re-emits these as ``1.0D0/3.0D0``. That is the more accurate
#: arithmetic, and it makes the transformed build disagree with the author's.
#: Measured on ``abuganza/UMAT_anisotropic_damage``: the author writes
#: ``sigmaiso(i) = sigmabar(i) - (1./3.)*tr_sigmabar`` for i=1,2,3 and nothing
#: of the kind for the shear components, so the promoted constant lands as one
#: common additive offset on exactly the three normal stresses.
#:
#: Only quotients whose value is not a dyadic rational matter. ``1./2.`` and
#: ``3./4.`` are exact in both precisions and are not reported.
_LITERAL_RATIO = re.compile(
    r"(?<![\dDdEe.])(\d+)\.(\d*)\s*/\s*(\d+)\.(\d*)(?![\dDdEe])")


def inexact_single_precision_literals(source_text: str) -> list:
    """Default-real literal quotients the author evaluates in single precision.

    Source-text evidence. It says the constant is written that way, not that
    the statement ran or that any output moved. Confirming one takes what
    confirmed the damage case: promote it in the ORIGINAL, change nothing
    else, and see the original reproduce the transformed build.
    """
    from fractions import Fraction

    found: list = []
    for match in _LITERAL_RATIO.finditer(source_text):
        numerator = f"{match.group(1)}.{match.group(2) or '0'}"
        denominator = f"{match.group(3)}.{match.group(4) or '0'}"
        try:
            value = Fraction(numerator) / Fraction(denominator)
        except ZeroDivisionError:
            continue
        # Exactly representable in binary iff the reduced denominator is a
        # power of two. Those agree in both precisions and are not evidence.
        if value.denominator & (value.denominator - 1):
            found.append(match.group(0))
    return found


def first_call_difference(original_history: list,
                          transformed_history: list) -> float:
    """The largest absolute output difference at the FIRST recorded call.

    The cheapest discriminator there is, and it needs no rebuild. A difference
    here cannot be the path, the solver or accumulated state: there is no path
    yet. Agreement here with disagreement later says the opposite -- whatever
    separated the builds did so through the history, and the entry's reported
    number is measured at inputs the two builds no longer share.

    Returns ``inf`` if either build's first record is not finite, and 0.0 if
    there is nothing to compare.
    """
    if not original_history or not transformed_history:
        return 0.0
    left, right = original_history[0], transformed_history[0]
    worst = 0.0
    for block in ("STRESS", "STATEV"):
        for x, y in zip(left.get(block) or (), right.get(block) or ()):
            if not (math.isfinite(x) and math.isfinite(y)):
                return math.inf
            worst = max(worst, abs(x - y))
    return worst



def _closeness(left: float, right: float) -> float:
    scale = max(abs(left), abs(right))
    return abs(abs(left) - abs(right)) / scale if scale else 0.0


def _where(at: Sequence) -> str:
    if len(at) >= 2:
        return f"record {at[0]}, component {at[1]}"
    return ""


# ---------------------------------------------------------------------------
# the hypotheses, each with what would settle it
# ---------------------------------------------------------------------------
def _iterative_solver() -> Hypothesis:
    return Hypothesis(
        ITERATIVE_SOLVER,
        claim="both builds solved the author's own iteration correctly and "
              "stopped at different iterates, because the residual was "
              "accumulated in a different order and crossed the author's "
              "tolerance on a different pass",
        predicts=(
            "the two builds take different numbers of passes through the "
            "author's loop for the same increment",
            "at the call where they part, EVERY output the loop writes has "
            "moved, not one of them",
            "the size of the move is about the author's own convergence "
            "tolerance, not about machine epsilon and not about 100%",
        ),
        what_would_confirm="instrument the author's loop to write its "
                           "iteration count and per-iteration residual norm, "
                           "run both builds on one increment from the same "
                           "recorded entry state, and show the counts differ "
                           "and the final residuals are both inside tolerance",
        what_would_refute="a call at which the two builds were handed "
                          "bit-identical arguments, took the same number of "
                          "equilibrium passes, and returned outputs that are "
                          "bit-identical except for a few components")


def _branch_divergence() -> Hypothesis:
    return Hypothesis(
        BRANCH_DIVERGENCE,
        claim="a conditional inside the routine tested a quantity that "
              "differed between the builds and sent them down different paths",
        predicts=(
            "the outputs written only on one side of the branch differ while "
            "those written on both sides agree",
            "the tested quantity is near the branch's threshold at the call "
            "where they part",
        ),
        what_would_confirm="record which branch each build took, per call, "
                           "and show they differ at the first divergent call "
                           "while the tested quantity sits within rounding of "
                           "the threshold",
        what_would_refute="the two builds returning bit-identical values for "
                          "every quantity the conditional tests")


def _single_output_slot() -> Hypothesis:
    return Hypothesis(
        SINGLE_OUTPUT_SLOT,
        claim="the transformed routine reproduces the call except for a small "
              "fixed set of output components, which are written with a value "
              "the arithmetic does not explain",
        predicts=(
            "at the first divergent call the inputs are bit-identical",
            "the great majority of outputs are bit-identical too",
            "the components that differ do so by far more than rounding, and "
            "are the same components at every point and every increment",
        ),
        what_would_confirm="show, over every recorded call, that the set of "
                           "differing output components is the same small set "
                           "and that the rest are bit-identical",
        what_would_refute="a first divergent call at which most outputs moved "
                          "by a similar small amount")


def _reduced_precision() -> Hypothesis:
    return Hypothesis(
        REDUCED_PRECISION_INPUT,
        claim="a constant, modulus or argument reaches the arithmetic at "
              "single precision in one build and double in the other",
        predicts=(
            "the first divergent call has bit-identical inputs",
            "its relative difference sits near single-precision epsilon, far "
            "above double rounding and far below a branch change",
            "the difference appears immediately, not after accumulation",
        ),
        what_would_confirm="find the constant or expression in the generated "
                           "source whose value differs from the original's at "
                           "single precision, and show that restoring it "
                           "removes the first-call difference",
        what_would_refute="a first-call difference at last-place rounding, or "
                          "one far larger than single-precision epsilon")


def _round_off_growth() -> Hypothesis:
    return Hypothesis(
        ROUND_OFF_GROWTH,
        claim="the two builds compute the same arithmetic in a different "
              "order, part at the last representable bit, and the reported "
              "difference is that parting amplified along the path",
        predicts=(
            "the first divergent call differs by about one unit in the last "
            "place of a double",
            "the difference grows along the history rather than arriving",
            "no output component moves by more than rounding at the first "
            "divergence",
        ),
        what_would_confirm="show the first divergence is at last-place "
                           "rounding AND that re-running the ORIGINAL build "
                           "with its own arithmetic reassociated moves the "
                           "history by a comparable amount -- the model's own "
                           "sensitivity, measured rather than assumed",
        what_would_refute="a first divergent call whose outputs differ by more "
                          "than a few units in the last place")


def _non_finite() -> Hypothesis:
    return Hypothesis(
        NON_FINITE,
        claim="the transformed build returned a value that is not a number, "
              "so the comparison established nothing about the model",
        predicts=("the probe records a non-finite output at a specific call",),
        what_would_confirm="locate the first call whose result is non-finite "
                           "and show its inputs were finite",
        what_would_refute="every recorded value being finite")


def _data_or_lifetime() -> Hypothesis:
    return Hypothesis(
        DATA_OR_LIFETIME,
        claim="the routine keeps something between calls -- a SAVE, a COMMON, "
              "a file read once -- and the two builds do not agree about when "
              "it is set",
        predicts=(
            "the two builds agree on the first call and part on a later one "
            "whose inputs are identical",
            "what differs is a quantity the routine reads rather than one it "
            "computes from its arguments",
        ),
        what_would_confirm="record the saved quantity at entry to every call "
                           "in both builds and show the first call at which "
                           "they differ is a call that did not re-read it",
        what_would_refute="the builds differing on their very first call")


def _different_function() -> Hypothesis:
    return Hypothesis(
        DIFFERENT_FUNCTION,
        claim="the transformed routine does not compute the author's function: "
              "given the same arguments it returns a materially different "
              "answer, and does so on the first call of the analysis",
        predicts=(
            "the first controlled call is the first call of the analysis",
            "most output components differ, by far more than rounding",
            "the difference does not need any history to appear",
        ),
        what_would_confirm="re-run one call of each build from the same "
                           "recorded entry state and show the outputs differ "
                           "by the same amounts, then locate the statement in "
                           "the generated source whose value differs",
        what_would_refute="agreement on the first call, with the difference "
                          "appearing only later")


def _near_zero() -> Hypothesis:
    return Hypothesis(
        NEAR_ZERO,
        claim="most of what was compared is too small a fraction of the "
              "response to carry a claim either way, so the reported number is "
              "about rounding in quantities that are not part of the answer",
        predicts=("more components are below the resolvable fraction than "
                  "above it",),
        what_would_confirm="a deck that makes those components part of the "
                           "response, and agreement or disagreement there",
        what_would_refute="the worst difference sitting in a component that is "
                          "a large fraction of the response")


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def classify(primal: dict, source_text: str = "",
             complete_increments: int = 0,
             isolation: Optional[Any] = None,
             iteration_counts_differ: Optional[int] = None) -> Signature:
    """Raise every hypothesis the evidence permits, and mark where each stands.

    ``isolation`` is a :class:`~umat_oti.abaqus.call_isolation.Isolation` --
    the controlled single-call comparison. Without it nothing can be refuted
    and nothing can be confirmed, and every hypothesis comes back open, because
    the summary numbers alone cannot tell these mechanisms apart. That is the
    point: the old version returned a confident name from exactly those
    numbers.
    """
    worst = float(primal.get("worst_stress_relative") or 0.0)
    state = float(primal.get("worst_state_relative") or 0.0)
    # A non-finite worst-case is not improved by the other field being
    # finite: max(inf, 1.29) is inf, and reporting 1.29 because the stress
    # column was the one that went to NaN would rank an entry whose stresses
    # are not numbers below one whose state moved by a percent.
    magnitude = (math.inf if not (math.isfinite(worst) and math.isfinite(state))
                 else max(worst, state))
    at = list(primal.get("worst_stress_at") or ())
    state_at = list(primal.get("worst_state_at") or ())

    signature = Signature(magnitude=magnitude, where=_where(at or state_at))
    raised: dict = {}

    def raise_(builder) -> Hypothesis:
        hypothesis = builder()
        raised[hypothesis.name] = hypothesis
        signature.hypotheses.append(hypothesis)
        return hypothesis

    # -- observations that stand on their own -----------------------------
    if primal.get("non_finite_components"):
        count = primal["non_finite_components"]
        raise_(_non_finite).support(Evidence(
            f"{count} compared values are not finite, so every comparison "
            f"against them is False and the run establishes nothing about the "
            f"model", FROM_PROBE))

    # -- sign flip raises two rival hypotheses, never one -----------------
    for label, row in (("stress", at), ("state", state_at)):
        if len(row) >= 4:
            left, right = float(row[2]), float(row[3])
            if left * right < 0 and _closeness(left, right) <= SIGN_FLIP_CLOSENESS:
                note = Evidence(
                    f"the worst {label} pair is {left:.6g} against "
                    f"{right:.6g}: opposite signs, magnitudes within "
                    f"{_closeness(left, right):.1%} of each other, which one "
                    f"number computed two ways does not produce",
                    FROM_PROBE)
                for builder in (_iterative_solver, _branch_divergence,
                                _single_output_slot):
                    if builder().name not in raised:
                        raise_(builder).support(note)
                    else:
                        raised[builder().name].support(note)
                break

    if source_text and _ITERATION.search(source_text):
        hypothesis = raised.get(ITERATIVE_SOLVER) or raise_(_iterative_solver)
        hypothesis.support(Evidence(
            "the source contains a convergence loop, so the mechanism is "
            "available to it -- this says the construct exists, not that it "
            "ran, and not that it ran differently", FROM_SOURCE_TEXT))
    if source_text and _BRANCH_ON_STATE.search(source_text):
        hypothesis = raised.get(BRANCH_DIVERGENCE) or raise_(_branch_divergence)
        hypothesis.support(Evidence(
            "the source branches on its own stress or state, so a difference "
            "below the branch could decide which way it goes", FROM_SOURCE_TEXT))
    if source_text and _FILE_IO.search(source_text) and _SAVED.search(source_text):
        raise_(_data_or_lifetime).support(Evidence(
            "the source reads a file and keeps what it read between calls",
            FROM_SOURCE_TEXT))

    unresolved = int(primal.get("unresolved_components") or 0)
    resolved = int(primal.get("resolved_components") or 0)
    if unresolved > resolved and magnitude > 0:
        raise_(_near_zero).support(Evidence(
            f"{unresolved} of {resolved + unresolved} components sit below "
            f"the resolvable fraction of the response", FROM_PROBE))

    # -- the controlled measurement ---------------------------------------
    if isolation is not None:
        _apply_isolation(signature, raised, raise_, isolation,
                         iteration_counts_differ)
    else:
        for hypothesis in signature.hypotheses:
            hypothesis.needs_abaqus(
                "no controlled single-call comparison was supplied; pair the "
                "two probe files with call_isolation.isolate_first_divergence "
                "before any of this is more than a guess")

    if not signature.hypotheses:
        signature.hypotheses.append(Hypothesis(
            UNCLASSIFIED,
            claim="no mechanism has been proposed for this disagreement",
            what_would_confirm="run call_isolation over the two probe files"))
    return signature


def _apply_isolation(signature: Signature, raised: dict, raise_,
                     isolation: Any,
                     iteration_counts_differ: Optional[int]) -> None:
    """Let the controlled call speak: it refutes, it never confirms alone."""
    from umat_oti.abaqus import call_isolation as ci

    verdict = getattr(isolation, "verdict", None)
    if verdict is None:                      # a plain dict from JSON
        verdict = isolation.get("verdict")
        beyond = isolation.get("output_slots_beyond_rounding") or []
        total = isolation.get("output_slots_total") or 0
        differing = isolation.get("output_slots_differing") or 0
        call_index = isolation.get("call_index")
        worst_input = isolation.get("worst_input_relative") or 0.0
    else:
        beyond = isolation.output_slots_beyond_rounding
        total = isolation.output_slots_total
        differing = isolation.output_slots_differing
        call_index = isolation.call_index
        worst_input = isolation.worst_input_relative

    if verdict == ci.INPUTS_ALREADY_DIVERGED:
        note = Evidence(
            f"at the first divergent call the two builds had already been "
            f"handed different arguments (worst {worst_input:.2e} of the "
            f"block's scale), so nothing this call did is attributable to the "
            f"routine", FROM_ISOLATION)
        for hypothesis in signature.hypotheses:
            hypothesis.support(note)
            hypothesis.needs_abaqus(
                "re-run one increment in both builds from the same recorded "
                "entry state, so the call is controlled")
        return
    if verdict != ci.SAME_INPUTS_DIFFERENT_OUTPUTS:
        for hypothesis in signature.hypotheses:
            hypothesis.needs_abaqus(
                f"the probe files could not be paired into controlled calls "
                f"({verdict})")
        return

    controlled = Evidence(
        f"at call {call_index} the two builds were handed arguments agreeing "
        f"to {worst_input:.2e} of their own scale -- the call is controlled",
        FROM_ISOLATION)
    fraction = (len(beyond) / total) if total else 0.0
    # SlotDifference carries `relative_to(scale)` as a method, not as an
    # attribute: reading it with getattr(slot, "relative_to_block_scale", 0.0)
    # returned the default for every object-shaped isolation, so every
    # refutation printed "0.000e+00" beside a slot it had just called "beyond
    # rounding", and the reduced-precision band -- which is a test on this very
    # number -- could never be entered.
    scales = ({} if isinstance(isolation, dict)
              else getattr(isolation, "scales", {}) or {})
    worst_output = 0.0
    for slot in beyond:
        if isinstance(slot, dict):
            value = slot.get("relative_to_block_scale") or 0.0
        else:
            value = slot.relative_to(scales.get(slot.block, 0.0))
        if value is None:
            value = 0.0
        if math.isfinite(value):
            worst_output = max(worst_output, value)
        else:
            worst_output = math.inf
            break

    # ITERATIVE_SOLVER predicts that every output the loop writes has moved
    # and that the builds took different numbers of passes. Two ways to lose.
    hypothesis = raised.get(ITERATIVE_SOLVER)
    if hypothesis is not None:
        hypothesis.support(controlled)
        if not beyond:
            hypothesis.refute(Evidence(
                f"at the first controlled call no output component differs by "
                f"more than rounding ({differing} of {total} differ at all, "
                f"none beyond it); a solve that stopped at a different iterate "
                f"would have moved its outputs by about its own convergence "
                f"tolerance, not by one unit in the last place",
                FROM_ISOLATION))
        elif fraction <= 0.25:
            hypothesis.refute(Evidence(
                f"at the first controlled call {len(beyond)} of {total} output "
                f"components differ beyond rounding and the other "
                f"{total - len(beyond)} are bit-identical; a different iterate "
                f"of one solve moves everything the solve writes",
                FROM_ISOLATION))
        if iteration_counts_differ == 0:
            hypothesis.refute(Evidence(
                "both builds took the same number of passes through the "
                "solver for every increment, which is the count this "
                "hypothesis says must differ", FROM_PROBE))

    # SINGLE_OUTPUT_SLOT predicts exactly the shape ITERATIVE_SOLVER forbids.
    # It also claims the moved components are wrong by far more than rounding,
    # and that half of it has to be tested too. From-2D-to-2D-Scallop,
    # From-3D-to-3D-SeaShell and Alex_Shocked/Growth-Alex each move three or
    # fewer of fifteen components at the first controlled call -- the right
    # SHAPE -- but by 1.1e-10, 6.9e-10 and 2.9e-10 of their field, which is
    # what a constant carried at the wrong precision looks like and not what a
    # destroyed slot looks like. Raising "one output slot corrupted" for them
    # put a strong claim on a marginal number, and the cut it sat just above
    # was a sorting threshold, not a finding.
    if beyond and fraction <= 0.25 and worst_output > SINGLE_PRECISION_EPSILON:
        hypothesis = raised.get(SINGLE_OUTPUT_SLOT) or raise_(_single_output_slot)
        hypothesis.support(controlled)
        named = ", ".join(
            f"{(s.get('block') if isinstance(s, dict) else s.block)}"
            f"({(s.get('fortran_index') if isinstance(s, dict) else s.fortran_index)})"
            for s in beyond[:6])
        hypothesis.support(Evidence(
            f"{len(beyond)} of {total} output components differ beyond "
            f"rounding at the first controlled call ({named}); the remaining "
            f"{total - len(beyond)} are bit-identical", FROM_ISOLATION))
        hypothesis.needs_abaqus(
            "re-run the same increment with the named component traced "
            "through the generated source, to show which statement writes it")

    # DIFFERENT_FUNCTION: most of the call moved, and it moved at call zero.
    if beyond and fraction > 0.25:
        hypothesis = raised.get(DIFFERENT_FUNCTION) or raise_(_different_function)
        hypothesis.support(controlled)
        hypothesis.support(Evidence(
            f"{len(beyond)} of {total} output components differ beyond "
            f"rounding at call {call_index}, the worst by {worst_output:.3e} "
            f"of its field", FROM_ISOLATION))
        if call_index == 0:
            hypothesis.support(Evidence(
                "and call 0 is the first call of the analysis, so no history "
                "had accumulated and no path can be responsible",
                FROM_ISOLATION))
        else:
            hypothesis.support(Evidence(
                f"though the first divergence is at call {call_index}, not at "
                f"the first call, so some accumulation preceded it",
                FROM_ISOLATION))
        hypothesis.needs_abaqus(
            "re-run one call of each build from the recorded entry state of "
            "this call and show the same two answers come back")

    # REDUCED_PRECISION predicts a first-call difference near single epsilon.
    if beyond and math.isfinite(worst_output) and \
            LAST_PLACE * 50 < worst_output < SINGLE_PRECISION_EPSILON * 50:
        hypothesis = raised.get(REDUCED_PRECISION_INPUT) or raise_(_reduced_precision)
        hypothesis.support(controlled)
        hypothesis.support(Evidence(
            f"the first controlled call differs by {worst_output:.3e} of the "
            f"field, which is {worst_output / SINGLE_PRECISION_EPSILON:.2g} "
            f"times single-precision epsilon and "
            f"{worst_output / LAST_PLACE:.2g} times a double's last place",
            FROM_ISOLATION))
        hypothesis.needs_abaqus(
            "compare the generated source's constants against the original's "
            "at both precisions, then re-run with the constant restored")

    # ROUND_OFF_GROWTH predicts nothing beyond rounding at the first call.
    hypothesis = raised.get(ROUND_OFF_GROWTH) or raise_(_round_off_growth)
    hypothesis.support(controlled)
    if beyond:
        hypothesis.refute(Evidence(
            f"the first controlled call already differs by {worst_output:.3e} "
            f"of the field in {len(beyond)} components, which is "
            f"{worst_output / LAST_PLACE:.3g} times a double's last place; "
            f"rounding does not start there", FROM_ISOLATION))
    else:
        hypothesis.support(Evidence(
            f"at the first controlled call {differing} of {total} components "
            f"differ and none by more than rounding", FROM_ISOLATION))
        hypothesis.needs_abaqus(
            "measure the ORIGINAL build's own sensitivity by reassociating "
            "its arithmetic: until that moves the history by a comparable "
            "amount, 'this is round-off' is an assumption, and it is never a "
            "reason to widen the tolerance")

    # NON_FINITE, if raised, is settled by where the first non-finite value is.
    hypothesis = raised.get(NON_FINITE)
    if hypothesis is not None and not math.isfinite(worst_output):
        hypothesis.support(Evidence(
            f"the first controlled call already returns a non-finite output "
            f"from finite, bit-identical inputs", FROM_ISOLATION))

    # DATA_OR_LIFETIME predicts agreement on the first call.
    hypothesis = raised.get(DATA_OR_LIFETIME)
    if hypothesis is not None and call_index == 0 and beyond:
        hypothesis.refute(Evidence(
            "the two builds already differ on the very first call of the "
            "analysis, before anything could have been saved between calls",
            FROM_ISOLATION))


@dataclass(frozen=True)
class RecordedConfirmation:
    """A reproduction that was performed, keyed to what it observed.

    A confirmation has to be re-checkable, not remembered. Each entry here
    names the exact output component and the exact two values a controlled
    call produced. It is applied only when a fresh isolation reproduces those
    values bit for bit -- so if the transform changes, or the deck changes, or
    the numbers move at all, the confirmation stops applying and the hypothesis
    goes back to open rather than standing on a note somebody wrote once.
    """

    hypothesis: str
    root_cause: str
    reproduction: Reproduction
    block: str
    fortran_index: int
    original: float
    transformed: float
    #: How many components the experiment saw move beyond rounding. The match
    #: requires the same count: "one slot of 154 moved" and "nine of twelve
    #: moved" are different findings and a confirmation of one must not stand
    #: in for the other.
    slots_beyond_rounding: int = 1

    @staticmethod
    def _same(left: float, right: float) -> bool:
        """Equality that a NaN can satisfy.

        The simplified_curing finding IS a NaN, and ``nan == nan`` is False:
        keyed on equality alone, the one confirmation built for a non-finite
        result could never match the measurement it was built from.
        """
        if math.isnan(left) and math.isnan(right):
            return True
        return left == right

    def matches(self, isolation) -> bool:
        beyond = (isolation.get("output_slots_beyond_rounding")
                  if isinstance(isolation, dict)
                  else isolation.output_slots_beyond_rounding) or []
        if len(beyond) != self.slots_beyond_rounding:
            return False
        for slot in beyond:
            block = slot.get("block") if isinstance(slot, dict) else slot.block
            index = (slot.get("fortran_index") if isinstance(slot, dict)
                     else slot.fortran_index)
            left = slot.get("original") if isinstance(slot, dict) else slot.original
            right = (slot.get("transformed") if isinstance(slot, dict)
                     else slot.transformed)
            if (block, index) == (self.block, self.fortran_index) and \
                    self._same(left, self.original) and \
                    self._same(right, self.transformed):
                return True
        return False


#: Confirmations performed against the pass9 probe records. Each was a
#: controlled comparison of two real Abaqus runs, not a re-reading of a summary.
CONFIRMED_FINDINGS: tuple = (
    RecordedConfirmation(
        hypothesis=SINGLE_OUTPUT_SLOT,
        root_cause=(
            "the generated unit passes an untransformed REAL*8 actual "
            "argument to an OTI-typed dummy, and the callee's store runs off "
            "the end of it. `CALL LUDCMP_OTI(WORKST_OTI, NSLPTL, ND, INDX, "
            "DDCMP)` passes DDCMP, which no declaration in the generated unit "
            "mentions and which ABA_PARAM.INC's IMPLICIT REAL*8(A-H,O-Z) "
            "therefore makes an 8-byte scalar. The callee declares its fifth "
            "dummy through `implicit type(ONUMM4N1) (a-h,o-z)`, so D is a "
            "40-byte derived type, and `D=1.0D0` at the top of LUDCMP_OTI "
            "writes 40 bytes into those 8. Every call overruns the caller's "
            "frame by 32 bytes. There is no explicit interface, so nothing "
            "diagnoses it. That is why the value moved with -auto, with "
            "-align array64byte, with -fstack-protector-strong, with -O1 and "
            "with -no-vec: each of those changes what occupies the 32 bytes "
            "after DDCMP, and none of them removes the write. CONFIRMED by "
            "repair: adding the single line `TYPE(ONUMM4N1) :: DDCMP` to the "
            "generated unit, changing nothing else and building at the "
            "solver's own flags with vectorisation ON, returns "
            "-73.4629074865463 in place of -1.6982275886200392e-30. The same "
            "unit audited for this class of mismatch shows one more instance, "
            "`CALL LUBKSB_OTI(..., DDGDDE(1,I))`, where DDGDDE is REAL*8 "
            "DDGDDE(ND,6) and the dummy is TYPE(ONUMM4N1) :: B(N): that one "
            "reads 60 doubles where 12 were written, which -init=snan,arrays "
            "catches as `forrtl: error (65): floating invalid` at that call. "
            "It is a real defect of the same class but it is NOT this "
            "corruption: patching that call out alone leaves STATEV(25) at "
            "-1.6982275886200392e-30. REFUTED along the way: this is not a "
            "compiler bug (the author's own source is clean under "
            "-init=snan,arrays and returns -73.46290748654624 under every "
            "build tried), and it is not the sequence association at "
            "CALL ITERATION_OTI(STATEV_OTI(NSLPTL+1), STATEV_OTI(2*NSLPTL+1), "
            "...) -- the author's original contains that same overlapping "
            "pair and compiles correctly, and `-assume dummy_aliases`, which "
            "is the flag that actually disables the no-alias assumption about "
            "dummy arguments, does not change the value"),
        reproduction=Reproduction(
            held_fixed=(
                "the deck, the element, the integration point, the increment "
                "and the entry state: at call 4 (element 1, point 1, "
                "increment 1, t=0) STRESS0 and STATEV0 are all zero in both "
                "builds and every other argument agrees to 1.07e-47 of its "
                "own scale; both builds took two solver passes in every one "
                "of the 140 increments, so the number of passes is held fixed "
                "as well"),
            varied="first only the build -- the author's source compiled "
                   "unchanged against the OTI-transformed source of the same "
                   "file -- and then, holding the build fixed at the solver's "
                   "own flags, exactly one line of the generated source: the "
                   "declaration `TYPE(ONUMM4N1) :: DDCMP`",
            observed=(
                "of 154 output components, 153 agree -- the four stresses to "
                "5.0e-17 of the stress field -- and exactly one does not: "
                "STATEV(25) is -73.46290748654624 in the original and "
                "-1.6982275886200392e-30 in the transformed build, a "
                "difference of 24.9% of the state field. Replayed offline "
                "from the recorded arguments of that call, the generated "
                "source reproduces -1.6982275886200392e-30 bit for bit; with "
                "the one declaration added and nothing else changed it "
                "returns -73.4629074865463, and it keeps returning it under "
                "-no-vec, -O1, -heap-arrays and -init=snan,arrays. The "
                "unrepaired source returns the right answer under -no-vec and "
                "the wrong one again under -no-vec -heap-arrays, which is "
                "what distinguishes a repair from a coincidence"),
            where="corpus_run/pass9/work/{0d97f9db648d23a064062989,"
                  "73bdb227267602e659445b72,71a0523bc387a9b773773a24}",
            repeatable=True),
        block="STATEV", fortran_index=25,
        original=-73.46290748654624,
        transformed=-1.6982275886200392e-30,
        slots_beyond_rounding=1),

    RecordedConfirmation(
        hypothesis=SINGLE_OUTPUT_SLOT,
        root_cause=(
            "the generated source calls the OTI helper ROTSIG_OTI, whose "
            "first dummy is declared TYPE(ONUMM3N1) :: S(NDI+NSHR), and "
            "passes it the REAL*8 array element statev(1): "
            "`call ROTSIG_OTI(statev(1), DROT_OTI, EELAS_OTI, 2, ndi, nshr)`. "
            "There is no explicit interface, so nothing catches it. The "
            "helper reads four consecutive doubles of the author's state "
            "array as one OTI number -- S(1)%R=statev(1), S(1)%E1=statev(2), "
            "S(1)%E2=statev(3), S(1)%E3=statev(4), S(2)%R=statev(5) -- and "
            "the rotated elastic strain written back into statev(1:ntens) "
            "therefore carries values from elsewhere in the state array. "
            "STATEV(3) comes back as 333.5668828923864, a stress-sized "
            "number, where the author's build has 6.660008321683725e-04, a "
            "strain. Distinguished from the crystal-plasticity defect by "
            "measurement: this one reproduces identically at -O0 and with "
            "-no-vec, so it is what the source says, not what the compiler "
            "made of it. Noted separately and NOT established: the "
            "transformed file also defines a harness-supplied ROTSIG, which "
            "the original file does not, so one build's user library carries "
            "a definition the other's does not. Which ROTSIG the transformed "
            "build actually calls depends on ELF interposition order and was "
            "not determined here"),
        reproduction=Reproduction(
            held_fixed=(
                "the deck, the element, the integration point and the entry "
                "state of call 8 (element 1, point 1, increment 2), which the "
                "two builds received bit-identically; and the optimisation "
                "level, varied from -O0 to the solver's own flags without "
                "changing the result"),
            varied="only the build: the author's source compiled unchanged "
                   "against the OTI-transformed source of the same file",
            observed=(
                "4 of 26 output components move beyond rounding and 22 do "
                "not; STATEV(3) is 6.660008321683725e-04 in the original and "
                "333.5668828923864 in the transformed build. Replayed "
                "offline from the recorded arguments the transformed source "
                "returns the same 333.5668828923864 at every optimisation "
                "level tried, so the difference is in the source and not in "
                "its compilation"),
            where="corpus_run/pass9/work/f425611a8d9036c13b6f1d58",
            repeatable=True),
        block="STATEV", fortran_index=3,
        original=0.0006660008321683725,
        transformed=333.5668828923864,
        slots_beyond_rounding=4),

    RecordedConfirmation(
        hypothesis=DIFFERENT_FUNCTION,
        root_cause=(
            "two independent faults meet at the first call. (1) The deck "
            "generated for this entry carries no *INITIAL CONDITIONS, "
            "TYPE=SOLUTION, USER, so Abaqus never calls the author's own "
            "SDVINI, and the degree of cure STATEV(1) starts at exactly 0 "
            "rather than at the 1.d-15 the author writes there with the "
            "comment 'Initial cure (small non-zero value)'. Zero is the "
            "singular point of the rate law. (2) The generated helper "
            "declares the author's `double precision K, Beta, n, m, TK, "
            "max_cure` as TYPE(ONUMM6N1), so `(cure/max_cure)**m` resolves to "
            "ONUMM6N1_POW_OO instead of ONUMM6N1_POW_OR. Measured side by "
            "side on the shipped module: q**0.4d0 returns R = 0.0 with NaN "
            "imaginary parts, and q**oti(0.4) returns R = NaN. The real part "
            "is lost in ONUMM6N1_F2EVAL, which forms `RES = RES + COEF*DX` "
            "with whole-number arithmetic where the one-argument FEVAL "
            "touches only the imaginary components: COEF is "
            "0.4*0**(-0.6) = +Inf, DX%R has just been set to 0, and Inf*0 is "
            "NaN in the real slot. The author's build survives the same deck "
            "because IEEE 0.0**0.4 is 0.0"),
        reproduction=Reproduction(
            held_fixed=(
                "the deck, the element, the integration point and every "
                "argument of call 0 -- the first UMAT call of the analysis -- "
                "which both builds received bit-identically with STRESS0, "
                "DSTRAN and STATEV0 all zero"),
            varied="only the build; and then, inside the transformed build, "
                   "only the declared type of the exponent",
            observed=(
                "the original returns STRESS = 0 in all six components and "
                "STATEV(3) = 1.2470275728981441E-02; the transformed build "
                "returns NaN in all six stresses and in STATEV(1), (2) and "
                "(4), with the same STATEV(3). Replayed offline from the "
                "recorded arguments the transformed source reproduces that "
                "exactly. Reducing it to the operation alone: with a real "
                "exponent the real part survives, with an OTI exponent it "
                "does not"),
            where="corpus_run/pass9/work/a3f970a8788b998cd2fef291",
            repeatable=True),
        block="STRESS", fortran_index=1,
        original=0.0, transformed=float("nan"),
        slots_beyond_rounding=9),
)



@dataclass(frozen=True)
class DiagnosedEntry:
    """One corpus entry taken to a confirmed root cause.

    Separate from ``RecordedConfirmation`` because these are not keyed to a
    single moved output slot. The crystal-plasticity finding is: one slot of
    154 moved. These two are not that shape -- one is a common offset across
    three components with nothing beyond rounding anywhere, and the other has
    the stress agreeing bit for bit while the tangent does not -- and forcing
    them into the slot-matching shape would record them as something they are
    not.
    """

    source: str
    hypothesis: str
    root_cause: str
    reproduction: Reproduction
    confirmation_status: str = CONFIRMED


#: Entries diagnosed offline, by replaying recorded calls. Every one names a
#: control that was actually run, not a construct that was read.
DIAGNOSED_ENTRIES: tuple = (
    DiagnosedEntry(
        source="abuganza__UMAT_anisotropic_damage/"
               "UMAT_Tissue_2d_plane_strain.f",
        hypothesis=REDUCED_PRECISION_INPUT,
        root_cause=(
            "the AUTHOR's constant is the single-precision one and the "
            "transform's is correct. The author writes "
            "`sigmaiso(i) = sigmabar(i) - (1./3.)*tr_sigmabar` for i=1,2,3. "
            "`1./3.` is a quotient of two DEFAULT REAL literals, so it is "
            "evaluated in single precision: 0.3333333432674408, not "
            "0.33333333333333331. ABA_PARAM.INC's IMPLICIT REAL*8 does not "
            "reach literal constants and Abaqus does not compile with -r8. "
            "The transform re-emits it as `(1.0D0/3.0D0)`. The difference "
            "between the two constants, 9.93e-09 relative, multiplies "
            "tr_sigmabar and lands as ONE COMMON ADDITIVE OFFSET on exactly "
            "the three normal stresses -- the shear component is assigned "
            "without the term and does not move. The offset is therefore "
            "proportional to tr_sigmabar, hence to mu0 = props(1), which is "
            "what the controlled sweep measured: doubling props(1) doubles "
            "the difference and none of the other nine props changes it. "
            "This entry is the transform being MORE accurate than the source, "
            "and the harness reporting the improvement as a disagreement"),
        reproduction=Reproduction(
            held_fixed="the recorded entry state of the first call of the "
                       "analysis, handed bit-identically to both builds, and "
                       "the compiler flags from the job's own .com",
            varied="one literal constant in the ORIGINAL source: `(1./3.)` "
                   "promoted to `(1.0D0/3.0D0)`, and nothing else",
            observed=(
                "as built, the two differ by 7.145e-11 on STRESS(1), (2) and "
                "(3) -- the same absolute offset on all three -- and by "
                "2.8e-16 on STRESS(4). With the one constant promoted, the "
                "ORIGINAL returns the TRANSFORMED build's STRESS(1) bit for "
                "bit; promoting `(-2./3.)` as well reproduces the transformed "
                "build bit for bit in every component. Promoting `(-2./3.)` "
                "ALONE changes nothing, so the carrier is the deviatoric "
                "projection and not the `detf**` exponent. The author's own "
                "model moves only 4.44e-15 when one ulp is added to its own "
                "input, which is 16000 times SMALLER than the difference, so "
                "this is not round-off and must not be recorded as round-off"),
            where="corpus_run/pass10/work/d08cead8f57af10c6eb7e138",
            repeatable=True)),

    DiagnosedEntry(
        source="Jeff97__General-shape-control-of-shell/Abaqus_Files/2Dto2D/"
               "From-2D-to-2D-Axe.for",
        hypothesis=ROUND_OFF_GROWTH,
        root_cause=(
            "the stress agrees bit for bit and the TANGENT does not, and the "
            "deck is conditioned so that the tangent amplifies the last bit "
            "by 3e+08. props are (EMOD, ENU) = (906512.0, 0.4995), and the "
            "source forms `D1 = SIX*(ONE-TWO*ENU)/EMOD`: 1 - 2*0.4995 is a "
            "cancellation leaving 0.001, so D1 = 6.6e-09 and the volumetric "
            "penalty 2/D1 is 3.0e+08. Replayed from the recorded entry state "
            "of the first call, the two builds return STRESS bit-identically "
            "in all six components and DDSDDE differing by 6.95e-07 of its "
            "own scale (210 on 3.03e+08) in 25 of 36 components. Abaqus "
            "steers Newton with DDSDDE, so the two builds converge to "
            "different displacement fields: at the very first CONVERGED "
            "record the solver already hands the two UMATs DSTRAN differing "
            "by 4.4e-07 relative -- the same order as the tangent difference. "
            "Every later record is therefore compared at inputs the two "
            "builds no longer share, and over 20 increments of a growth model "
            "that drift compounds into the reported 1.920e-04. The pass9 "
            "entry hid this behind a strain-driven experiment that never "
            "developed growth; the disagreement was always there"),
        reproduction=Reproduction(
            held_fixed="the recorded entry state, handed bit-identically to "
                       "both builds, and the job's own compiler flags",
            varied="only the build, and separately props(2) = ENU, to test "
                   "whether the difference tracks the 1/D1 amplification",
            observed=(
                "at the first call both builds return the same six stresses "
                "to the last bit while the tangent differs by 6.95e-07 of its "
                "scale. At record 99 (element 1, point 5, increment 20) the "
                "two RECORDED histories differ by 0.837 on STRESS(4), but "
                "replayed from one entry state the two builds differ by "
                "3.35e-08 and agree exactly on STRESS(4) -- seven orders of "
                "magnitude apart, which is the accumulation and not the call. "
                "Halving ENU raises D1 by 500 and drops the difference by the "
                "same factor, so the carrier is the volumetric penalty. The "
                "author's own model moves 6.72e-08 when ONE ULP is added to "
                "its own DFGRD1 at that call -- TWICE the whole transform "
                "difference -- so at this call the transform sits inside the "
                "model's own last-bit noise. That is a statement about this "
                "deck's conditioning and is NOT a reason to widen a tolerance"),
            where="corpus_run/pass10/work/d6c1a1095875c2d4007280d6",
            repeatable=True)),
)

def apply_recorded_confirmations(signature: Signature, isolation) -> Signature:
    """Mark a hypothesis confirmed when a recorded reproduction still matches.

    Confirmation is never inferred from the classification. It is applied only
    when the measurement in front of us is the measurement the experiment made.
    """
    for finding in CONFIRMED_FINDINGS:
        if not finding.matches(isolation):
            continue
        for hypothesis in signature.hypotheses:
            if hypothesis.name != finding.hypothesis:
                continue
            if hypothesis.confirmation_status == REFUTED:
                continue
            hypothesis.confirm(finding.root_cause, finding.reproduction)
    return signature


def review_entry(primal: dict, work_dir, source_text: str = "") -> Signature:
    """Classify one entry against the probe files its run left behind.

    This is the whole point of the restructuring in one function: the summary
    numbers raise the hypotheses, and the recorded calls decide which of them
    survive. An entry reviewed without its probe files comes back with every
    hypothesis open, which is the honest answer for it.

    Both isolations are used. The bit-level one establishes that the call was
    controlled -- that the solver handed both builds the same arguments -- and
    the material one finds where the routine first returned an answer that
    rounding cannot explain. Classifying on the bit-level one alone reports
    every entry in this corpus as round-off, because every entry's first
    difference of any kind is at the last place of the first call.
    """
    from umat_oti.abaqus import call_isolation as ci

    try:
        original, transformed = ci.read_pair(work_dir)
    except Exception as error:                     # pragma: no cover - I/O
        signature = classify(primal, source_text)
        for hypothesis in signature.hypotheses:
            hypothesis.needs_abaqus(
                f"the probe files could not be read ({type(error).__name__}), "
                f"so no call could be controlled")
        return signature
    if not original or not transformed:
        signature = classify(primal, source_text)
        for hypothesis in signature.hypotheses:
            hypothesis.needs_abaqus(
                "one of the builds left no probe records, so no call could be "
                "controlled")
        return signature

    left, right = ci.pair_calls(original), ci.pair_calls(transformed)
    counts_left, counts_right = ci.iteration_counts(left), ci.iteration_counts(right)
    differ = sum(1 for key in set(counts_left) | set(counts_right)
                 if counts_left.get(key, 0) != counts_right.get(key, 0))

    non_finite_original = ci.first_non_finite(left)
    non_finite_transformed = ci.first_non_finite(right)

    material = ci.isolate_first_divergence(original, transformed,
                                           require_beyond_rounding=True)
    any_bit = ci.isolate_first_divergence(original, transformed)
    chosen = material if material.verdict == ci.SAME_INPUTS_DIFFERENT_OUTPUTS \
        else any_bit

    signature = classify(primal, source_text, isolation=chosen,
                         iteration_counts_differ=differ)
    apply_recorded_confirmations(signature, chosen)
    beyond_at = (f"call {material.call_index}" if material.call_index >= 0
                 else "no call in the whole run")
    increments = len(set(counts_left) | set(counts_right))
    note = Evidence(
        f"the two builds first differ at all at call {any_bit.call_index} and "
        f"first differ beyond rounding at {beyond_at}; they took a different "
        f"number of solver passes in {differ} of {increments} increments",
        FROM_PROBE)
    for hypothesis in signature.hypotheses:
        hypothesis.supporting_evidence.append(note) \
            if hypothesis.confirmation_status != REFUTED else None

    if non_finite_original is not None:
        where = non_finite_original
        signature.blocking_observations.append(Evidence(
            f"the ORIGINAL build's own record goes non-finite first at call "
            f"{where['call_index']} ({where['block']} components "
            f"{where['components']}, increment {where['at']['increment']}), so "
            f"the reference this entry is measured against left its own "
            f"domain on this deck"
            + (f"; the transformed build reached the same state at call "
               f"{non_finite_transformed['call_index']}"
               if non_finite_transformed else "")
            + ". Which of two builds reaches NaN first is not a measurement "
              "of a transform, and this entry cannot support a claim about "
              "one until the deck keeps the author's model inside its domain",
            FROM_PROBE))
    return signature
