"""Plain-language wording for what the intake scan needs from the user.

``tools/intake_scan.py`` carries default wording and replaces it, key by key,
with :data:`NEEDS` here when this module exists. Each entry has:

* ``ask``     what is needed and why, in one or two sentences;
* ``default`` what will be used if the user says nothing, or that nothing can
  be used;
* ``whose``   whose move it is (the same words as ``refusal_cards``: "you",
  "the author of this UMAT", "this program").

Fields filled in by the scanner: ``{why}`` (routine, element), ``{slots}``
(props_values), ``{names}`` (helpers, includes, modules). No other braces may
appear. Constants (the material values) are never defaulted. No expert
vocabulary: ``jargon_in`` is run over every entry by a test.
"""
from __future__ import annotations

__all__ = ["NEEDS"]

NEEDS: dict = {
    "routine": {
        "ask": "This file does not hold the Abaqus material routine (the "
               "UMAT): {why}.",
        "default": "Nothing can be assumed. Give the file that holds the "
                   "UMAT itself; helper files go beside it or in a folder "
                   "named with --dependency-root FOLDER.",
        "whose": "you or the author",
    },
    "ntens": {
        "ask": "The files do not say how many stress components the routine "
               "is called with.",
        "default": "6, which is right for a solid three-dimensional element. "
                   "Say so if your element is plane strain, plane stress or "
                   "something else, in the material file given with "
                   "--material-config FILE.",
        "whose": "you",
    },
    "element": {
        "ask": "This kind of material or element is not one this program "
               "can run yet: {why}.",
        "default": "Nothing can be assumed. Use a solid, plane-strain or "
                   "plane-stress setup for this check, or send the file to "
                   "the maintainers.",
        "whose": "this program",
    },
    "props_values": {
        "ask": "I could not find the numbers this material "
               "needs: the values of {slots}, in the order the routine "
               "reads them.",
        "default": "None. The constants are never guessed or filled in for "
                   "you. Put an Abaqus input file with a *USER MATERIAL "
                   "block next to the UMAT, or type the values into a "
                   "material file and pass it with --material-config FILE "
                   "(if the input file lives elsewhere, use "
                   "--material-discovery-root FOLDER).",
        "whose": "you",
    },
    "helpers": {
        "ask": "Your routine calls {names}, which are not in the files this "
               "program was given, so it cannot follow the stress "
               "calculation through them.",
        "default": "None. Put the file that defines {names} beside your "
                   "UMAT, or give its folder with --dependency-root FOLDER. "
                   "If it is an Abaqus library routine or was never "
                   "published, ask the author.",
        "whose": "you",
    },
    "includes": {
        "ask": "Your routine includes {names}, which are not in the files "
               "this program was given.",
        "default": "None. Put the file beside your UMAT, or give its folder "
                   "with --dependency-root FOLDER.",
        "whose": "you",
    },
    "modules": {
        "ask": "Your routine uses the module {names}, whose file was not "
               "given, so this program cannot tell what the names it "
               "provides are.",
        "default": "None. Get the file that contains the module (look for "
                   "'module' followed by its name in the same project) and "
                   "put it beside your UMAT, or name its folder with "
                   "--dependency-root FOLDER.",
        "whose": "you",
    },
    "temperature": {
        "ask": "The routine reads the temperature and the files do not "
               "state one.",
        "default": "293.15 (the same for every increment, no heating). "
                   "Change it in the material file given with "
                   "--material-config FILE if it matters for your "
                   "material.",
        "whose": "you",
    },
    "coordinates": {
        "ask": "The routine reads where its material point is in the "
               "model, and no input file gives a mesh.",
        "default": "The origin (0, 0, 0). This is a placeholder and may not "
                   "suit a routine whose answer depends on position; give "
                   "a loading with --abaqus-experiment FILE if it does.",
        "whose": "you",
    },
    "fields": {
        "ask": "The routine reads extra field values (such as a "
               "concentration or a damage field) and no input file says "
               "what they are.",
        "default": "All zero. Give the real values in the loading file "
                   "passed with --abaqus-experiment FILE if your material "
                   "depends on them.",
        "whose": "you",
    },
}
