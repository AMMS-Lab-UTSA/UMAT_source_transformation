"""A plain sentence and a next action for every refusal a command-line user meets.

The pipeline's own refusal text is evidence written for the people who maintain
it ("anchors not located: missing_stress_update_regions", "stress_path_consumes
_the_seed"). A mechanics student who has just run ``umat-oti`` reads those and
cannot tell three things: what is wrong in one sentence, whose move it is, and
what to fetch or type next. This module answers those three, and nothing else.
It never rewrites the evidence: the original reason stays beside the card.

* :func:`card_for` takes a terminal state and the reason text the run recorded
  and returns a :class:`Card`.
* The rules are tried in order, most specific first. A rule that matches names
  itself in ``Card.rule``; the fall-back is the per-state card
  (``state:<name>``), and only a state this module has never heard of reaches
  the ``default`` card -- which says so, and which a test forbids any record in
  the corpus registry from reaching.
* Every card says whose move it is, in the same three words as
  :data:`umat_oti.app.plain_language.PLAIN`: "you", "the author of this UMAT",
  "this program".
* Flags are the real ones (``--dependency-root``,
  ``--material-config``, ``--material-discovery-root``,
  ``--abaqus-experiment``); a test checks each against the command-line parser.

No default sentence may contain the words :data:`plain_language.EXPERT_TERMS`
forbids; a test runs ``jargon_in`` over every card.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

__all__ = ["Card", "card_for", "STATE_CARDS", "RULES", "FLAGS_USED", "state_after_reading"]

YOU = "you"
AUTHOR = "the author of this UMAT"
PROGRAM = "this program"

#: Every command-line flag the cards name. A test asserts each one exists.
FLAGS_USED = ("--dependency-root",
              "--material-config", "--material-discovery-root",
              "--abaqus-experiment", "--peak", "--props")


@dataclass(frozen=True)
class Card:
    rule: str            # which rule matched; "default" means none did
    sentence: str        # what is wrong, in one plain sentence
    whose_move: str      # "you" | "the author of this UMAT" | "this program"
    next_action: str     # what to fetch, type or do next

    def lines(self) -> list:
        return [self.sentence,
                f"Whose move: {self.whose_move}.",
                f"Next: {self.next_action}"]


def _names(text: str, pattern: str, default: str = "a routine") -> str:
    m = re.search(pattern, text or "")
    if not m:
        return default
    raw = m.group(1)
    names = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw)
    names = [n for n in names if n.upper() not in {"AND", "OR"}] or [raw]
    shown = ", ".join(names[:4]) + (" and others" if len(names) > 4 else "")
    return shown


# ---------------------------------------------------------------------------
# rules on the reason text, most specific first
# ---------------------------------------------------------------------------
def _callee(text, state):
    who = _names(text, r"external or undefined callee (\w+)")
    return (
        f"Your routine calls {who}, which is not in the files this program was "
        "given, so it cannot follow the stress calculation through it.",
        YOU,
        f"Find the file that defines {who} (it is usually another .f or .for "
        "file from the same project) and put it beside your UMAT, or give its "
        "folder with --dependency-root FOLDER. If it is an Abaqus library routine or the "
        "author never published it, ask the author for it.")


def _defs(text, state):
    who = _names(text, r"requires source definitions for \[([^\]]*)\]")
    return (
        f"Your routine calls {who}, and no file with their code was given.",
        YOU,
        f"Put the file(s) that define {who} beside the UMAT or name their "
        "folder with --dependency-root FOLDER. The code is normally in the same repository as "
        "the UMAT; if it is not published there, ask the author.")


def _module_use(text, state):
    mod = _names(text, r"USEs ([\w, ]+?) without defining", "a shared-definitions file")
    who = _names(text, r"^(\w+) appears as", "a name")
    return (
        f"The stress calculation uses {who}, which is defined in a shared-definitions "
        f"file called {mod} (a Fortran 'module'), and that file was not given, so "
        "the program cannot tell what it is.",
        YOU,
        f"Put the file that defines {mod} (look for the line 'module {mod}' in the "
        "same project) beside your UMAT, or name its folder with "
        "--dependency-root FOLDER. Then run again.")


def _module_var(text, state):
    mod = _names(text, r"variable of module (\w+)", "a shared-definitions file")
    return (
        f"The stress calculation reads a value that lives in the shared-definitions "
        f"file {mod} (a Fortran 'module'), which this program does not follow.",
        PROGRAM,
        "Nothing is missing on your side. Reading values through a shared "
        "file like that is not supported yet. If you can, pass the value into the "
        "routine as an argument or a constant; otherwise send the file to the "
        "maintainers so it is recorded as not supported yet.")


def _include(text, state):
    who = _names(text, r"INCLUDE '([^']+)'", "an include file")
    return (
        f"The routine includes the file {who}, which was not given.",
        YOU,
        f"Put {who} beside your UMAT, or name its folder with "
        "--dependency-root FOLDER.")


def _delegates(text, state):
    who = _names(text, r"delegates its whole body to (\w+)")
    return (
        f"The routine only hands its work to {who}, and {who} is not in the "
        "files given, so there is no stress calculation here to follow.",
        YOU,
        f"Add the file that defines {who} next to the UMAT, or give its "
        "folder with --dependency-root FOLDER.")


def _anchor_args(text, state):
    return (
        "This routine's header does not use the standard Abaqus argument "
        "names, so this program cannot tell which argument is the strain "
        "increment and which is the stress.",
        PROGRAM,
        "Nothing is wrong with your file. Either rename the arguments of the "
        "UMAT line to Abaqus's standard names from the Abaqus "
        "manual in a copy and run again, or send the file "
        "to the maintainers so it is recorded as not supported yet.")


def _anchor(text, state):
    return (
        "This program could not find where the routine sets the stress and "
        "the stiffness, so it does not know what to differentiate.",
        PROGRAM,
        "Nothing is wrong with your file. Send it to the maintainers so it is "
        "recorded as not supported yet. Do not try to fill in line numbers by "
        "hand: that is not needed for any supported routine.")


def _seed(text, state):
    return (
        "In this routine the stress does not visibly depend on the strain "
        "increment (it may reach it through a shared COMMON block, a shared-definitions "
        "file or a call this program cannot see), so the derivative would come "
        "out wrong.",
        PROGRAM,
        "Check that the stress is computed from the strain increment or the deformation gradient in the "
        "routine itself or in a routine in the files you give with "
        "--dependency-root. If it is, send the file to the maintainers.")


def _semantic(text, state):
    name = _names(text, r"Semantic check failed: (\w+)", "a check")
    return (
        "A safety check on the converted code failed, so the program refuses "
        "to go on rather than give a derivative it cannot trust "
        f"(check: {name}).",
        PROGRAM,
        "Nothing is wrong with your file as far as this program can tell. "
        "Send it to the maintainers with the check name so it is recorded as "
        "not supported yet.")


def _unsupported_construct(text, state):
    return (
        "The routine uses a Fortran construct this program cannot "
        "differentiate yet (for example a vector SUM with DIM or MASK, an "
        "array of unknown size, EQUIVALENCE, or a routine that is passed the "
        "differentiated value).",
        PROGRAM,
        "If you can, rewrite that statement in a plain form (explicit loops, "
        "fixed array sizes) in a copy and run again; otherwise send the file "
        "to the maintainers so it is recorded as not supported yet.")


def _not_lifted(text, state):
    who = _names(text, r"is passed to (\w+)")
    return (
        f"A differentiated quantity is passed to {who}, which this program "
        "could neither convert nor find, so the chain of derivatives stops "
        "there.",
        YOU,
        f"If {who} is in another file, put it beside the UMAT or give its "
        "folder with --dependency-root FOLDER. If it is already there, the "
        "call form is not supported yet: send the file to the maintainers.")


def _scalar_stress(text, state):
    return (
        "This routine has a single stress value per point (a truss or "
        "one-dimensional element), which this program does not handle.",
        PROGRAM,
        "Use a UMAT that returns the full set of stress values (3D, plane strain or "
        "plane stress) for this check; one-value routines are not "
        "supported yet.")


def _lu_eigen(text, state):
    return (
        "The routine solves a linear system or eigenvalue problem with an "
        "Abaqus-style library routine, and differentiating through it can "
        "give a wrong answer where the pivot or the eigenvalue choice "
        "changes.",
        PROGRAM,
        "No action on your side is needed to decide this. Send the file to "
        "the maintainers; a routine that avoids these library calls can be "
        "checked today.")


def _complex_step(text, state):
    return (
        "The routine already computes its own derivative by a complex-step "
        "trick, which cannot be differentiated again by this program.",
        PROGRAM,
        "Use the plain version of the routine, without the complex-step "
        "branch, if the author published one.")


def _no_deck(text, state):
    return (
        "This program could not find the numbers this material needs: "
        "nobody published an input file with a *USER MATERIAL block next to "
        "this routine, so there is nothing that says what it is made of.",
        YOU,
        "Either put an Abaqus input file that uses this material next to the "
        "UMAT (it is read for the constants and the loading), or write the "
        "constants and a loading in a small material file and pass it with "
        "--material-config FILE. If the input file lives elsewhere, point "
        "at its folder with --material-discovery-root FOLDER.")


def _deck_hides_constants(text, state):
    return (
        "The input file beside this routine uses named constants and does "
        "not say what values they have.",
        YOU,
        "Give the values yourself in a material file with "
        "--material-config FILE (one number per constant, in the order the "
        "routine reads them), or add them to the input file.")


def _no_material_found(text, state):
    return (
        "None of the material descriptions found next to this routine can "
        "feed it: it reads more constants or state variables than any of "
        "them provides.",
        YOU,
        "Give the constants and the number of state variables yourself in a "
        "material file with --material-config FILE, or point at the right "
        "input file with --material-discovery-root FOLDER.")


def _needs_initial_state(text, state):
    return (
        "The routine needs a starting state read from a file (for example "
        "grain orientations) that is not available here.",
        YOU,
        "Provide that file next to the UMAT, or describe the starting state "
        "in a material file with --material-config FILE.")


def _material_mismatch(text, state):
    return (
        "The input file beside this routine publishes a material this "
        "routine cannot be run with.",
        YOU,
        "Give the right constants in a material file with "
        "--material-config FILE.")


def _opens_files(text, state):
    return (
        "The routine opens data files from a fixed place on the author's "
        "own computer, and nothing here provides them.",
        YOU,
        "Get the data files from the author, put them where the routine "
        "looks (or change the path in a copy of the routine), and run "
        "again.")


def _uel(text, state):
    return (
        "This file's Abaqus entry point is a different kind of subroutine "
        "(a user element, UEL), not a material, so there is no material "
        "behaviour here to convert.",
        AUTHOR,
        "Use the file that holds the actual material routine (UMAT), if the "
        "project has one.")


def _interface_mismatch(text, state):
    return (
        "A routine is named like an Abaqus material routine but its "
        "arguments are not the Abaqus ones, so it is something else.",
        AUTHOR,
        "Give the file whose UMAT line has the standard Abaqus arguments.")


def _not_umat_file(text, state):
    return (
        "This file does not contain an Abaqus material subroutine as its "
        "entry point (it may be a file of extra subroutines, a shared-definitions "
        "file or another kind of routine).",
        AUTHOR,
        "Give the file that holds the UMAT itself; files with its extra "
        "subroutines go beside it or in --dependency-root FOLDER.")


def _viz_umat(text, state):
    return (
        "This UMAT only exists to display results of a user element; it is "
        "not a material model.",
        AUTHOR,
        "Nothing to do: there is no material here to check.")


def _no_subroutine(text, state):
    return (
        "The file has no complete subroutine or function this program can "
        "read.",
        AUTHOR,
        "Check that you gave the right file (and the whole file). If the file "
        "is a fragment, ask the author for the complete one.")


def _no_compile(text, state):
    return (
        "The routine as published does not compile with the compiler "
        "Abaqus uses, so there is nothing that can be run.",
        AUTHOR,
        "If you can fix the first compiler error shown above in a copy and "
        "run again, do. Otherwise ask the author for a version that builds.")


def _element_not_read(text, state):
    return (
        "The input file uses this material on an element type this "
        "program cannot read the geometry of, so it cannot place a test "
        "point.",
        PROGRAM,
        "Provide a loading of your own with --abaqus-experiment FILE, or "
        "use an input file with a solid, plane-strain or plane-stress "
        "element.")


def _ntens_mismatch(text, state):
    return (
        "The input file calls this material with a different number of "
        "stress values per point than the converted version was built for.",
        YOU,
        "Say how many stress values per point you want checked (for a 3D solid it "
        "is 6) in the material file given with --material-config FILE, or "
        "use an input file with a matching element.")


def _truss_beam(text, state):
    return (
        "The input file uses this material on truss or beam elements, which "
        "call a UMAT with fewer stress values than a solid; this "
        "program does not handle that.",
        PROGRAM,
        "Use an input file with solid or shell elements for this check.")


def _no_constants(text, state):
    return (
        "No constants were found for this material.",
        YOU,
        "Give them in a material file with --material-config FILE, or put an "
        "input file with a *USER MATERIAL block next to the UMAT.")


_FIND_UNSET = ("To find the line, compile your original with "
               "`gfortran -g -fbacktrace -finit-real=snan -ffpe-trap=invalid` and run it: "
               "it stops at the first read of the unset value and prints the line.")


def _undefined(text, state):
    return (
        "The routine reads a value it never sets, so its answer changes "
        "with whatever happens to be in memory and there is no single "
        "answer to check against.",
        AUTHOR,
        "The author has to give that variable a starting value. " + _FIND_UNSET
        + " Set it in a copy and run again, or send the line to the author.")


#: The constants WERE read from the deck, and the model they belong to cannot be checked here.
DISCOVERED_UNSUPPORTED = re.compile(
    r"Discovered (model is not supported|settings cannot be represented|loading is not a prescribed)"
    r"|Experiment the number of stress components must match")


def state_after_reading(state: str, reason: Optional[str]) -> str:
    """``unsupported_formulation`` when the reason says the deck was read but its model is not supported.

    The pipeline files that stage under material settings, which reads as "could not find the
    numbers" -- not true when the numbers were found and the model is the problem.
    """
    if state in ("missing_material_data", "") and DISCOVERED_UNSUPPORTED.search(str(reason or "")):
        return "unsupported_formulation"
    return state


def _discovered(text, state):
    t = str(text or "")
    if "number of stress components must match" in t:
        what = ("this file is written for elements with a different number of stress values per point than "
                "the 3D element this check command runs (for example plane-stress elements have three, a 3D solid six)")
    elif "model is not supported" in t:
        what = ("it is a large-deformation (finite-strain) model, a plane-stress or shell model, "
                "or one with another number of stress values per point than six")
    elif "settings cannot be represented" in t:
        listed = re.search(r"provider:\s*([^\n.]*)", t)
        what = ("the deck asks for something this check cannot represent"
                + (f" ({listed.group(1).strip()})" if listed else ""))
    elif "loading is not a prescribed" in t:
        what = ("its loading is not a prescribed strain history (it uses a body force, a "
                "separation, time alone, a rotation or a clamped face)")
    else:
        what = "its setup is outside what this check can represent"
    return (
        f"Your constants were read from the deck, but this check command (it does not run Abaqus) cannot check this kind of model yet: {what}. "
        "It checks small-deformation three-dimensional solid models (strains of a few percent at most) with six stress values per point "
        "(three normal and three shear).",
        PROGRAM,
        "Nothing is missing from your files and there is nothing to fix on your side: send the file to the "
        "maintainers so it is recorded as not supported by the check command yet. (Only if you can rewrite the "
        "model as a small-deformation 3D solid can this check command run it.)")


RULES: tuple = (
    ("discovered", DISCOVERED_UNSUPPORTED.pattern, _discovered),
    ("anchor_args", r"anchors not located.*own_argument_names|umat_interface_uses_the_authors_own_argument_names", _anchor_args),
    ("anchor", r"anchors not located", _anchor),
    ("seed", r"stress_path_consumes_the_seed", _seed),
    ("semantic", r"Semantic check failed", _semantic),
    ("callee", r"external or undefined callee", _callee),
    ("definitions", r"requires source definitions for", _defs),
    ("include", r"Missing helper INCLUDE", _include),
    ("module_use", r"USEs [\w, ]+? without defining", _module_use),
    ("module_var", r"is a variable of module", _module_var),
    ("delegates", r"delegates its whole body to", _delegates),
    ("not_lifted", r"neither lifted, inlined, nor transformed", _not_lifted),
    ("scalar_stress", r"declared as a scalar in UMAT", _scalar_stress),
    ("lu_eigen", r"DGETRF|DSPEVD|HQR2|built-in (OTI )?(unblocked|Jacobi)|eigenvalue cluster", _lu_eigen),
    ("complex_step", r"complex-step derivative", _complex_step),
    ("construct", r"Unsupported intrinsic|deferred shape|EQUIVALENCE|DATA statement|applies ATAN2|generic the OTI support|dummy the lifted body keeps", _unsupported_construct),
    ("opens_files", r"opens \d+ file\(s\) it requires", _opens_files),
    ("no_deck", r"publishes no deck with a \*USER MATERIAL|no deck", _no_deck),
    ("deck_hides", r"declares \d+ constants and does not publish", _deck_hides_constants),
    ("no_material", r"no material published in .* can feed this routine", _no_material_found),
    ("initial_state", r"needs_initial_state", _needs_initial_state),
    ("material_mismatch", r"publishes a material this routine cannot be run with", _material_mismatch),
    ("uel", r"entry point is SUBROUTINE UEL", _uel),
    ("interface_mismatch", r"shares an Abaqus name but not its interface", _interface_mismatch),
    ("viz_umat", r"visualisation UMAT", _viz_umat),
    ("not_umat_file", r"not a UMAT by the file", _not_umat_file),
    ("no_subroutine", r"defines no SUBROUTINE and no FUNCTION", _no_subroutine),
    ("no_compile", r"does not compile with Abaqus", _no_compile),
    ("element_not_read", r"declares no element of a type whose corners", _element_not_read),
    ("ntens_mismatch", r"stored transform was built for NTENS", _ntens_mismatch),
    ("truss_beam", r"truss elements|beam elements", _truss_beam),
    ("no_constants", r"^no material constants", _no_constants),
    ("undefined", r"undefined_in_original \(D-", _undefined),
)


# ---------------------------------------------------------------------------
# one card per terminal state, for the ones with no more specific rule
# ---------------------------------------------------------------------------
def _c(sentence, whose, action):
    return (sentence, whose, action)


STATE_CARDS: dict = {
    "missing_material_data": _c(
        "This program could not find the numbers this material needs.", YOU,
        "Put an Abaqus input file with a *USER MATERIAL block next to the "
        "UMAT, or give the constants and a loading in a material file with "
        "--material-config FILE."),
    "external_dependency_unavailable": _c(
        "The routine needs a file that was not given.", YOU,
        "Put the missing file beside the UMAT or give its folder with "
        "--dependency-root FOLDER."),
    "transform_refused": _c(
        "This program cannot convert this routine yet.", PROGRAM,
        "Nothing is wrong on your side. Send the file to the maintainers so "
        "it is recorded as not supported yet."),
    "unsupported_formulation": _c(
        "This kind of material or element is not supported yet.", PROGRAM,
        "Use a solid, plane-strain or plane-stress setup, or send the file "
        "to the maintainers."),
    "not_a_umat": _c(
        "This file is not a material subroutine.", AUTHOR,
        "Give the file that holds the UMAT."),
    "published_stub_no_constitutive_content": _c(
        "This file is a template with no material in it.", AUTHOR,
        "Ask the author for the finished routine, or write the material in "
        "yourself: make the routine compute the stress and the stiffness from "
        "the strain increment and the material constants. Then run the same "
        "command again; until then there is nothing to check."),
    "incomplete_or_corrupt_source": _c(
        "The file does not build as published.", AUTHOR,
        "Fix the first compiler error in a copy, or ask the author for a "
        "version that builds."),
    "undefined_in_original": _c(
        "The routine reads a value it never sets, so its answer is not "
        "repeatable.", AUTHOR,
        "The author has to give that value a starting value. " + _FIND_UNSET),
    "waits_for_input": _c(
        "The routine stops to ask for keyboard input, which a batch run "
        "cannot give.", AUTHOR,
        "Remove the read statement in a copy and run again."),
    "experiment_not_generated": _c(
        "This program could not build a loading that makes the material do "
        "anything.", YOU,
        "Give a loading of your own with --abaqus-experiment FILE (for "
        "example a peak strain large enough to reach yield), or an input "
        "file with the steps."),
    "experiment_not_informative": _c(
        "The test loading did not make the material do anything, so the "
        "agreement shown means little.", YOU,
        "Give a stronger loading with --abaqus-experiment FILE, for example "
        "a larger peak strain."),
    "informativeness_not_established": _c(
        "It was never established whether the test loading exercised the "
        "material, so the agreement shown cannot be trusted yet.", YOU,
        "Give a loading known to reach the behaviour you care about with "
        "--abaqus-experiment FILE."),
    "original_job_failed": _c(
        "Your original routine did not run in a simple test.", YOU,
        "Check whether it needs a temperature, a field value or a time "
        "step, and give them in a loading with --abaqus-experiment FILE."),
    "transformed_job_failed": _c(
        "The converted version failed to run; nothing is known to be wrong "
        "with your file.", PROGRAM,
        "Run again; if it fails again send the report folder to the "
        "maintainers."),
    "support_build_failed": _c(
        "A supporting piece of this program failed to build for your "
        "routine.", PROGRAM,
        "Send the report folder to the maintainers."),
    "harness_error": _c(
        "Something inside this program went wrong; nothing is known to be "
        "wrong with your file.", PROGRAM,
        "Run again; if it fails again send the report folder to the "
        "maintainers."),
    "both_builds_non_finite": _c(
        "Both the original and the converted version produced invalid "
        "numbers (not-a-number or infinity) under this loading.", YOU,
        "Use gentler constants or a smaller loading (--material-config FILE "
        "or --abaqus-experiment FILE) and run again."),
    "manifest_refused": _c(
        "The run's setup did not meet this program's rules for a test.",
        PROGRAM,
        "Send the report folder to the maintainers."),
    "arguments_diverged_before_the_routine": _c(
        "The two versions were handed different inputs before reaching your "
        "routine, so they cannot be compared.", PROGRAM,
        "Nothing is wrong with your file. Send the report folder to the "
        "maintainers."),
    "disagreement_not_in_any_recorded_call": _c(
        "The two versions differ, but the difference is not in any call "
        "this program recorded.", PROGRAM,
        "Do not use these results. Send the report folder to the "
        "maintainers."),
    "primal_disagreed": _c(
        "The converted version computes different stresses from your "
        "original.", PROGRAM,
        "Do not use the derivatives. Send the report folder to the "
        "maintainers."),
    "primal_mismatch_explained": _c(
        "The two versions differ by no more than the original differs from "
        "itself when the arithmetic is reordered, but that is an "
        "explanation and not a pass.", PROGRAM,
        "Treat the result as not verified. Send the report folder to the "
        "maintainers if you need it settled."),
    "primal_control_not_decided": _c(
        "The extra comparison that would settle a small difference in "
        "stresses did not run, so the stresses cannot be called equal.",
        PROGRAM,
        "Nothing is wrong with your file and you cannot settle this from "
        "your side; treat the result as not verified. The maintainers' move: "
        "run this one source again on its own with "
        "tools/verify_store_in_abaqus.py, filtered to its name, and read the "
        "control record in the report. To hand it over, send the report "
        "folder with the outcome name shown at the top of the report."),
    "derivative_truncated": _c(
        "Part of the derivative is dropped on the way to the stress, so the "
        "derivatives may be incomplete.", PROGRAM,
        "Do not use the derivatives for the affected constants. Send the "
        "report folder to the maintainers."),
    "tangent_not_verified": _c(
        "The numerical check of the stiffness derivatives did not settle.",
        YOU,
        "In the numerical check (each constant is nudged a little and the change in stress is compared) the stresses "
        "agreed and no derivative disagreed; too few load states "
        "could be judged. Run your command again over other strain ranges: "
        "add --peak 0.005, then --peak 0.05 (--peak is how far the test strains "
        "the material, 0.02 meaning 2 %; it goes with --props and your constants), "
        "and compare. A derivative judged at one range is checked "
        "at that range only. If none settles, treat the derivatives as "
        "unchecked and send the report folder to the maintainers."),
    "not_attempted": _c(
        "This step was not reached.", YOU,
        "Run the command again once the earlier problem is fixed."),
}


_DEFAULT = Card(
    rule="default",
    sentence="This program has no plain-language explanation for this "
             "outcome yet.",
    whose_move=PROGRAM,
    next_action="Send the report folder to the maintainers; do not rely on "
                "this result.")


def card_for(terminal_state: str, reason: Optional[str] = None) -> Card:
    """The card for one refusal: specific rule on the reason, else the state's."""
    text = str(reason or "")
    state = str(terminal_state or "")
    for name, pattern, build in RULES:
        if re.search(pattern, text):
            sentence, whose, action = build(text, state)
            return Card(f"rule:{name}", sentence, whose, action)
    entry = STATE_CARDS.get(state)
    if entry:
        return Card(f"state:{state}", *entry)
    return _DEFAULT
