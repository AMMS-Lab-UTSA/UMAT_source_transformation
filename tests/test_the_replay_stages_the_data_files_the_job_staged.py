"""B20 rule H2: the offline replay of a tangent state stages the data files the Abaqus job staged.

Human-face, Alex 20470, Alex 749 and TendrilOfPumpkin open ``C:\\Users\\...\\E0.CSV`` and the replay directories
held nothing: every chosen state read "Cannot open file". A name held in a PARAMETER (jpsferreira
``DIR1='fibers.inp'``) was never seen at all.
"""
import os
import shutil
from pathlib import Path

import pytest

from umat_oti.abaqus.data_files import opened_files, redirect_indirect, stage

UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      OPEN(301,FILE='C:\\\\Users\\\\x\\\\'//
     &  'E0.CSV',STATUS='OLD')
      READ(301,*) V
      CLOSE(301)
      DO I=1,NTENS
        STRESS(I)=V*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        DDSDDE(I,I)=V
      END DO
      RETURN
      END
"""


def _repo(tmp_path):
    repo = tmp_path / "owner__repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "umat.for").write_text(UMAT)
    (repo / "data").mkdir()
    (repo / "data" / "E0.CSV").write_text("7.5\n")
    return repo


def test_the_file_the_source_requires_is_staged_under_its_literal_name(tmp_path):
    repo = _repo(tmp_path)
    work = tmp_path / "replay"
    staging = stage(repo / "src" / "umat.for", work, roots=[repo])
    assert staging.complete and "C:\\\\Users\\\\x\\\\E0.CSV" in staging.staged
    assert (work / "C:\\\\Users\\\\x\\\\E0.CSV").read_text().strip() == "7.5"


def test_a_file_nobody_published_is_still_reported_missing(tmp_path):
    # PLANTED ERROR: the repository does not hold the table
    repo = _repo(tmp_path)
    (repo / "data" / "E0.CSV").unlink()
    staging = stage(repo / "src" / "umat.for", tmp_path / "replay", roots=[repo])
    assert not staging.complete and staging.missing


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_replay_reads_the_staged_table_and_fails_without_it(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import verify_store_in_abaqus as V
    from umat_oti.abaqus.replay import build_replay, run_replay, write_state

    repo = _repo(tmp_path)
    entry = {"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
             "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
             "STATEV0": [0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
             "PROPS": [1.0], "COORDS": [0.0, 0.0, 0.0, 1.0]}

    def replay(directory, staged):
        directory.mkdir()
        write_state(entry, directory / "otis_state.txt")
        if staged:
            V.stage_replay_data(repo / "src" / "umat.for", directory, [repo])
        build = build_replay(repo / "src" / "umat.for", directory, name="T")
        assert build.ok, build.reason
        return run_replay(build, directory, 0, 0.0)

    stress, complaint = replay(tmp_path / "with", True)
    assert stress and abs(stress[0] - 7.5e-3) < 1e-12, (stress, complaint)
    stress, complaint = replay(tmp_path / "without", False)
    assert not stress and complaint, (stress, complaint)


JPS = """      SUBROUTINE UEXTERNALDB(LOP,LRESTART,TIME,DTIME,KSTEP,KINC)
      INCLUDE 'param_umat.inc'
      CHARACTER(256) FILENAME, JOBDIR
      INTEGER LENJOBDIR
      CALL GETOUTDIR(JOBDIR,LENJOBDIR)
      FILENAME=JOBDIR(:LENJOBDIR)//'/'//DIR1
      OPEN(15,FILE=FILENAME)
      READ(15,*) A
      CLOSE(15)
      RETURN
      END
"""


def test_a_name_held_in_a_parameter_is_found_staged_and_pointed_at(tmp_path):
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    (repo / "umat.for").write_text(JPS)
    (repo / "param_umat.inc").write_text(
        "      CHARACTER(256) DIR1\n      PARAMETER (DIR1='fibers.inp')\n")
    (repo / "fibers.inp").write_text("1, 1.d0, 0.d0, 0.d0\n")
    text = (repo / "umat.for").read_text()
    assert opened_files(text) == ()                      # the old reading sees nothing
    found = opened_files(text, [repo])
    assert len(found) == 1 and found[0].name == "fibers.inp" and found[0].indirect == "FILENAME"
    job = tmp_path / "job"
    staging = stage(repo / "umat.for", job, roots=[repo])
    assert "fibers.inp" in staging.staged and (job / "fibers.inp").is_file()
    new_text, extra, pointed = redirect_indirect(text, job, staged=["fibers.inp"],
                                                 include_dirs=[repo])
    literal = pointed["fibers.inp"]
    assert "param_umat.inc" in extra
    assert literal in extra["param_umat.inc"].replace("'//\n     &'", "")   # wrapped by concatenation
    assert extra["PARAM_UMAT.INC"] == extra["param_umat.inc"]       # every casing the sources use
    scratch = "/tmp/someuser_original_12345"
    assert os.path.normpath(f"{scratch}/{literal}") == str((job / "fibers.inp").resolve())
    # the original include on disk is never rewritten
    assert "'fibers.inp'" in (repo / "param_umat.inc").read_text()


def test_a_parameter_with_no_matching_file_is_not_pointed_at(tmp_path):
    # PLANTED ERROR: nothing was staged under that name, so nothing is rewritten
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    (repo / "umat.for").write_text(JPS)
    (repo / "param_umat.inc").write_text("      PARAMETER (DIR1='fibers.inp')\n")
    text = (repo / "umat.for").read_text()
    new_text, extra, pointed = redirect_indirect(text, tmp_path / "job", staged=[],
                                                 include_dirs=[repo])
    assert pointed == {} and extra == {} and new_text == text


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_a_long_staged_path_is_wrapped_and_still_evaluates_to_the_path(tmp_path):
    import subprocess
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    (repo / "umat.for").write_text(JPS)
    (repo / "param_umat.inc").write_text(
        "      CHARACTER(256) DIR1\n      PARAMETER (DIR1='fibers.inp')\n")
    (repo / "fibers.inp").write_text("1, 1.d0, 0.d0, 0.d0\n")
    job = tmp_path / ("a_deliberately_long_directory_name_" * 3) / "job"
    job.mkdir(parents=True)
    text = (repo / "umat.for").read_text()
    stage(repo / "umat.for", job, roots=[repo])
    _, extra, pointed = redirect_indirect(text, job, staged=["fibers.inp"], include_dirs=[repo])
    include = extra["param_umat.inc"]
    assert max(len(line) for line in include.splitlines()) <= 72, include     # fixed-form safe
    (tmp_path / "param_umat.inc").write_text(include)
    (tmp_path / "t.f").write_text("      PROGRAM T\n      INCLUDE 'param_umat.inc'\n      WRITE(*,'(A)') TRIM(DIR1)\n      END\n")
    done = subprocess.run(["gfortran", "-w", "t.f", "-o", "t"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    out = subprocess.run(["./t"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert out == pointed["fibers.inp"]
