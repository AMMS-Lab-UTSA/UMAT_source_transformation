"""Finding the gh CLI where it is actually installed.

A per-user install under ~/.local/bin is not on a default PATH, so
`shutil.which("gh")` returns nothing and the machine looks like it has no
credentials at all. That failure is not loud: GitHub's code-search endpoint
answers 401 rather than degrading, so an unauthenticated client reads as
"search is unavailable" instead of "you are not logged in", and discovery
quietly stops finding sources.
"""
from __future__ import annotations

import os
import stat

import pytest

from umat_oti.corpus import acquire


@pytest.fixture
def no_environment_token(monkeypatch):
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def _fake_gh(directory, *, token: str = "", exit_code: int = 0):
    """An executable stand-in for the gh CLI."""
    path = directory / "gh"
    path.write_text("#!/bin/sh\n"
                    + (f'printf "%s" "{token}"\n' if token else "")
                    + f"exit {exit_code}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_an_environment_token_wins(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "from-the-environment")
    token, source = acquire._discover_token()
    assert token == "from-the-environment"
    assert "GH_TOKEN" in source


def test_gh_on_the_path_is_used(tmp_path, monkeypatch, no_environment_token):
    _fake_gh(tmp_path, token="path-token")
    monkeypatch.setenv("PATH", str(tmp_path))
    token, source = acquire._discover_token()
    assert token == "path-token"
    assert "gh auth token" in source


def test_gh_only_under_a_fallback_location_is_still_found(
        tmp_path, monkeypatch, no_environment_token):
    """The case that looked like an absent tool."""
    home_bin = tmp_path / ".local" / "bin"
    home_bin.mkdir(parents=True)
    _fake_gh(home_bin, token="fallback-token")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(acquire, "_GH_FALLBACK_PATHS", (str(home_bin / "gh"),))
    token, source = acquire._discover_token()
    assert token == "fallback-token"
    assert str(home_bin / "gh") in source


def test_gh_installed_but_logged_out_says_so(
        tmp_path, monkeypatch, no_environment_token):
    """'Installed but not logged in' is a different problem from 'not installed'."""
    _fake_gh(tmp_path, exit_code=1)
    monkeypatch.setenv("PATH", str(tmp_path))
    token, source = acquire._discover_token()
    assert token is None
    assert "not logged in" in source
    assert "gh auth login" in source


def test_no_gh_anywhere_names_where_it_looked(
        tmp_path, monkeypatch, no_environment_token):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(acquire, "_GH_FALLBACK_PATHS", (str(tmp_path / "nowhere/gh"),))
    token, source = acquire._discover_token()
    assert token is None
    assert "unauthenticated" in source
    assert "nowhere/gh" in source, (
        "a reader who has gh somewhere else needs to know where this looked")


def test_a_directory_named_gh_is_not_an_executable(
        tmp_path, monkeypatch, no_environment_token):
    decoy = tmp_path / ".local" / "bin" / "gh"
    decoy.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(acquire, "_GH_FALLBACK_PATHS", (str(decoy),))
    assert acquire._gh_executable() is None


def test_the_token_is_never_placed_in_the_auth_source_string(
        tmp_path, monkeypatch, no_environment_token):
    """auth_source is printed and written into records; the token is a secret."""
    _fake_gh(tmp_path, token="gho_secretvalue")
    monkeypatch.setenv("PATH", str(tmp_path))
    token, source = acquire._discover_token()
    assert token == "gho_secretvalue"
    assert "gho_secretvalue" not in source
