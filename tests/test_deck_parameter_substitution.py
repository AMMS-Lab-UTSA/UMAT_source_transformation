"""A deck that writes its constants as ``<name>`` still publishes them.

Abaqus substitutes ``*PARAMETER`` values into data lines at input-processing
time. A deck written that way read as publishing no material constants at
all, so the source paired to it was classified as needing material data its
author had in fact published -- in the same file.

Reading them is not inventing them. Evaluating arbitrary text out of a
downloaded deck to obtain a material constant WOULD be a different thing,
which is why the arithmetic is walked against a whitelist rather than
evaluated, and why anything outside it leaves the constant unresolved.
"""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.corpus.abaqus_deck import (_arithmetic_value,  # noqa: E402
                                         _parameter_table, parse_deck)


def _deck(tmp_path, body):
    path = tmp_path / "deck.inp"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# ---- the substitution itself --------------------------------------------
def test_a_substituted_vector_is_read(tmp_path):
    deck = _deck(tmp_path, """
        *Parameter
        e = 210000.0
        nu = 0.3
        *Material, name=steel
        *Depvar
        4
        *User Material, constants=2
        <e>, <nu>
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [210000.0, 0.3]
    assert material.nstatv == 4
    assert material.problems == []


def test_an_unknown_name_leaves_the_vector_short_and_says_so(tmp_path):
    """Dropping it silently would shift every later constant one position
    left: a whole material vector wrong, in order, with nothing to show."""
    deck = _deck(tmp_path, """
        *Parameter
        e = 210000.0
        *Material, name=steel
        *User Material, constants=3
        <e>, <not_defined_anywhere>, 7.5
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [210000.0, 7.5]
    assert material.problems and "declares CONSTANTS=3" in material.problems[0]


def test_the_last_assignment_wins_and_a_comment_is_not_one(tmp_path):
    """These decks carry a superseded value commented out above the live one."""
    deck = _deck(tmp_path, """
        *Parameter
        **k = 0.663
        k = 0.24
        *Material, name=tissue
        *User Material, constants=1
        <k>
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [0.24]


def test_a_name_outside_a_parameter_block_is_not_collected(tmp_path):
    deck = _deck(tmp_path, """
        *Heading
        e = 999.0
        *Parameter
        k = 1.0
        """)
    assert _parameter_table(deck.read_text().splitlines()) == {"K": 1.0}


# ---- arithmetic the author wrote ----------------------------------------
def test_a_parameter_defined_from_another_is_resolved():
    """`bulk = mu*1e2` appears throughout one repository's decks."""
    assert _arithmetic_value("mu*1e2", {"MU": 3.0}) == 300.0


def test_resolution_does_not_depend_on_order_in_the_file(tmp_path):
    deck = _deck(tmp_path, """
        *Parameter
        bulk = mu*100.0
        mu = 2.0
        *Material, name=m
        *User Material, constants=2
        <mu>, <bulk>
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [2.0, 200.0]


def test_a_cycle_resolves_to_nothing_rather_than_looping(tmp_path):
    deck = _deck(tmp_path, """
        *Parameter
        a = b
        b = a
        """)
    assert _parameter_table(deck.read_text().splitlines()) == {}


def test_fortran_exponents_are_understood():
    assert _arithmetic_value("1.5d-3", {}) == 0.0015


# ---- what the evaluator must refuse -------------------------------------
def test_it_walks_a_tree_and_never_evaluates_the_text():
    """A material constant must not be a reason to run text from a download."""
    for hostile in ("__import__('os').system('id')",
                    "open('/etc/passwd').read()",
                    "().__class__.__bases__",
                    "[1, 2][0]",
                    "mu if mu else 0"):
        assert _arithmetic_value(hostile, {"MU": 1.0}) is None


def test_an_unbounded_exponent_is_refused():
    """A thousand decks are parsed in one pass; 2**5000 is a denial of
    service, not a material constant."""
    assert _arithmetic_value("2**5000", {}) is None
    assert _arithmetic_value("2**8", {}) == 256.0


def test_arithmetic_that_has_no_value_is_refused():
    assert _arithmetic_value("1/0", {}) is None
    assert _arithmetic_value("", {}) is None
    assert _arithmetic_value("not a number", {}) is None


def test_an_unresolvable_name_is_absent_rather_than_defaulted():
    """None must never become 0.0: a constant guessed at is worse than one
    reported missing."""
    assert _arithmetic_value("unknown * 2", {}) is None


# ---- a deck that needed none of this is unchanged -----------------------
def test_a_deck_with_plain_numbers_is_untouched(tmp_path):
    deck = _deck(tmp_path, """
        *Material, name=steel
        *User Material, constants=2
        210000.0, 0.3
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [210000.0, 0.3] and material.problems == []
