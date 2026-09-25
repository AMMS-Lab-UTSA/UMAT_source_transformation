import json
import shutil
import subprocess

import pytest

from umat_oti.transform.source_transform import _directions_required


def combined_config(count=89):
    return {
        "schema_version": "1.1",
        "parameters": [{"name": f"P{index}", "props_index": index}
                       for index in range(1, count + 1)],
        "derivatives": [
            {"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1},
            {"target": "DSIGMA_DP", "seed": "PROPS", "response": "STRESS", "order": 1},
            {"target": "DSTATEV_DP", "seed": "PROPS", "response": "STATEV", "order": 1},
        ],
    }


def test_combined_directions_deduplicate_stress_and_state_parameters():
    plan = _directions_required(6, combined_config())
    assert plan["total_directions"] == 95
    assert plan["parameter_directions"] == 89
    assert [row["direction"] for row in plan["parameter_slots"]] == list(range(7, 96))
    assert [row["props_index"] for row in plan["parameter_slots"]] == list(range(1, 90))


def test_tangent_only_direction_count_is_unchanged():
    plan = _directions_required(6, {})
    assert plan["total_directions"] == 6
    assert plan["parameter_slots"] == []


def test_parameter_aliases_share_slots_after_local_jacobian_directions():
    config = combined_config(2)
    config["parameters"].append({"name": "P1_ALIAS", "props_index": 1})
    config["extra_jacobian_contracts"] = [{
        "id": "local", "seed": {"variable": "ITERATE", "directions": 2},
        "output": {"variable": "RESIDUAL"},
    }]
    plan = _directions_required(6, config)
    assert plan["total_directions"] == 10
    assert plan["slot_assignments"][0]["slot_end"] == 8
    assert plan["parameter_slots"] == [
        {"name": "P1", "props_index": 1, "direction": 9},
        {"name": "P2", "props_index": 2, "direction": 10},
    ]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("form,count", [("free", 89), ("fixed", 2)])
def test_combined_entry_computes_tangent_and_parameter_history(tmp_path, form, count):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / ("material.f90" if form == "free" else "material.for")
    text = """subroutine umat(stress,statev,ddsdde,dstran,props,ntens,nstatv,nprops)
implicit none
integer :: ntens,nstatv,nprops,component
real(8) :: stress(ntens),statev(nstatv),ddsdde(ntens,ntens),dstran(ntens),props(nprops)
real(8) :: modulus,hardening,state_rate
modulus=props(1)
hardening=props(2)
state_rate=props(nprops)**2
do component=1,ntens
    stress(component)=stress(component)+modulus*dstran(component)+hardening*statev(1)
end do
statev(1)=statev(1)+props(1)*dstran(1)
statev(2)=statev(2)+state_rate
ddsdde=0.0d0
end subroutine umat
"""
    if form == "fixed":
        text = "\n".join("      " + line for line in text.splitlines()) + "\n"
    source.write_text(text)
    raw = {**combined_config(count), "source": str(source), "entry_routine": "UMAT", "ntens": 6}
    raw["material_point_driver"] = {"dstran_per_increment": None, "nstatv": None}
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(raw))
    output = tmp_path / "out"
    summary, code = run_transformation(config_path, output)
    assert code == 0, summary
    assert summary["artifacts"]["parameter_sensitivity_driver"] is None
    interface = summary["artifacts"]["combined_sensitivities"]
    assert interface["directions"]["total_directions"] == 6 + count
    manifest = json.loads((output / "derivative_manifest.json").read_text())
    assert "combined_sensitivity_interface.json" in json.dumps(manifest)
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True, text=True)
    driver = tmp_path / "driver.f90"
    driver.write_text(f"""program check
implicit none
real(8) :: stress(6),statev(2),ddsdde(6,6),dstran(6),props({count}),dsigma(6,{count}),dstate(2,{count})
real(8) :: dstate_de(2,6),df0_dp(3,3,{count}),df1_dp(3,3,{count})
integer :: step,component
stress=0; statev=0; dsigma=0; dstate=0; dstate_de=0
! This material has no deformation gradient to move, so the seeds are zero --
! but they are PASSED. A short actual argument list is undefined behaviour
! that happens to survive while the callee never touches the dummy, which is
! exactly the kind of pass that stops being a pass without warning.
df0_dp=0; df1_dp=0
props=3.0d0; props(1)=2.0d0; dstran=0.1d0
do step=1,2
call umat_with_sensitivities(stress,statev,ddsdde,dstran,props,6,2,{count},dsigma,dstate,dstate_de,df0_dp,df1_dp)
do component=1,6
if(abs(ddsdde(component,component)-2.0d0)>1d-12) stop 1
end do
end do
if(maxval(abs(stress-1.0d0))>1d-12) stop 2
if(maxval(abs(dsigma(:,1)-0.5d0))>1d-12) stop 3
if(maxval(abs(dsigma(:,2)-0.2d0))>1d-12) stop 4
if(abs(dstate(1,1)-0.2d0)>1d-12) stop 5
if(abs(dstate(1,2))>1d-12) stop 6
if(abs(dstate(2,{count})-12.0d0)>1d-12) stop 7
if(abs(statev(2)-18.0d0)>1d-12) stop 8
if(abs(dstate_de(1,1)-2.0d0)>1d-12) stop 10
if(maxval(abs(dstate_de(1,2:6)))>1d-12) stop 11
if(maxval(abs(dstate_de(2,:)))>1d-12) stop 12
stress=0; statev=0
call umat(stress,statev,ddsdde,dstran,props,6,2,{count})
if(maxval(abs(stress-0.2d0))>1d-12) stop 9
end program
""")
    executable = tmp_path / "check"
    subprocess.run(["gfortran", str(driver), *map(str, output.glob("*.o")), "-o", str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)