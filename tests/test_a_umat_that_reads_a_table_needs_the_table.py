"""Some constitutive models are not written entirely in Fortran.

A growth law reads its target shape from a table, a crystal-plasticity model
its orientations. ``Growth-Alex.for`` opens

    open(301, FILE='T:\\Abaqus-Temp\\20231205AlexCoarse\\'//'Lambda10.csv',
         status="old")

which named a drive on the author's Windows machine. Run anywhere else the
Fortran runtime aborts inside the element loop, and the job leaves a ``.msg``
whose last legible line is the tail of the file name it wanted. Eleven corpus
entries failed that way and were recorded as the ORIGINAL failing to run.

The data is not missing -- ``Lambda10.csv`` is in the repository beside the
source. What is missing is the path. So the file is staged into the job's own
directory under the exact literal name the source asks for, backslashes
included, because those are ordinary characters in a POSIX file name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.data_files import (joined_statements,  # noqa: E402
                                        opened_files, stage)

SOURCE = """\
      SUBROUTINE UMAT(STRESS)
      IF (KINC .EQ. 1) THEN
        open(301,FILE='T:\\Abaqus-Temp\\20231205AlexCoarse\\'//
     &  'Lambda10.csv',status="old")
        open(401,FILE='growth_log.txt',status="unknown")
      END IF
      RETURN
      END
"""


def test_a_name_split_across_a_continuation_is_read_whole():
    """Reading the first line alone gives a directory and no file."""
    joined = joined_statements(SOURCE)
    assert "'//'Lambda10.csv'" in joined, (
        "the continuation is joined onto the statement, so the two halves of "
        "the concatenation sit on one line")
    found = opened_files(SOURCE)
    names = {opened.basename for opened in found}
    assert "Lambda10.csv" in names


def test_a_windows_path_is_reduced_to_its_base_name():
    opened = next(o for o in opened_files(SOURCE) if o.basename == "Lambda10.csv")
    assert opened.name == "T:\\Abaqus-Temp\\20231205AlexCoarse\\Lambda10.csv"
    assert opened.required, "status='old' says the file has to be there"


def test_a_file_the_routine_writes_is_not_a_dependency():
    """A routine's own output is not something anybody has to publish."""
    written = next(o for o in opened_files(SOURCE) if o.basename == "growth_log.txt")
    assert not written.required
    assert written.status == "unknown"


def test_a_published_table_is_staged_under_the_name_the_source_asks_for(tmp_path):
    repository = tmp_path / "owner__repo"
    (repository / "example").mkdir(parents=True)
    source = repository / "example" / "umat.for"
    source.write_text(SOURCE, encoding="utf-8")
    (repository / "example" / "Lambda10.csv").write_text("1.0\n2.0\n")

    job = tmp_path / "job"
    staging = stage(source, job, roots=[repository])
    assert staging.complete, staging.reason()
    asked = "T:\\Abaqus-Temp\\20231205AlexCoarse\\Lambda10.csv"
    assert asked in staging.staged
    assert (job / asked).is_file()
    assert (job / asked).read_text() == "1.0\n2.0\n"


def test_a_table_nobody_published_is_named_as_missing(tmp_path):
    repository = tmp_path / "owner__repo"
    (repository / "example").mkdir(parents=True)
    source = repository / "example" / "umat.for"
    source.write_text(SOURCE, encoding="utf-8")

    staging = stage(source, tmp_path / "job", roots=[repository])
    assert not staging.complete
    assert any("Lambda10.csv" in name for name in staging.missing)
    assert "would be inventing it" in staging.reason()
    assert not staging.optional_missing or all(
        "growth_log" in name for name in staging.optional_missing)


def test_a_source_that_opens_nothing_needs_nothing(tmp_path):
    source = tmp_path / "umat.for"
    source.write_text("      SUBROUTINE UMAT(S)\n      RETURN\n      END\n")
    staging = stage(source, tmp_path / "job")
    assert staging.complete
    assert "opens no file" in staging.reason()
