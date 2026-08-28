#!/usr/bin/env python3
"""Propose corpus snapshot entries for discovered sources that ship a deck.

A source cannot be verified without a material vector, and for an externally
authored UMAT the only place one is written down is the example deck its
author shipped. Discovery caches both. This pairs them and writes what a
snapshot entry would look like, with every field carrying where it came from.

It proposes. It does not merge, and it does not verify. Two fields are worth
watching in the output:

``material.provenance`` names the deck file and the keyword the constants were
read from, so the vector can be checked against the upstream file by eye. The
numbers are read by :mod:`umat_oti.corpus.abaqus_deck`; if a model was
reachable it may have chosen *which* deck to look at, and the pairing is then
confirmed by arithmetic on counts both the source and the deck declare
independently -- never by the model's say-so.

``loading_path`` is the field this tool will not fill in from a deck. A deck
drives a mesh through boundary conditions; the corpus round drives a single
material point through a strain or deformation-gradient increment, and turning
one into the other is a modelling decision, not a parse. Entries are emitted
with the project's own declared default probe named as a *suggestion*, marked
so, and a reviewer has to accept it before any number rests on it.

    python tools/propose_corpus_entries.py --cache-dir <discovery cache>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.assist import model_from_environment  # noqa: E402
from umat_oti.assist.deck_pairing import pair_source_with_deck  # noqa: E402
from umat_oti.corpus.abaqus_deck import parse_deck  # noqa: E402
from umat_oti.fortran.scanner import analyze_fortran_source  # noqa: E402
from umat_oti.validation.job_builder import (  # noqa: E402
    infer_validation_dimensions_from_source, infer_validation_ntens_from_source,
)

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or Path.home() / "softwarex_work" / "discovery_cache")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "discovery"
LOADING_PATHS = REPO_ROOT / "parameter_sensitivity" / "loading_paths.json"

_FORTRAN = {".f", ".for", ".f90", ".f95", ".ftn"}


def _sources(cache: Path) -> list[Path]:
    return sorted(p for p in cache.rglob("*") if p.suffix.lower() in _FORTRAN)


def _decks(repository_dir: Path) -> list[Path]:
    return sorted(repository_dir.rglob("*.inp"))


def _default_probe() -> dict[str, Any]:
    """The project's own declared probe, named as what it is."""
    if not LOADING_PATHS.is_file():
        return {}
    block = json.loads(LOADING_PATHS.read_text(encoding="utf-8")).get("default") or {}
    return {
        "dstran_per_increment": block.get("dstran_per_increment"),
        "n_increments": block.get("n_increments"),
        "provenance": ("suggested only: the default probe declared in "
                       "parameter_sensitivity/loading_paths.json, which is what "
                       "the benchmark models use. It is not this source's own "
                       "loading history and no result may rest on it until a "
                       "reviewer accepts it."),
        "accepted_by_reviewer": False,
    }


