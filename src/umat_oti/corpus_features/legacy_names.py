"""Read records written under the project's earlier internal vocabulary.

Before publication the reviewer-designed experiments were called "council"
experiments (``council_plan.json``, ``council_<set>.inp``, ``council_deck_ref``,
``experiment_origin: council_deck``), and a hold-out selection named its
reviewer by a person's name (``selected_by``, ``vera_accepted``,
``held_for_vera_review``). The code now writes ``reviewer_*`` and
``review_accepted``. Records written before the rename are still readable:
every loader that may meet one passes it through :func:`upgrade`, and a path
that does not exist under the new name is looked up under the old one with
:func:`existing_path`.

Nothing here writes the old names.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["upgrade", "upgrade_text", "existing_path", "LEGACY_ROLE_LABELS"]

#: Role labels of the automated assistants that wrote records before 1.2.1,
#: plus the one user ID that appears in archived paths. They remain only in
#: the checksummed archives (verification/softwarex/evidence/,
#: paper_results/frozen/); tests use this list to check that nothing else
#: carries them.
LEGACY_ROLE_LABELS = ("vera", "curie", "scout", "noether", "ada", "atlas", "hopper", "quill",
                      "nico", "lovelace", "iris", "council", "vfn333")

#: Whole-token replacements, applied before the generic ``council`` rule.
_EXACT = {
    "vera_accepted": "review_accepted",
    "held_for_vera_review": "held_for_review",
}
#: Values of ``selected_by`` that named the reviewer by name.
_REVIEWER_NAMES = {"vera", "vera (review)", "vera's review"}


def upgrade_text(text: str) -> str:
    """One key or string value in the current vocabulary.

    ``vera_accepted`` is renamed wherever it occurs in a name
    (``vera_accepted_template`` -> ``review_accepted_template``), as the
    corpus registry's columns were.
    """
    if text in _EXACT:
        return _EXACT[text]
    for old, new in _EXACT.items():
        text = text.replace(old, new)
    return (text.replace("COUNCIL", "REVIEWER").replace("Council", "Reviewer")
            .replace("council", "reviewer"))


def upgrade(record: Any) -> Any:
    """A JSON-shaped record with every legacy key and value renamed.

    Applied to records only, never to evidence bytes whose digest is checked:
    a digest is computed over what was written, so a renamed copy is compared
    by its fields, not by its hash.
    """
    if isinstance(record, dict):
        out = {}
        for key, value in record.items():
            new_key = upgrade_text(key) if isinstance(key, str) else key
            if new_key == "selected_by" and isinstance(value, str) \
                    and value.strip().lower() in _REVIEWER_NAMES:
                value = "reviewer"
            out[new_key] = upgrade(value)
        return out
    if isinstance(record, list):
        return [upgrade(item) for item in record]
    if isinstance(record, str):
        return upgrade_text(record)
    return record


def existing_path(path: Path) -> Path:
    """``path`` if it exists, else the same path under the legacy names.

    ``corpus_campaign/reviewer_plans/K/reviewer_plan.json`` falls back to
    ``corpus_campaign/council_plans/K/council_plan.json``. When neither
    exists the new path is returned, so the caller's own "not found" message
    names the current layout.
    """
    path = Path(path)
    if path.exists():
        return path
    legacy = Path(*[part.replace("reviewer", "council") for part in path.parts])
    return legacy if legacy.exists() else path
