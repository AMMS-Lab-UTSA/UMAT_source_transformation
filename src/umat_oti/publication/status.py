"""The status vocabulary the interface, the figures and the tables all use.

One list, so a word cannot mean one thing in the interface and another in a
table. Colour is never the only carrier: every status has a word, and the word
is what is asserted in the tests.
"""

from __future__ import annotations

#: Backend outcome -> the word shown to a reader.
STATUS_WORDS: dict[str, str] = {
    "verified": "PASS",
    "partial": "PARTIAL",
    "unresolved": "WITHHELD",
    "not_requested": "NOT REQUESTED",
    "unsupported": "UNSUPPORTED",
    "failed": "FAILED",
    "blocked": "BLOCKED",
    "compiled": "BLOCKED",
}

#: What each word means, in one sentence a non-specialist can act on.
STATUS_MEANINGS: dict[str, str] = {
    "PASS": "Checked numerically against an independent reference and agreed.",
    "PARTIAL": "Some entries agreed and some could not be adjudicated; the "
               "counts are given with the result.",
    "WITHHELD": "The independent reference could not decide this, so no claim "
                "is made either way.",
    "NOT REQUESTED": "This product was not asked for in the request.",
    "UNSUPPORTED": "This product does not apply to this source or this request.",
    "FAILED": "Disagreed with a reference that was able to adjudicate it.",
    "BLOCKED": "An earlier stage stopped before this product could be checked. "
               "Building is not verification.",
}


def status_word(outcome: str) -> str:
    """The reader-facing word for a backend outcome.

    An unknown outcome is surfaced in upper case rather than silently mapped to
    something reassuring: a status nobody has defined must look undefined.
    """
    return STATUS_WORDS.get(outcome, str(outcome).replace("_", " ").upper())
