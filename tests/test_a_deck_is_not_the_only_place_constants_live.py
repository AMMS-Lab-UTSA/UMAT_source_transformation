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


def _named_document(tmp_path: Path) -> tuple:
    """A document whose filename names a routine in the same repository."""
    cache = tmp_path / "cache"
    document = cache / "owner__repo" / "docs" / "umat_elastic.md"
    document.parent.mkdir(parents=True)
    document.write_text(DOCUMENT, encoding="utf-8")
    (cache / "owner__repo" / "umat_elastic_official.f").write_text("      END\n")
    return cache, document


def test_the_extracted_deck_parses_as_a_deck(tmp_path: Path):
    cache, document = _named_document(tmp_path)
    record = extract(document, cache)
    assert record is not None
    deck = cache / record["deck"]
    materials = parse_deck(deck)
    assert len(materials) == 1
    assert materials[0].props == [210000.0, 0.3]
    assert materials[0].nstatv == 1


def test_the_extracted_deck_names_where_every_line_came_from(tmp_path: Path):
    cache, document = _named_document(tmp_path)
    extract(document, cache)
    written = (cache / "owner__repo" / "docs"
               / "umat_elastic.md.extracted.inp").read_text(encoding="utf-8")
    assert "extracted verbatim from owner__repo/docs/umat_elastic.md" in written
    assert "lines 6-11" in written
    assert "Nothing here was" in written


def test_a_document_with_no_material_block_produces_nothing(tmp_path: Path):
    cache = tmp_path / "cache"
    document = cache / "owner__repo" / "umat_elastic.md"
    document.parent.mkdir(parents=True)
    (cache / "owner__repo" / "umat_elastic_official.f").write_text("      END\n")
    document.write_text("# A repository\n\nNothing to see.\n", encoding="utf-8")
    assert extract(document, cache) is None
    assert not list(document.parent.glob("*.extracted.inp"))


# ---------------------------------------------------------------------------
# and a page of prose has to say what it is about
# ---------------------------------------------------------------------------
def test_a_document_is_only_used_when_it_names_its_routine(tmp_path: Path):
    """Constants in a DECK belong to whatever it runs, and the deck says so.
    Constants in a document belong to whatever it is about, and nothing says
    so -- so the only ones carried across are from a document that names its
    routine in its own filename.

    Without the rule, ``umat_plasticity.md`` -- five constants for a power-law
    hardening model -- was paired with ``umat_mises_plasticity_official.f``,
    which reads four and is a different model.
    """
    from extract_published_decks import documents

    cache = tmp_path / "cache"
    repo = cache / "owner__repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "src" / "umat_elastic_official.f").write_text("      END\n")
    (repo / "src" / "umat_mises_plasticity_official.f").write_text("      END\n")

    named = repo / "docs" / "umat_elastic.md"
    named.write_text(DOCUMENT, encoding="utf-8")
    assert documents(named, cache) == ["owner__repo/src/umat_elastic_official.f"]

    unnamed = repo / "docs" / "umat_plasticity.md"
    unnamed.write_text(DOCUMENT, encoding="utf-8")
    assert documents(unnamed, cache) == []


def test_a_short_name_does_not_match_by_accident(tmp_path: Path):
    """``abaqus`` appears inside ``umat_abaqus_elastic`` and means nothing."""
    from extract_published_decks import documents

    cache = tmp_path / "cache"
    repo = cache / "owner__repo"
    repo.mkdir(parents=True)
    (repo / "UMAT_ABAQUS_ELASTIC.f").write_text("      END\n")
    short = repo / "abaqus.rst"
    short.write_text(DOCUMENT, encoding="utf-8")
    assert documents(short, cache) == []


def test_a_document_that_names_nothing_produces_no_deck(tmp_path: Path):
    cache = tmp_path / "cache"
    repo = cache / "owner__repo"
    repo.mkdir(parents=True)
    (repo / "creep_material.md").write_text(DOCUMENT, encoding="utf-8")
    assert extract(repo / "creep_material.md", cache) is None


def test_the_extracted_deck_names_the_routine_it_is_about(tmp_path: Path):
    cache = tmp_path / "cache"
    repo = cache / "owner__repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "umat_elastic_official.f").write_text("      END\n")
    document = repo / "umat_elastic.md"
    document.write_text(DOCUMENT, encoding="utf-8")
    record = extract(document, cache)
    assert record["about"] == ["owner__repo/src/umat_elastic_official.f"]
    written = (cache / record["deck"]).read_text(encoding="utf-8")
    assert "names the routine it is about" in written
    assert "umat_elastic_official.f" in written
