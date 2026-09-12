"""Abaqus/Standard does not run in the job directory.

It runs in a scratch directory of its own making, so a routine that opens a
data file by a name with no directory in it -- or by the author's own Windows
path, which on POSIX is a name with no directory in it -- looks there and not
where the file was put. Measured on Growth-Alex.for, with all twelve of its
tables present under exactly the names it asks for, in the job directory::

    forrtl: severe (29): file not found, unit 301, file
    /tmp/ammslab3_original_1902146/T:\\Abaqus-Temp\\...\\Lambda10.csv

The job aborts in the element loop of its first increment. Thirteen corpus
entries failed their ORIGINAL run this way and the failure was recorded
against the model. Redirected to the staged copy, the same job runs all nine
increments and writes THE ANALYSIS HAS COMPLETED SUCCESSFULLY.
"""
from pathlib import Path

from umat_oti.abaqus.data_files import (
    FIXED_LIMIT, opened_files, redirect)


def _a_job_directory_as_deep_as_the_corpus_run_used() -> Path:
    """A path whose length is the point: ninety-odd characters.

    The corpus run's job directories are that deep, and an absolute name of
    that length does not fit in what a fixed-form OPEN statement has left.
    """
    return Path("/var") / "tmp" / "a_working_directory_of_the_usual_depth" / (
        "corpus_run") / "work" / "d55e74dd7861abaa38217335" / "discovery" / (
        "a1.000000e-04")

SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV)
      open(301,FILE='T:\\Abaqus-Temp\\20231205AlexCoarse\\'//
     &  'Lambda10.csv',status="old")
      read(301,*) X
      close(301)
      open(302,FILE='table.dat',status='old')
      close(302)
      RETURN
      END
"""


def test_the_author_s_windows_path_is_pointed_at_the_staged_copy():
    names = [o.name for o in opened_files(SOURCE)]
    out, pointed = redirect(SOURCE, Path("/work/job"), staged=names)
    assert set(pointed) == set(names)
    joined = out.replace("\n     &", "").replace("'//'", "")
    assert "/work/job/T:\\Abaqus-Temp\\20231205AlexCoarse\\Lambda10.csv" in joined
    assert "/work/job/table.dat" in joined


def test_a_name_not_staged_is_left_alone():
    """The rewrite can never point at a file that is not there."""
    out, pointed = redirect(SOURCE, Path("/work/job"), staged=["table.dat"])
    assert list(pointed) == ["table.dat"]
    assert "T:\\Abaqus-Temp\\20231205AlexCoarse\\'//" in out


def test_no_rewritten_line_runs_past_the_fixed_form_column():
    deep = _a_job_directory_as_deep_as_the_corpus_run_used()
    names = [o.name for o in opened_files(SOURCE)]
    out, pointed = redirect(SOURCE, deep, staged=names, form="fixed")
    assert pointed
    for line in out.splitlines():
        assert len(line) <= FIXED_LIMIT, line


def test_a_split_name_still_reads_as_the_same_name():
    """A character literal cannot be continued; it has to be concatenated.

    Continuing one in fixed form pads the first line to column 72 with
    blanks, and those blanks land INSIDE the file name.
    """
    deep = _a_job_directory_as_deep_as_the_corpus_run_used()
    out, _pointed = redirect(SOURCE, deep, staged=["table.dat"], form="fixed")
    statement = []
    for line in out.splitlines():
        if "302" in line or (statement and line.startswith("     &")):
            statement.append(line[6:] if line.startswith("     &") else line)
            if line.rstrip().endswith(")"):
                break
    joined = "".join(part.rstrip() for part in statement)
    # Every piece is a complete literal joined by //, so no blank can be
    # introduced by the continuation.
    assert joined.count("'") % 2 == 0
    assert "'//'" in joined or joined.count("//") >= 1
    expression = joined.split("FILE=", 1)[1].split(",", 1)[0]
    rebuilt = "".join(piece for index, piece in enumerate(expression.split("'"))
                      if index % 2 == 1)
    assert rebuilt == str(deep / "table.dat")


def test_the_runner_points_what_it_stages():
    text = Path(__file__).resolve().parents[1].joinpath(
        "tools", "run_abaqus_verification.py").read_text()
    assert "redirect_data_files(" in text, (
        "files are staged into a directory Abaqus never looks in")
    assert "staged=list(staging.staged)" in text, (
        "the rewrite must be bounded by what was actually staged")


# ---------------------------------------------------------------------------
# and the author may split the name anywhere
# ---------------------------------------------------------------------------
SPLIT_MID_DIRECTORY = """      SUBROUTINE UMAT(STRESS,STATEV)
      open(301,FILE='C:\\Users\\12872\\Desktop\\'//
     &  'Bunny\\part1\\E0.CSV',status="old")
      END
"""


def test_a_name_split_inside_its_directory_is_still_redirected():
    """The first version handled two shapes: the whole path in one literal,
    or a directory literal plus the bare basename. A concatenation can split
    ANYWHERE, and five corpus entries split it mid-directory -- the tail
    'Bunny\\part1\\E0.CSV' is a sub-path, not a basename. Neither shape
    matched, nothing was rewritten, and all five died in for_open on the
    first UMAT call with the staged file sitting unread in the job
    directory."""
    names = [o.name for o in opened_files(SPLIT_MID_DIRECTORY)]
    assert names == ["C:\\Users\\12872\\Desktop\\Bunny\\part1\\E0.CSV"]
    out, pointed = redirect(SPLIT_MID_DIRECTORY, Path("/work/job"), staged=names)
    assert len(pointed) == 1
    assert out != SPLIT_MID_DIRECTORY


def test_the_rewritten_name_reassembles_to_the_staged_path():
    names = [o.name for o in opened_files(SPLIT_MID_DIRECTORY)]
    out, _pointed = redirect(SPLIT_MID_DIRECTORY, Path("/work/job"),
                             staged=names, form="fixed")
    statement = "".join(line[6:] if line.startswith("     &") else line
                        for line in out.splitlines()
                        if "open(" in line or line.startswith("     &"))
    expression = statement.split("FILE=", 1)[1].split(",status")[0]
    rebuilt = "".join(piece for index, piece in enumerate(expression.split("'"))
                      if index % 2 == 1)
    assert rebuilt == "/work/job/C:\\Users\\12872\\Desktop\\Bunny\\part1\\E0.CSV"


def test_a_tail_that_will_not_fit_goes_on_its_own_continuation():
    """A value that fits in ONE piece can still leave the line too long once
    ,status="old") is put back after it. That used to emit the single piece
    twice, producing a name concatenated with itself."""
    names = [o.name for o in opened_files(SPLIT_MID_DIRECTORY)]
    out, _pointed = redirect(SPLIT_MID_DIRECTORY, Path("/work/job"),
                             staged=names, form="fixed")
    for line in out.splitlines():
        assert len(line) <= FIXED_LIMIT, line
    body = "\n".join(out.splitlines())
    assert body.count("/work/job/C:") == 1, "the name must be written once"
