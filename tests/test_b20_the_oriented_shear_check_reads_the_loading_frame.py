"""B20 FRAME RULE (written before it was run): the oriented family's shear check is evaluated in the
loading's frame, STRAN and STRESS rotated back by the manifest's rotation about the 3 axis; with no
rotation it is the old check."""
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.abaqus import experiment as ex

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.unit

def _isotropic_local(angle, e=0.01, young=100.0):
    """A pure global e11 and the isotropic plane-stress response, both handed to a
    routine in the material frame."""
    c, s = math.cos(angle), math.sin(angle)
    strain_g = (e, 0.0, 0.0)
    stress_g = (young * e, 0.0, 0.0)                 # isotropic: no shear in any frame
    local_strain = [c * c * strain_g[0], s * s * strain_g[0], -2 * c * s * strain_g[0]]
    local_stress = [c * c * stress_g[0], s * s * stress_g[0], -c * s * stress_g[0]]
    local_stress[2] += 1e-9 * young * e              # round-off: never exactly zero
    return {"kind": "result", "STRAN": [0.0] * 3, "DSTRAN": local_strain,
            "STRESS": local_stress}


def test_the_shear_check_reads_the_loading_frame_and_an_isotropic_material_fails_it():
    manifest = SimpleNamespace(orientation_axes=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                               orientation_rotation=(3, 30.0))
    record = _isotropic_local(math.radians(30.0))
    # read in the local frame there is no increment without shear: not measurable
    assert ex.direct_strain_produced_shear([record]).met is None
    # read in the loading frame: an isotropic response gives NO shear -- the check fails
    # (canary: a material that lost its orientation cannot pass it)
    found = ex.direct_strain_produced_shear([record], manifest)
    assert found.met is False and found.magnitude < 1e-9
    # an anisotropic response (a shear stress in the global frame) passes
    coupled = dict(record)
    c, s = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    global_stress = (100.0, 5.0, 40.0)               # sxx, syy, sxy: coupling present
    coupled["STRESS"] = [c * c * global_stress[0] + s * s * global_stress[1] + 2 * c * s * global_stress[2],
                         s * s * global_stress[0] + c * c * global_stress[1] - 2 * c * s * global_stress[2],
                         -c * s * (global_stress[0] - global_stress[1]) + (c * c - s * s) * global_stress[2]]
    assert ex.direct_strain_produced_shear([coupled], manifest).met is True


def test_with_no_rotation_the_shear_check_is_the_old_one():
    manifest = SimpleNamespace(orientation_axes=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                               orientation_rotation=(3, 0.0))
    record = {"kind": "result", "STRAN": [0.0] * 3, "DSTRAN": [0.01, 0.0, 0.0],
              "STRESS": [100.0, 3.0, 20.0]}
    assert ex.direct_strain_produced_shear([record], manifest).met == \
        ex.direct_strain_produced_shear([record]).met is True
    assert ex.material_axis_angle(None) == 0.0 and ex.material_axis_angle(manifest) == 0.0
