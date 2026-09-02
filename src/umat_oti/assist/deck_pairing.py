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
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from umat_oti.assist.local_model import LocalModel
from umat_oti.assist.proposals import Proposal, Verdict
from umat_oti.corpus.abaqus_deck import DeckMaterial, parse_deck

__all__ = ["candidate_decks", "pair_source_with_deck", "check_pairing"]

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


def check_pairing(source: Path, deck: Path, *, expected_nprops: Optional[int],
                  expected_nstatv: Optional[int]) -> tuple[bool, str]:
    """Does that deck actually supply what that source expects?

    The check is arithmetic on counts both sides declare independently. It
    cannot confirm that a deck is the one the author intended -- only that it
    is dimensionally capable of driving this subroutine, which is the property
    the corpus round needs and the property a wrong guess most often fails.
    """
    materials = [m for m in parse_deck(deck) if m.props]
    if not materials:
        return False, f"{deck.name} declares no *User Material with constants"

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
        return not (expected_nstatv is not None and material.nstatv is not None
                    and material.nstatv < expected_nstatv)

    # An exact match is still preferred, so no pairing that succeeded before
    # can be displaced by a larger deck that merely also fits.
    exact = [m for m in materials
             if expected_nprops is not None and len(m.props) == expected_nprops
             and sufficient(m)]
    for material in exact or [m for m in materials if sufficient(m)]:
        supplied = len(material.props)
        detail = (f"{deck.name} *Material {material.name or '(unnamed)'} "
                  f"supplies {supplied} constants")
        if material.nstatv is not None:
            detail += f" and declares *Depvar {material.nstatv}"
        if expected_nprops is not None:
            detail += f"; the source expects {expected_nprops}"
            if supplied > expected_nprops:
                detail += f" and reads the first {expected_nprops}"
        return True, detail
    counts = ", ".join(str(len(m.props)) for m in materials)
    return False, (f"{deck.name} supplies {counts} constants; the source "
                   f"expects at least {expected_nprops}")


def pair_source_with_deck(
    source: Path,
    decks: Sequence[Path],
    *,
    expected_nprops: Optional[int] = None,
    expected_nstatv: Optional[int] = None,
    model: Optional[LocalModel] = None,
    head_lines: int = 40,
) -> Proposal:
    """Choose the deck for a source, with a model if one is reachable.

    With no model this checks every deck in order and takes the first that
    fits, which is the behaviour that existed before and remains the fallback.
    The model only changes which deck is examined first; the verdict is the
    arithmetic either way, so the result cannot depend on the model being
    present, only the number of files opened before reaching it.
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

    # Two passes over the decks, exact before merely sufficient. A deck that
    # supplies exactly what the source reads is the better answer wherever one
    # exists, and taking it first means loosening the check to "at least" can
    # only add pairings -- it can never displace one that already worked.
    fallback: Optional[tuple[Path, str]] = None
    for deck in ordered:
        ok, detail = check_pairing(deck=deck, source=source,
                                   expected_nprops=expected_nprops,
                                   expected_nstatv=expected_nstatv)
        if not ok:
            continue
        if expected_nprops is None or "reads the first" not in detail:
            proposal.proposed = str(deck)
            named = proposal.metadata.get("model_named")
            proposal.metadata["model_was_right"] = bool(named == str(deck))
            return proposal.confirm(
                checked_by="umat_oti.corpus.abaqus_deck", evidence=detail)
        if fallback is None:
            fallback = (deck, detail)
    if fallback is not None:
        deck, detail = fallback
        proposal.proposed = str(deck)
        named = proposal.metadata.get("model_named")
        proposal.metadata["model_was_right"] = bool(named == str(deck))
        return proposal.confirm(
            checked_by="umat_oti.corpus.abaqus_deck", evidence=detail)
    proposal.contradict(
        checked_by="umat_oti.corpus.abaqus_deck",
        evidence=(f"none of the {len(decks)} decks supplies at least "
                  f"{expected_nprops} constants"))
    return proposal


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
