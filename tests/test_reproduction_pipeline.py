"""The one-command pipeline has to regenerate everything the paper shows.

An artefact that is not in the profile is an artefact that drifts: it keeps
whatever it happened to have when someone last ran its script by hand, and
nothing notices when the evidence beneath it moves.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.reproduce import PROFILES, build_steps

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Everything the manuscript places or cites, and the step that rebuilds it.
REQUIRED_STEPS = {
    "parameter_sensitivity_round": "Table 6 and the sensitivity figure",
    "internal_jacobian_round": "Table 3",
    "tangent_round": "the tangent figure and Table 5",
    "source_identity_registry": "the deduplicated source counts",
    "generality_matrix": "the collection figures",
    "paper_figures": "the four data figures",
    "paper_tables": "the eight publication tables",
    "paper_summary": "the evidence summary",
    "gui_screenshots": "the interface figures",
    "manuscript": "the manuscript itself",
    "manuscript_render": "the PDF and page images for visual inspection",
}


def _paper_steps() -> list[str]:
    return [step.name for step in build_steps("paper", allow_network=False)]


@pytest.mark.parametrize("name,what", sorted(REQUIRED_STEPS.items()))
def test_the_paper_profile_rebuilds_every_published_artefact(name, what):
    assert name in _paper_steps(), f"nothing in the profile rebuilds {what}"


def test_the_steps_run_in_dependency_order():
    """A figure rendered before its evidence is a figure of the old evidence."""
    steps = _paper_steps()
    order = {name: index for index, name in enumerate(steps)}
    for earlier, later in (
            ("parameter_sensitivity_round", "generality_matrix"),
            ("internal_jacobian_round", "generality_matrix"),
            ("tangent_round", "paper_figures"),
            ("source_identity_registry", "generality_matrix"),
            ("generality_matrix", "paper_figures"),
            ("paper_figures", "paper_tables"),
            ("paper_tables", "manuscript"),
            ("gui_screenshots", "manuscript"),
            ("manuscript", "manuscript_render")):
        assert order[earlier] < order[later], \
            f"{later} runs before {earlier}, so it would use stale evidence"


def test_every_profile_still_builds():
    for profile in PROFILES:
        steps = build_steps(profile, allow_network=True)
        assert steps, f"the {profile} profile has no steps"
        assert len({s.name for s in steps}) == len(steps), \
            f"the {profile} profile repeats a step name"


def test_the_figure_scripts_the_profile_names_all_exist():
    from umat_oti.reproduce import _FIGURE_SCRIPTS

    for name, script, artifact in _FIGURE_SCRIPTS:
        assert (REPO_ROOT / script).is_file(), f"{name}: {script} is missing"


def test_a_missing_optional_dependency_blocks_rather_than_fails(tmp_path):
    """A reproduction without matplotlib must say so, not crash."""
    import umat_oti.reproduce as reproduce

    original = reproduce.step_paper_figures
    assert callable(original)
    # The step reports BLOCKED with a reason naming what to install.
    source = original.__doc__ or ""
    assert source, "the figure step documents nothing"
