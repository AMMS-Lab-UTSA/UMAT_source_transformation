"""derivative_manifest.json records ``source.git_commit``: the commit of the
repository that tracks the author's source file, or null.

Two ways it used to say something else:

* With ``dependency_roots`` the transform reads a resolved closure that the run
  writes into its own output directory. The manifest took the commit from that
  copy, so it was null, or, when the output directory sat inside a repository
  (a gitignored workspace), that repository's HEAD.
* Any file inside a git work tree was stamped with HEAD, tracked or not, so an
  untracked file got a commit that does not contain it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.reports.manifest import source_git_commit
from umat_oti.services.transformation import TransformationOptions, run_transformation

pytestmark = [pytest.mark.regression]

ENTRY = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),DSTRAN(NTENS),DDSDDE(NTENS,NTENS),PROPS(NPROPS)
      CALL KSCALE(DDSDDE,NTENS,PROPS(1))
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+DDSDDE(I,I)*DSTRAN(I)
      END DO
      RETURN
      END
"""
HELPER = """\
      SUBROUTINE KSCALE(A,N,S)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION A(N,N)
      DO I=1,N
        A(I,I)=S
      END DO
      RETURN
      END
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is required")
    root = tmp_path / "repo"
    (root / "entry").mkdir(parents=True)
    (root / "helpers").mkdir()
    (root / "entry" / "umat_entry.for").write_text(ENTRY)
    (root / "helpers" / "library.for").write_text(HELPER)
    (root / ".gitignore").write_text("out*/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "source")
    return root


def _contract(root: Path, roots) -> Path:
    payload = {"name": "entry", "source": "entry/umat_entry.for", "ntens": 6, "order": 1,
               "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
               "promote": ["STRESS"], "replace": []}
    if roots is not None:
        payload["dependency_roots"] = roots
    path = root / ("contract_closure.json" if roots else "contract.json")
    path.write_text(json.dumps(payload))
    return path


def _manifest_source(contract: Path, out: Path) -> dict:
    summary, _code = run_transformation(contract, out, TransformationOptions())
    assert summary.get("transform_success"), summary
    return json.loads(Path(summary["manifest"]).read_text())["source"]


def test_a_tracked_source_records_its_repository_commit(repo):
    assert source_git_commit(repo / "entry" / "umat_entry.for") == _git(repo, "rev-parse", "HEAD")


def test_an_untracked_file_inside_a_repository_records_no_commit(repo):
    stray = repo / "entry" / "scratch.for"
    stray.write_text(ENTRY)
    assert source_git_commit(stray) is None


def test_a_source_outside_any_repository_records_no_commit(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is required")
    lone = tmp_path / "lone" / "umat.for"
    lone.parent.mkdir()
    lone.write_text(ENTRY)
    assert source_git_commit(lone) is None
    assert source_git_commit(tmp_path / "missing.for") is None


def test_the_manifest_records_the_commit_of_the_source_it_was_given(repo):
    source = _manifest_source(_contract(repo, None), repo / "out_single")
    assert source["git_commit"] == _git(repo, "rev-parse", "HEAD")


def test_a_resolved_closure_records_the_commit_of_the_entry_file(repo, tmp_path):
    # The resolved file is written into an output directory outside the
    # repository; the commit is still the one that holds the entry file.
    source = _manifest_source(_contract(repo, ["helpers"]), tmp_path / "out_closure")
    assert Path(source["path"]).name == "umat_entry_resolved.for"
    assert source["git_commit"] == _git(repo, "rev-parse", "HEAD")


def test_a_resolved_closure_of_an_unversioned_source_records_no_commit(repo, tmp_path):
    # The output directory sits inside a repository that ignores it, so the
    # resolved copy must not be stamped with that repository's HEAD.
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"))
    source = _manifest_source(_contract(copy, ["helpers"]), repo / "out_copy")
    assert source["git_commit"] is None