def propose(source: Path, cache: Path, model) -> dict[str, Any]:
    repository_dir = cache / source.relative_to(cache).parts[0]
    relative = source.relative_to(repository_dir)
    entry: dict[str, Any] = {
        "id": f"{repository_dir.name}__{source.stem}",
        "repository": repository_dir.name.replace("__", "/"),
        "source": str(relative),
        "status": "proposed",
    }
    try:
        analysis = analyze_fortran_source(source)
    except Exception as exc:  # noqa: BLE001
        entry.update(status="unreadable", reason=f"{type(exc).__name__}: {exc}")
        return entry
    if not analysis.get("has_subroutine_umat"):
        entry.update(status="not_a_umat",
                     reason="the scanner finds no UMAT subroutine")
        return entry

    text = source.read_text(errors="replace")
    ntens, _why = infer_validation_ntens_from_source(text, fallback_ntens=6)
    nstatv, nprops = infer_validation_dimensions_from_source(
        text, statev_name="STATEV", ntens=ntens)
    entry.update(ntens=ntens, ndi=3, nshr=ntens - 3,
                 nstatv_inferred=nstatv, nprops_inferred=nprops)

    decks = _decks(repository_dir)
    if not decks:
        entry.update(status="no_deck",
                     reason=("the repository ships no .inp deck, so no material "
                             "vector is available and none may be invented"))
        return entry

    proposal = pair_source_with_deck(
        source, decks, expected_nprops=nprops, expected_nstatv=nstatv,
        model=model)
    pairing = proposal.as_dict()
    for key in ("proposed",):
        value = pairing.get(key)
        if isinstance(value, str) and value.startswith(str(cache)):
            pairing[key] = str(Path(value).relative_to(cache))
    pairing["alternatives"] = [
        str(Path(a).relative_to(cache)) if a.startswith(str(cache)) else a
        for a in pairing.get("alternatives", [])]
    metadata = pairing.get("metadata") or {}
    for key in ("model_answer", "model_named"):
        if isinstance(metadata.get(key), str):
            metadata[key] = metadata[key].replace(str(cache) + "/", "")
    entry["pairing"] = pairing
    if proposal.verdict.value != "confirmed":
        entry.update(status="no_matching_deck",
                     reason=(f"no deck supplies {nprops} constants; "
                             f"{proposal.evidence}"))
        return entry

    deck = Path(proposal.confirmed_value())
    materials = [m for m in parse_deck(deck)
                 if m.props and len(m.props) == nprops]
    if not materials:
        entry.update(status="no_matching_deck",
                     reason="the paired deck lost its material on re-read")
        return entry
    material = materials[0]
    record = material.as_dict()
    # Provenance names the deck relative to the cache root. An absolute path
    # records the machine that ran the search, which is not part of the
    # evidence and which audit_repository_standards refuses in a tracked file.
    try:
        deck_shown = str(deck.relative_to(cache))
    except ValueError:
        deck_shown = deck.name
    entry["material"] = {
        "props": record["props"],
        "provenance": (f"{deck_shown}, *Material "
                       f"name={material.name or '(unnamed)'}"
                       + (f" at line {material.line_numbers['user_material']}"
                          if "user_material" in material.line_numbers else "")),
        "nstatv_declared_by_deck": record["nstatv"],
        "meaning": ("not established: the deck gives values, not names. A "
                    "reviewer has to say what these constants mean before any "
                    "result is published against them."),
    }
    entry["loading_path"] = _default_probe()
    entry["status"] = "proposed_needs_review"
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-model", action="store_true",
                        help="never consult a local model, even if one is up")
    args = parser.parse_args(argv)

    sources = _sources(args.cache_dir)
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        print(f"no cached sources under {args.cache_dir}")
        return 2

    model = None if args.no_model else model_from_environment()
    print(f"  {len(sources)} sources; model: {model.name if model else 'none'}")

    entries = [propose(s, args.cache_dir, model) for s in sources]
    by_status: dict[str, int] = {}
    for entry in entries:
        by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1

    ready = [e for e in entries if e["status"] == "proposed_needs_review"]
    summary = {
        "sources": len(entries),
        "by_status": by_status,
        "with_a_material_vector": len(ready),
        "model": model.name if model else "none",
        "model_chose_the_deck_and_was_confirmed": sum(
            1 for e in ready
            if (e.get("pairing") or {}).get("metadata", {}).get("model_was_right")),
        "caveat": (
            "Every entry here is a proposal. The constants are read from the "
            "deck named in each material.provenance, but nothing has been "
            "transformed, compiled, executed or compared, no loading history "
            "has been accepted, and the meaning of the constants is not "
            "established. Nothing may be counted until a reviewer accepts an "
            "entry and the corpus round runs it."),
    }
    print(json.dumps(summary, indent=2))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "proposed_corpus_entries.json").write_text(
        json.dumps({"summary": summary, "entries": entries}, indent=2,
                   sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote {args.out_dir / 'proposed_corpus_entries.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
