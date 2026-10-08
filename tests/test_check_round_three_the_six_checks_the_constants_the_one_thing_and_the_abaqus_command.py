"""Nico round 3: lines that contradicted themselves, a silent count mismatch, two items under 'one thing', a missing command."""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app import check_command as check                       # noqa: E402
from umat_oti.app import verified_lookup as vl                         # noqa: E402
from umat_oti.app.check_compact import compact_intake                  # noqa: E402
from umat_oti.app.refusal_cards import card_for, state_after_reading   # noqa: E402
from umat_oti.app.verdict_page import render_verdict, verdict_for      # noqa: E402

pytestmark = pytest.mark.unit
HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1 DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,
     2 NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,
     3 NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),PROPS(NPROPS),
     1 DSTRAN(NTENS)
"""
JC = HEAD + """      A=PROPS(1)
      IFLAG=NINT(PROPS(2))
      B=PROPS(3)
      C=PROPS(4)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+(A+B+C)*DSTRAN(I)
      END DO
      RETURN
      END
"""
NEEDS_HELPER = HEAD + """      A=PROPS(1)
      CALL SHEARMOD(A, B)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+B*DSTRAN(I)
      END DO
      RETURN
      END
"""


def _scanner():
    spec = importlib.util.spec_from_file_location("scan_round3", REPO / "tools" / "intake_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _scan(tmp_path, text):
    src = tmp_path / "u.for"
    src.write_text(text)
    return _scanner().scan(src, None)


# ---- 1. the six checks never read as "none ran" when some did, and never list passes as unrun
def test_the_line_names_what_held_what_failed_and_what_was_not_run_and_never_says_none_ran_when_one_did():
    held_one = {"terminal_state": "primal_disagreed", "evidence": {"abaqus_job_completed": True, "primal_agreed": False}}
    text = render_verdict(held_one)
    assert "None of the checks" not in text
    line = [ln for ln in text.splitlines() if ln.startswith("The six checks")][0]
    assert "held: did the Abaqus job run to the end?." in line and "Failed: did both versions compute the same stresses?." in line
    none_ran = render_verdict({"terminal_state": "tangent_not_verified"})
    line = [ln for ln in none_ran.splitlines() if ln.startswith("The six checks")][0]
    assert "held: none. Failed: none. Not run here (they need Abaqus" in line
    for question in ("did the Abaqus job run to the end?", "did the test make the material act?"):
        assert line.index("Not run here") < line.index(question)          # the six are listed ONLY under 'not run'


# ---- 2. a constant used without a plain NAME = PROPS(k) line is listed by number, not left out
def test_every_constant_is_listed_so_the_count_and_the_list_agree(tmp_path):
    found = _scan(tmp_path, JC)
    ask = found.item("props_values").ask
    assert "its 4 constants: A, constant 2, B, C" in ask
    note = found.item("props_names").note
    assert "3 of the 4 constants have a name" in note and "constants 2 " in note
    listed = ask.split("constants: ", 1)[1].split(" (read", 1)[0].split(", ")
    assert len(listed) == 4 == found.item("props_count").value


# ---- 3. plane-stress element: the real cause, in plain words, one next step
def test_a_stress_value_count_mismatch_is_not_reported_as_missing_numbers():
    reason = "Automatic material configuration failed: Experiment the number of stress components must match --ntens."
    assert state_after_reading("missing_material_data", reason) == "unsupported_formulation"
    card = card_for("missing_material_data", reason)
    assert "Your constants were read from the deck" in card.sentence and "plane-stress" in card.sentence
    assert "could not find the numbers" not in card.sentence + card.next_action
    page = render_verdict({"terminal_state": "missing_material_data", "reason": reason})
    assert "could not find the numbers" not in page and "--ntens" not in page and page.splitlines()[1].startswith("RED")
    amber = render_verdict({"terminal_state": "missing_material_data", "reason": reason}, "pass23")
    assert amber.splitlines()[1].startswith("AMBER") and "(run pass23)" in amber


# ---- 4. one thing under 'one thing'; no blank run id
def test_the_intake_asks_one_thing_first_and_names_what_comes_after(tmp_path):
    found = _scan(tmp_path, NEEDS_HELPER)
    text = compact_intake(found)
    bullets = [ln for ln in text.splitlines() if ln.startswith("  - ")]
    assert len(bullets) == 1, text
    assert "Needs you (one thing first):" in text and "SHEARMOD" in bullets[0]
    assert "After that I will also need:" in text


def test_no_row_of_the_digest_table_has_a_blank_run_and_a_blank_run_is_not_printed():
    table = vl.load_table()
    assert all(r["run"] for r in table["rows"])
    row = dict(next(r for r in table["rows"] if r["state"] == "transform_refused"), run="")
    lines = vl.render(vl.judge([row], deck_compared=False), final="blue", table=table)
    assert "run  (" not in lines[0]


# ---- 5. a verified result needs the Abaqus comparison: the command exists and says what it does
def _flags_of_all():
    return subprocess.run([sys.executable, str(REPO / "umat-oti"), "all", "--help"], capture_output=True, text=True, cwd="/").stdout


def test_the_abaqus_command_is_built_from_flags_that_exist_and_names_the_users_files(tmp_path):
    check._RUN.clear()
    check._RUN.update(source=tmp_path / "u.for", deck=tmp_path / "d" / "job.inp", out=tmp_path / "u_check")
    command = check.abaqus_command()
    assert command == (f"umat-oti all {tmp_path / 'u.for'} --material-discovery-root {tmp_path / 'd'} "
                       f"--out {tmp_path / 'u_check'}_abaqus --abaqus")
    helped = _flags_of_all()
    for flag in re.findall(r"--[a-z-]+", command):
        assert flag in helped, flag
    check._RUN["material_config"] = tmp_path / "m.json"
    assert f"--material-config {tmp_path / 'm.json'}" in check.abaqus_command()


@pytest.mark.parametrize("final,says", [("amber", True), ("blue", False), ("red", False), ("green", False)])
def test_the_green_needs_abaqus_line_is_printed_only_after_an_amber_verdict_with_nothing_on_record(tmp_path, capsys, final, says):
    check._RUN.clear()
    check._RUN.update(source=tmp_path / "u.for", deck=None, out=tmp_path / "o", final=final, match=None, elsewhere=None)
    check.print_corpus_record()
    out = capsys.readouterr().out
    assert ("To call this file verified, the six-check Abaqus comparison is needed" in out) is says
    if says:
        assert "umat-oti all" in out and "--abaqus" in out


def test_a_finite_strain_amber_next_step_is_the_command_not_a_rewrite_of_the_model():
    record = {"terminal_state": "missing_material_data",
              "reason": "Automatic material configuration failed: Discovered model is not supported by the small-strain NTENS=6 sensitivity provider."}
    page = render_verdict(record, "pass23", "umat-oti all /x/u.for --out /x/o_abaqus --abaqus")
    nxt = [ln for ln in page.splitlines() if ln.startswith("Next:")][0]
    assert "set it up as a small" not in page
    assert "a verified result for your version needs the six-check Abaqus comparison" in nxt and "umat-oti all /x/u.for" in nxt


# ---- 6. words
def test_the_words_a_novice_cannot_look_up_are_defined_where_they_first_appear(tmp_path):
    from umat_oti.app.check_summary import render as _render  # noqa: F401  (imports cleanly)
    ask = card_for("missing_material_data", "Discovered model is not supported by the small-strain NTENS=6 sensitivity provider.").sentence
    assert "stress values per point (three normal and three shear)" in ask
    assert "(it does not run Abaqus)" in ask and "(strains of a few percent at most)" in ask
    tangent = card_for("tangent_not_verified", "").next_action
    assert "numerical check (each constant is nudged a little" in tangent and "how far the test strains the material" in tangent
    text = " ".join(card_for(s, "").sentence + " " + card_for(s, "").next_action for s in ("tangent_not_verified", "undefined_in_original"))
    assert "finite differences" not in text and "quick check" not in text
    import inspect
    from umat_oti.app import check_summary
    assert "finite differences" not in inspect.getsource(check_summary)


# ---- 7. a UMAT verified with another deck
def test_the_umat_verified_with_another_deck_is_amber_not_red_and_says_which_deck(tmp_path, capsys):
    umat = tmp_path / "u.for"
    umat.write_text("      SUBROUTINE UMAT\n      END\n")
    shear, mine = tmp_path / "ShearUMAT.inp", tmp_path / "Extension.inp"
    shear.write_text("*USER MATERIAL, CONSTANTS=1\n1.\n")
    mine.write_text("*USER MATERIAL, CONSTANTS=1\n2.\n")
    row = {"source_id": "x/u.for", "sha256": vl._digest(umat), "deck": "x/ShearUMAT.inp", "deck_sha256": vl._digest(shear),
           "state": "fully_verified", "run": "pass23", "reason": "", "all_gates_true": True,
           "gates": {g: "true" for g in ("abaqus_job_completed", "all_requested_outputs_present", "complete_history_finite",
                                         "derivatives_verified", "primal_agreed", "mechanically_informative")}}
    table = {"registry_generated": "2026-10-06T18:47:50+00:00", "rows": [row]}
    original = vl.load_table
    vl.load_table = lambda path=None: table
    try:
        check._RUN.clear()
        check.prepare_corpus_record(umat, mine, suppress=False)
        assert check._RUN["elsewhere"] == "pass23" and check._RUN["other_deck"] == "ShearUMAT.inp"
        reason = "Discovered model is not supported by the small-strain NTENS=6 sensitivity provider."
        check.print_card("missing_material_data", reason)
        out = capsys.readouterr().out
        assert "AMBER: VERIFIED ANOTHER WAY" in out and "RED" not in out
        assert "with a different deck (ShearUMAT.inp; run pass23)" in out
        check.print_corpus_record()
        out = capsys.readouterr().out
        assert "On record: this file was verified with a different deck: ShearUMAT.inp (run pass23, 2026-10-06)" in out
        assert "GREEN" not in out
    finally:
        vl.load_table = original
    v = verdict_for({"terminal_state": "missing_material_data", "reason": reason}, "pass23", None, "ShearUMAT.inp")
    assert v["colour"] == "amber" and "different deck (ShearUMAT.inp; run pass23)" in v["sentence"]
