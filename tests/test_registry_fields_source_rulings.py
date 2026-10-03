"""Verdicts a source's own text decides, and Vera's B10 rulings (Scout, B10).

* ruling (b), vishalsubbiah: a routine that READs a file named by the
  author's ABSOLUTE path, which the repository does not publish, is
  ``missing_material_data`` (needs_initial_state when it fills STATEV);
* ruling (c), irfancn UEL-elastic: a UMAT whose STATEV are copies of a COMMON
  block only the file's UEL fills, at NOEL minus an offset, is the UEL's
  visualisation layer -> ``not_a_umat``;
* pass21 review: the routine-level count requires
  ``gate_mechanically_informative == "true"`` explicitly;
* laufogh: a subdirectory licence governs the files under it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_corpus_registry as reg  # noqa: E402
from umat_oti.corpus import source_rulings as sr  # noqa: E402
from umat_oti.corpus_features.manifest import scan_sources  # noqa: E402

CACHE = REPO.parent / "discovery_cache"

SDVINI_ABSOLUTE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      STRESS(1)=PROPS(1)*STATEV(1)
      RETURN
      END
      SUBROUTINE SDVINI(STATEV,COORDS,NSTATV,NCRDS,NOEL,NPT,
     1 LAYER,KSPT)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STATEV(NSTATV),COORDS(NCRDS)
C     OPEN(13,FILE='/commented/out.txt')
       OPEN(12,FILE='/work/btech/someone/Results/output1.txt')
       READ(12,*)STATEV(1),STATEV(2),STATEV(3)
      RETURN
      END
"""

WINDOWS_PUBLISHED = """\
      SUBROUTINE UMAT(STRESS)
      DIMENSION STRESS(6)
      open(301,FILE='T:\\\\Abaqus-Temp\\\\run\\\\'//
     &  'Lambda10.csv',status="old")
      read(301,*) A
      STRESS(1)=A
      END
"""

WRITE_ONLY = """\
      SUBROUTINE UMAT(STRESS)
      DIMENSION STRESS(6)
      OPEN(20,FILE='C:/Data/run/log.txt',STATUS='UNKNOWN')
      WRITE(20,*) STRESS(1)
      END
"""

DECOY = """\
      subroutine uel(rhs,amatrx,svars,energy,ndofel,nrhs,nsvars,
     1 props,nprops,coords,mcrd,nnode,u,du,v,a,jtype,time,dtime,
     2 kstep,kinc,jelem,params,ndload,jdltyp,adlmag,predef,npredf,
     3 lflags,mlvarx,ddlmag,mdload,pnewdt,jprops,njprop,period)
      include 'aba_param.inc'
      parameter(nelem=10, nsdv=4)
      common/custom/uvars(nelem, 4, 1)
      do k = 1, nsdv
        uvars(jelem, k, 1) = svars(k)
      end do
      return
      end
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     1 rpl,ddsddt,drplde,drpldt,
     2 stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     3 ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,
     4 celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      parameter (nelem=10, nsdv=4)
      common/custom/uvars(nelem, 4, 1)
      do k1 = 1, ntens
        stress(k1) = stress(k1) + props(1)*dstran(k1)
      end do
      kelem = noel - nelem
      do k1 = 1, nsdv
        statev(k1) = uvars(kelem, k1, npt)
      end do
      return
      end
"""


# ---------------------------------------------------------------- the scan
@pytest.mark.parametrize("name,absolute", [
    ("/work/a/b.txt", True), ("C:\\Data\\x\\E0.CSV", True),
    ("F:/Master/run.csv", True), ("\\\\server\\share\\f.txt", True),
    ("~/data.txt", True), ("Lambda10.csv", False), ("data/run.txt", False),
    ("./run.txt", False), ("", False)])
def test_absolute_paths_are_recognised_on_every_os(name, absolute):
    assert sr.is_absolute_path(name) is absolute


