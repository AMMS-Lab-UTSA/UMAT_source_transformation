"""Why did this source stop, proposed by a model and checked against the file.

The triage round already reports *that* a source failed and prints the message
the pipeline emitted. What it cannot say is which line of the author's Fortran
is responsible, because the message names an internal symptom -- "Promoted
variable X is indexed in a stress region but has no confirmed shape" -- and the
cause is a COMMON block ninety lines earlier that the reader never learned to
read. Turning the second into the first is reading comprehension over a few
hundred lines of fixed-form Fortran, which is the one thing here a model is
actually good at and the one thing a regex histogram is not.

So the model proposes a *cause*: one construct, named from a closed vocabulary,
at one line number. Then deterministic code re-opens the source and looks. The
proposal is confirmed only if that construct really is at that line, by the same
regexes the transformer's own diagnostics use; if the line holds something else,
or a comment, or nothing, the verdict is CONTRADICTED and the proposal is
discarded. A model cannot introduce a cause that is not in the vocabulary and
cannot point at a line that does not contain one.

Nothing here can change what the triage round decides. ``blocker_kind`` is still
assigned by ``tools/run_discovery_triage.py`` from the pipeline's own message,
the stage is still whatever the pipeline reported, and a proposal is written to
a separate artefact beside the CSV. The value is that a histogram reading
"shape_unknown: 2" becomes two line numbers a person can open.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from umat_oti.assist.local_model import LocalModel
from umat_oti.assist.proposals import Proposal
from umat_oti.core.diagnostics import UNSUPPORTED_PATTERNS

__all__ = ["CONSTRUCT_PATTERNS", "construct_occurrences", "verify_construct",
           "propose_blocker_cause"]

#: Constructs the transformer already declares it cannot read, reused verbatim
#: rather than restated. These are the authority on what the words mean; a
#: second copy of the same regexes that drifted from them would make a
#: "confirmed" cause name something the transformer does not actually object to.
_DECLARED = {code: pattern for code, pattern, _ in UNSUPPORTED_PATTERNS}

#: Constructs that are not declared unsupported but that the observed failures
#: are actually about. Kept deliberately small and deliberately precise: every
#: pattern added here is another way for a wrong proposal to find something to
#: match, so the vocabulary is worth less the longer it gets.
_TRIAGE_ONLY = {
    # 1.D-12 becoming 1.D_OTI-12 is a rename that walked into the exponent of a
    # real literal. Naming the literal is how that gets attributed to the line
    # that has one rather than to "syntax".
    "real_literal_exponent": r"\d\s*\.?\s*\d*[dDeE][+-]?\d+",
    "include_file": r"^\s*include\b",
    "entry_statement": r"^\s*entry\b",
    "computed_goto": r"^\s*go\s*to\s*\(",
    "implicit_typing": r"^\s*implicit\b",
    "character_declaration": r"^\s*character\b",
    "dimension_statement": r"^\s*dimension\b",
    "parameter_statement": r"^\s*parameter\s*\(",
    "external_declaration": r"^\s*external\b",
}

#: The closed vocabulary. A model answer naming anything else is not a choice.
CONSTRUCT_PATTERNS: dict[str, str] = {**_DECLARED, **_TRIAGE_ONLY}

_PROMPT = """\
A source-to-source transformer failed on this Fortran UMAT. You are naming the
construct in the author's source that is most likely responsible.

The message the transformer emitted:
{blocker}

The source, with line numbers:
{window}

