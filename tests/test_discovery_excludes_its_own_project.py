"""A corpus of externally authored sources must not contain the author.

The search query legitimately finds this project's own repository -- it
contains UMAT sources, which is what the query asks for. Admitting it would
make a corpus assembled to show the transformer works on code nobody here
wrote partly a mirror of the thing being measured.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from discover_umat_sources import (  # noqa: E402
    OWN_REPOSITORIES, is_own_repository,
)


def test_this_repository_is_excluded():
    assert is_own_repository("AMMS-Lab-UTSA/UMAT_source_transformation")


def test_the_sibling_repository_is_excluded():
    assert is_own_repository("AMMS-Lab-UTSA/Residual_Assembler")


def test_the_match_ignores_case_and_surrounding_space():
    assert is_own_repository("  amms-lab-utsa/umat_source_transformation  ")


def test_an_unrelated_project_sharing_the_name_is_not_excluded():
    """Matching a bare repository name would refuse someone else's work."""
    assert not is_own_repository("someone-else/UMAT_source_transformation")


def test_a_genuine_external_repository_is_admitted():
    assert not is_own_repository("mholla/growth")


def test_every_listed_name_is_a_full_owner_slash_repository():
    """A bare name here would silently never match and look like a working guard."""
    for name in OWN_REPOSITORIES:
        assert name.count("/") == 1, name
        assert name == name.lower(), f"{name} would never match a lowered input"
