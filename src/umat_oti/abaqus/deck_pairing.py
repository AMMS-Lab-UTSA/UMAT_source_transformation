"""Which deck actually uses this UMAT, decided by evidence rather than distance.

A source and a deck are paired so that the verification can use material
constants the author published instead of numbers this harness invented. The
pairing used to be made by walking outward from the source file and taking the
first deck whose ``*USER MATERIAL, CONSTANTS=`` count did not contradict it.
Proximity is not evidence, and in this corpus it was wrong in ways that decided
results:

``mholla__growth/umats/umat_area_morph_Abaqus.f``
    paired with ``input_files/circle_pressure.inp``. That routine reads
    ``props(1:7)`` -- ``lam, mu, tmax, tau, n0(1:3)`` -- and writes
    ``statev(1:3)``. ``circle_pressure.inp`` publishes 9 constants and
    ``*Depvar 6``, and its README says in a table that it belongs to
    ``umat_area_stretch.f``. Driven with it, ``tau`` becomes ``props(4) = 0``
    and the growth factor is ``(tmax-1)*(1-exp(-time(2)/tau)) + 1`` -- a
    division by zero on the first call. The verdict that came back was "the
    model produced no numbers at any amplitude ... there is no loading here
    this harness can drive it at". The loading was never the problem.

``theysy__mml_subroutine_public/MML_U2/MML_U2.for``
    paired with ``MML_V2F/SHELL_GTN_NECK.inp``, a deck belonging to a
    different subroutine two directories away, from which no material was read
    at all. Its own directory holds ``MML_U2/SHELL_TCT_IM.inp``, whose
    ``*Shell Section`` names ``TR1180_HAH20_U2`` -- the routine's own name --
    with 40 constants and ``*Depvar 65``.

``Jeff97__.../Examples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for``
    paired with a deck from ``Examples-In-Section-3/ArcDown/Th001``, a
    different experiment in a different section of the paper. Its own
    directory holds ``Beam-PureGrowth.inp``.

So the pairing is made from what an author states, in this order:

1. **A table in the repository's README** that names an input file and a
   subroutine file on the same row. That is the author saying it outright.
2. **A shared file stem**: ``l1-is-1--l2-is-102.for`` and
   ``l1-is-1--l2-is-102-H0001.inp``; ``PureGrowth.for`` and
   ``Beam-PureGrowth.inp``.
3. **The step structure** the source's own clock demands. A routine that
   branches on ``TIME(2) .LE. 1.0 / .LE. 2.0 / .LE. 3.0`` is written for a
   three-step analysis, and a one-step deck is not the deck it belongs to.
4. **Its own directory**, as a tie-break between candidates that are already
   admissible -- never as evidence on its own.

And a candidate is ADMISSIBLE only if the material block can actually feed the
routine: at least as many constants as the highest ``PROPS(n)`` the routine
subscripts, and at least as many state variables as the highest ``STATEV(n)``.
A routine that subscripts PROPS only by literal numbers has STATED its own
NPROPS, and for those the count must match exactly -- which is what separates
``umat_iso_morph_Abaqus.f`` (4 constants, none published) from a deck with 9.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

_COMMENT = re.compile(r"^[cC*!]")
_LITERAL = re.compile(r"\b(PROPS|STATEV|STATE_VAR|STAT_VAR)\s*\(\s*(\d+)\s*\)",
                      re.IGNORECASE)
_VARIABLE = re.compile(
    r"\b(PROPS|STATEV|STATE_VAR|STAT_VAR)\s*\(\s*([A-Za-z_]\w*)\s*[,)]",
    re.IGNORECASE)
#: Names that are the array's own extent rather than an index into it.
_EXTENTS = {"NPROPS", "NSTATV", "NSTATEV", "NSTAT_VAR", "NSTATVS"}

_KEYWORD = re.compile(r"^\s*\*(?!\*)\s*([^,\n]+)(.*)$")
_PARAMETER = re.compile(r"([A-Za-z][\w \-]*)\s*=\s*([^,]+)")

#: A markdown or reStructuredText table row: cells separated by pipes.
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")

_DECK_SUFFIXES = (".inp", ".INP")
_SOURCE_SUFFIXES = (".f", ".for", ".f90", ".F", ".FOR", ".F90", ".f77")


def _code_lines(text: str) -> Iterable[str]:
    for line in (text or "").splitlines():
        if not line.strip() or _COMMENT.match(line) or line.lstrip().startswith("!"):
            continue
        yield line.split("!")[0]


# ---------------------------------------------------------------------------
# what the source demands of a material block
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Demand:
    """The material block this routine can be fed, in its own subscripts.

    ``nprops`` and ``nstatv`` are the highest literal subscripts the routine
    uses. ``props_exact`` says whether that number is the routine's whole
    NPROPS: a routine that never subscripts PROPS by a variable has named
    every constant it reads, so a block with a different count is a different
    material -- not merely a bigger one.
    """

    nprops: int = 0
    nstatv: int = 0
    props_exact: bool = False
    statev_exact: bool = False
    evidence: tuple[str, ...] = ()

    def admits(self, constants: int, depvar: int) -> tuple[bool, str]:
        """Can a block of this size feed this routine, and if not, why not?

        Three rules, and they are not symmetric, because over-supply and
        under-supply are different mistakes.

        *DEPVAR is a FLOOR.* Abaqus allocates what the deck asks for and a
        UMAT may leave some of it untouched; authors over-allocate routinely.
        ``l1-is-1--l2-is-101.for`` writes STATEV(1:9) and its own deck
        declares 10, and treating that as a mismatch would refuse the only
        material the repository publishes.

        *More constants than the routine names is a different material.* A
        routine that subscripts PROPS only by literal numbers has said what
        each constant is. ``umat_iso_morph_Abaqus.f`` reads
        ``lam, mu, tmax, tau`` and nothing else; ``circle_pressure.inp``
        publishes nine values whose third and fourth are ``0, 0``. Feeding
        them sets the growth time constant to zero, and
        ``exp(-time(2)/tau)`` divides by it on the first call. That is not a
        block with slack in it; it is another model's parameters.

        *Fewer constants than the routine reads is the author's own deck with
        a routine that over-reads.* ``MML_U2.for`` assigns ``Y18=PROPS(50)``
        unconditionally and its author's only deck publishes 40. Refusing it
        would discard the material; it is admitted, ranked below anything that
        supplies enough, and the range read past the end is named.
        """
        if depvar < self.nstatv:
            return False, (f"the routine subscripts STATEV({self.nstatv}) and "
                           f"this block declares only *DEPVAR {depvar}")
        if not constants:
            return False, ("this block states no usable constant count, so it "
                           "publishes no material")
        if self.props_exact and self.nprops and constants > self.nprops:
            return False, (f"the routine reads PROPS(1:{self.nprops}) by "
                           f"literal subscript and nothing else, so it names "
                           f"every constant it takes; this block publishes "
                           f"{constants}, which is a different parameterisation "
                           f"rather than the same one with slack")
        return True, ""

    def as_dict(self) -> dict:
        return {"nprops": self.nprops, "nstatv": self.nstatv,
                "props_exact": self.props_exact,
                "statev_exact": self.statev_exact,
                "evidence": list(self.evidence)}


def demanded(source_text: str) -> Demand:
    """What a material block has to carry for this routine to run.

    Measured on the eleven sources this module was written for: PureGrowth.for
    reads PROPS(1) and writes STATEV(9) and its deck publishes exactly 1 and 9;
    umat_iso_morph_Abaqus.f reads PROPS(1:4) and writes STATEV(1:3), and no
    deck in its repository publishes 4 constants; MML_U2.for reads PROPS(50)
    and its only deck publishes 40, which is recorded rather than hidden.
    """
    highest = {"PROPS": 0, "STATEV": 0}
    variable = {"PROPS": set(), "STATEV": set()}
    evidence: list[str] = []
    for line in _code_lines(source_text):
        for name, number in _LITERAL.findall(line):
            key = "PROPS" if name.upper() == "PROPS" else "STATEV"
            value = int(number)
            if value > highest[key]:
                highest[key] = value
                evidence.append(f"{key}({value}) at {line.strip()[:60]!r}")
        for name, subscript in _VARIABLE.findall(line):
            key = "PROPS" if name.upper() == "PROPS" else "STATEV"
            if subscript.upper() in _EXTENTS:
                continue
            variable[key].add(subscript.upper())
    return Demand(
        nprops=highest["PROPS"], nstatv=highest["STATEV"],
        props_exact=bool(highest["PROPS"]) and not variable["PROPS"],
        statev_exact=bool(highest["STATEV"]) and not variable["STATEV"],
        evidence=tuple(evidence[-4:]))


# ---------------------------------------------------------------------------
# how many stages the source's own clock has
# ---------------------------------------------------------------------------
_STAGE_TEST = re.compile(
    r"(?:TIME\s*\(\s*2\s*\)[^\n]*?)(?:\.LE\.|<=|\.LT\.|<)\s*"
    r"([0-9]+(?:\.[0-9]*)?)", re.IGNORECASE)


def declared_stages(source_text: str) -> tuple[float, ...]:
    """The TOTAL-time boundaries this routine branches its own law on.

    ``BodyForce-Growth-2Stages.for`` reads::

        IF ( (TIME(2)+DTIME) .LE. 1.0) THEN ...
        ELSE IF ( (TIME(2)+DTIME) .LE. 2.0) THEN ...
        ELSE IF ( (TIME(2)+DTIME) .LE. 3.0) THEN ...

    TIME(2) is the total time of the analysis, not the time within a step, so
    those three numbers are three steps of unit period. An experiment that
    stops at 0.34 never leaves the first of them.
    """
    found = sorted({float(value)
                    for value in _STAGE_TEST.findall(source_text or "")
                    if float(value) > 0.0})
    return tuple(found)


# ---------------------------------------------------------------------------
# what a deck publishes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DeckMaterial:
    """One ``*MATERIAL`` block of a deck, and what uses it."""

    deck: Path
    name: str
    constants: int
    depvar: int
    values: tuple[float, ...] = ()
    unsymmetric: bool = False
    elements: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    #: Whether a section line NAMES this material, as against the deck holding
    #: exactly one element type and the attribution being read off that. Seven
    #: materials are defined in ``MML_U2/SHELL_TCT_IM.inp`` and its
    #: ``*Shell Section`` names one of them; the other six are siblings.
    explicit: bool = False
    #: How many elements the deck declares. A deck with ONE is the author's
    #: own single-element test, which is the experiment this harness is trying
    #: to reconstruct -- ``harshaa765__Bilinear-CZM-UMAT`` publishes one and
    #: its README calls it "Single element patch test".
    element_count: int = 0
    #: The lowest element label the deck gives an element of this material's
    #: type. Normally nothing depends on it, but a UMAT is handed ``NOEL`` and
    #: some of the corpus indexes with it: ``irfancn/Abaqus-UEL-elastic``
    #: computes ``kelem = noel - 185`` because its own ``decoy`` elements are
    #: numbered 186 upward, and a deck that calls its one element 1 sends that
    #: routine reading at -184. Zero means the deck said nothing useful.
    first_element_label: int = 0
    steps: int = 0
    #: Whether any ``*STEP`` of this deck carries ``NLGEOM=YES``. The author
    #: saying the geometry is nonlinear is a statement about the problem, and
    #: a routine that never touches DFGRD can still be run in a step whose
    #: element formulation is finite-strain -- the cohesive patch test opens
    #: to half its own thickness and its author wrote ``nlgeom=YES``.
    nlgeom: bool = False
    step_periods: tuple[float, ...] = ()
    user_initial_state: bool = False

    def as_dict(self) -> dict:
        return {"deck": str(self.deck), "material": self.name,
                "constants": self.constants, "depvar": self.depvar,
                "unsymmetric": self.unsymmetric,
                "elements": list(self.elements),
                "sections": list(self.sections), "explicit": self.explicit,
                "element_count": self.element_count, "steps": self.steps,
                "first_element_label": self.first_element_label,
                "nlgeom": self.nlgeom,
                "step_periods": list(self.step_periods),
                "user_initial_state": self.user_initial_state}


def _parameters(remainder: str) -> dict:
    return {name.strip().upper().replace(" ", ""): value.strip()
            for name, value in _PARAMETER.findall(remainder or "")}


def _whole(value: str) -> int:
    """A count a deck states, or zero when it states something that is not one."""
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0


def _numbers(line: str) -> list[float]:
    out: list[float] = []
    for piece in line.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(float(piece.replace("D", "E").replace("d", "e")))
        except ValueError:
            return out
    return out


def materials_in(deck: Path, text: Optional[str] = None) -> tuple[DeckMaterial, ...]:
    """Every user material a deck publishes, with the elements that use it.

    Element types are resolved through the section keyword rather than by
    position, because a deck that defines several materials attaches each to
    its own element set -- and a UMAT driven on the wrong one is handed a
    tensor of the wrong size.
    """
    from umat_oti.abaqus.formulation import elements_by_material

    if text is None:
        try:
            text = Path(deck).read_text(errors="replace")
        except OSError:
            return ()
    lines = text.splitlines()

    found: list[DeckMaterial] = []
    steps = 0
    periods: list[float] = []
    name = ""
    depvar = 0
    constants = 0
    values: list[float] = []
    unsymm = False
    user_state = False
    mode = ""
    pending_static = False
    element_count = 0
    in_material = False
    element_block_type = ""
    #: The lowest label each ``*ELEMENT, TYPE=`` block numbers, so a material
    #: can be given the label its OWN element type starts at rather than the
    #: deck's first element, which in a mixed deck belongs to somebody else.
    lowest_label: dict = {}
    nlgeom = False

    attributions = elements_by_material(text)

    def flush() -> None:
        # ``in_material`` rather than ``name``: a *MATERIAL block that carries
        # no NAME= still publishes its constants, and those are the thing being
        # looked for. Dropping it refused a deck that names what the routine is
        # made of because the author left the label off.
        if in_material and constants:
            kinds, where = attributions.get(
                name.upper(), attributions.get("", ((), "")))
            found.append(DeckMaterial(
                deck=Path(deck), name=name, constants=constants, depvar=depvar,
                values=tuple(values[:constants]), unsymmetric=unsymm,
                elements=tuple(kinds), sections=(where,) if where else (),
                explicit=where.startswith("line ")))

    for raw in lines:
        line = raw.rstrip()
        if line.lstrip().startswith("**") or not line.strip():
            continue
        keyword_match = _KEYWORD.match(line)
        if keyword_match:
            keyword = "".join(keyword_match.group(1).split()).upper()
            parameters = _parameters(keyword_match.group(2))
            pending_static = False
            if keyword == "MATERIAL":
                flush()
                name = parameters.get("NAME", "")
                in_material = True
                depvar, constants, values, unsymm = 0, 0, [], False
                mode = ""
            elif keyword == "DEPVAR":
                mode = "depvar"
            elif keyword == "USERMATERIAL":
                # ``constants=?`` is what three mholla decks publish: a
                # template the author never filled in. It is not a count, and
                # reading it as one would attribute numbers to an author who
                # wrote a question mark.
                constants = _whole(parameters.get("CONSTANTS", ""))
                unsymm = "UNSYMM" in keyword_match.group(2).upper()
                mode = "props"
            elif keyword == "INITIALCONDITIONS":
                if parameters.get("TYPE", "").upper() == "SOLUTION":
                    user_state = user_state or (
                        "USER" in keyword_match.group(2).upper())
                mode = ""
            elif keyword == "ELEMENT":
                mode = "element"
                element_block_type = parameters.get("TYPE", "").upper()
            elif keyword == "STEP":
                steps += 1
                nlgeom = nlgeom or parameters.get("NLGEOM", "").upper() == "YES"
                mode = ""
            elif keyword in ("STATIC", "VISCO", "DYNAMIC",
                             "COUPLEDTEMPERATURE-DISPLACEMENT"):
                pending_static = True
                mode = ""
            else:
                mode = ""
            continue
        if pending_static:
            pending_static = False
            numbers = _numbers(line)
            if len(numbers) >= 2:
                periods.append(numbers[1])
            continue
        if mode == "element":
            head = line.split(",")[0].strip()
            if head.lstrip("-").isdigit():
                element_count += 1
                if element_block_type:
                    label = int(head)
                    lowest = lowest_label.get(element_block_type)
                    if lowest is None or label < lowest:
                        lowest_label[element_block_type] = label
            continue
        if mode == "depvar":
            numbers = _numbers(line)
            if numbers:
                depvar = int(numbers[0])
            else:
                depvar = _whole(line.split(",")[0])
            mode = ""
        elif mode == "props":
            values.extend(_numbers(line))
    flush()
    # The step count and the *INITIAL CONDITIONS keyword belong to the deck
    # rather than to any one material, and both are only known once the whole
    # file has been read -- so they are attached here rather than in flush().
    return tuple(
        DeckMaterial(deck=material.deck, name=material.name,
                     constants=material.constants, depvar=material.depvar,
                     values=material.values, unsymmetric=material.unsymmetric,
                     elements=material.elements, sections=material.sections,
                     explicit=material.explicit, element_count=element_count,
                     first_element_label=min(
                         (lowest_label[kind.upper()] for kind in material.elements
                          if kind.upper() in lowest_label), default=0),
                     steps=steps, step_periods=tuple(periods), nlgeom=nlgeom,
                     user_initial_state=user_state)
        for material in found)


# ---------------------------------------------------------------------------
# what the README says
# ---------------------------------------------------------------------------
def stated_pairs(repository: Path) -> dict[str, set[str]]:
    """Deck-to-source pairs the repository states in a table of its own.

    ``mholla__growth``'s README carries a two-column table headed "Input files"
    and "UMAT files" whose seventeen rows say exactly which deck runs with
    which subroutine. That is the strongest evidence available and it costs one
    regular expression to read.
    """
    pairs: dict[str, set[str]] = {}
    for readme in sorted(Path(repository).glob("*")):
        if not readme.is_file() or readme.suffix.lower() not in (
                ".md", ".rst", ".txt"):
            continue
        try:
            text = readme.read_text(errors="replace")
        except OSError:                            # pragma: no cover
            continue
        for raw in text.splitlines():
            row = _TABLE_ROW.match(raw)
            if not row:
                continue
            cells = [cell.strip().strip("`*") for cell in row.group(1).split("|")]
            decks = [cell for cell in cells if cell.lower().endswith(".inp")]
            sources = [cell for cell in cells
                       if any(cell.endswith(s) for s in _SOURCE_SUFFIXES)]
            for source in sources:
                pairs.setdefault(Path(source).name.lower(), set()).update(
                    Path(deck).name.lower() for deck in decks)
    return pairs


# ---------------------------------------------------------------------------
# the pairing itself
# ---------------------------------------------------------------------------
def _stem_tokens(name: str) -> set[str]:
    stem = Path(name).stem.lower()
    return {token for token in re.split(r"[^a-z0-9]+", stem) if token}


def _stem_affinity(source: Path, deck: Path) -> tuple[int, str]:
    """How strongly two file names say they belong together.

    The source's own DIRECTORY name counts as one of its names. Two of the
    Jeff97 growth sources live in ``PathSensitivity/Th001-1MPa`` and
    ``PathSensitivity/Th001-5MPa`` with no deck beside them, and the decks
    they belong to are called ``Beam-Gravity-Growth-C0-1MPa.inp`` and
    ``Beam-Gravity-Growth-C0-5MPa.inp``. The file stems share nothing; the
    directory names share the constant the author varied.
    """
    best = (0, "")
    for candidate in (Path(source), Path(source).parent):
        score = _one_stem_affinity(candidate, deck)
        if score[0] > best[0]:
            best = score
    return best


def _one_stem_affinity(source: Path, deck: Path) -> tuple[int, str]:
    source_stem = Path(source).stem.lower()
    deck_stem = Path(deck).stem.lower()
    if source_stem and (deck_stem.startswith(source_stem)
                        or deck_stem.endswith(source_stem)):
        return 3, (f"the deck's name {Path(deck).name!r} contains the whole of "
                   f"the source's stem {source_stem!r}")
    if source_stem and source_stem in deck_stem:
        return 2, (f"the deck's name {Path(deck).name!r} contains the source's "
                   f"stem {source_stem!r}")
    shared = _stem_tokens(source) & _stem_tokens(deck)
    shared -= {"inp", "for", "f", "umat", "abaqus", "beam", "job", "model"}
    # A shared token with a digit in it names a QUANTITY -- ``1mpa``,
    # ``th001``, ``l2is102`` -- and two files that agree on one agree about
    # the author's parameter. A shared word like ``growth`` names a kind, and
    # every deck of that kind shares it.
    numeric = {token for token in shared if any(ch.isdigit() for ch in token)}
    if numeric:
        return 2, (f"the two names agree on {', '.join(sorted(numeric))}, "
                   f"which is a value the author varied rather than a word "
                   f"every file of this kind carries")
    if shared:
        return 1, (f"the two names share {', '.join(sorted(shared))}")
    return 0, ""


#: ``NAME = PROPS(n)``, which is a routine saying what its n-th constant is.
#: The name keeps its own literal subscript, because an array element is a
#: different constant from its siblings. ``xn0(1) = props(5)`` in one routine
#: and ``xn0(3) = props(5)`` in another are not the same constant, and reading
#: both as "XN0" said two routines agreed about a fibre direction when they
#: had it in different slots.
_NAMED_PROP = re.compile(
    r"^\s*(?:\d+\s+)?([A-Za-z_]\w*(?:\s*\(\s*\d+\s*\))?)\s*=\s*"
    r"PROPS\s*\(\s*(\d+)\s*\)\s*$", re.IGNORECASE)


def named_constants(source_text: str) -> dict[int, str]:
    """What this routine calls each of its constants, by position.

    ``lam = props(1)``, ``tau = props(4)``, ``xn0(1) = props(5)``. A routine
    that names its constants has documented its own material block, and two
    routines that name the same constants in the same order take the same
    block.
    """
    found: dict[int, str] = {}
    for line in _code_lines(source_text):
        match = _NAMED_PROP.match(line.split("!")[0])
        if match:
            found.setdefault(int(match.group(2)),
                             "".join(match.group(1).split()).upper())
    return found


def sibling_constants(source: Path, repository: Path,
                      source_text: str) -> str:
    """What a near-namesake of this source reads, and where the two diverge.

    A refusal that says "no published block fits" is right and not yet
    useful. ``umat_area_morph_Abaqus.f`` reads seven constants and no deck
    publishes seven -- but its sibling ``umat_area_morph.f`` sits in the same
    directory, this repository's README pairs it with ``sheet_noload.inp``,
    and the two routines agree on ``lam = props(1)`` and ``mu = props(2)``
    and diverge from the third. So what is missing is not a material: it is
    two numbers, ``tmax`` and ``tau``, and this says which.
    """
    mine = named_constants(source_text)
    if not mine:
        return ""
    stem = Path(source).stem.lower()
    notes: list[str] = []
    for other in sorted(Path(source).parent.glob("*")):
        if other == Path(source) or other.suffix not in _SOURCE_SUFFIXES:
            continue
        theirs_stem = other.stem.lower()
        if not (stem.startswith(theirs_stem) or theirs_stem.startswith(stem)):
            continue
        try:
            theirs = named_constants(other.read_text(errors="replace"))
        except OSError:                            # pragma: no cover
            continue
        if not theirs:
            continue
        shared = sorted(index for index in set(mine) & set(theirs)
                        if mine[index] == theirs[index])
        only_mine = sorted(index for index in mine
                           if index not in shared)
        if not shared:
            continue
        notes.append(
            f"its near-namesake {other.name} reads "
            f"PROPS(1:{max(theirs)}) and agrees with this routine on "
            + ", ".join(f"PROPS({index})={mine[index]}" for index in shared[:6])
            + (f"; what this routine reads and that one does not is "
               + ", ".join(f"PROPS({index})={mine[index]}"
                           for index in only_mine[:6])
               if only_mine else ""))
    if not notes:
        return ""
    return (". The constants are not all unpublished: " + "; ".join(notes[:2])
            + ". A block for this routine would be that one's values with "
              "those positions filled in, and nobody has published them")


@dataclass(frozen=True)
class Pairing:
    """The deck a verification reads its material from, and why that one."""

    material: Optional[DeckMaterial] = None
    demand: Demand = field(default_factory=Demand)
    why: str = ""
    refusal: str = ""
    rejected: tuple[tuple[str, str], ...] = ()
    alternatives: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    #: Where the search went and what it found there. A refusal is a statement
    #: about this pipeline until it says where it looked -- the pattern
    #: ``where_we_looked()`` in the verification tool already sets -- so the
    #: scan is recorded rather than the negative asserted.
    searched: dict = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.material is not None

    def as_dict(self) -> dict:
        return {"material": self.material.as_dict() if self.material else None,
                "demand": self.demand.as_dict(), "why": self.why,
                "refusal": self.refusal,
                "rejected": [list(pair) for pair in self.rejected],
                "alternatives": list(self.alternatives),
                "warnings": list(self.warnings),
                "searched": dict(self.searched)}


def _where_we_looked(repository: Path, decks: Sequence[Path],
                     materials: Sequence[DeckMaterial],
                     demand: Demand) -> dict:
    """Every place a material block was looked for, and what was in it.

    Named the way the verification tool names it, and carrying the same three
    things: which repository, how many files were opened, and what each one
    published. The counts are what make the refusal checkable -- a reader who
    doubts "no material published here can feed this routine" can compare the
    listed constant counts against the demand without opening anything.
    """
    published = sorted({material.constants for material in materials
                        if material.constants})
    return {
        "repository": str(repository),
        "decks_scanned": len(decks),
        "decks": [str(Path(deck).relative_to(repository)) for deck in decks][:40],
        "decks_not_listed": max(0, len(decks) - 40),
        "material_blocks_found": len(materials),
        "constant_counts_published": published,
        "depvar_counts_published": sorted({material.depvar
                                           for material in materials}),
        "expected_nprops": demand.nprops,
        "expected_nstatv": demand.nstatv,
        "nprops_is_exact": demand.props_exact,
        "scanner": "umat_oti.abaqus.deck_pairing.pair",
        "documentation": ("every *.md, *.rst and *.txt in the repository was "
                          "read for a table naming this source file beside an "
                          "input file"),
    }


#: Materials already read out of a repository, so that a run pairing every
#: source in one repository reads its decks once rather than once per source.
#: Keyed by the repository path and the (name, size, mtime) of every deck in
#: it, so a changed or added deck invalidates it rather than being missed.
_SCANNED: dict = {}


def _fingerprint(decks: Sequence[Path]) -> tuple:
    out = []
    for deck in decks:
        try:
            stat = deck.stat()
        except OSError:                            # pragma: no cover
            continue
        out.append((str(deck), stat.st_size, int(stat.st_mtime)))
    return tuple(out)


def candidates(source: Path, repository: Path,
               limit: int = 4000) -> tuple[DeckMaterial, ...]:
    """Every user material published anywhere in this source's repository."""
    decks = sorted(deck for deck in Path(repository).rglob("*")
                   if deck.is_file() and deck.suffix in _DECK_SUFFIXES)
    key = (str(repository), _fingerprint(decks))
    cached = _SCANNED.get(key)
    if cached is not None:
        return cached
    found: list[DeckMaterial] = []
    for deck in decks:
        found.extend(materials_in(deck))
        if len(found) > limit:                     # pragma: no cover - guard
            break
    answer = tuple(found)
    if len(_SCANNED) > 8:                          # pragma: no cover - bound
        _SCANNED.clear()
    _SCANNED[key] = answer
    return answer


