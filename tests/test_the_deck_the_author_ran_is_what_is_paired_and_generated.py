"""B20 rule H4: pairing and generation carry what the author's deck says.

(a) a routine dimensioned by (NSTATV - a)/b is not fed a *DEPVAR that leaves no whole group;
(b) a USER MATERIAL of another TYPE (THERMAL) is not a UMAT's constants;
(c) *INITIAL CONDITIONS TYPE=SOLUTION values and TYPE=STRESS, USER are carried;
(d) *ORIENTATION keeps the author's SYSTEM.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck import generate_deck
from umat_oti.abaqus.deck_pairing import demanded, materials_in, pair
from umat_oti.abaqus.experiment import plan

pytestmark = pytest.mark.unit

HEAD = """      subroutine umat(stress,statev,ddsdde,sse,spd,scd,rpl,ddsddt,drplde,
     1 drpldt,stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     2 ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,celent,
     3 dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv),ddsdde(ntens,ntens),
     1 stran(ntens),dstran(ntens),props(nprops),coords(3)
"""
TAIL = """      do i=1,ntens
        stress(i)=stress(i)+props(1)*dstran(i)
        ddsdde(i,i)=props(1)
      end do
      return
      end
"""
GRID = HEAD + "      double precision, dimension((nstatv - 4)/7,3,3) :: be\n" \
    "      statev(1) = props(1) + props(2)\n" + TAIL
PLAIN = HEAD + "      statev(1) = props(1) + props(2)\n" + TAIL


def deck(depvar, extra="", constants="    100., 0.3", orient=""):
    return f"""\
*Node
1, 0., 0., 0.
2, 1., 0., 0.
3, 1., 1., 0.
4, 0., 1., 0.
5, 0., 0., 1.
6, 1., 0., 1.
7, 1., 1., 1.
8, 0., 1., 1.
{orient}*Element, type=C3D8H
1, 1, 2, 3, 4, 5, 6, 7, 8
*Elset, elset=ALL
 1,
*Solid Section, elset=ALL, material=MAT{', orientation=Ori-1' if orient else ''}
*Material, name=MAT
*Depvar
    {depvar},
