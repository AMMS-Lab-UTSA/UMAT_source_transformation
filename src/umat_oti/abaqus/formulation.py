"""Which formulation the author ran this material in, read from their own deck.

A UMAT is called with the number of stress components its ELEMENT decides.
Plane strain hands it four, plane stress three, a continuum element six -- and
a routine written for one, driven on another, is asked for components it never
computes and compared against components it never returned.

The tensor size used to come from a scan of the source. That is a reasonable
inference and it is not evidence, and on
``abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f`` -- a file
whose name says plane strain -- it produced NTENS=6 and a C3D4 tetrahedron.

The deck the constants were read from says what the author actually did:
``*Element, type=CPS8R`` under a ``*Solid Section`` naming that material. That
is a statement, not an inference, and it is what this module reads.

It also decides which element the VERIFICATION runs on, which is not the same
element: the author's may be reduced-integration (needing an hourglass
stiffness this harness may not invent), higher-order, or hybrid. What is kept
is the FORMULATION -- the family and therefore the tensor the UMAT is handed --
and what is dropped is everything else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from pathlib import Path

from umat_oti.abaqus.elements import SUPPORTED, UnsupportedElement, geometry_for

_KEYWORD = re.compile(r"^\s*\*(?!\*)\s*([^,\n]+)(.*)$")
_PARAMETER = re.compile(r"([A-Za-z][\w \-]*)\s*=\s*([^,]+)")

#: Section keywords that attach a material to an element set.
_SECTIONS = ("SOLID SECTION", "SHELL SECTION", "MEMBRANE SECTION",
             "COHESIVE SECTION", "BEAM SECTION", "TRUSS SECTION",
             "GASKET SECTION", "SHELL GENERAL SECTION")

#: Element-family prefixes and the formulation each one means, longest first
#: so ``CPEG`` is not read as ``CPE``.
_FAMILIES: tuple[tuple[str, str], ...] = (
    ("CPEG", "generalised plane strain"),
    ("CGAX", "axisymmetric with twist"),
    ("COH", "cohesive"),
    ("SAX", "axisymmetric shell"),
    ("CAX", "axisymmetric"),
    ("CPE", "plane strain"),
    ("CPS", "plane stress"),
    ("C3D", "three-dimensional continuum"),
    ("CIN", "infinite"),
    ("DC", "heat transfer"),
    ("AC", "acoustic"),
    ("S", "shell"),
    ("M", "membrane"),
    ("B", "beam"),
    ("T", "truss"),
    ("R", "rigid"),
    ("U", "user element"),
)

#: What a verification runs each formulation on: first order, full integration,
#: same family, hybrid preserved where the registry has it.
_VERIFICATION_ELEMENT: dict[str, tuple[str, str]] = {
    "three-dimensional continuum": ("C3D8", "C3D8H"),
    "plane strain": ("CPE4", "CPE4H"),
    "plane stress": ("CPS4", "CPS4"),
    "axisymmetric": ("CAX4", "CAX4H"),
}


@dataclass(frozen=True)
class Formulation:
    """What the author's deck says, and what a verification may run.

    ``element`` is empty when there is nothing this harness can drive. The
    reason then names the formulation rather than the element, because
    "COH2D4 is not supported" tells a reader less than "this material is used
    on cohesive elements, which hand a UMAT tractions and separations".
    """

    author_elements: tuple[str, ...] = ()
    family: str = ""
    element: str = ""
    reason: str = ""
    provenance: str = ""

    @property
    def known(self) -> bool:
        return bool(self.element)

    def as_dict(self) -> dict:
        return {"author_elements": list(self.author_elements),
                "family": self.family, "element": self.element,
                "reason": self.reason, "provenance": self.provenance}


def _parameters(remainder: str) -> dict:
    return {name.strip().upper().replace(" ", ""): value.strip()
            for name, value in _PARAMETER.findall(remainder or "")}


def elements_using(text: str, material: str) -> tuple[tuple[str, ...], str]:
    """Every element type whose section names ``material``, and where it says so.

    Resolved through the element set, which is how a deck connects the two:
    ``*Element, type=CPS8R`` numbers the elements, ``*Elset, elset=Body``
    gathers them, and ``*Solid Section, elset=Body, material=Skin`` names the
    material. All three steps are needed: a ``*Element`` line often carries no
    ``elset=`` at all, so the connection runs through the element numbers.
    """
    elset_type: dict = {}
    element_type_of: dict = {}
    elset_members: dict = {}
    sections: list = []
    section_keywords = {"".join(name.split()) for name in _SECTIONS}

    current_type = ""
    current_elset = ""
    mode = ""
    generate = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("**"):
            continue
        found = _KEYWORD.match(line)
        if found:
            keyword = "".join(found.group(1).split()).upper()
            parameters = _parameters(found.group(2))
            mode, generate = "", False
            if keyword == "ELEMENT":
                current_type = parameters.get("TYPE", "").upper()
                current_elset = parameters.get("ELSET", "").upper()
                if current_elset and current_type:
                    elset_type.setdefault(current_elset, current_type)
                mode = "element"
            elif keyword == "ELSET":
                current_elset = parameters.get("ELSET", "").upper()
                generate = "GENERATE" in parameters or "generate" in (
                    found.group(2) or "").lower()
                elset_members.setdefault(current_elset, [])
                mode = "elset"
            elif keyword in section_keywords:
                sections.append((parameters.get("ELSET", "").upper(),
                                 parameters.get("MATERIAL", "").upper(),
                                 number, line.strip()[:90]))
            continue
        if mode == "element" and current_type:
            first = line.split(",")[0].strip()
            if first.isdigit():
                element_type_of[int(first)] = current_type
        elif mode == "elset" and current_elset:
            pieces = [p.strip() for p in line.split(",") if p.strip()]
            if generate and len(pieces) >= 2 and all(
                    p.lstrip("-").isdigit() for p in pieces[:3]):
                start, stop = int(pieces[0]), int(pieces[1])
                step = int(pieces[2]) if len(pieces) > 2 else 1
                elset_members[current_elset].extend(
                    range(start, stop + 1, max(step, 1)))
            else:
                elset_members[current_elset].extend(
                    int(p) if p.isdigit() else p.upper() for p in pieces)

    def types_in(name: str, depth: int = 0) -> set:
        if depth > 6:
            return set()
        found: set = set()
        if name in elset_type:
            found.add(elset_type[name])
        for member in elset_members.get(name, ())[:20000]:
            if isinstance(member, int):
                kind = element_type_of.get(member)
                if kind:
                    found.add(kind)
            else:
                found |= types_in(member, depth + 1)
        return found

    wanted = (material or "").upper()
    kinds: set = set()
    where: list = []
    for elset, named, number, quoted in sections:
        if wanted and named != wanted:
            continue
        found_kinds = types_in(elset)
        if found_kinds:
            kinds |= found_kinds
            where.append(f"line {number}: {quoted}")
    if not kinds and sections:
        # A section named the material and its set could not be resolved to a
        # type -- which happens in an assembly whose parts are instanced. The
        # deck still says what elements it holds, and a deck that holds exactly
        # one element type holds it for this material too.
        distinct = {kind for kind in element_type_of.values() if kind}
        distinct |= {kind for kind in elset_type.values() if kind}
        if len(distinct) == 1:
            kinds = distinct
            where.append(f"the deck declares one element type, {next(iter(kinds))}")
    return tuple(sorted(k for k in kinds if k)), "; ".join(where[:3])


def family_of(element: str) -> str:
    """Which formulation an Abaqus element name belongs to."""
    name = str(element or "").strip().upper()
    for prefix, family in _FAMILIES:
        if name.startswith(prefix):
            return family
    return ""


def hybrid(element: str) -> bool:
    """Whether the author asked for the hybrid (mixed pressure) variant."""
    return str(element or "").strip().upper().rstrip("0123456789").endswith("H")


def choose(author_elements, *, provenance: str = "",
           ntens_hint: int = 0) -> Formulation:
    """The element a verification runs on, from the elements the author used.

    The author's element is not reused: it may be reduced-integration, which
    Abaqus refuses under a user material without an hourglass stiffness this
    harness will not invent, or higher-order, which adds nodes without adding
    anything a material-point comparison needs. What is kept is the family, and
    with it the tensor size the UMAT is called with -- which is the whole point.
    """
    kinds = tuple(sorted({str(k).strip().upper() for k in (author_elements or ())
                          if str(k).strip()}))
    if not kinds:
        return _from_hint(ntens_hint, provenance)

    families = {family_of(kind) for kind in kinds} - {""}
    if len(families) > 1:
        # More than one formulation uses this material. Not resolvable here:
        # picking one would attribute a result to a test the author did not run.
        return Formulation(
            author_elements=kinds, family="/".join(sorted(families)),
            provenance=provenance,
            reason=(f"the deck uses this material on {len(families)} different "
                    f"formulations ({', '.join(sorted(families))}), so which "
                    f"tensor its UMAT is called with is not settled by the "
                    f"deck: elements {', '.join(kinds)}"))
    family = next(iter(families), "")
    choice = _VERIFICATION_ELEMENT.get(family)
    if choice is None:
        return Formulation(
            author_elements=kinds, family=family, provenance=provenance,
            reason=(f"the deck uses this material on {family or 'an unfamiliar'} "
                    f"elements ({', '.join(kinds)}), which do not hand a UMAT "
                    f"the continuum stress tensor this harness drives"))
    plain, hybrid_name = choice
    element = hybrid_name if any(hybrid(kind) for kind in kinds) else plain
    if element not in SUPPORTED:                   # pragma: no cover - registry
        element = plain
    return Formulation(
        author_elements=kinds, family=family, element=element,
        provenance=provenance,
        reason=(f"the author's deck runs this material on {', '.join(kinds)}, "
                f"which is {family}; the verification runs the same "
                f"formulation on {element}, whose "
                f"NTENS={geometry_for(element).ntens} is the same tensor the "
                f"UMAT is called with"))


#: What each tensor size means when the deck says nothing. An inference, and
#: labelled one wherever it is used: three sizes, three formulations, and a
#: plane-strain routine and an axisymmetric one are both called with four.
_BY_NTENS: dict = {
    6: ("C3D8", "three-dimensional continuum"),
    4: ("CPE4", "plane strain"),
    3: ("CPS4", "plane stress"),
}


def _from_hint(ntens: int, provenance: str) -> Formulation:
    found = _BY_NTENS.get(int(ntens or 0))
    if found is None:
        return Formulation(
            reason=(f"the deck does not say which element uses this material, "
                    f"and NTENS={ntens} inferred from the source matches no "
                    f"formulation this harness drives"),
            provenance=provenance)
    element, family = found
    return Formulation(
        family=family, element=element, provenance=provenance,
        reason=(f"the deck does not say which element uses this material, so "
                f"the formulation is INFERRED from NTENS={ntens} read off the "
                f"source: {family}, driven on {element}"))


# ---------------------------------------------------------------------------
# what the SOURCE says about its own tensor
# ---------------------------------------------------------------------------
#: A DO loop with a literal upper bound. Both forms, with or without a label.
_DO = re.compile(
    r"^\s*(?:\d+\s+)?DO\s+(?:\d+\s*,?\s*)?([A-Za-z_]\w*)\s*=\s*[^,]+,\s*(\d+)\s*(?:,|$)",
    re.IGNORECASE)

_LOOP_END = re.compile(r"^\s*(?:\d+\s+)?(?:END\s*DO|ENDDO|CONTINUE)\b",
                       re.IGNORECASE)

#: A literal subscript on one of the arrays whose length is NTENS.
_TENSOR_SUBSCRIPT = re.compile(
    r"\b(?:STRESS|DDSDDE|STRAN|DSTRAN|DDSDDT|DRPLDE)\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)",
    re.IGNORECASE)

#: A subscript that is an index plus an offset: ``DDSDDE(i+3,i+3)``. It is the
#: tell that a loop bounded at 3 is filling one BLOCK of a larger matrix, not
#: the whole of it. PlatypusBytes' Mohr-Coulomb fills DDSDDE(i,j) over
#: ``Do i=1,3`` and then DDSDDE(i+3,i+3) over the same loop, four lines after
#: calling ``MZeroR(DDSDDE,36)``: it is a six-component model whose tangent
#: loop is bounded at three.
_OFFSET_SUBSCRIPT = re.compile(
    r"\b(?:STRESS|DDSDDE|STRAN|DSTRAN)\s*\(\s*[A-Za-z_]\w*\s*[+-]\s*\d+",
    re.IGNORECASE)

#: An explicit test on the tensor size the routine was called with.
_SIZE_TEST = re.compile(r"\b(NTENS|NDI|NSHR)\b\s*(?:\.EQ\.|==)\s*(\d+)",
                        re.IGNORECASE)

#: What a file's own name says, when it says anything. Weakest evidence here
#: and used only to corroborate: a header that reads "not valid for plane
#: stress" contains the words too, which is why the TEXT is never searched for
#: them -- only the path.
_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("plane_strain", "plane strain"), ("planestrain", "plane strain"),
    ("plane-strain", "plane strain"), ("plane strain", "plane strain"),
    ("plane_stress", "plane stress"), ("planestress", "plane stress"),
    ("plane-stress", "plane stress"), ("plane stress", "plane stress"),
    ("axisym", "axisymmetric"),
    ("cohesive", "cohesive"), ("czm", "cohesive"), ("coh_", "cohesive"),
)

_NTENS_OF_FAMILY = {"plane stress": 3, "plane strain": 4,
                    "axisymmetric": 4, "three-dimensional continuum": 6}
_FAMILY_OF_NTENS = {3: "plane stress", 4: "plane strain",
                    6: "three-dimensional continuum"}


@dataclass(frozen=True)
class SourceFormulation:
    """What the routine's own text says about the tensor it is called with."""

    ntens: int = 0
    family: str = ""
    evidence: tuple = ()

    @property
    def known(self) -> bool:
        """A named formulation counts even without a tensor size.

        A cohesive law says what it is by being one; it is handed tractions
        and separations, and how many of them there are does not make it a
        continuum material point.
        """
        return bool(self.ntens) or bool(self.family)

    def as_dict(self) -> dict:
        return {"ntens": self.ntens, "family": self.family,
                "evidence": list(self.evidence)}


