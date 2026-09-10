"""Some authors publish the material block in their documentation.

The pairing looks for constants in ``.inp`` decks because that is where they
usually are; it is not the only place. ``jasonanewcoder/abaqus_skills`` has 98
files and not one of them is a ``.inp``, and its reference page for the elastic
UMAT carries

    *Material, name=Elastic_UMAT
    *User Material, constants=2
    ** E, NU
    210000.0, 0.3

which is exactly the two constants ``umat_elastic_official.f`` reads. A corpus
that looked only at decks was reporting where it looked rather than what
exists.

What the extraction does is narrow on purpose: it copies the KEYWORD BLOCK out
verbatim into a ``.inp`` beside the file it came from, with a header naming the
file and the lines. Nothing is interpreted, nothing is converted, and no value
crosses that the author did not write as an Abaqus material keyword. The
pairing then reads it with the same parser it reads every other deck with.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from extract_published_decks import blocks, extract  # noqa: E402
from umat_oti.corpus.abaqus_deck import parse_deck  # noqa: E402

DOCUMENT = """\
# Using the elastic UMAT

Define the material like this:

```abaqus
*Material, name=Elastic_UMAT
*User Material, constants=2
** E, NU
210000.0, 0.3
*Depvar
1
```

Then submit the job with `user=umat_elastic.f`.
"""


def test_a_fenced_block_is_found():
    found = blocks(DOCUMENT)
    assert len(found) == 1
    first, last, text = found[0]
    assert "*User Material, constants=2" in text
    assert "210000.0, 0.3" in text
    assert (first, last) == (6, 11)


def test_the_prose_around_it_does_not_come_with_it():
    _first, _last, text = blocks(DOCUMENT)[0]
    assert "Then submit the job" not in text
    assert "Define the material" not in text
    assert "```" not in text


def test_a_material_block_with_no_user_material_is_not_extracted():
    """A built-in *Elastic block is not a UMAT's constants, and carrying it
    would attach somebody's steel to a routine that never asked for it."""
    builtin = ("*Material, name=Steel\n*Elastic\n210000.0, 0.3\n")
    assert blocks(builtin) == []


def test_the_extracted_deck_parses_as_a_deck(tmp_path: Path):
    cache = tmp_path / "cache"
    document = cache / "owner__repo" / "docs" / "guide.md"
    document.parent.mkdir(parents=True)
    document.write_text(DOCUMENT, encoding="utf-8")
    record = extract(document, cache)
    assert record is not None
    deck = cache / record["deck"]
    materials = parse_deck(deck)
    assert len(materials) == 1
    assert materials[0].props == [210000.0, 0.3]
    assert materials[0].nstatv == 1


def test_the_extracted_deck_names_where_every_line_came_from(tmp_path: Path):
    cache = tmp_path / "cache"
    document = cache / "owner__repo" / "docs" / "guide.md"
    document.parent.mkdir(parents=True)
    document.write_text(DOCUMENT, encoding="utf-8")
    extract(document, cache)
    written = (cache / "owner__repo" / "docs"
               / "guide.md.extracted.inp").read_text(encoding="utf-8")
    assert "extracted verbatim from owner__repo/docs/guide.md" in written
    assert "lines 6-11" in written
    assert "Nothing here was" in written


def test_a_document_with_no_material_block_produces_nothing(tmp_path: Path):
    cache = tmp_path / "cache"
    document = cache / "owner__repo" / "README.md"
    document.parent.mkdir(parents=True)
    document.write_text("# A repository\n\nNothing to see.\n", encoding="utf-8")
    assert extract(document, cache) is None
    assert not list(document.parent.glob("*.extracted.inp"))