Answer with exactly one line, in the form CODE|LINE, where CODE is one of:
{vocabulary}
and LINE is the line number above where that construct appears. Copy the line
number exactly. If none of those constructs is responsible, answer NONE.
"""


def _is_comment(line: str, *, form: str) -> bool:
    """A construct inside a comment is not a construct.

    Confirming ``common_block`` against the line ``C     COMMON blocks are
    shared`` would make the check agree with a proposal about prose, which is
    the failure mode the check exists to prevent.
    """
    if not line.strip():
        return True
    if form == "fixed" and line[:1] in ("C", "c", "*", "!", "d", "D"):
        return True
    return line.lstrip().startswith("!")


def _form_of(path: Path) -> str:
    return "free" if path.suffix.lower() in {".f90", ".f95", ".f03", ".f08"} else "fixed"


def _code_part(line: str, *, form: str) -> str:
    """The part of a physical line a construct can live in."""
    return line.split("!", 1)[0] if form == "free" else line


def construct_occurrences(text: str, code: str, *, form: str = "fixed") -> list[int]:
    """Every 1-based line where that construct really appears. Deterministic."""
    pattern = CONSTRUCT_PATTERNS.get(code)
    if pattern is None:
        return []
    compiled = re.compile(pattern, flags=re.IGNORECASE)
    found: list[int] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _is_comment(line, form=form):
            continue
        if compiled.search(_code_part(line, form=form)):
            found.append(number)
    return found


def verify_construct(text: str, code: str, line: int, *,
                     form: str = "fixed") -> tuple[bool, str]:
    """Is that construct at that line of that file?

    The whole fence is this function. It answers from the file only -- the
    proposal, the model and the blocker message are all absent from it.
    """
    if code not in CONSTRUCT_PATTERNS:
        return False, (f"{code!r} is not one of the "
                       f"{len(CONSTRUCT_PATTERNS)} known constructs")
    lines = text.splitlines()
    if not (1 <= line <= len(lines)):
        return False, f"line {line} is outside the file (1..{len(lines)})"
    physical = lines[line - 1]
    if _is_comment(physical, form=form):
        return False, f"line {line} is a comment or blank, not a {code}"
    if not re.search(CONSTRUCT_PATTERNS[code], _code_part(physical, form=form),
                     flags=re.IGNORECASE):
        return False, (f"line {line} does not match {code}: "
                       f"{physical.strip()[:80]!r}")
    return True, f"line {line} is a {code}: {physical.strip()[:80]!r}"


def _numbered_window(text: str, *, limit: int) -> str:
    lines = text.splitlines()[:limit]
    return "\n".join(f"{n}:{line}" for n, line in enumerate(lines, start=1))


def _parse(answer: str) -> tuple[str, int] | None:
    """CODE|LINE out of whatever the model actually said.

    Matched against the vocabulary rather than parsed freely, so a sentence, a
    restated header or a fenced block all reduce to the same choice or to none.
    """
    text = (answer or "").strip()
    if not text:
        return None
    for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\|\s*(\d+)", text):
        code = match.group(1).strip().lower()
        if code in CONSTRUCT_PATTERNS:
            return code, int(match.group(2))
    return None


def propose_blocker_cause(
    source: Path,
    blocker: str,
    *,
    model: Optional[LocalModel] = None,
    window_lines: int = 400,
) -> Proposal:
    """A candidate cause for one failed source, checked against that source.

    With no model this returns an UNVERIFIED proposal carrying nothing, which
    is exactly what the triage round had before: no cause, just the message.
    """
    source = Path(source)
    text = source.read_text(errors="replace")
    form = _form_of(source)
    proposal = Proposal(
        subject=f"blocker cause for {source.name}",
        proposed=None,
        model=model.name if model else "none (no model reachable)",
        alternatives=tuple(sorted(CONSTRUCT_PATTERNS)),
    )
    proposal.metadata["blocker"] = str(blocker)[:300]
    if model is None:
        proposal.evidence = "no model was reachable; no cause was proposed"
        return proposal

    prompt = _PROMPT.format(
        blocker=str(blocker)[:600],
        window=_numbered_window(text, limit=window_lines),
        vocabulary=", ".join(sorted(CONSTRUCT_PATTERNS)))
    try:
        answer, digest = model.ask(prompt, max_tokens=40)
    except Exception:
        proposal.evidence = "the model did not answer; no cause was proposed"
        return proposal
    proposal.prompt_sha256 = digest
    proposal.metadata["model_answer"] = (answer or "").strip()[:200]

    parsed = _parse(answer)
    if parsed is None:
        proposal.evidence = "the model named no construct from the vocabulary"
        return proposal
    code, line = parsed
    proposal.proposed = {"construct": code, "line": line}
    ok, detail = verify_construct(text, code, line, form=form)
    # Recorded either way: where the model pointed at a real construct on the
    # wrong line, the real ones are the useful half of the answer.
    occurrences = construct_occurrences(text, code, form=form)
    proposal.metadata["actual_occurrences"] = occurrences[:20]
    proposal.metadata["occurrence_count"] = len(occurrences)
    if ok:
        return proposal.confirm(checked_by="umat_oti.assist.blocker_triage",
                                evidence=detail)
    return proposal.contradict(checked_by="umat_oti.assist.blocker_triage",
                               evidence=detail)
