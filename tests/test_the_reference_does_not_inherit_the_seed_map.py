"""A reference built from the seed map cannot falsify the seed map.

``difference_tangent`` reads the transform's own seed out of the transformed
file so that it perturbs the right DIRECTION. It then used to add that seed
straight onto DFGRD1 -- which is what the seed itself does -- so the value
under test and the value it was checked against shared a definition of what
their own input meant. The two then agreed, to 1.2e-06 on
``From-2D-to-2D-Axe.for``, about a matrix that is not the one the solver
asked for.

This drives the real ``difference_tangent`` against a stub replay program that
is the Abaqus manual's compressible neo-Hookean -- a model whose consistent
tangent is published, so the right answer is known independently of anything
in this repository.

MEASURED HERE, at ``F = [[1.15, .06, 0], [.02, .95, 0], [0, 0, 1.04]]``, worst
componentwise relative error against that published tangent:

    sweep.seed_map_matrices (what the reference used to be)   ~9.6
    sweep.matrices          (what it is now)                  ~4e-7

MEASURED on real Fortran, offline, on pass9's own recorded states and its own
compiled replay binaries for
``Jeff97__growth-of-shell/.../Example3/Trachea.for``, whose analytic DDSDDE is
the same manual tangent: against the author's own DDSDDE the seed-map
reference sits at 3.000 at every step from 1e-1 to 1e-6, and the corrected one
at 7.12e-06 and 2.40e-06 at the two coarsest, a relative Frobenius residual of
2.33e-12. pass9 recorded that state as "tangent not verified".
"""
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from umat_oti.abaqus.replay import (
    STATE_FILE, DifferenceSweep, ReplayBuild, difference_tangent, read_state,
    write_state)


GRADIENT = [1.15, 0.06, 0.0, 0.02, 0.95, 0.0, 0.0, 0.0, 1.04]
C10, D1 = 1.2e5, 4.0e-6

#: A replay program that is the Abaqus manual's neo-Hookean, in the shape the
#: real driver writes its answer: NTENS, the stress, then DDSDDE row by row.
#: It reads DFGRD1 out of the state file and adds the gradient perturbation
#: file, exactly as the Fortran driver does.
_STUB = '''
import sys
from pathlib import Path

C10, D1 = {c10!r}, {d1!r}

rows = [line.split() for line in
        Path("{state}").read_text().splitlines() if line.strip()]
ntens = int(rows[0][0])
f = [float(v) for v in rows[9][:9]]
if len(sys.argv) > 3:
    pert = [float(v) for line in Path(sys.argv[3]).read_text().splitlines()
            if line.strip() for v in line.split()]
    f = [a + b for a, b in zip(f, pert)]
F = [f[0:3], f[3:6], f[6:9]]

J = (F[0][0] * (F[1][1] * F[2][2] - F[1][2] * F[2][1])
     - F[0][1] * (F[1][0] * F[2][2] - F[1][2] * F[2][0])
     + F[0][2] * (F[1][0] * F[2][1] - F[1][1] * F[2][0]))
s = J ** (-1.0 / 3.0)
G = [[s * F[i][j] for j in range(3)] for i in range(3)]
b = [[sum(G[i][k] * G[j][k] for k in range(3)) for j in range(3)]
     for i in range(3)]
tr = b[0][0] + b[1][1] + b[2][2]
eg = 2.0 * C10 / J
pr = 2.0 / D1 * (J - 1.0)
stress = [eg * (b[i][i] - tr / 3.0) + pr for i in range(3)]
stress += [eg * b[0][1], eg * b[0][2], eg * b[1][2]]

eg23 = eg * 2.0 / 3.0
ek = 2.0 / D1 * (2.0 * J - 1.0)
B = [b[0][0], b[1][1], b[2][2], b[0][1], b[0][2], b[1][2]]
d = [[0.0] * 6 for _ in range(6)]
d[0][0] = eg23 * (B[0] + tr / 3.0) + ek
d[0][1] = -eg23 * (B[0] + B[1] - tr / 3.0) + ek
d[0][2] = -eg23 * (B[0] + B[2] - tr / 3.0) + ek
d[0][3] = eg23 * B[3] / 2.0
d[0][4] = eg23 * B[4] / 2.0
d[0][5] = -eg23 * B[5]
d[1][1] = eg23 * (B[1] + tr / 3.0) + ek
d[1][2] = -eg23 * (B[1] + B[2] - tr / 3.0) + ek
d[1][3] = eg23 * B[3] / 2.0
d[1][4] = -eg23 * B[4]
d[1][5] = eg23 * B[5] / 2.0
d[2][2] = eg23 * (B[2] + tr / 3.0) + ek
d[2][3] = -eg23 * B[3]
d[2][4] = eg23 * B[4] / 2.0
d[2][5] = eg23 * B[5] / 2.0
d[3][3] = eg * (B[0] + B[1]) / 2.0
d[3][4] = eg * B[5] / 2.0
d[3][5] = eg * B[4] / 2.0
d[4][4] = eg * (B[0] + B[2]) / 2.0
d[4][5] = eg * B[3] / 2.0
d[5][5] = eg * (B[1] + B[2]) / 2.0
for i in range(6):
    for j in range(i):
        d[i][j] = d[j][i]

out = ["NTENS 6"] + ["%.17e" % v for v in stress] + ["DDSDDE"]
out += ["%.17e" % d[i][j] for i in range(6) for j in range(6)]
Path("otis_replay_out.txt").write_text("\\n".join(out) + "\\n")
'''

