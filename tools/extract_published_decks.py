#!/usr/bin/env python3
"""Deck fragments an author published somewhere other than a .inp file.

The pairing looks for material constants in ``.inp`` decks, because that is
where they usually are. It is not the only place. Some authors publish the
material block in the repository's own documentation -- a fenced ``abaqus``
block in a README, a reference page, an example script -- and a corpus that
looked only at decks was reporting where it looked rather than what exists.

Measured on ``jasonanewcoder/abaqus_skills``: 98 files, not one of them a
``.inp``, and
``abaqus_subroutine_skills/reference/material/umat_elastic.md`` carries

    *Material, name=Steel_Elastic
    *User Material, constants=2
    ** E, NU
    210000.0, 0.3

which is exactly the two constants ``umat_elastic_official.f`` reads.

What this does is narrow on purpose. It copies the KEYWORD BLOCK out, verbatim,
into a ``.inp`` beside the file it came from, with a header naming the file and
the lines. Nothing is interpreted, nothing is converted, and no value is
carried across that was not written as an Abaqus material keyword by the
author. The existing pairing then reads it with the same parser it reads every
other deck with, and its provenance names the document.

    tools/extract_published_decks.py --cache-dir <discovery cache>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO.parent / "discovery_cache")

#: Where a published block might be written down. Not .inp: those are already
#: read as decks.
DOCUMENT_SUFFIXES = (".md", ".rst", ".txt", ".py", ".m", ".dat", ".csv")

#: The suffix an extracted fragment is written with, so the pairing reads it
#: and a reader can tell at a glance that it was extracted.
EXTRACTED = ".extracted.inp"

_KEYWORD = re.compile(r"^\s*\*(?!\*)\s*([A-Za-z][^,\n]*)", re.IGNORECASE)
_MATERIAL = re.compile(r"^\s*\*\s*material\b", re.IGNORECASE)
_USER_MATERIAL = re.compile(r"^\s*\*\s*user\s+material\b", re.IGNORECASE)

#: A data line under a keyword: numbers, possibly with a trailing comma.
_DATA = re.compile(r"^\s*[-+0-9.][^A-Za-z]*$")

#: Keywords that belong to a material definition and may be carried with it.
_MATERIAL_KEYWORDS = ("MATERIAL", "USER MATERIAL", "DEPVAR", "DENSITY",
                      "ELASTIC", "PLASTIC", "EXPANSION", "CONDUCTIVITY",
                      "SPECIFIC HEAT", "USER OUTPUT VARIABLES", "ORIENTATION")


def _keyword_of(line: str) -> str:
    found = _KEYWORD.match(line)
    if not found:
        return ""
    return " ".join(found.group(1).split()).upper()


def blocks(text: str) -> list:
    """Every ``*Material`` block in this text, with the lines it spans.

    A block begins at a ``*Material`` line and runs while the lines are either
    data or one of the material keywords. It ends at the first keyword that is
    not one of those, or at the first line that is neither -- prose, a fence, a
    blank followed by prose.
    """
    lines = text.splitlines()
    found: list = []
    index = 0
    while index < len(lines):
        if not _MATERIAL.match(lines[index]) or _USER_MATERIAL.match(lines[index]):
            index += 1
            continue
        start = index
        end = index
        index += 1
        while index < len(lines):
            line = lines[index]
            keyword = _keyword_of(line)
            if keyword:
                if keyword not in _MATERIAL_KEYWORDS:
                    break
                end = index
                index += 1
                continue
            if line.strip().startswith("**") or _DATA.match(line):
                end = index
                index += 1
                continue
            break
        block = lines[start:end + 1]
        if any(_USER_MATERIAL.match(line) for line in block):
            found.append((start + 1, end + 1, "\n".join(block)))
    return found


def extract(path: Path, cache_root: Path) -> Optional[dict]:
    """Write one file's material blocks out as a deck beside it."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    found = blocks(text)
    if not found:
        return None
    relative = path.relative_to(cache_root)
    header = [
        "*HEADING",
        f"material blocks extracted verbatim from {relative}",
        "** Extracted by tools/extract_published_decks.py. Nothing here was",
        "** interpreted or converted: these are the author's own Abaqus",
        "** material keywords, copied out of the file named above so that the",
        "** same parser that reads every other deck can read them.",
    ]
    body: list = []
    for first, last, block in found:
        body.append(f"** from {relative} lines {first}-{last}")
        body.append(block)
    target = path.with_suffix(path.suffix + EXTRACTED)
    target.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    return {"source_document": str(relative),
            "deck": str(target.relative_to(cache_root)),
            "blocks": len(found),
            "lines": [[first, last] for first, last, _ in found]}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--manifest", type=Path,
                        default=REPO / "paper_results/corpus/extracted_decks.json")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)

    cache = Path(args.cache_dir)
    written: list = []
    for suffix in DOCUMENT_SUFFIXES:
        for path in sorted(cache.rglob(f"*{suffix}")):
            if EXTRACTED in path.name or args.only.lower() not in str(path).lower():
                continue
            record = extract(path, cache)
            if record:
                written.append(record)
                print(f"  {record['deck']}  ({record['blocks']} block(s) from "
                      f"{record['source_document']})")
    manifest = {
        "what_this_is": (
            "Abaqus material keyword blocks copied verbatim out of files that "
            "are not decks -- documentation, reference pages, model scripts -- "
            "so that the pairing can read them with the same parser it reads "
            "decks with. Nothing was interpreted or converted."),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cache_root_name": cache.name,
        "extracted": written,
        "count": len(written),
    }
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=1) + "\n",
                                   encoding="utf-8")
    print(f"  {len(written)} document(s) carried a material block; "
          f"wrote {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
