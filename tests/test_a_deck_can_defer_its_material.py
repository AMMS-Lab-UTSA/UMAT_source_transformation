"""A deck may put its material behind ``*INCLUDE``, and it is still published.

Two decks in this corpus defer their whole constant vector to another file.
The parser read one file, found zero constants, and the source paired to them
was reported as needing material data that its author had published one
directory away.

Following the directive reads what the author wrote. It does not invent
anything: an include that cannot be resolved is reported, and the deck is then
short of constants for a reason a reader can act on.
"""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.corpus.abaqus_deck import parse_deck  # noqa: E402


def _write(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_material_behind_an_include_is_read(tmp_path):
    _write(tmp_path, "mat.inp", """
        *Material, name=steel
        *Depvar
        4
        *User Material, constants=2
        210000.0, 0.3
        """)
    deck = _write(tmp_path, "job.inp", """
        *Heading
        *INCLUDE, INPUT=mat.inp
        *Step
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [210000.0, 0.3]
    assert material.nstatv == 4


def test_a_windows_path_separator_resolves(tmp_path):
    """Several of these decks were written on Windows."""
    _write(tmp_path, "parts/mat.inp", """
        *Material, name=steel
        *User Material, constants=1
        7.0
        """)
    deck = _write(tmp_path, "job.inp", """
        *INCLUDE, INPUT=parts\\mat.inp
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [7.0]


def test_a_nested_include_is_followed(tmp_path):
    _write(tmp_path, "inner.inp", """
        *Material, name=steel
        *User Material, constants=1
        3.5
        """)
    _write(tmp_path, "outer.inp", "*INCLUDE, INPUT=inner.inp\n")
    deck = _write(tmp_path, "job.inp", "*INCLUDE, INPUT=outer.inp\n")
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [3.5]


def test_a_cycle_stops_rather_than_reading_forever(tmp_path):
    _write(tmp_path, "a.inp", "*INCLUDE, INPUT=b.inp\n")
    _write(tmp_path, "b.inp", "*INCLUDE, INPUT=a.inp\n")
    assert parse_deck(tmp_path / "a.inp") == []


def test_an_unresolved_include_invents_nothing(tmp_path):
    deck = _write(tmp_path, "job.inp", """
        *INCLUDE, INPUT=absent.inp
        *Material, name=steel
        *User Material, constants=2
        1.0, 2.0
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [1.0, 2.0]


def test_a_commented_include_is_not_followed(tmp_path):
    """`**` is a comment in an Abaqus deck."""
    _write(tmp_path, "mat.inp", """
        *Material, name=steel
        *User Material, constants=1
        9.0
        """)
    deck = _write(tmp_path, "job.inp", """
        ** *INCLUDE, INPUT=mat.inp
        """)
    assert [m for m in parse_deck(deck) if m.props] == []


def test_a_deck_with_no_include_is_unchanged(tmp_path):
    deck = _write(tmp_path, "job.inp", """
        *Material, name=steel
        *User Material, constants=2
        210000.0, 0.3
        """)
    material, = [m for m in parse_deck(deck) if m.props]
    assert material.props == [210000.0, 0.3]