def _code_lines(text: str):
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in "cC*!" or line.lstrip().startswith("!"):
            continue
        yield line.split("!")[0]


def from_source(text: str, name: str = "") -> SourceFormulation:
    """The tensor size this routine is written for, from what it does with it.

    Three signals, and only one of them decides anything on its own.

    A DO loop with a LITERAL bound whose index subscripts the whole of DDSDDE
    or of STRESS says how many components the routine fills:
    ``do II=1,4 / do JJ=1,4 / ddsdde(II,JJ) = ...`` is a four-by-four tangent
    and therefore a plane-strain or axisymmetric routine, whatever the file is
    called. Measured on the three ``abuganza__UMAT_anisotropic_damage`` tissue
    UMATs -- the same model in three formulations, almost identical text --
    the bounds are 4, 3 and 6 and every one is right.

    A LITERAL SUBSCRIPT is a lower bound and never an answer. ``STRESS(3)`` is
    the 33 component of a six-component tensor as often as it is the last
    component of a plane-stress one, and ``DDSDDE(i)`` inside ``Do i=1,3`` is
    a partial fill of a 6x6 matrix -- ``PlatypusBytes__ConstitutiveModels``'s
    Mohr-Coulomb does exactly that, and calls ``MZeroR(DE,36)`` four lines
    earlier. So a loop bound is believed only when nothing larger appears.

    A TEST on the routine's own tensor size -- ``if (ntens .eq. 3)`` -- says
    the routine HANDLES that size, not that it is only ever called with it.
    Three ``RitioL__PolyFatigueCrackSim`` crystal-plasticity UMATs branch on
    it and run happily at six; taking the test as the answer would have moved
    them off the element they verified on. It bounds and does not decide.

    Where nothing decides, the answer is no answer, and the deck gets to speak.
    """
    evidence: list = []
    lines = list(_code_lines(text))
    joined = "\n".join(lines)

    open_loops: list = []
    by_loop = 0
    for line in lines:
        opened = _DO.match(line)
        if opened:
            open_loops.append((opened.group(1).upper(), int(opened.group(2))))
            continue
        if _LOOP_END.match(line):
            if open_loops:
                open_loops.pop()
            continue
        # STRESS(i) is the whole of the stress; DDSDDE(i,j) is the whole of
        # the tangent. DDSDDE(i) is neither -- it is one linear index into a
        # matrix, and a loop over it says nothing about the matrix's extent.
        for pattern in (r"\bSTRESS\s*\(\s*([A-Za-z_]\w*)\s*\)",
                        r"\bDDSDDE\s*\(\s*([A-Za-z_]\w*)\s*,"
                        r"\s*([A-Za-z_]\w*)\s*\)"):
            for found in re.findall(pattern, line, re.IGNORECASE):
                names = (found,) if isinstance(found, str) else found
                for subscript in names:
                    for variable, bound in open_loops:
                        if (variable == subscript.upper()
                                and bound in _FAMILY_OF_NTENS and bound > by_loop):
                            by_loop = bound

    by_subscript = 0
    for first, second in _TENSOR_SUBSCRIPT.findall(joined):
        for value in (first, second):
            if value:
                by_subscript = max(by_subscript, int(value))

    tested = [int(value) for _which, value in _SIZE_TEST.findall(joined)
              if int(value) in _FAMILY_OF_NTENS]

    named = ""
    lowered = str(name or "").lower()
    for needle, family in _NAME_HINTS:
        if needle in lowered:
            named = family
            break

    if named == "cohesive":
        # A cohesive law is handed tractions and separations, not a stress
        # tensor, whatever NTENS happens to be. Naming it lets the choice be
        # refused with the right reason instead of driven as plane stress.
        return SourceFormulation(
            family="cohesive",
            evidence=(f"the file is named {Path(name).name!r}",))

    # A loop bound is the whole tensor only if nothing reaches past it.
    offsets = _OFFSET_SUBSCRIPT.findall(joined)
    if offsets:
        by_loop = 0
        evidence.append(
            f"a subscript with an offset ({offsets[0].strip()}) reaches past "
            f"any loop bound, so the loop fills a block and not the whole")

    lower = max([by_subscript] + tested)
    ntens = 0
    if by_loop and by_loop >= lower:
        ntens = by_loop
        evidence.append(f"a DO loop bounded at {by_loop} fills the whole of "
                        f"STRESS or DDSDDE, and no larger subscript or size "
                        f"test appears")
    elif by_subscript >= 5:
        ntens = 6
        evidence.append(f"a literal subscript {by_subscript} on a tensor "
                        f"array, which only a six-component tensor has")
    elif named and _NTENS_OF_FAMILY.get(named, 0) >= lower:
        ntens = _NTENS_OF_FAMILY[named]
        evidence.append(f"the file is named {Path(name).name!r} and nothing in "
                        f"it contradicts {named}")
    if not ntens:
        why = []
        if by_loop:
            why.append(f"a DO loop bounded at {by_loop}")
        if by_subscript:
            why.append(f"a literal subscript {by_subscript}")
        if tested:
            why.append("size tests against "
                       + ", ".join(str(v) for v in sorted(set(tested))))
        return SourceFormulation(
            evidence=tuple(f"{part} -- a bound, not an answer" for part in why))
    family = _FAMILY_OF_NTENS.get(ntens, "")
    # Four components is plane strain OR axisymmetric, and the file's own name
    # is the only thing that separates them.
    if ntens == 4 and named == "axisymmetric":
        family = "axisymmetric"
    return SourceFormulation(ntens=ntens, family=family,
                             evidence=tuple(evidence))