def test_an_unpublished_absolute_input_read_into_statev_needs_initial_state():
    found = sr.unpublished_absolute_inputs(SDVINI_ABSOLUTE, ["Cu_brick.inp"],
                                           form="fixed")
    assert [o.name for o in found] == ["/work/btech/someone/Results/output1.txt"]
    opened = found[0]
    assert opened.routine == "SDVINI" and opened.unit == "12"
    assert opened.read_targets == ("STATEV(1)", "STATEV(2)", "STATEV(3)")
    reason = sr.missing_input_reason(found)
    assert reason.startswith("needs_initial_state:")
    assert "STATEV(1-3)" in reason and "absolute path" in reason
    # the commented-out OPEN decides nothing
    assert "/commented/out.txt" not in reason


def test_a_published_file_behind_an_absolute_path_is_not_missing():
    # Growth-Alex: the path is the author's, the file is in the repository,
    # and umat_oti.abaqus.data_files stages it under the literal name.
    opens = sr.absolute_opens(WINDOWS_PUBLISHED, form="fixed")
    assert opens and opens[0].basename == "Lambda10.csv" and opens[0].is_input
    assert sr.unpublished_absolute_inputs(
        WINDOWS_PUBLISHED, ["sub/Lambda10.csv"], form="fixed") == ()
    assert len(sr.unpublished_absolute_inputs(
        WINDOWS_PUBLISHED, ["other.csv"], form="fixed")) == 1


def test_an_absolute_path_the_routine_only_writes_is_not_a_dependency():
    opens = sr.absolute_opens(WRITE_ONLY, form="fixed")
    assert len(opens) == 1 and not opens[0].is_input
    assert sr.unpublished_absolute_inputs(WRITE_ONLY, [], form="fixed") == ()


def test_the_manifest_scan_lists_absolute_open_paths(tmp_path):
    files = []
    for name, text in (("a.for", SDVINI_ABSOLUTE), ("b.for", WINDOWS_PUBLISHED),
                       ("c.for", "      OPEN(1,FILE='rel/x.txt')\n      END\n")):
        (tmp_path / name).write_text(text)
        files.append(tmp_path / name)
    scan = scan_sources(files, ["fixed"] * 3)
    assert "/work/btech/someone/Results/output1.txt" in scan.data_files_absolute
    # the literal as written in the source (concatenation joined)
    assert "T:\\\\Abaqus-Temp\\\\run\\\\Lambda10.csv" in scan.data_files_absolute
    assert not any("rel/x.txt" in n for n in scan.data_files_absolute)
    assert any("rel/x.txt" in n for n in scan.data_files)


# ------------------------------------------------- the visualisation UMAT
def test_a_umat_that_displays_its_uels_common_block_is_recognised():
    shown = sr.visualisation_umat(DECOY, form="fixed")
    assert shown is not None
    assert shown.block == "CUSTOM" and shown.umat_array == "UVARS"
    assert "kelem = noel - nelem" in shown.offset_text
    assert "statev(k1) = uvars(kelem, k1, npt)" in shown.statev_text
    assert "uvars(jelem, k, 1) = svars(k)" in shown.uel_write_text


@pytest.mark.parametrize("change", [
    # no UEL in the file: the COMMON is somebody else's business
    lambda t: t.replace("subroutine uel(", "subroutine uelx("),
    # the UMAT writes the array itself: it is the UMAT's own state
    lambda t: t.replace("      kelem = noel - nelem\n",
                        "      kelem = noel - nelem\n"
                        "      uvars(1, 1, 1) = 0.0\n"),
    # no NOEL offset: the index is not another mesh's element number
    lambda t: t.replace("kelem = noel - nelem", "kelem = 1"),
    # the UEL never fills the block
    lambda t: t.replace("        uvars(jelem, k, 1) = svars(k)\n", ""),
])
def test_the_visualisation_rule_needs_all_four_conditions(change):
    assert sr.visualisation_umat(change(DECOY), form="fixed") is None