#: A transformed source carrying nothing but the seed lines the reader looks
#: for. That is all ``seeded_kinematics`` reads.
_SEEDED = """      DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1
      DFGRD1_OTI(2,2) = DFGRD1_OTI(2,2) + OTI_E2
      DFGRD1_OTI(3,3) = DFGRD1_OTI(3,3) + OTI_E3
      DFGRD1_OTI(1,2) = DFGRD1_OTI(1,2) + 0.5D0*OTI_E4
      DFGRD1_OTI(2,1) = DFGRD1_OTI(2,1) + 0.5D0*OTI_E4
      DFGRD1_OTI(1,3) = DFGRD1_OTI(1,3) + 0.5D0*OTI_E5
      DFGRD1_OTI(3,1) = DFGRD1_OTI(3,1) + 0.5D0*OTI_E5
      DFGRD1_OTI(2,3) = DFGRD1_OTI(2,3) + 0.5D0*OTI_E6
      DFGRD1_OTI(3,2) = DFGRD1_OTI(3,2) + 0.5D0*OTI_E6
"""


def _worst_relative(exact, other):
    scale = max(abs(value) for row in exact for value in row)
    floor = 1.0e-8 * scale
    worst = 0.0
    for i, row in enumerate(exact):
        for j, value in enumerate(row):
            denominator = abs(value) if abs(value) > floor else scale
            worst = max(worst, abs(value - other[i][j]) / denominator)
    return worst


@pytest.fixture()
def replayed(tmp_path):
    """A work directory the real ``difference_tangent`` can drive."""
    work = tmp_path / "replay"
    work.mkdir()
    write_state({
        "NTENS": 6, "NSTATV": 1, "NPROPS": 2, "NDI": 3, "NSHR": 3,
        "STRESS0": [0.0] * 6, "STATEV0": [0.0], "STRAN": [0.0] * 6,
        "DSTRAN": [0.0] * 6, "PROPS": [C10, D1], "DTIME": [1.0],
        "TEMP": [293.15, 0.0], "TIME": [0.0, 0.0],
        "DFGRD0": list(GRADIENT), "DFGRD1": list(GRADIENT),
        "DROT": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "COORDS": [0.3, 0.7, 0.5, 1.0],
        "element": 1, "point": 1, "step": 1, "increment": 1,
    }, work / STATE_FILE)

    program = work / "stub_replay"
    program.write_text("#!" + sys.executable + "\n"
                       + _STUB.format(c10=C10, d1=D1, state=STATE_FILE))
    program.chmod(program.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)

    transformed = tmp_path / "transformed.for"
    transformed.write_text(_SEEDED)
    return work, ReplayBuild(program=program, ok=True), transformed


