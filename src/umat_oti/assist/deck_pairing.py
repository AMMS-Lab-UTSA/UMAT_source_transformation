"""Which deck supplies which source's material, proposed and then checked.

A repository that ships several UMATs and several example decks does not say
which goes with which in any machine-readable way. The pairing lives in prose,
in directory layout, in a README paragraph -- exactly the material a parser
cannot read and the thing that has kept sources out of the corpus for want of
a material vector.

So a model proposes the pairing, and arithmetic decides it. The source declares
how many constants and state variables it expects; the deck declares how many
it supplies. Those two numbers either agree or they do not, and no amount of
plausible prose changes that. A proposal that survives contributes a *filename*;
the constants themselves are then read out of that file by
:mod:`umat_oti.corpus.abaqus_deck`.

Nothing here can put a number into the evidence. The worst a wrong proposal can
do is name a deck whose counts happen to match, and a deck whose counts match is
a deck the deterministic path would have accepted anyway -- which is why the
fallback, when no model is reachable, is simply to check every deck.

The arithmetic is one-sided, and the two counts are not symmetric. Constants
are supplied by the deck and by nothing else: a deck that publishes fewer than
the routine indexes is refused, because the values past its end would come from
nobody. State variables are *allocated by the harness*, which already takes the
larger of the deck's ``*Depvar`` and what inference reads off the source (see
:func:`umat_oti.validation.job_builder.build_validation_workspace`), so a deck
declaring fewer of them costs nothing and refusing it threw away constants the
author had published -- UEL8_PCLK and UEL9_PCLK read ``PROPS(1..6)`` and their
repository ships a deck declaring exactly six, refused over ``*Depvar 14``
against an inferred 20. Worse, every refusal was written up as a constants
shortfall, so those rows were filed as "no published material constants" and
the recorded reason was false. A refusal now names the arm that refused.

Those relaxations are applied as *fallbacks*, in :data:`_LEVELS`, never as
preferences: the strictest rule runs first over every deck, and a looser one is
reached only when the one above it paired nothing at all. That ordering is the
whole reason the change is safe to make. Run as a single loosened rule it moved
44 pairings that already worked onto different decks -- a source's recorded
material vector, and the provenance line under it, changing because an
unrelated rule was widened. A source that paired before pairs with the same
deck now; a source that paired with nothing is the only kind that can reach a
lower level, and the level that recovered it is recorded in the evidence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

from umat_oti.assist.local_model import LocalModel
from umat_oti.assist.proposals import Proposal, Verdict
from umat_oti.corpus.abaqus_deck import DeckMaterial, parse_deck
from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.validation.job_builder import (
    infer_validation_dimensions_from_source, infer_validation_ntens_from_source,
)

__all__ = ["candidate_decks", "pair_source_with_deck", "check_pairing",
           "expected_counts_for_routine", "resolved_nstatv"]

_PROMPT = """\
A Fortran Abaqus UMAT and several Abaqus input decks come from one repository.
Say which single deck supplies the material for that subroutine.

Subroutine file: {source}
First lines of the subroutine:
{head}

Decks available:
{decks}