def pair(source: Path, repository: Path,
         source_text: Optional[str] = None,
         pool: Optional[Sequence[DeckMaterial]] = None) -> Pairing:
    """The deck that actually uses this UMAT, or a refusal saying why none does.

    The refusal matters as much as the pairing. Three mholla ``_Abaqus``
    growth routines were reported as "this harness generated no experiment
    this source will run" when what had actually happened is that no deck in
    their repository publishes the constants they read, and the deck they were
    handed set their growth time constant to zero.
    """
    source = Path(source)
    if source_text is None:
        try:
            source_text = source.read_text(errors="replace")
        except OSError:                            # pragma: no cover
            source_text = ""
    demand = demanded(source_text)
    stages = declared_stages(source_text)
    materials = tuple(pool) if pool is not None else candidates(source, repository)
    decks = sorted({material.deck for material in materials}) if pool is not None \
        else sorted(deck for deck in Path(repository).rglob("*")
                    if deck.is_file() and deck.suffix in _DECK_SUFFIXES)
    searched = _where_we_looked(Path(repository), decks, materials, demand)
    if not materials:
        return Pairing(demand=demand, searched=searched,
                       refusal=(f"{Path(repository).name} publishes no deck "
                                f"with a *USER MATERIAL block, so there is "
                                f"nothing here that says what this routine is "
                                f"made of. Searched {len(decks)} .inp file(s) "
                                f"in {repository}, and every .md, .rst and "
                                f".txt in it for a table naming this source"))

    stated = stated_pairs(repository)
    named = stated.get(source.name.lower(), set())

    # A routine that reads COORDS is a routine whose answer depends on the
    # mesh it is run on, and the constants it hard-codes say which mesh. Only
    # computed for those: for every other source the geometry of the deck says
    # nothing about whether the material is its own.
    from umat_oti.abaqus.coordinate_domain import (geometry_agreement,
                                                   reads_coordinates)
    positional = reads_coordinates(source_text)
    geometry_cache: dict = {}

    def geometry_of(deck: Path) -> tuple[int, str]:
        if not positional:
            return 0, ""
        if deck not in geometry_cache:
            try:
                geometry_cache[deck] = geometry_agreement(
                    source_text, deck.read_text(errors="replace"))
            except OSError:                        # pragma: no cover
                geometry_cache[deck] = (0, "")
        return geometry_cache[deck]

    scored: list[tuple[tuple, DeckMaterial, list[str]]] = []
    rejected: list[tuple[str, str]] = []
    for material in materials:
        ok, why_not = demand.admits(material.constants, material.depvar)
        surplus = ""
        if not ok and material.constants > demand.nprops and material.depvar >= demand.nstatv:
            # Over-supply is re-admitted on the same naming evidence that
            # re-admits under-supply, and for the same reason: a block in the
            # source's own directory is the author's material even when it
            # publishes one constant the code does not reach.
            # ``notched_plate_CZM_random_mesh_shear.inp`` publishes twelve and
            # its czmHealing.f reads eleven -- because the twelfth,
            # ``Eps_crit = PROPS(12)``, is commented out and hard-coded to
            # -1e-15 instead. The source's own header still lists it:
            # ``PROPS={Kplus,...,mu,Eps_crit}``. Rejecting that deck sent the
            # routine to a deck in a different benchmark directory.
            if (material.deck.name.lower() in named
                    or material.deck.parent == source.parent
                    or _stem_affinity(source, material.deck)[0] >= 2):
                ok = True
                surplus = (f"this block publishes {material.constants} "
                           f"constants and the routine's literal subscripts "
                           f"reach PROPS({demand.nprops}); the extra "
                           f"{material.constants - demand.nprops} are read by "
                           f"Abaqus and not by the routine")
        if not ok:
            rejected.append((f"{material.deck.name}:{material.name}", why_not))
            continue
        reasons: list[str] = []
        if surplus:
            reasons.append(surplus)
        by_readme = 1 if material.deck.name.lower() in named else 0
        if by_readme:
            reasons.append(f"{Path(repository).name}'s README states that "
                           f"{material.deck.name} runs with {source.name}")
        # A routine that reads past the end of the block is admitted only
        # where something NAMES the block as its own, and ranked below
        # anything that supplies enough. Without that it is a different
        # material with a plausible size: ``cube_1_C3D8_noload.inp`` publishes
        # six constants and ``umat_area_morph_Abaqus.f`` reads seven, and the
        # seventh -- a fibre-direction component -- would be whatever lies
        # past the end of the array.
        supplied = 0 if material.constants < demand.nprops else 1
        # A block a *SECTION actually names is the material the author ran;
        # one merely defined beside it is a sibling. Seven materials are
        # defined in MML_U2/SHELL_TCT_IM.inp and its *Shell Section names one.
        attached = 2 if material.explicit else (1 if material.elements else 0)
        # The author's own single-element test IS the experiment this harness
        # builds. Where one exists it outranks a benchmark of the same
        # material: ``harshaa765__Bilinear-CZM-UMAT`` publishes both a DCB and
        # a one-element patch test, and the patch test is the verification.
        single = 1 if material.element_count == 1 else 0
        if single:
            reasons.append(f"{material.deck.name} declares exactly one "
                           f"element, so it is the author's own "
                           f"single-element test of this material")
        if attached:
            reasons.append(f"a section in {material.deck.name} attaches "
                           f"{material.name} to "
                           f"{', '.join(material.elements)}")
        affinity, affinity_why = _stem_affinity(source, material.deck)
        named_affinity, named_why = _stem_affinity(source, Path(material.name))
        if named_affinity > affinity:
            affinity, affinity_why = named_affinity, (
                f"the material is called {material.name!r}, which carries the "
                f"source's own name")
        if affinity_why:
            reasons.append(affinity_why)
        # A routine that branches its law on N total-time boundaries is
        # written for N steps. A deck with a different count is a different
        # experiment, however close it sits on disk.
        by_stages = 0
        if stages and material.steps:
            if material.steps == len(stages):
                by_stages = 2
                reasons.append(
                    f"the routine branches on {len(stages)} total-time "
                    f"boundaries ({', '.join(f'{s:g}' for s in stages)}) and "
                    f"this deck runs {material.steps} steps")
            else:
                by_stages = -1
                reasons.append(
                    f"the routine branches on {len(stages)} total-time "
                    f"boundaries and this deck runs {material.steps} steps")
        same_directory = 1 if material.deck.parent == source.parent else 0
        if same_directory:
            reasons.append("the deck sits in the source's own directory")
        # Tightest fit last: among equals, the block that publishes exactly
        # what the routine reads is likelier to be its own, and among decks
        # whose names are equally close the SHORTER name is the base variant
        # rather than a mesh study of it -- ``l1-is-1--l2-is-11-H0001.inp``
        # rather than ``l1-is-1--l2-is-11-H0001-M15.inp``.
        slack = abs(material.constants - demand.nprops)
        # Naming evidence, in any of the forms an author leaves it: the
        # README, a file stem that contains the source's, or a block sitting
        # in the source's own directory whose material name carries the
        # source's own token (``MML_U2.for`` beside a section naming
        # ``TR1180_HAH20_U2``).
        named_as_ours = bool(by_readme) or affinity >= 2 or (
            same_directory and affinity >= 1)
        if not supplied and not named_as_ours:
            rejected.append((
                f"{material.deck.name}:{material.name}",
                f"the routine assigns from PROPS({material.constants + 1}:"
                f"{demand.nprops}) and this block publishes "
                f"{material.constants} constants, and nothing in the "
                f"repository names it as this routine's material -- so the "
                f"values past the end would be whatever the array happens to "
                f"be followed by, not constants an author published"))
            continue
        # Order matters and was once wrong. The step structure used to rank
        # ABOVE the source's own directory, and it moved
        # ``ParabolicDown/Th002/BodyForce-Growth-2Stages.for`` onto an ArcUp
        # deck two directories away: the routine branches at total times 1, 2
        # and 3, and the author's own ParabolicDown deck runs only two steps.
        # That is the author saying their experiment stopped before the third
        # branch, not evidence that the deck beside the source is somebody
        # else's. A deck in the source's own directory outranks it.
        scored.append(((by_readme, supplied, single, affinity, attached,
                        same_directory, by_stages, -slack,
                        -len(material.deck.name)),
                       material, reasons))

    if not scored:
        detail = "; ".join(f"{where}: {why}" for where, why in rejected[:6])
        counts = ", ".join(str(count) for count
                           in searched["constant_counts_published"]) or "none"
        return Pairing(
            demand=demand, rejected=tuple(rejected), searched=searched,
            refusal=(f"no material published in {Path(repository).name} can "
                     f"feed this routine. It reads PROPS(1:{demand.nprops}) "
                     f"and writes STATEV(1:{demand.nstatv}). Searched: "
                     f"{searched['decks_scanned']} .inp file(s) in "
                     f"{repository}, carrying {searched['material_blocks_found']}"
                     f" *USER MATERIAL block(s) whose constant counts are "
                     f"{counts}; and every .md, .rst and .txt in the "
                     f"repository for a table naming this source beside an "
                     f"input file. Every block was rejected: {detail}"
                     + sibling_constants(source, Path(repository), source_text)
                     + ". Supplying constants from anywhere else would be "
                       "inventing them"))

    # A block in the source's OWN directory that was rejected outright is a
    # finding about the author's own deck, and reaching past it into another
    # directory buries it. ``Benchmarks/Notched_plate_shear/czmHealing.f``
    # writes STATEV(13) and the deck beside it declares ``*Depvar 12``, which
    # is a write past the end of the array Abaqus allocates; the only other
    # admissible block in that repository belongs to a different benchmark
    # with a different toughness. Running the second in place of the first
    # would verify one experiment's routine against another's material and
    # hide a defect in the author's deck behind it.
    beside_it = [material for material in materials
                 if material.deck.parent == source.parent]
    rejected_names = {where for where, _why in rejected}
    if beside_it and all(f"{material.deck.name}:{material.name}"
                         in rejected_names for material in beside_it):
        if not any(material.deck.parent == source.parent
                   for _key, material, _why in scored):
            detail = "; ".join(f"{where}: {why}" for where, why in rejected
                               if where in {f"{m.deck.name}:{m.name}"
                                            for m in beside_it})[:600]
            return Pairing(
                demand=demand, rejected=tuple(rejected), searched=searched,
                refusal=(f"the deck beside this source publishes a material "
                         f"this routine cannot be run with, and the only "
                         f"blocks that fit belong to other directories of "
                         f"{Path(repository).name}. Beside it: {detail}. "
                         f"Using another experiment's constants would verify "
                         f"this routine against a material its author did not "
                         f"give it, and would bury what is wrong with the "
                         f"deck its author did"))

    scored.sort(key=lambda item: item[0], reverse=True)
    best_key = scored[0][0]
    level = [(material, why) for key, material, why in scored if key == best_key]
    # Geometry breaks ties and nothing else. Reading the node box of every
    # deck in a repository that publishes seven hundred of them costs more
    # than the whole pairing; reading it for the handful that are otherwise
    # indistinguishable costs nothing, and those are the only ones where the
    # mesh's shape can decide anything.
    if positional and len(level) > 1:
        ranked = []
        for material, why in level:
            score, geometry_why = geometry_of(material.deck)
            ranked.append((score, material, why, geometry_why))
        ranked.sort(key=lambda item: item[0], reverse=True)
        top = ranked[0][0]
        level = [(material, why + ([f"the constants this routine hard-codes "
                                    f"account for this mesh: {geometry_why}"]
                                   if geometry_why and score == top else []))
                 for score, material, why, geometry_why in ranked
                 if score == top]
    best, reasons = level[0]
    tied = [material for material, _ in level]
    warnings: list[str] = []
    if demand.nprops > best.constants:
        warnings.append(
            f"the routine assigns from PROPS({best.constants + 1}:"
            f"{demand.nprops}) and {best.name} publishes {best.constants} "
            f"constants, so those reads go past the end of the array the "
            f"author's deck allocates. Whatever they return is not a material "
            f"constant, and a difference between two builds in a quantity that "
            f"depends on them is not a difference about this material")
    if demand.props_exact and best.constants > demand.nprops:
        warnings.append(
            f"the routine's literal subscripts reach PROPS({demand.nprops}) "
            f"and {best.name} publishes {best.constants}. The surplus is "
            f"accepted because this block is named as this routine's; a "
            f"constant the routine never reads cannot change what it computes, "
            f"but NPROPS does, so both builds are handed the same "
            f"{best.constants}")
    if not demand.props_exact and best.constants > demand.nprops:
        warnings.append(
            f"the routine's highest literal subscript is PROPS({demand.nprops}) "
            f"and it also indexes PROPS by a variable, so the {best.constants} "
            f"constants of {best.name} are taken on the deck's word")
    if positional:
        score, detail = geometry_of(best.deck)
        box_axes = 3
        if score < box_axes and detail:
            warnings.append(
                f"this routine reads COORDS, so the mesh it runs on is part "
                f"of what it computes, and the constants it hard-codes "
                f"account for only {score} of this mesh's extents ({detail})")
    if best_key[0] == 0 and best_key[3] == 0 and best_key[6] <= 0:
        warnings.append(
            "nothing in the repository states this pairing: it rests on the "
            "material block fitting what the routine reads")
    if len(tied) > 1:
        warnings.append(
            f"{len(tied)} materials in this repository fit this routine "
            f"equally well ("
            + ", ".join(sorted(f"{m.deck.name}:{m.name}" for m in tied)[:6])
            + "); the first by name is used and the rest are recorded")
    return Pairing(
        material=best, demand=demand, searched=searched,
        why="; ".join(reasons) or "it is the only admissible material block",
        rejected=tuple(rejected[:12]),
        alternatives=tuple(sorted(f"{m.deck.name}:{m.name}" for m in tied[1:])),
        warnings=tuple(warnings))
