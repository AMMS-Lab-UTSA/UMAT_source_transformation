#!/usr/bin/env python3
"""Derive a verification manifest from a source and the deck that feeds it.

A manifest says what a UMAT is made of. The rule this repository works under is
that those numbers are read from something the model's author published and are
never invented, so this tool derives them from a deck rather than offering a
way to type them in: the material constants, their count, the state-variable
count and the symmetry of the tangent all come from the ``*MATERIAL`` block,
and the manifest records which file and which block they came from.

What it cannot derive it refuses to guess. A source with no usable deck gets a
manifest marked ``needs_material_data`` -- which is a result, not a failure.
A model that cannot be run because nobody has established what it is made of
should be reported that way rather than run on numbers somebody made up.

  tools/make_verification_manifest.py --source u.for --deck job.inp \
      --out verification_manifests/u.json

The loading history is a default: a single element driven along a named path.
Pass --strain and --increments to change its size, --shear for simple shear,
and --reverse to add a reversal, which is what makes state evolution visible --
a monotonic path cannot distinguish a model that stores state from one that
recomputes it.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.job_status import blocking_statements      # noqa: E402
from umat_oti.abaqus.manifest import (                          # noqa: E402
    NEEDS_MATERIAL_DATA, VerificationManifest, reverse, simple_shear, uniaxial)
from umat_oti.corpus.abaqus_deck import parse_deck              # noqa: E402


def choose_material(path: Path, name: str | None):
    """The named ``*MATERIAL`` block, or the one with the most constants.

    Choosing the largest is a stated default and not a guess about physics: a
    deck for a user material usually carries exactly one, and when it carries
    more the one feeding the UMAT is the one with the constants. The chosen
    block's name goes into the manifest either way, so a reader can check.
    """
    materials = [m for m in parse_deck(path) if m.props]
    if not materials:
        return None
    if name:
        for material in materials:
            if material.name.upper() == name.upper():
                return material
        return None
    return max(materials, key=lambda m: len(m.props))


def build(args) -> dict:
    source = Path(args.source)
    loading = []
    if args.shear:
        loading.append(simple_shear(args.strain, args.increments))
    else:
        loading.append(uniaxial(args.strain, args.increments))
    if args.reverse:
        loading.append(reverse(loading[0]))

    material = choose_material(Path(args.deck), args.material) if args.deck else None
    if material is None:
        manifest = VerificationManifest(
            name=args.name or source.stem, source=source,
            element_type=args.element, loading=tuple(loading),
            status=NEEDS_MATERIAL_DATA,
            notes=("no *MATERIAL block with constants was found for this source. "
                   "An LLM may propose a candidate manifest; it cannot certify "
                   "that the values are valid."))
        return manifest.as_dict()

    manifest = VerificationManifest(
        name=args.name or source.stem, source=source,
        element_type=args.element,
        kinematics=args.kinematics,
        nprops=len(material.props), props=tuple(material.props),
        nstatv=material.nstatv or 1,
        unsymmetric=material.unsymmetric,
        material_provenance=(
            f"{Path(args.deck).name} *MATERIAL {material.name}: "
            f"{len(material.props)} constants"
            + (f", *DEPVAR {material.nstatv}" if material.nstatv else "")
            + (", UNSYMM" if material.unsymmetric else "")),
        loading=tuple(loading),
        notes=args.notes or "")

    record = manifest.as_dict()
    # A statement that waits for terminal input can hang a solver rather than
    # failing it. Naming it in the manifest means a reader of the result knows
    # the run could stall for a reason that is in the source, not the harness.
    waits = blocking_statements(source.read_text(errors="replace"))
    if waits:
        record["blocking_statements"] = list(waits)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--deck", type=Path, help="a deck whose *MATERIAL feeds it")
    parser.add_argument("--material", help="which *MATERIAL block, by name")
    parser.add_argument("--name")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--element", default="C3D4",
                        help="default: the constant-strain tetrahedron, which "
                             "has one integration point and no hourglass modes")
    parser.add_argument("--kinematics", default="small strain",
                        choices=("small strain", "finite"))
    parser.add_argument("--strain", type=float, default=0.005)
    parser.add_argument("--increments", type=int, default=10)
    parser.add_argument("--shear", action="store_true")
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    record = build(args)
    text = json.dumps(record, indent=1) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out}: {record.get('status')}, "
              f"{len(record.get('props') or [])} constants, "
              f"nstatv {record.get('nstatv')}")
    else:
        print(text)
    return 0 if record.get("status") != NEEDS_MATERIAL_DATA else 3


if __name__ == "__main__":
    raise SystemExit(main())