Answer with the deck path alone, copied exactly from the list, and nothing
else. If none of them plausibly belongs to this subroutine, answer NONE.
"""


def candidate_decks(root: Path, *, limit: int = 40) -> list[Path]:
    """Decks under a repository, in a stable order."""
    return sorted(Path(root).rglob("*.inp"))[:limit]


def resolved_nstatv(declared_by_deck: Optional[int],
                    expected_by_source: Optional[int]) -> Optional[int]:
    """How many state variables the round allocates, given both declarations.

    The larger of the two, which is what
    :func:`umat_oti.validation.job_builder.build_validation_workspace` has
    always allocated and for the reason stated there: a count that
    under-declares would shrink the array and reintroduce the out-of-bounds
    write that guard exists to prevent. Nothing is invented by taking a
    maximum -- the extra slots start at zero, as every slot does in the
    offline probe -- which is why this arm resolves where the constants arm,
    whose values can only come from the deck, has to refuse.
    """
    candidates = [n for n in (declared_by_deck, expected_by_source)
                  if n is not None]
    return max(candidates) if candidates else None


def check_pairing(source: Path, deck: Path, *, expected_nprops: Optional[int],
                  expected_nstatv: Optional[int],
                  read_uel_property: bool = True,
                  refuse_short_depvar: bool = False) -> tuple[bool, str]:
    """Does that deck actually supply what that source expects?

    The check is arithmetic on counts both sides declare independently. It
    cannot confirm that a deck is the one the author intended -- only that it
    is dimensionally capable of driving this subroutine, which is the property
    the corpus round needs and the property a wrong guess most often fails.

    Constants decide it. State variables are reported and resolved (see
    :func:`resolved_nstatv`) but do not refuse, because refusing on them
    discarded published constants and then blamed the constants for it. The
    two flags exist so :func:`pair_source_with_deck` can run the older, stricter
    rules first and reach these only as a fallback; a direct caller gets the
    full reading.
    """
    ok, detail, _rank, _material = _check(
        source, deck, expected_nprops, expected_nstatv, read_uel_property,
        refuse_short_depvar)
    return ok, detail


def _check(source: Path, deck: Path, expected_nprops: Optional[int],
           expected_nstatv: Optional[int], read_uel_property: bool,
           refuse_short_depvar: bool
           ) -> tuple[bool, str, tuple[int, ...], Optional[DeckMaterial]]:
    """:func:`check_pairing`, plus which vector it accepted and how good a fit.

    ``rank`` orders the accepted decks so the caller can prefer an exact match
    over a merely sufficient one across the whole repository, which is what
    keeps a source already paired with its exact deck from being moved onto a
    larger one that also fits. The material itself comes back so the proposal
    can carry the exact vector it was confirmed on: a deck can publish several,
    and re-deriving "the one that fits" from the filename alone picks a
    different one whenever the caller's NPROPS differs from the one the pairing
    used -- which, since the pairing may correct NPROPS down to the transformed
    routine's own, it now can.
    """
    published = [m for m in parse_deck(deck) if m.props]
    materials = [m for m in published
                 if read_uel_property or m.kind != "uel property"]
    if not materials:
        keywords = ("*User Material or *UEL PROPERTY" if read_uel_property
                    else "*User Material")
        return (False, f"{deck.name} publishes no constants under {keywords}",
                (), None)

    def sufficient(material) -> bool:
        """Is this material dimensionally capable of driving the source?

        Capable, not identical. A UMAT declares PROPS(NPROPS) and reads the
        indices it needs; a deck that supplies more leaves the rest unread,
        which is why the state-variable arm of this check has always asked
        for *at least* the expected count. The constants arm asked for
        exactly it, and so rejected decks that can drive the source perfectly
        well -- three crystal-plasticity UMATs whose own repository ships a
        deck declaring 168 constants where the source reads 160, and whose
        highest indexed reference in executable code is PROPS(97).
        """
        if expected_nprops is not None and len(material.props) < expected_nprops:
            return False
        if not refuse_short_depvar:
            return True
        return not (expected_nstatv is not None and material.nstatv is not None
                    and material.nstatv < expected_nstatv)

    # An exact match is still preferred, so no pairing that succeeded before
    # can be displaced by a larger deck that merely also fits.
    exact = [m for m in materials
             if expected_nprops is not None and len(m.props) == expected_nprops
             and sufficient(m)]
    for material in exact or [m for m in materials if sufficient(m)]:
        supplied = len(material.props)
        detail = (f"{deck.name} {material.citation} supplies "
                  f"{supplied} constants")
        surplus = expected_nprops is not None and supplied > expected_nprops
        if expected_nprops is not None:
            detail += f"; the source expects {expected_nprops}"
            if surplus:
                detail += f" and reads the first {expected_nprops}"
        resolved = resolved_nstatv(material.nstatv, expected_nstatv)
        if resolved is not None:
            detail += (f"; state variables resolve to {resolved} "
                       f"(deck {material.nstatv}, source {expected_nstatv})")
        return True, detail, (1 if surplus else 0,), material
    counts = ", ".join(str(len(m.props)) for m in materials)
    return False, (f"{deck.name} supplies {counts} constants; the source "
                   f"reads PROPS up to {expected_nprops}"), (), None


#: Abaqus calls these itself; none of them is ever reached from a UMAT, so
#: none of them can contribute to the UMAT's NPROPS. They are named only to
#: make the reachability walk below cheap to read -- the walk is what decides,
#: and a helper called from the UMAT is followed whatever it is called.
_ENTRY_POINTS = frozenset({
    "UMAT", "UEL", "VUMAT", "VUEL", "UMATHT", "UEXPAN", "UHYPER", "UHYPEL",
    "UANISOHYPER_INV", "UANISOHYPER_STRAIN", "USDFLD", "SDVINI", "UVARM",
    "DLOAD", "DISP", "UTRACLOAD", "UEXTERNALDB", "URDFIL", "HETVAL", "UFIELD",
})


def expected_counts_for_routine(
    source: Path, routine: str = "UMAT", *, statev_name: str = "STATEV",
) -> tuple[int, int, str]:
    """NPROPS and NSTATV for one subprogram, not for the file that holds it.

    NPROPS is a property of a subroutine: it is how far that routine's own
    PROPS references reach. Inferring it from a whole file takes the maximum
    over every subprogram in it, which is the right answer only when the file
    holds one. hamza-djeloud/plate_with_notch.for holds a UEL reading
    ``PROPS(1..4)`` beside a UMAT reading ``PROPS(1..2)``; judged by the file
    the UMAT wanted 4, and the deck's own ``*User Material, constants=2`` --
    fully numeric, ``1e-11, 0.3`` -- was refused as too short and the row was
    filed as having no published constants.

    "That routine" means the routine and everything it calls. A UMAT that
    hands PROPS to a helper reads every index the helper reads, so the count
    is taken over the transitive closure of CALL statements from the named
    entry point. Counting the entry point's own lines alone would under-declare
    NPROPS and pair a deck too short for the routine, which is the failure this
    whole area exists to prevent -- the reverse of the one being fixed, and the
    worse of the two.

    Returns ``(nprops, nstatv, why)``. Falls back to the whole file, which is
    the behaviour that existed before, whenever the routine cannot be located
    or the file holds only one subprogram: there is then nothing to
    disambiguate and the answers are identical anyway.
    """
    source = Path(source)
    text = source.read_text(encoding="utf-8", errors="replace")

    def counts(body: str, why: str) -> tuple[int, int, str]:
        ntens, _ = infer_validation_ntens_from_source(body, fallback_ntens=6)
        nstatv, nprops = infer_validation_dimensions_from_source(
            body, statev_name=statev_name, ntens=ntens)
        return nprops, nstatv, why

    whole_file = counts(text, "inferred from the whole file")
    try:
        parsed = parse_fortran_file(source)
    except Exception:  # noqa: BLE001 - an unparsable source keeps the old answer
        return whole_file
    by_name = {r.name.upper(): r for r in parsed.subroutines}
    if len(by_name) < 2 or routine.upper() not in by_name:
        return whole_file

    # The transitive closure of CALL statements from the entry point. A
    # sibling entry point is unreachable by construction: Abaqus calls it, the
    # UMAT does not, so its PROPS indices are not the UMAT's.
    reached: set[str] = set()
    frontier = [routine.upper()]
    while frontier:
        name = frontier.pop()
        if name in reached or name not in by_name:
            continue
        reached.add(name)
        for line in by_name[name].lines:
            for called in re.findall(r"\bcall\s+(\w+)", line.text,
                                     flags=re.IGNORECASE):
                frontier.append(called.upper())
    body = "\n".join(line.text for name in sorted(reached)
                      for line in by_name[name].lines)
    unreached = sorted(set(by_name) - reached)
    return counts(
        body,
        f"inferred from {routine.upper()} and the {len(reached) - 1} "
        f"subprogram(s) it calls; not from "
        + (", ".join(unreached) if unreached else "(nothing else in the file)"))



#: The rules, strictest first. Each row is strictly more permissive than the
#: one above it, and :func:`pair_source_with_deck` drops to the next only when
#: the one above paired nothing at all against any deck. Ordered that way a
#: relaxation can only add pairings; run as a single loosened rule instead,
#: these three moved 44 sources that already paired onto different decks and
#: changed the material vector recorded for them.
#:
#: ``label`` is written into the evidence, so a row says which relaxation
#: recovered it and a reviewer can go straight to the reason.
_LEVELS: tuple[dict[str, object], ...] = (
    {"label": "",
     "read_uel_property": False, "refuse_short_depvar": True,
     "per_routine_nprops": False},
    {"label": "; paired against the NPROPS of the routine being transformed "
              "rather than of the whole file",
     "read_uel_property": False, "refuse_short_depvar": True,
     "per_routine_nprops": True},
    {"label": "; paired by reading *UEL PROPERTY, which is where this "
              "author's constants are published",
     "read_uel_property": True, "refuse_short_depvar": True,
     "per_routine_nprops": True},
    {"label": "; paired after resolving the deck's *Depvar against the "
              "source's own count rather than refusing on it",
     "read_uel_property": True, "refuse_short_depvar": False,
     "per_routine_nprops": True},
)


def _nprops_for_routine(source: Path, routine: str,
                        expected_nprops: Optional[int],
                        proposal: Proposal) -> Optional[int]:
    """The caller's NPROPS, corrected to the transformed routine's own.

    Corrected only when the caller's number *is* the file-wide inference this
    module can reproduce, and only downward. A count a caller established some
    other way -- a reviewed snapshot entry, a routine that reads PROPS in a
    loop rather than by literal index -- is left exactly as given, because
    lowering one of those would pair a deck shorter than the routine reads and
    the values past its end would come from nobody. Both numbers are recorded
    so the correction is visible in the proposal rather than silent.
    """
    if expected_nprops is None:
        return None
    try:
        text = Path(source).read_text(encoding="utf-8", errors="replace")
        ntens, _ = infer_validation_ntens_from_source(text, fallback_ntens=6)
        _, file_wide = infer_validation_dimensions_from_source(
            text, statev_name="STATEV", ntens=ntens)
        routine_nprops, _routine_nstatv, why = expected_counts_for_routine(
            source, routine)
    except OSError:
        return expected_nprops
    if file_wide != expected_nprops or routine_nprops >= expected_nprops:
        return expected_nprops
    proposal.metadata["nprops_file_wide"] = file_wide
    proposal.metadata["nprops_routine"] = routine_nprops
    proposal.metadata["nprops_note"] = why
    return routine_nprops


def pair_source_with_deck(
    source: Path,
    decks: Sequence[Path],
    *,
    expected_nprops: Optional[int] = None,
    expected_nstatv: Optional[int] = None,
    model: Optional[LocalModel] = None,
    head_lines: int = 40,
    routine: str = "UMAT",
) -> Proposal:
    """Choose the deck for a source, with a model if one is reachable.

    With no model this checks every deck in order and takes the first that
    fits, which is the behaviour that existed before and remains the fallback.
    The model only changes which deck is examined first; the verdict is the
    arithmetic either way, so the result cannot depend on the model being
    present, only the number of files opened before reaching it.

    The rules in :data:`_LEVELS` are tried strictest first, and each is run
    over every deck before the next is reached, so a source that already
    paired keeps the deck it paired with.

    ``routine`` names the subprogram being transformed. It is consulted only
    by the fallback levels, to correct a file-wide NPROPS down to that
    routine's own -- see :func:`expected_counts_for_routine`. The strictest
    level never sees it, which is why no pairing that already worked can move.
    """
    decks = list(decks)
    proposal = Proposal(
        subject=f"material deck for {source.name}",
        proposed=None,
        model=model.name if model else "none (deterministic scan)",
        alternatives=tuple(str(d) for d in decks),
    )
    if not decks:
        proposal.contradict(checked_by="deck parser",
                            evidence="the repository ships no .inp deck")
        return proposal

    ordered = decks
    if model is not None:
        head = "\n".join(
            source.read_text(errors="replace").splitlines()[:head_lines])
        prompt = _PROMPT.format(source=source.name, head=head,
                                decks="\n".join(str(d) for d in decks))
        try:
            answer, digest = model.ask(prompt, max_tokens=120)
        except Exception:
            answer, digest = "", ""
        proposal.prompt_sha256 = digest
        chosen = _match_answer(answer, decks)
        if chosen is not None:
            # Examined first, never trusted: the same check runs on it.
            ordered = [chosen] + [d for d in decks if d != chosen]
            proposal.metadata["model_answer"] = answer.strip()[:200]
            proposal.metadata["model_named"] = str(chosen)
        else:
            proposal.metadata["model_answer"] = answer.strip()[:200]
            proposal.metadata["model_named"] = ""

    # A level whose parameters come out identical to one already run would
    # re-derive the same answer; skipped so the recorded label names a
    # relaxation that actually did something.
    already: set[tuple] = set()
    per_routine: Optional[int] = None  # read once, on the first level to ask
    for level, rule in enumerate(_LEVELS):
        wanted = expected_nprops
        if rule["per_routine_nprops"]:
            if per_routine is None:
                per_routine = _nprops_for_routine(source, routine,
                                                  expected_nprops, proposal)
            wanted = per_routine
        settings = (wanted, rule["read_uel_property"],
                    rule["refuse_short_depvar"])
        if settings in already:
            continue
        already.add(settings)
        # Two passes over the decks, exact before merely sufficient. A deck
        # that supplies exactly what the source reads is the better answer
        # wherever one exists, and taking it first means loosening the check
        # to "at least" can only add pairings -- it can never displace one
        # that already worked.
        fallback: Optional[tuple[Path, str, Optional[DeckMaterial]]] = None
        for deck in ordered:
            ok, detail, rank, material = _check(
                source, deck, wanted, expected_nstatv,
                bool(rule["read_uel_property"]),
                bool(rule["refuse_short_depvar"]))
            if not ok:
                continue
            if rank and rank[0] == 0:
                return _confirm(proposal, deck, detail + str(rule["label"]),
                                level, wanted, material)
            if fallback is None:
                fallback = (deck, detail, material)
        if fallback is not None:
            deck, detail, material = fallback
            return _confirm(proposal, deck, detail + str(rule["label"]),
                            level, wanted, material)

    # Report the smallest count any level asked for, which is the one whose
    # refusal actually stands.
    shortest = min([n for n in (expected_nprops, per_routine) if n is not None],
                   default=None)
    proposal.metadata["expected_nprops"] = shortest
    # Name the arm. Every refusal used to be written up as a constants
    # shortfall, so a pairing rejected on its *Depvar count was recorded as
    # "no published material constants" and a reader chasing that row went
    # looking for numbers the author had already published. Constants are now
    # the only arm that can refuse, and the sentence says so.
    proposal.contradict(
        checked_by="umat_oti.corpus.abaqus_deck",
        evidence=(f"none of the {len(decks)} decks publishes at least "
                  f"{shortest} constants under *User Material or "
                  f"*UEL PROPERTY, which is how far the PROPS references of "
                  f"{routine.upper()} in this source reach"))
    return proposal


def _confirm(proposal: Proposal, deck: Path, detail: str, level: int,
             wanted: Optional[int],
             material: Optional[DeckMaterial]) -> Proposal:
    """Record the deck, the vector, and which rule in :data:`_LEVELS` took it.

    ``material`` is recorded because the filename alone is no longer enough to
    find it again: ``plate_with_notch.inp`` publishes a two-value *Material
    beside two *UEL PROPERTY vectors of three and four values, and which one
    this pairing accepted depends on the NPROPS it used. A consumer that
    re-reads the deck with a file-wide NPROPS picks the four-value element
    property vector and then cites it as a *Material -- constants the author
    published, under a citation the author would not recognise.
    """
    proposal.proposed = str(deck)
    proposal.metadata["model_was_right"] = bool(
        proposal.metadata.get("model_named") == str(deck))
    proposal.metadata["pairing_level"] = level
    proposal.metadata["expected_nprops"] = wanted
    if material is not None:
        proposal.metadata["material"] = material.as_dict()
    return proposal.confirm(checked_by="umat_oti.corpus.abaqus_deck",
                            evidence=detail)


def _match_answer(answer: str, decks: Sequence[Path]) -> Optional[Path]:
    """The deck the model named, matched against the list it was given.

    Matched rather than parsed: a model may answer with a path, a basename or
    a sentence, and anything it says that is not one of the offered files is
    not a choice at all.
    """
    text = (answer or "").strip()
    if not text or text.upper().startswith("NONE"):
        return None
    for deck in decks:
        if str(deck) in text:
            return deck
    for deck in decks:
        if deck.name and deck.name in text:
            return deck
    return None