# ------------------------------------------------- the registry applies them
def _cached(tmp_path, source_id, text, extra=()):
    path = tmp_path / source_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    for name in extra:
        (path.parent / name).write_text("x")
    from umat_oti.store.transform_store import file_digest
    return reg.Record(source_id=source_id, sha256=file_digest(path),
                      is_umat=True, source_form="fixed",
                      terminal_state="original_job_failed", kind="internal",
                      reason="original.sta was not written")


def test_the_registry_files_both_rules_as_external_and_out_of_d2(tmp_path):
    vis = _cached(tmp_path, "a__decoy/uel.for", DECOY)
    data = _cached(tmp_path, "b__data/umat.f", SDVINI_ABSOLUTE, ["deck.inp"])
    fine = _cached(tmp_path, "c__fine/umat.f", WINDOWS_PUBLISHED, ["Lambda10.csv"])
    reg.apply_source_rulings([vis, data, fine], tmp_path, [])
    assert (vis.terminal_state, vis.kind, vis.is_umat) == ("not_a_umat", "external", False)
    assert vis.source_ruling == "visualisation_umat"
    assert (data.terminal_state, data.kind) == ("missing_material_data", "external")
    assert data.reason.startswith("needs_initial_state:")
    assert "`original_job_failed`" in data.reason       # the batch's rung is kept
    assert fine.terminal_state == "original_job_failed" and not fine.source_ruling
    for record in (vis, data):
        adequate, _basis, kind = reg._adequacy(record)
        assert adequate is False and kind == "external"


def test_a_reviewed_ruling_is_about_one_sha256_and_must_agree(tmp_path):
    data = _cached(tmp_path, "b__data/umat.f", SDVINI_ABSOLUTE)
    ruling = {"source_id": data.source_id, "sha256": data.sha256,
              "terminal_state": "missing_material_data",
              "reason": "needs_initial_state: reviewed wording",
              "ruled_by": "Vera", "ruling": "B10 (b)", "evidence": ["x:1: y"]}
    reg.apply_source_rulings([data], tmp_path, [ruling])
    assert data.reason.startswith("needs_initial_state: reviewed wording")
    assert data.source_ruling == "reviewed"
    assert "rule unpublished_absolute_input" in data.source_ruling_evidence

    other = _cached(tmp_path, "d__other/umat.f", WINDOWS_PUBLISHED, ["Lambda10.csv"])
    stale = dict(ruling, source_id=other.source_id, sha256="0" * 64)
    reg.apply_source_rulings([other], tmp_path, [stale])
    assert other.terminal_state == "original_job_failed"
    assert "not applied" in other.source_ruling_evidence

    clash = _cached(tmp_path, "e__clash/umat.f", SDVINI_ABSOLUTE)
    wrong = dict(ruling, source_id=clash.source_id, sha256=clash.sha256,
                 terminal_state="not_a_umat")
    with pytest.raises(reg.SourceRulingConflict):
        reg.apply_source_rulings([clash], tmp_path, [wrong])


def test_the_committed_rulings_name_the_files_they_ruled():
    rulings = reg.load_source_rulings(reg.DEFAULT_SOURCE_RULINGS)
    by_id = {r["source_id"]: r for r in rulings}
    vishal = by_id["vishalsubbiah__Abaqus-Multi-scale-modelling/Abaqus/umatcode3.f"]
    assert vishal["terminal_state"] == "missing_material_data"
    assert vishal["reason"] == (
        "needs_initial_state: the orientation file (SDVINI reads STATEV(1-3) "
        "Euler angles) is at the author's absolute path and not published")
    assert by_id["irfancn__Abaqus-UEL-elastic/uel_elastic.for"][
        "terminal_state"] == "not_a_umat"
    hamza = by_id["hamza-djeloud__thesis_project/plate_with_notch.for"]
    assert hamza["terminal_state"] == "not_a_umat"
    assert any("1e-11" in line for line in hamza["evidence"])
    for r in rulings:
        assert len(r["sha256"]) == 64 and r["evidence"] and r["ruling"]


