"""The binary32 variables on the derivative path are listed, machine-readably.

Jeff97 Wrinkle (pass21 key 254a65c2) declares ``REAL ... MMOD,G11,G12,G21,G22``.
The transform keeps their primal binary32 (rule B-W) but carries their
derivatives in double, so a sensitivity through them is the double idealisation
of a binary32 original -- which differed from the original's own derivative by
a factor of four there (Ada, B8 wrinkle_proof). The list says so, per variable,
in the lifted build's layout and ``binary32_stores.json``, the tangent
transform's report, and the derivative manifest, under ``binary32_stores``.
"""
from __future__ import annotations

import json
from pathlib import Path

from umat_oti.reports.manifest import build_manifest
from umat_oti.transform.binary32 import (
    BINARY32_STORES_FIELD,
    BINARY32_STORES_SCHEMA,
    binary32_store_report,
)
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    transform_umat_for_parameter_sensitivity,
)

_TOY = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATEV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATEV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      REAL GROW, SPARE
      GROW = (STATEV(1)*STATEV(1) + 1.D0)/(STATEV(1)*STATEV(1) + 2.D0)
      DO K1 = 1, NTENS
        STRESS(K1) = STRESS(K1) + PROPS(1)*GROW*DSTRAN(K1)
        DO K2 = 1, NTENS
          DDSDDE(K1, K2) = 0.D0
        END DO
        DDSDDE(K1, K1) = PROPS(1)*GROW
      END DO
      STATEV(2) = GROW
      RETURN
      END
"""


def _lift(tmp_path: Path, text: str):
    source = tmp_path / "toy.for"
    source.write_text(text, encoding="utf-8")
    contract = GenericPSContract(
        name="toy", umat_source_path=source, parameters=(("E", 1),), parameter_values=(100.0,),
        state_variables=(("A", 1), ("B", 2)), ntens=6, nstatv=2, ndi=3, nshr=3,
        dstran_per_increment=(0.0,) * 6, n_increments=1, static_props=(100.0,))
    return transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path / "ps", extra_directions=2)


def test_the_lifted_build_lists_each_binary32_store_with_its_declaration(tmp_path):
    layout = _lift(tmp_path, _TOY)
    report = layout.binary32_stores
    assert report["schema"] == BINARY32_STORES_SCHEMA and report["present"] is True
    by_name = {row["name"].upper(): row for row in report["stores"]}
    # GROW is on the derivative path; SPARE is declared REAL but never stored.
    assert set(by_name) == {"GROW"}
    grow = by_name["GROW"]
    assert grow["declaration_line"] == 12
    assert grow["declarations"] == [{"line": 12, "text": "REAL GROW, SPARE"}]
    assert grow["typed_by"] == "explicit declaration"
    assert grow["rule"] == "B-W" and grow["rounded_stores"] == 1
    assert "double idealisation of a binary32 original" in report["statement"]
    on_disk = json.loads((tmp_path / "ps" / "binary32_stores.json").read_text(encoding="utf-8"))
    assert on_disk == report
    # The list is read off the code: the store it names is in the lifted file.
    lifted = layout.lifted_umat.read_text(encoding="utf-8")
    assert "GROW%R = REAL(REAL(GROW%R, 4), 8)" in lifted.replace("grow", "GROW")


def test_a_source_in_double_precision_lists_nothing(tmp_path):
    layout = _lift(tmp_path, _TOY.replace("      REAL GROW, SPARE\n", ""))
    report = layout.binary32_stores
    assert report["present"] is False and report["stores"] == []
    assert report["rounded_operations"] == 0


def test_the_store_build_shadow_suffix_is_stripped_and_implicit_typing_named():
    generated = "      GROW_OTI = X\n      GROW_OTI%R = REAL(REAL(GROW_OTI%R, 4), 8)\n" \
                "      Z = OTI_R4(A-B)\n"
    report = binary32_store_report(generated, "      IMPLICIT REAL (A-Z)\n")
    assert [row["name"] for row in report["stores"]] == ["GROW"]
    assert report["stores"][0]["declaration_line"] is None
    assert report["stores"][0]["typed_by"] == "implicit typing"
    assert report["rounded_operations"] == 1


def test_the_derivative_manifest_carries_the_field(tmp_path):
    source = tmp_path / "toy.for"
    source.write_text(_TOY, encoding="utf-8")
    listed = binary32_store_report("      GROW%R = REAL(REAL(GROW%R, 4), 8)\n", _TOY)
    manifest = build_manifest(source_path=source, entry_routine="UMAT", ntens=6, nstatv=2,
                              nprops=1, requests=(), binary32_stores=listed)
    assert manifest[BINARY32_STORES_FIELD] == listed
    assert manifest[BINARY32_STORES_FIELD]["stores"][0]["declaration_line"] == 12
    unassessed = build_manifest(source_path=source, entry_routine="UMAT", ntens=6, nstatv=2,
                                nprops=1, requests=())
    assert unassessed[BINARY32_STORES_FIELD]["present"] is None
