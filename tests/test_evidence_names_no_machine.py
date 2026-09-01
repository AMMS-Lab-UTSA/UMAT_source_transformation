"""Published evidence must not name the computer that produced it.

A blocker column quotes whatever the compiler or the Fortran runtime said, and
both name the absolute path of every file they were handed. Those paths are a
property of the machine, not of the failure: they mean nothing to a reader, and
they are what the repository-standards audit refuses.

The filter existed and was applied at most of the places that needed it. It
knew the repository root and the home directory, and it did not know the work
directory a run had been given -- so a run whose scratch space was under /tmp
wrote three of those absolute paths straight into the published table, and the
audit passed because the string never said /home/.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovery_triage import without_machine_paths  # noqa: E402


class TestWhatItReplaces:
    def test_the_repository_root(self):
        assert without_machine_paths(f"at {REPO_ROOT}/src/a.py line 3") \
            == "at <repo>/src/a.py line 3"

    def test_the_home_directory(self):
        assert "<home>" in without_machine_paths(f"{Path.home()}/elsewhere/u.for")

    def test_a_work_directory_it_is_told_about(self):
        text = "as shipped: /tmp/scratch/w/x/baseline/u.for:3: Error"
        assert without_machine_paths(text, Path("/tmp/scratch/w")) \
            == "as shipped: <work>/x/baseline/u.for:3: Error"

    def test_a_work_directory_it_is_not_told_about_is_not_invented(self):
        # The filter replaces roots it is given. Silently guessing at other
        # absolute paths would rewrite parts of a compiler message that are
        # about the source rather than about the machine.
        text = "as shipped: /tmp/scratch/w/u.for:3: Error"
        assert "/tmp/scratch/w" in without_machine_paths(text)


class TestWhatItKeeps:
    def test_the_failure_is_still_identifiable(self):
        text = f"{REPO_ROOT}/src/umat_oti/transform/source_transform.py:1476 KeyError: 'x'"
        cleaned = without_machine_paths(text)
        assert "source_transform.py:1476" in cleaned
        assert "KeyError: 'x'" in cleaned

    def test_empty_text_is_returned_unchanged(self):
        assert without_machine_paths("") == ""

    def test_a_nested_work_directory_is_named_as_the_work_directory(self):
        # The work root sits inside the home directory here. Replacing <home>
        # first would leave "<home>/scratch/w/..." -- half rewritten, and no
        # longer matching either root.
        work = Path.home() / "scratch" / "w"
        cleaned = without_machine_paths(f"{work}/x/u.for:3: Error", work)
        assert cleaned == "<work>/x/u.for:3: Error"


class TestATruncatedPathIsStillAPath:
    """A blocker is cut to a length before the filter sees it.

    The cut can land in the middle of a path, leaving a fragment that matches
    no root and survives every replacement. Three rows kept a partial
    "/tmp/claude-1000/-home-..." exactly that way -- the filter ran, the audit
    passed, and the evidence still named one computer.
    """

    WORK = Path("/tmp/scratch-abc/-home-someone/run/triage_work")

    def test_a_trailing_fragment_of_a_root_is_named(self):
        assert without_machine_paths(
            "as shipped: /tmp/scratch-abc/-home-so", self.WORK) == "as shipped: <work>"

    def test_a_whole_root_still_works(self):
        assert without_machine_paths(
            f"as shipped: {self.WORK}/x/u.for:3", self.WORK) == "as shipped: <work>/x/u.for:3"

    def test_an_unrelated_absolute_path_is_left_alone(self):
        # Only prefixes of roots it was given. Trimming anything that merely
        # looks like a path would delete parts of a compiler message that are
        # about the source.
        text = "mentions /tmp/other/thing"
        assert without_machine_paths(text, self.WORK) == text

    def test_ordinary_text_is_untouched(self):
        for text in ("Error: Expecting END IF statement", "/", "u.for:3: Error"):
            assert without_machine_paths(text, self.WORK) == text

    def test_it_does_not_eat_a_single_leading_slash(self):
        # The scan stops above the root's first component, so a fragment has
        # to be long enough to actually identify the machine.
        assert without_machine_paths("path ends in /", self.WORK) == "path ends in /"