@pytest.mark.skipif(not CACHE.is_dir(), reason="discovery cache not on this machine")
def test_the_ruled_sources_are_reached_by_the_rules_in_the_real_cache():
    from umat_oti.store.transform_store import file_digest
    hits = {}
    for sid in ("vishalsubbiah__Abaqus-Multi-scale-modelling/Abaqus/umatcode3.f",
                "irfancn__Abaqus-UEL-elastic/uel_elastic.for",
                "hamza-djeloud__thesis_project/plate_with_notch.for",
                "Jeff97__General-shape-control-of-shell/Abaqus_Files/Alex_Shocked/"
                "Growth-Alex.for"):
        path = CACHE / sid
        if not path.is_file():
            pytest.skip(f"{sid} not cached")
        record = reg.Record(source_id=sid, sha256=file_digest(path), is_umat=True,
                            terminal_state="original_job_failed", kind="internal")
        reg.apply_source_rulings([record], CACHE,
                                 reg.load_source_rulings(reg.DEFAULT_SOURCE_RULINGS))
        hits[sid.split("__")[0]] = (record.terminal_state, record.source_ruling)
    assert hits["vishalsubbiah"] == ("missing_material_data", "reviewed")
    assert hits["irfancn"] == ("not_a_umat", "reviewed")
    assert hits["hamza-djeloud"] == ("not_a_umat", "reviewed")
    # Growth-Alex opens T:\... absolute paths, but publishes the files
    assert hits["Jeff97"] == ("original_job_failed", "")


# ------------------------------------------------ the informativeness gate
def _routine_cells(sid):
    return {sid: {"primal_stress_state": {"status": "verified"},
                  "ddsdde": {"status": "verified",
                             "stress_and_ddsdde_fully_defined": True}}}


@pytest.mark.parametrize("state,gate,counted", [
    ("tangent_not_verified", "true", True),
    ("tangent_not_verified", "null", False),      # the shell-growth trio
    ("derivative_truncated", "false", False),
    ("fully_verified", "absent", False),
    ("fully_verified", "", False),
    ("informativeness_not_established", "true", False),
])
def test_routine_level_requires_the_informative_gate_explicitly(state, gate, counted):
    record = reg.Record(source_id="x__y/u.f", terminal_state=state,
                        gate_mechanically_informative=gate)
    assert reg.routine_verified(record, _routine_cells("x__y/u.f")) is counted
    hidden = state in reg.PRIMAL_GATE_PASSED and gate != "true"
    assert reg.informative_gate_hidden(record) is hidden
    assert reg.informative_gate_hidden(
        {"terminal_state": state, "gate_mechanically_informative": gate}) is hidden
    summary = reg.summarise([record])
    assert bool(summary["primal_gate_passed_informative_gate_not_true"]) is hidden


# --------------------------------------------------------- the licence
def test_a_subdirectory_licence_governs_the_files_under_it():
    entry = {"license_spdx": "MIT", "license_by_path": [
        {"path_prefix": "constitutive/hypoplasticity-staubach",
         "license_spdx": "GPL-3.0-or-later"},
        {"path_prefix": "constitutive", "license_spdx": "BSD-3-Clause"}]}
    base = "laufogh__fe-large-displacement/"
    assert reg.licence_for(base + "constitutive/hypoplasticity-staubach/H.f",
                           entry) == "GPL-3.0-or-later"
    assert reg.licence_for(base + "constitutive/other/M.f", entry) == "BSD-3-Clause"
    assert reg.licence_for(base + "constitutive-x/M.f", entry) == "MIT"
    assert reg.licence_for(base + "lib/a.py", entry) == "MIT"


def test_laufogh_reads_gpl_3_or_later_from_the_acquisition_manifest():
    found = reg.acquisition_provenance(reg.DEFAULT_ACQUISITION)
    entry = found["laufogh__fe-large-displacement"]
    sid = ("laufogh__fe-large-displacement/constitutive/hypoplasticity-staubach/"
           "HPP_Staubach_implicit.f")
    assert reg.licence_for(sid, entry) == "GPL-3.0-or-later"
    scoped = entry["license_by_path"][0]
    assert "PROVENANCE.md" in scoped["license_source"]
    assert "da38fedd" in scoped["license_source"]
