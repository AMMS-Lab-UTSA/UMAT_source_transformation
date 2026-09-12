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

#: Families whose element is not a continuum one and is chosen from what the
#: author used rather than from a family-to-element table.
_COHESIVE_ELEMENT: dict[int, str] = {2: "COH2D4", 3: "COH3D8"}

#: What a family this harness does NOT emit hands a UMAT, where that is known.
#: Stated so a refusal names the obstacle rather than the absence: an
#: axisymmetric shell is refused because nothing here hands two direct
#: components and no shear, not because shells are refused -- they are not.
_TENSOR_OF_FAMILY: dict[str, str] = {
    "axisymmetric shell": ("two direct components (meridional and hoop) and "
                           "no shear, NTENS=2"),
    "beam": ("an axial stress and the transverse shears of a cross-section "
             "it integrates over, which is a section response and not a "
             "material point"),
    "truss": "one axial component, NTENS=1",
    "generalised plane strain": ("four components like plane strain, but with "
                                 "an out-of-plane strain the element solves "
                                 "for rather than holds at zero"),
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


def elements_by_material(text: str) -> dict[str, tuple[tuple[str, ...], str]]:
    """Every material a deck's sections name, and the elements each one runs on.

    One pass over the deck for the whole file, because the per-material form
    used to re-read it once per material. ``notched_plate_CZM_random_mesh.inp``
    defines several hundred cohesive materials in eighteen thousand lines, and
    asking each of them separately turned one pairing into a quadratic scan
    that did not finish.

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
        # A deck is mostly node and connectivity data, and only a line that
        # begins with a star can change what is being read. Skipping the rest
        # without touching a regular expression is what makes a 33 000-line
        # deck cheap enough to scan once per material rather than once per
        # question about it.
        starred = line.lstrip()[:1] == "*"
        if not starred and not mode:
            continue
        if line.lstrip().startswith("**"):
            continue
        found = _KEYWORD.match(line) if starred else None
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

    resolved: dict = {}
    by_material: dict = {}
    for elset, named, number, quoted in sections:
        found_kinds = resolved.get(elset)
        if found_kinds is None:
            found_kinds = types_in(elset)
            resolved[elset] = found_kinds
        kinds, where = by_material.setdefault(named, (set(), []))
        if found_kinds:
            kinds |= found_kinds
            where.append(f"line {number}: {quoted}")

    # A section named a material and its set could not be resolved to a type --
    # which happens in an assembly whose parts are instanced. The deck still
    # says what elements it holds, and a deck that holds exactly one element
    # type holds it for that material too.
    distinct = {kind for kind in element_type_of.values() if kind}
    distinct |= {kind for kind in elset_type.values() if kind}
    lonely = next(iter(distinct)) if len(distinct) == 1 else ""

    answer: dict = {}
    for named, (kinds, where) in by_material.items():
        if not kinds and lonely:
            kinds = {lonely}
            where = where + [f"the deck declares one element type, {lonely}"]
        answer[named] = (tuple(sorted(k for k in kinds if k)),
                         "; ".join(where[:3]))
    if sections and lonely:
        answer.setdefault("", ((lonely,),
                               f"the deck declares one element type, {lonely}"))
    return answer


def elements_using(text: str, material: str) -> tuple[tuple[str, ...], str]:
    """Every element type whose section names ``material``, and where it says so.

    The whole-deck form is :func:`elements_by_material`; this asks it for one.
    """
    by_material = elements_by_material(text)
    wanted = (material or "").upper()
    if not wanted:
        # No material named: every section counts, which is what the caller
        # asking about "the deck" rather than about one material means.
        kinds: set = set()
        where: list = []
        for found_kinds, found_where in by_material.values():
            kinds |= set(found_kinds)
            if found_where:
                where.append(found_where)
        return tuple(sorted(kinds)), "; ".join(where[:3])
    found = by_material.get(wanted)
    if found is not None:
        return found
    lonely = by_material.get("")
    return lonely if lonely is not None else ((), "")


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
           ntens_hint: int = 0,
           temperature: Optional[float] = None) -> Formulation:
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

    if family == "cohesive":
        return _cohesive_choice(kinds, provenance, temperature)
    if family in ("shell", "membrane"):
        return _plane_stress_substitute(kinds, family, provenance, ntens_hint)

    choice = _VERIFICATION_ELEMENT.get(family)
    if choice is None:
        # Say WHICH tensor, where the tensor is known. "Do not hand a UMAT the
        # continuum stress tensor" is true of a shell too, and a shell is
        # drivable; what makes these different is that no element in the
        # registry hands the same components, so there is nothing to
        # substitute rather than nothing to say.
        detail = _TENSOR_OF_FAMILY.get(family, "")
        return Formulation(
            author_elements=kinds, family=family, provenance=provenance,
            reason=(f"the deck uses this material on {family or 'an unfamiliar'} "
                    f"elements ({', '.join(kinds)})"
                    + (f", which call a UMAT with {detail}. No element this "
                       f"harness emits hands those components, so there is "
                       f"nothing here to run it on that would be the same "
                       f"question" if detail else
                       ", which do not hand a UMAT the continuum stress "
                       "tensor this harness drives")))
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


def _cohesive_choice(kinds: tuple, provenance: str,
                     temperature: Optional[float] = None) -> Formulation:
    """A cohesive law IS drivable, on a cohesive element.

    Abaqus calls a UMAT for a ``*COHESIVE SECTION, RESPONSE=TRACTION
    SEPARATION`` and hands it a separation where a continuum element hands a
    strain. The refusal this replaces -- "no continuum element in this harness
    calls a UMAT that way" -- was a true statement about continuum elements
    and a false one about the harness's reach: the author of
    ``harshaa765__Bilinear-CZM-UMAT`` published a single COH3D8 patch test in
    the same repository as the source that was refused.

    What stays refused is the COUPLED form. ``COH2D4T`` is called with a
    temperature, and ``lucassalmon83860-bit``'s healing law computes
    ``PROPS(8)*Exp(-PROPS(9)/(8.34*TEMP))``; driving it at TEMP=0 divides by
    zero and choosing a temperature would choose the experiment.
    """
    coupled = [kind for kind in kinds if kind.rstrip("H").endswith("T")]
    three_d = any(kind.startswith("COH3D") for kind in kinds)
    if coupled:
        if temperature is None:
            return Formulation(
                author_elements=kinds, family="cohesive",
                provenance=provenance,
                reason=(f"the author drives this cohesive law on "
                        f"{', '.join(coupled)}, which is the coupled "
                        f"temperature-displacement form: the UMAT is called "
                        f"with a temperature that its own kinetics read, and "
                        f"no temperature is published anywhere in this deck "
                        f"to hold it at. Running it at zero would divide by "
                        f"zero in an Arrhenius term, and choosing one would "
                        f"choose the experiment"))
        element = _COHESIVE_ELEMENT[3 if three_d else 2] + "T"
        return Formulation(
            author_elements=kinds, family="cohesive", element=element,
            provenance=provenance,
            reason=(f"the author drives this cohesive law on "
                    f"{', '.join(coupled)}, which is called with a "
                    f"temperature. A single element has no neighbour to "
                    f"conduct to and cannot solve for the temperature the "
                    f"author's model solves for, so the verification runs "
                    f"{element} ISOTHERMALLY at {temperature:g}, which is a "
                    f"temperature the author STATED rather than one this "
                    f"harness chose. What it does not exercise is the law's "
                    f"temperature DEPENDENCE"))
    # Three components means the three-dimensional cohesive element and two
    # the planar one, which is what the author's own element names say.
    element = _COHESIVE_ELEMENT[3 if three_d else 2]
    return Formulation(
        author_elements=kinds, family="cohesive", element=element,
        provenance=provenance,
        reason=(f"the author's deck runs this material on "
                f"{', '.join(kinds)}, which is a traction-separation law; the "
                f"verification runs {element} under a *COHESIVE SECTION with "
                f"RESPONSE=TRACTION SEPARATION, which hands the UMAT the same "
                f"NTENS={geometry_for(element).ntens} separation the author's "
                f"element does"))


def _plane_stress_substitute(kinds: tuple, family: str, provenance: str,
                             ntens_hint: int = 0) -> Formulation:
    """A shell's UMAT is a plane-stress UMAT, and CPS4 hands it the same tensor.

    Abaqus calls a UMAT from a shell or a membrane with NDI=2, NSHR=1,
    NTENS=3 -- the plane-stress contract, which the routine has to enforce
    itself -- and calls it from CPS4 with exactly the same three components.
    So the refusal "shell elements do not hand a UMAT the continuum stress
    tensor this harness drives" named a true difference that does not reach
    the constitutive routine.

    ``theysy__mml_subroutine_public/MML_U2.for`` settles it in its own text::

        IF(NDIM3 .EQ. 3) THEN !PLANE STRESS
            NDIM4=NDIM3+1
        ELSEIF(NDIM3 .EQ. 6) THEN !3-D STRESS
            ...
        ELSE
            WRITE(*,*) '# ERROR: CHECK THE INPUT FILE'

    and its author's own constants select YLD2000_2D, which STOPs unless
    NTENS is 3. The routine is a plane-stress routine and CPS4 is how this
    harness drives one.

    What the substitution does NOT verify is said out loud: the shell's own
    kinematics -- its bending, its transverse shear stiffness, its through-
    thickness integration -- are the element's, not the material's, and none
    of them is a UMAT.
    """
    if ntens_hint and ntens_hint != 3:
        return Formulation(
            author_elements=kinds, family=family, provenance=provenance,
            reason=(f"the author's deck runs this material on "
                    f"{', '.join(kinds)}, which calls a UMAT with three "
                    f"plane-stress components, and the source fills "
                    f"{ntens_hint}. One of the two is wrong about this "
                    f"material and this harness will not pick"))
    return Formulation(
        author_elements=kinds, family=family, element="CPS4",
        provenance=provenance,
        reason=(f"the author's deck runs this material on "
                f"{', '.join(kinds)}; Abaqus calls a UMAT from a {family} "
                f"with NDI=2, NSHR=1, NTENS=3, which is the plane-stress "
                f"contract, and CPS4 hands the routine the same three "
                f"components. What this SUBSTITUTES is the element: the "
                f"{family}'s bending, transverse shear and through-thickness "
                f"integration are not part of the material and are not "
                f"verified here"))


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
           deck_name: str = "", material: str = "",
           temperature: Optional[float] = None) -> Settled:
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
    # The tensor size the source fills is handed to the chooser ONLY when the
    # deck named an element, because there it is a cross-check: a deck that
    # says "shell" is saying "three plane-stress components", and whether the
    # source agrees decides whether the substitution is honest. Handing it over
    # when the deck named nothing turns the hint into the deck's own answer,
    # and the richer reason this function builds from the source's evidence --
    # "a DO loop bounded at 4 fills the whole of STRESS" -- is then never
    # reached.
    from_the_deck = choose(kinds, provenance=provenance,
                           ntens_hint=from_the_source.ntens if kinds else 0,
                           temperature=temperature)

    # A cohesive element in the deck settles the question outright: the
    # author drove this material as a traction-separation law, and the
    # chooser has already worked out which cohesive element and whether its
    # coupled form puts it out of reach.
    if from_the_deck.family == "cohesive":
        return Settled(from_the_deck, from_the_source, kinds,
                       agreement=("the deck runs this material on cohesive "
                                  "elements" + ("; the source names itself a "
                                                "cohesive law too"
                                                if from_the_source.family
                                                == "cohesive" else "")))

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
        # The source's own NAME says cohesive and the deck said nothing that
        # confirms it. A cohesive law is drivable -- see _cohesive_choice --
        # but which of the two cohesive elements it wants is a statement only
        # the deck can make, and guessing would run a two-component law on a
        # three-component element or the reverse.
        return Settled(
            Formulation(author_elements=kinds, family="cohesive",
                        provenance=provenance,
                        reason=("this source names itself a cohesive law, so "
                                "it is handed separations and returns "
                                "tractions rather than a strain and a stress "
                                "tensor. This harness drives COH2D4 and "
                                "COH3D8; nothing in the deck paired with it "
                                "says which of the two the author used, so how "
                                "many separation components the routine is "
                                "called with is unsettled")),
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


# ---------------------------------------------------------------------------
# the frame the author ran the material in
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Orientation:
    """The local axes a deck gives a material, exactly as the deck writes them.

    Two halves, and both are the author's. ``*ORIENTATION`` names the frame --
    six numbers giving a point on the local 1-axis and a point in the local
    1-2 plane, then an axis and an angle to rotate about it. A composite
    ``*SHELL SECTION`` then rotates each ply again on its own data line.

    ``CAEAssistant-Group``'s deck carries both::

        *Orientation, name=Ori-1
                  1.,  0.,  0.,  0.,  1.,  0.
        3, 0.
        *Shell Section, elset=..., composite, orientation=Ori-1, layup=...
        0.1, 3, COMPOSITE, 30., Ply-1

    and the harness refused it saying "this harness can read the orientation's
    name but not its axes, and will not run the material in a frame its author
    never published". The axes are published: they are the global ones, and
    the ply is turned thirty degrees about the shell normal.
    """

    axes: tuple[float, ...] = ()
    rotation: tuple[int, float] = (3, 0.0)
    provenance: str = ""

    @property
    def known(self) -> bool:
        return len(self.axes) == 6

    def as_dict(self) -> dict:
        return {"axes": list(self.axes), "rotation": list(self.rotation),
                "provenance": self.provenance}


def _floats(line: str) -> list[float]:
    out: list[float] = []
    for piece in str(line or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(float(piece.replace("D", "E").replace("d", "e")))
        except ValueError:
            return out
    return out


def read_orientation(deck_text: str, material: str = "") -> Orientation:
    """The frame this deck runs ``material`` in, or an empty answer.

    Returns nothing rather than a default. An orientation this harness made up
    would run an anisotropic material along axes its author did not choose,
    and for a material whose whole behaviour is directional that is a
    different material.
    """
    frames: dict[str, tuple[list[float], tuple[int, float]]] = {}
    section_orientation = ""
    ply_angle: Optional[float] = None
    section_line = ""
    wanted = (material or "").upper()

    mode = ""
    name = ""
    pending: list[float] = []
    for number, raw in enumerate(deck_text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("**"):
            continue
        found = _KEYWORD.match(line)
        if found:
            keyword = "".join(found.group(1).split()).upper()
            parameters = _parameters(found.group(2))
            if keyword == "ORIENTATION":
                name = parameters.get("NAME", "").upper()
                pending = []
                mode = "orientation"
                continue
            if keyword in {"".join(part.split()) for part in _SECTIONS}:
                if wanted and parameters.get("MATERIAL", "").upper() == wanted:
                    section_orientation = parameters.get("ORIENTATION", "").upper()
                    section_line = f"line {number}: {line.strip()[:90]}"
                    mode = "section"
                elif "COMPOSITE" in found.group(2).upper():
                    section_orientation = (parameters.get("ORIENTATION", "")
                                           .upper() or section_orientation)
                    section_line = section_line or f"line {number}: {line.strip()[:90]}"
                    mode = "composite"
                else:
                    mode = ""
                continue
            mode = ""
            continue
        if mode == "orientation":
            numbers = _floats(line)
            if len(pending) < 6 and len(numbers) >= 6:
                pending = numbers[:6]
                continue
            if pending and len(numbers) >= 2:
                frames[name] = (pending, (int(numbers[0]), float(numbers[1])))
                mode = ""
            continue
        if mode in ("section", "composite"):
            # A composite ply line is ``thickness, nip, material, angle, name``
            # and the angle is the author turning that ply.
            fields = [field.strip() for field in line.split(",")]
            if len(fields) >= 4 and wanted and fields[2].upper() == wanted:
                try:
                    ply_angle = float(fields[3])
                except ValueError:
                    ply_angle = None
            mode = ""
            continue

    if not frames:
        return Orientation()
    chosen = section_orientation or next(iter(frames))
    frame = frames.get(chosen)
    if frame is None:
        return Orientation()
    axes, (axis, angle) = frame
    total = angle + (ply_angle or 0.0)
    detail = (f"*ORIENTATION {chosen}: axes {axes}, rotation {angle:g} about "
              f"axis {axis}")
    if ply_angle:
        detail += f"; the ply is turned a further {ply_angle:g} ({section_line})"
    return Orientation(tuple(axes), (axis, total), detail)


#: ``*INITIAL CONDITIONS, TYPE=TEMPERATURE`` with a set name and a value.
_TEMPERATURE_KEYWORD = "INITIALCONDITIONS"


def stated_temperature(deck_text: str) -> tuple:
    """A temperature the author's deck states, and where it says so.

    Returns ``(value, provenance)`` or ``(None, reason)``. Only an INITIAL
    CONDITION counts: a temperature the analysis SOLVES for is an outcome of a
    conduction problem a single element has no way to reproduce, and a
    temperature a *BOUNDARY holds is one too when the set it names is not the
    whole model. What an initial condition states is a number the author
    wrote, and holding a single element at it is isothermal rather than
    invented.

    Measured on ``lucassalmon83860-bit``'s fuel-pellet deck: ``*Initial
    Conditions, type=TEMPERATURE / Set-3, 673.`` -- and the source's own FILM
    routine sets ``SINK = 273 + 400``, the same 673, so the number is stated
    twice and by both halves of the model.
    """
    values: list[tuple[float, str]] = []
    inside = False
    for number, raw in enumerate(deck_text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            found = _KEYWORD.match(line)
            keyword = "".join((found.group(1) if found else "").split()).upper()
            parameters = _parameters(found.group(2) if found else "")
            inside = (keyword == _TEMPERATURE_KEYWORD
                      and parameters.get("TYPE", "").upper() == "TEMPERATURE")
            continue
        if not inside:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 2:
            continue
        try:
            values.append((float(fields[1]),
                           f"line {number}: {line[:70]}"))
        except ValueError:
            continue
    if not values:
        return None, ("this deck states no *INITIAL CONDITIONS, "
                      "TYPE=TEMPERATURE, so there is no temperature of the "
                      "author's to hold a single element at")
    distinct = sorted({value for value, _where in values})
    if len(distinct) > 1:
        return None, (f"this deck states {len(distinct)} different initial "
                      f"temperatures ("
                      + ", ".join(f"{value:g}" for value in distinct[:5])
                      + "); which one a single element is at is a choice, and "
                        "choosing it would choose the experiment")
    return distinct[0], f"{values[0][1]} (stated for {len(values)} node set(s))"