*User Material, constants=2
{constants}
{extra}"""


def repo(tmp_path, source, decks):
    r = tmp_path / "owner__repo"
    r.mkdir()
    (r / "umat.for").write_text(source)
    for name, text in decks.items():
        (r / name).write_text(text)
    return r


def test_a_depvar_that_leaves_no_whole_group_is_refused_and_the_one_that_does_is_paired(tmp_path):
    r = repo(tmp_path, GRID, {"cubeU.inp": deck(10), "cubeUH.inp": deck(11)})
    d = demanded(GRID)
    assert d.statev_grids == ((4, 7),)
    ok, why = d.admits(2, 10)
    assert not ok and "(NSTATV - 4)/7" in why           # PLANTED ERROR: DEPVAR 10 -> zero groups
    assert d.admits(2, 11) == (True, "")
    found = pair(r / "umat.for", r)
    assert found.found and found.material.deck.name == "cubeUH.inp"
    # a routine with no such declaration is paired as before (the deck that is not refused)
    assert demanded(PLAIN).statev_grids == ()


def test_an_over_supplied_block_with_no_whole_group_is_not_readmitted(tmp_path):
    # PLANTED ERROR (the pass24 pairing): the decks publish more constants than the routine names and sit
    # beside it, which re-admits an over-supplied block; its DEPVAR must still leave a whole group.
    three = "    100., 0.3, 0.1"
    r = repo(tmp_path, GRID, {
        "cubeU.inp": deck(10).replace("constants=2", "constants=3").replace("    100., 0.3", three),
        "cubeUH.inp": deck(11).replace("constants=2", "constants=3").replace("    100., 0.3", three)})
    found = pair(r / "umat.for", r)
    assert found.found and found.material.deck.name == "cubeUH.inp" and found.material.depvar == 11
    assert any(where.startswith("cubeU.inp") for where, _ in found.rejected)


def test_a_thermal_user_material_is_not_the_umats_constants(tmp_path):
    text = (deck(1, extra="")
            .replace("*User Material, constants=2\n    100., 0.3",
                     "*User Material, constants=6, type=MECHANICAL\n"
                     "0.64, 29.66, 333.22, 0.69, 100.0, 1.0\n"
                     "*User Material, constants=2, type=THERMAL\n"
                     "1.0, 20.0"))
    p = tmp_path / "m1.inp"
    p.write_text(text)
    (found,) = materials_in(p)
    assert found.constants == 6 and found.values[:6] == (0.64, 29.66, 333.22, 0.69, 100.0, 1.0)


def test_a_material_with_only_a_thermal_block_publishes_no_umat_constants(tmp_path):
    # PLANTED ERROR: the only block is UMATHT's
    text = deck(1).replace("*User Material, constants=2\n    100., 0.3",
                           "*User Material, constants=2, type=THERMAL\n1.0, 20.0")
    p = tmp_path / "m1.inp"
    p.write_text(text)
    assert materials_in(p) == ()


def test_solution_values_and_a_user_stress_card_are_carried(tmp_path):
    cards = ("*Initial Conditions, type=SOLUTION\n"
             "ALL, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0\n"
             "*Initial Conditions, type=STRESS, user\n")
    r = repo(tmp_path, PLAIN, {"job.inp": deck(6, extra=cards)})
    found = plan(r / "umat.for", r)
    assert found.found, found.experiment.refusal
    m = found.manifest
    assert m.initial_statev == (1.0, 1.0, 1.0, 0.0, 0.0, 0.0) and m.initial_statev_provenance
    assert m.initial_stress_from_user_subroutine is True
    text = generate_deck(m)
    assert "*INITIAL CONDITIONS, TYPE=SOLUTION\n" in text
    assert "*INITIAL CONDITIONS, TYPE=STRESS, USER" in text


def test_nothing_is_defaulted_when_the_deck_states_no_initial_condition(tmp_path):
    r = repo(tmp_path, PLAIN, {"job.inp": deck(6)})
    m = plan(r / "umat.for", r).manifest
    assert m.initial_statev == () and not m.initial_stress_from_user_subroutine
    assert "INITIAL CONDITIONS" not in generate_deck(m)


@pytest.mark.parametrize("system", ["CYLINDRICAL", "RECTANGULAR"])
def test_the_authors_orientation_system_is_kept(tmp_path, system):
    orient = (f"*Orientation, name=Ori-1, system={system}\n"
              "0., 0., -0.1, 0., 0., 0.9\n3, 0.\n")
    r = repo(tmp_path, PLAIN, {"job.inp": deck(1, orient=orient)})
    found = plan(r / "umat.for", r)
    assert found.found, found.experiment.refusal
    assert found.manifest.orientation_system == system
    assert f"*ORIENTATION, NAME=LOCAL, SYSTEM={system}" in generate_deck(found.manifest)


@pytest.mark.parametrize("option,expected", [(", HYBRID FORMULATION = TOTAL", "TOTAL"),
                                             (", hybrid formulation=incremental", "INCREMENTAL"),
                                             ("", "")])
def test_the_hybrid_formulation_option_is_carried_as_written_and_never_added(tmp_path, option, expected):
    text = deck(1).replace("*User Material, constants=2", f"*User Material, constants=2{option}")
    r = repo(tmp_path, PLAIN, {"job.inp": text})
    found = plan(r / "umat.for", r)
    assert found.found, found.experiment.refusal
    assert found.manifest.hybrid_formulation == expected
    generated = generate_deck(found.manifest)
    line = next(l for l in generated.splitlines() if l.startswith("*USER MATERIAL"))
    if expected:
        assert f"HYBRID FORMULATION={expected}" in line
    else:
        assert "HYBRID" not in line                    # nothing is added when the author's line has none
