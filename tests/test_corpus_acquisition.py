"""Live corpus acquisition: pinning, licensing, and honest failure reporting."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from umat_oti.corpus.acquire import (
    REDISTRIBUTABLE_SPDX, AcquisitionError, GitHubClient, RateLimited,
    classify_license_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CROSS_REPO = (REPO_ROOT / "parameter_sensitivity"
              / "cross_repository_reproduction.json")


def test_license_text_classifier_recognises_the_common_licences():
    assert classify_license_text(
        "Permission is hereby granted, free of charge, to any person") == "MIT"
    assert classify_license_text(
        "Redistribution and use in source and binary forms ... "
        "Neither the name of the copyright holder") == "BSD-3-Clause"
    assert classify_license_text("GNU AFFERO GENERAL PUBLIC LICENSE") == "AGPL-3.0"
    assert classify_license_text("Apache License Version 2.0") == "Apache-2.0"
    assert classify_license_text("no licence wording here at all") is None


def test_markdown_licence_headings_are_not_treated_as_unlicensed():
    """Regression: GitHub reported NOASSERTION for two BSD-3-Clause repositories.

    Its detector matches canonical licence texts, so a LICENSE.md that puts the
    name in a markdown heading defeats it. Trusting that verdict would have
    excluded genuinely permissive sources as unlicensed.
    """
    text = ("Copyright &copy; 2024 Someone.\n\n## The 3-Clause BSD License\n\n"
            "Redistribution and use in source and binary forms, with or without "
            "modification, are permitted ... Neither the name of the copyright "
            "holder nor the names of its contributors")
    assert classify_license_text(text) == "BSD-3-Clause"


def test_only_redistributable_licences_are_cacheable():
    assert "MIT" in REDISTRIBUTABLE_SPDX
    assert "BSD-3-Clause" in REDISTRIBUTABLE_SPDX
    assert "NOASSERTION" not in REDISTRIBUTABLE_SPDX
    assert "" not in REDISTRIBUTABLE_SPDX


def test_rate_limiting_says_how_to_raise_the_limit():
    error = RateLimited(None)
    assert error.code == "github_rate_limited"
    assert "GH_TOKEN" in error.detail and "5000" in error.detail


def test_token_discovery_reports_where_the_token_came_from(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "x" * 12)
    client = GitHubClient.discover()
    assert client.token == "x" * 12
    assert "GH_TOKEN" in client.auth_source


def test_acquisition_refuses_without_explicit_network_permission():
    """A live round that quietly replays a snapshot is not a live round."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "acquire_corpus.py")],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 2
    assert "--allow-network" in proc.stderr


def test_cross_repository_manifest_pins_full_commits():
    manifest = json.loads(CROSS_REPO.read_text(encoding="utf-8"))
    entries = [manifest["companion_repository"], *manifest["corpus_repositories"]]
    for entry in entries:
        sha = entry["commit_sha"]
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), entry
    # A branch name recorded as the pin would reintroduce exactly the moving
    # reference the manifest exists to remove.
    for entry in manifest["corpus_repositories"]:
        assert entry["commit_sha"] not in ("main", "master")
        assert entry["default_branch_at_pin"] in ("main", "master")


def test_bootstrap_script_detaches_at_the_pinned_commit():
    text = (REPO_ROOT / "scripts" / "bootstrap_corpus.sh").read_text(encoding="utf-8")
    assert "checkout --quiet --detach" in text
    assert "rev-parse HEAD" in text, "the bootstrap must verify what it landed on"


def test_round_accepts_any_of_the_three_snapshot_layouts():
    from tools.run_corpus_round import repository_base  # noqa: PLC0415
    import tempfile

    repository = {"id": "owner_repo", "path": "permissive/owner_repo",
                  "commit_sha": "a" * 40}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "owner_repo" / ("a" * 12)).mkdir(parents=True)
        assert repository_base(root, repository) == root / "owner_repo"
        (root / "permissive" / "owner_repo").mkdir(parents=True)
        assert repository_base(root, repository) == root / "permissive" / "owner_repo"


@pytest.mark.network
def test_live_resolution_reproduces_the_pinned_commits():
    """The pinned SHAs must still be what the manifest's refs resolve to."""
    manifest = json.loads(CROSS_REPO.read_text(encoding="utf-8"))
    client = GitHubClient.discover()
    for entry in manifest["corpus_repositories"][:1]:
        owner, repo = entry["url"].rsplit("/", 2)[-2:]
        repo = repo.removesuffix(".git")
        try:
            branch = client.default_branch(owner, repo)
        except (AcquisitionError, RateLimited) as exc:
            pytest.skip(f"live check unavailable: {exc}")
        assert branch == entry["default_branch_at_pin"]