@dataclass(frozen=True)
class Settled:
    """The formulation a verification will run, and everything that decided it."""

    formulation: Formulation
    source: SourceFormulation
    deck_elements: tuple = ()
    agreement: str = ""

    @property
    def element(self) -> str:
        return self.formulation.element

    def as_dict(self) -> dict:
        return {"element": self.formulation.element,
                "family": self.formulation.family,
                "reason": self.formulation.reason,
                "provenance": self.formulation.provenance,
                "agreement": self.agreement,
                "deck_elements": list(self.deck_elements),
                "source": self.source.as_dict()}


def settle(source_text: str, source_name: str, deck_text: str = "",
           deck_name: str = "", material: str = "") -> Settled:
    """Which element to run, from the source's own text and the author's deck.

    Two independent witnesses. The source says what tensor it fills; the deck
    says what element the author ran the material on. Where they agree the
    answer is as good as it gets. Where they disagree the SOURCE decides --
    it is what will execute, and the deck was paired to it by counting
    constants, which can pair a plane-strain routine with its plane-stress
    sibling's deck. That is exactly what happened to
    ``UMAT_Tissue_2d_plane_strain.f``, whose constants came from a CPS8R deck.

    Where neither says anything the answer is a three-dimensional continuum,
    which is the commonest case in this corpus and is labelled an assumption
    wherever it is reported.
    """
    from_the_source = from_source(source_text, source_name)
    kinds, where = elements_using(deck_text, material) if deck_text else ((), "")
    provenance = (f"{deck_name}: {where}" if where else
                  (f"{deck_name} names no element for material "
                   f"{material or '(unnamed)'}" if deck_text else "no deck"))
    from_the_deck = choose(kinds, provenance=provenance)

    if from_the_source.known and from_the_deck.known:
        if from_the_source.family == from_the_deck.family:
            return Settled(from_the_deck, from_the_source, kinds,
                           agreement=(f"the source and the deck agree: "
                                      f"{from_the_source.family}"))
        chosen = choose((), provenance=provenance,
                        ntens_hint=from_the_source.ntens)
        chosen = Formulation(
            author_elements=kinds, family=from_the_source.family,
            element=chosen.element, provenance=provenance,
            reason=(f"the source fills a {from_the_source.ntens}-component "
                    f"tensor ({'; '.join(from_the_source.evidence[:2])}), which "
                    f"is {from_the_source.family}, and the deck runs its "
                    f"material on {', '.join(kinds)}, which is "
                    f"{from_the_deck.family}. The source decides: it is what "
                    f"executes, and the deck was paired to it by counting "
                    f"constants"))
        return Settled(chosen, from_the_source, kinds,
                       agreement=(f"the source says {from_the_source.family} "
                                  f"and the deck says {from_the_deck.family}; "
                                  f"the source decides"))
    if from_the_source.family == "cohesive":
        return Settled(
            Formulation(author_elements=kinds, family="cohesive",
                        provenance=provenance,
                        reason=("this source is a cohesive law: it is handed "
                                "tractions and separations rather than a stress "
                                "tensor, and no continuum element in this "
                                "harness calls a UMAT that way")),
            from_the_source, kinds,
            agreement="the source names itself a cohesive law")
    if from_the_source.known:
        chosen = choose((), provenance=f"the source itself; {provenance}",
                        ntens_hint=from_the_source.ntens)
        if chosen.known:
            # Say what was READ, not that something was inferred: a DO loop
            # bounded at four writing STRESS(II) is the routine stating its own
            # tensor size, and calling that an inference understates it.
            chosen = Formulation(
                author_elements=kinds, family=from_the_source.family,
                element=chosen.element, provenance=provenance,
                reason=(f"the source fills a {from_the_source.ntens}-component "
                        f"tensor ({'; '.join(from_the_source.evidence[:3])}), "
                        f"which is {from_the_source.family}; the deck names no "
                        f"element for this material, so the source is the only "
                        f"witness and the verification runs on {chosen.element}"))
        return Settled(chosen, from_the_source, kinds,
                       agreement=("only the source says what tensor it fills"
                                  + ("; the deck names no element"
                                     if not kinds else
                                     f"; the deck says {from_the_deck.family}")))
    if from_the_deck.known or kinds:
        return Settled(from_the_deck, from_the_source, kinds,
                       agreement="only the deck says which element is used")
    return Settled(
        Formulation(family="three-dimensional continuum", element="C3D8",
                    provenance=provenance,
                    reason=("neither the source nor the deck says which tensor "
                            "this UMAT is called with, so it is ASSUMED to be a "
                            "three-dimensional continuum, which is what 6 of "
                            "every 7 sources in this corpus are")),
        from_the_source, kinds,
        agreement="neither says; three-dimensional continuum is assumed")
