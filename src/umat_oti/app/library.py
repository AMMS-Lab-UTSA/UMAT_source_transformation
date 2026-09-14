"""The UMAT library: everything that is here, searchable, in plain words.

One row per material. The status column is the plain sentence from
:mod:`umat_oti.app.plain_language` and never the batch's rung, so a reader
scanning the list is reading answers rather than a ladder -- and the rung is
carried on the row beside it, so the Evidence panel can show both and nobody
has to take the plain sentence on trust.

The filters are the questions a user actually has: what is finished, what is
waiting on me, what is waiting on this program, what is a dead end because of
how the file was published. "Whose move is it" is the filter that makes a list
of 237 materials actionable, and it is not derivable from the stage name
without the taxonomy this module calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from umat_oti.app.plain_language import (Failure, failure_for,
                                         may_say_verified, plain_status)

__all__ = ["Row", "FILTERS", "rows", "search", "counts_by_filter"]


#: The filters offered, each a question rather than a category name. ``key``
#: is what a widget stores; ``matches`` decides membership from a row.
FILTERS: tuple[dict, ...] = (
    {"key": "all", "label": "Everything",
     "explains": "every material that has been brought in"},
    {"key": "verified", "label": "Verified",
     "explains": "every check was measured and every check passed -- these "
                 "are the materials you can use"},
    {"key": "needs_you", "label": "Waiting on you",
     "explains": "something you can supply would move these forward"},
    {"key": "ours", "label": "Waiting on this program",
     "explains": "these stopped on a limitation of this program, not of your "
                 "material"},
    {"key": "published", "label": "Answered by the file itself",
     "explains": "these are facts about how the file was published; nothing "
                 "you or this program can do changes them"},
    {"key": "not_started", "label": "Not started",
     "explains": "nothing has been run for these, so nothing about them has "
                 "passed and nothing has failed"},
    {"key": "nearly", "label": "Ran to the end, did not pass everything",
     "explains": "these reached the last step of the pipeline and at least "
                 "one check did not pass or was never measured -- they are "
                 "results, and they are not verifications"},
)


@dataclass(frozen=True)
class Row:
    """One material in the list."""

    source_id: str
    repository: str
    key: str
    #: The plain sentence. This is what the list shows.
    status: str
    #: Why, in one sentence, for a reader who wants it without opening a panel.
    means: str
    whose_move: str
    verified: bool
    #: The batch's own rung, carried so the Evidence panel can show the plain
    #: sentence and the rung side by side. Never the list's status column.
    stage: str
    terminal_state: str
    kind: str
    #: Non-empty where the material reached the end and a check did not pass.
    qualifier: str = ""
    #: Where this entry may be used in the Residual Assembler without a
    #: warning. Identical to ``verified`` by construction; named separately so
    #: the bridge reads a field that says what it is for.
    usable_as_fixture: bool = False
    material: str = ""
    formulation: str = ""
    element: str = ""
    seconds: Optional[float] = None
    #: Everything a free-text search matches against, lowercased.
    haystack: str = ""

    def as_dict(self) -> dict:
        return {"source": self.source_id, "repository": self.repository,
                "key": self.key, "status": self.status, "why": self.means,
                "whose move": self.whose_move, "verified": self.verified,
                "stage the run reached": self.stage,
                "terminal state": self.terminal_state, "kind": self.kind,
                "qualifier": self.qualifier,
                "usable as a fixture": self.usable_as_fixture,
                "material": self.material, "formulation": self.formulation,
                "element": self.element, "seconds": self.seconds}


def _text(entry: Any, *names: str) -> str:
    for name in names:
        value = getattr(entry, name, None)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            for inner in ("family", "element", "material_block", "name"):
                if isinstance(value.get(inner), str) and value[inner]:
                    return value[inner]
    return ""


def rows(entries: Iterable[Any]) -> list:
    """Every entry as a list row, plain status first."""
    built = []
    for entry in entries:
        status = plain_status(entry)
        verified = may_say_verified(entry)
        manifest = getattr(entry, "manifest", None) or {}
        formulation = getattr(entry, "formulation", None) or {}
        source_id = str(getattr(entry, "source_id", "") or "")
        repository = str(getattr(entry, "repository", "") or "")
        material = str(manifest.get("material_block")
                       or manifest.get("material") or "")
        family = str(formulation.get("family") or "")
        element = str(manifest.get("element_type")
                      or formulation.get("element") or "")
        built.append(Row(
            source_id=source_id,
            repository=repository,
            key=str(getattr(entry, "key", "") or ""),
            status=status.headline,
            means=status.means,
            whose_move=status.whose_move,
            verified=verified,
            stage=status.stage,
            terminal_state=status.terminal_state,
            kind=status.kind,
            qualifier=status.qualifier,
            usable_as_fixture=verified,
            material=material,
            formulation=family,
            element=element,
            seconds=getattr(entry, "seconds", None),
            haystack=" ".join((source_id, repository, material, family,
                               element, status.headline,
                               status.whose_move)).lower(),
        ))
    return built


def _matches(row: Row, key: str) -> bool:
    if key == "all":
        return True
    if key == "verified":
        return row.verified
    if key == "needs_you":
        return not row.verified and row.whose_move == "you"
    if key == "ours":
        return not row.verified and row.whose_move == "this program"
    if key == "published":
        return not row.verified and row.whose_move == "the author of this UMAT"
    if key == "not_started":
        return row.terminal_state == "not_attempted"
    if key == "nearly":
        # Reached the pipeline's last rung without satisfying it. The number
        # this filter exists to make findable: 13 on pass11, each of which a
        # page that trusted the rung would have shown as finished work.
        return row.stage == "verified" and not row.verified
    raise ValueError(f"{key!r} is not a filter; known: "
                     + ", ".join(f["key"] for f in FILTERS))


def search(all_rows: Iterable[Row], *, text: str = "",
           filter_key: str = "all", whose_move: str = "",
           sort: str = "status") -> list:
    """The rows a user asked for.

    Free text matches the source path, the repository, the material name, the
    formulation, the element and the plain status -- the things somebody
    actually types. It does not match the stage name: a user who has not been
    taught the ladder cannot search by it, and one who has can use the
    Advanced panel.
    """
    found = [r for r in all_rows if _matches(r, filter_key)]
    needle = (text or "").strip().lower()
    if needle:
        terms = needle.split()
        found = [r for r in found if all(t in r.haystack for t in terms)]
    if whose_move:
        found = [r for r in found if r.whose_move == whose_move]
    if sort == "status":
        # Verified first, then what the user can act on, then ours, then the
        # ones nobody can move. A list sorted alphabetically buries the two
        # groups a user came to find.
        order = {"nobody": 0, "you": 1, "this program": 2,
                 "the author of this UMAT": 3}
        found.sort(key=lambda r: (not r.verified,
                                  order.get(r.whose_move, 9), r.source_id))
    elif sort == "name":
        found.sort(key=lambda r: r.source_id)
    return found


def counts_by_filter(all_rows: Iterable[Row]) -> dict:
    """How many rows each filter would show, so the tabs can carry numbers."""
    materialised = list(all_rows)
    return {spec["key"]: sum(1 for r in materialised
                             if _matches(r, spec["key"]))
            for spec in FILTERS}