def test_the_corrected_reference_recovers_the_published_tangent(replayed):
    work, build, transformed = replayed
    sweep = difference_tangent(build, work, 6, (1e-3, 1e-4, 1e-5),
                               scale=1.0, transformed_source=transformed)
    assert sweep.ok, sweep.reason
    assert sweep.driven_through == "deformation gradient"
    exact = sweep.original_tangent          # the stub's own analytic DDSDDE
    errors = {step: _worst_relative(exact, matrix)
              for step, matrix in sweep.matrices.items()}
    assert min(errors.values()) < 1e-5, errors
    assert sum(1 for e in errors.values() if e < 1e-4) >= 2, errors


def test_the_seed_map_difference_is_kept_and_is_a_different_matrix(replayed):
    work, build, transformed = replayed
    sweep = difference_tangent(build, work, 6, (1e-3, 1e-4, 1e-5),
                               scale=1.0, transformed_source=transformed)
    exact = sweep.original_tangent
    seed_errors = {step: _worst_relative(exact, matrix)
                   for step, matrix in sweep.seed_map_matrices.items()}
    assert set(seed_errors) == set(sweep.matrices)
    assert min(seed_errors.values()) > 1.0, seed_errors
    # Flat across three decades: a definition, not a truncation error.
    spread = max(seed_errors.values()) - min(seed_errors.values())
    assert spread / max(seed_errors.values()) < 1e-3, seed_errors


def test_the_record_names_how_the_reference_was_built(replayed):
    work, build, transformed = replayed
    sweep = difference_tangent(build, work, 6, (1e-4,), scale=1.0,
                               transformed_source=transformed)
    assert "eps.F" in sweep.reference_definition
    assert "sigma_ij delta_kl" in sweep.reference_definition


def test_a_strain_driven_source_is_untouched(replayed):
    # No DFGRD1 seed: the perturbation is DSTRAN, there is no gradient to push
    # through and no Kirchhoff term to add, and the two matrices coincide.
    work, build, _transformed = replayed
    strain_seeded = work.parent / "strain.for"
    strain_seeded.write_text(
        "      DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1\n")
    sweep = difference_tangent(build, work, 6, (1e-4,), scale=1.0,
                               components=(1,),
                               transformed_source=strain_seeded)
    assert sweep.driven_through == "strain increment"
    assert sweep.reference_definition == "d STRESS / d DSTRAN"
    for step, matrix in sweep.matrices.items():
        assert matrix == sweep.seed_map_matrices[step]


def test_a_state_file_with_no_gradient_refuses_to_half_correct(replayed):
    work, build, transformed = replayed
    (work / STATE_FILE).write_text("6 1 2 3 3\n")
    sweep = difference_tangent(build, work, 6, (1e-4,), scale=1.0,
                               transformed_source=transformed)
    assert not sweep.ok or "uncorrected" in sweep.reference_definition
    assert any("Kirchhoff" in note for note in sweep.failures), sweep.failures


def test_the_state_reader_returns_the_gradient_it_was_given(tmp_path):
    path = tmp_path / STATE_FILE
    write_state({"NTENS": 4, "NSTATV": 2, "NPROPS": 1, "NDI": 3, "NSHR": 1,
                 "DFGRD1": list(GRADIENT), "PROPS": [1.0]}, path)
    state = read_state(path)
    assert state["NTENS"] == 4 and state["NDI"] == 3
    assert state["DFGRD1"] == pytest.approx(GRADIENT)


def test_the_state_reader_says_nothing_rather_than_guessing(tmp_path):
    assert read_state(tmp_path / "absent.txt") == {}
    short = tmp_path / "short.txt"
    short.write_text("6 1 2 3 3\n")
    assert read_state(short) == {}


def test_the_sweep_carries_the_new_fields_by_default():
    sweep = DifferenceSweep()
    assert sweep.seed_map_matrices == {}
    assert sweep.reference_definition == "d STRESS / d DSTRAN"


def test_the_stub_is_executable_where_it_is_written(replayed):
    work, build, _transformed = replayed
    assert os.access(build.program, os.X_OK)
    assert Path(build.program).read_text().startswith("#!")
