"""The constitutive Jacobian from four fields and one click.

This is the whole request a material developer has to make: load the UMAT, say how many stress components it has,
and name what to differentiate -- ``STRESS`` with respect to ``DSTRAN``, written
into ``DDSDDE``. Nothing else is typed. In particular the lines that assign the
old tangent are *not* given: the compact contract built here leaves
``replace`` empty, and the transformer's own anchor inference
(:func:`umat_oti.core.transformation_anchors.merge_completed_anchors_into_config`)
locates the DDSDDE output block, exactly as it does for any other contract that
does not name one.

Both front ends reach the transformation through this module and then through
:func:`umat_oti.services.transformation.run_transformation`:

* the GUI screen ``Constitutive Jacobian`` (``streamlit run scripts/app.py``),
* the command ``umat-oti jacobian SOURCE --ntens N --out DIR``.

So the same four fields give the same contract, and the same contract gives the
same generated files. The contract is written next to the output
(``jacobian_contract.json``) so ``umat-oti-config --config`` reproduces the run
from it as well.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from umat_oti.services.transformation import TransformationOptions, run_transformation

#: The defaults the presentation shows. They are the standard consistent
#: tangent of an Abaqus UMAT: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j).
DEFAULT_SEED = "DSTRAN"
DEFAULT_RESPONSE = "STRESS"
DEFAULT_TARGET = "DDSDDE"

#: What each field may be. The seed and the response are variables of the
#: Abaqus UMAT interface; the target is where the derivative is written.
SEED_CHOICES = ("DSTRAN", "DFGRD1")
RESPONSE_CHOICES = ("STRESS",)
TARGET_CHOICES = ("DDSDDE",)

#: NTENS values an Abaqus UMAT is called with: plane stress (3), plane strain
#: and axisymmetric (4), and three-dimensional (6).
NTENS_CHOICES = (3, 4, 6)

CONTRACT_NAME = "jacobian_contract.json"


def jacobian_contract(source: Path | str, *, ntens: int,
                      seed: str = DEFAULT_SEED, response: str = DEFAULT_RESPONSE,
                      target: str = DEFAULT_TARGET, order: int = 1,
                      name: str | None = None) -> dict[str, Any]:
    """The compact contract the four fields stand for.

    ``replace`` is present and empty on purpose: it is the contract's way of
    saying "the tangent block is not named here", which leaves it to the
    transformer's anchor inference. ``promote`` names only the response, which
    must carry derivatives whatever the role classifier suggests; every other
    variable keeps the role the classifier gives it.
    """
    source = Path(source).expanduser().resolve()
    ntens = int(ntens)
    if ntens not in NTENS_CHOICES:
        raise ValueError(f"NTENS must be one of {NTENS_CHOICES}, not {ntens}")
    for label, value, choices in (("seed", seed, SEED_CHOICES),
                                  ("response", response, RESPONSE_CHOICES),
                                  ("target", target, TARGET_CHOICES)):
        if str(value).upper() not in choices:
            raise ValueError(f"{label} must be one of {choices}, not {value!r}")
    if int(order) < 1:
        raise ValueError("order must be at least 1")
    return {
        "name": name or source.stem,
        "description": "Constitutive Jacobian requested from four fields "
                       "(source, NTENS, seed/response/target); tangent block "
                       "located by the transformer's anchor inference.",
        "source": str(source),
        "jacobian": {"seed": seed.upper(), "output": response.upper(),
                     "target": target.upper()},
        "ntens": ntens,
        "order": int(order),
        "promote": [response.upper()],
        "replace": [],
    }


@dataclass
class JacobianRun:
    """What one four-field transformation produced."""

    summary: dict[str, Any]
    exit_code: int
    contract_path: Path
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and bool(self.summary.get("transform_success"))

    @property
    def transformed_source(self) -> Path | None:
        value = self.summary.get("transformed_source")
        return Path(value) if value and Path(value).is_file() else None

    @property
    def drop_in_source(self) -> Path | None:
        artifact = (self.summary.get("artifacts") or {}).get("abaqus_umat") or {}
        value = artifact.get("source")
        return Path(value) if value and Path(value).is_file() else None

    @property
    def text_report(self) -> Path | None:
        path = Path(str(self.summary.get("out_dir", ""))) / "transform_report.txt"
        return path if path.is_file() else None

    def tangent_lines(self) -> list[tuple[int, int]]:
        """The old tangent block(s) the transformer replaced."""
        return [(int(row["start_line"]), int(row["end_line"]))
                for row in self.report.get("tangent_output_regions_replaced") or []
                if isinstance(row, dict) and row.get("start_line")]

    def carried_variables(self) -> list[str]:
        """The variables carried through the derivative (promoted to OTI)."""
        return list(self.report.get("promoted_variables") or [])


def run_jacobian_transform(source: Path | str, out_dir: Path | str, *, ntens: int,
                           seed: str = DEFAULT_SEED, response: str = DEFAULT_RESPONSE,
                           target: str = DEFAULT_TARGET, order: int = 1,
                           name: str | None = None,
                           compile_generated: bool = False) -> JacobianRun:
    """Write the four-field contract beside the output and transform with it."""
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = jacobian_contract(source, ntens=ntens, seed=seed, response=response,
                                 target=target, order=order, name=name)
    contract_path = out_dir / CONTRACT_NAME
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    summary, code = run_transformation(
        contract_path, out_dir, TransformationOptions(compile_generated=compile_generated))
    report: dict[str, Any] = {}
    report_path = Path(str(summary.get("report_path", "")))
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return JacobianRun(summary=summary, exit_code=int(code),
                       contract_path=contract_path, report=report)


def preview_tangent_block(source: Path | str, *, ntens: int,
                          seed: str = DEFAULT_SEED, response: str = DEFAULT_RESPONSE,
                          target: str = DEFAULT_TARGET, order: int = 1) -> dict[str, Any]:
    """What the transformer will detect, before anything is written.

    Runs the same two steps the transformation service starts with -- expand
    the contract, then complete its anchors -- and reports the tangent block and
    the carried variables they settle on. It writes nothing. The transform
    report after the run states the same two things from the transformer's
    side, so a preview that disagreed with it would be visible.
    """
    from umat_oti.core.config_loader import load_project_config_json
    from umat_oti.core.transformation_anchors import (
        anchor_completion_status, merge_completed_anchors_into_config,
    )

    contract = jacobian_contract(source, ntens=ntens, seed=seed, response=response,
                                 target=target, order=order)
    payload = json.dumps(contract).encode("utf-8")
    config = load_project_config_json(payload, origin_path=contract["source"])
    text = Path(contract["source"]).read_text(encoding="utf-8", errors="replace")
    config = merge_completed_anchors_into_config(config, text)
    anchors = config.get("transformation_anchors") or {}
    output = ((anchors.get("old_tangent") or {}).get("output_region") or {})
    roles = config.get("variable_roles") or {}
    carried = sorted(name for name, row in roles.items()
                     if isinstance(row, dict) and row.get("selected_role") == "Promote")
    lines = ([(int(output["start_line"]), int(output["end_line"]))]
             if output.get("start_line") else [])
    kept = _merged([(int(row["start_line"]), int(row["end_line"]))
                    for row in anchors.get("shared_setup_regions_to_keep") or []
                    if isinstance(row, dict)
                    and row.get("role") == "keep_real_required_by_stress_update"])
    extraction = (anchors.get("ddsdde_extraction") or {}).get("insert_after_line")
    return {"tangent_lines": lines, "kept_lines": kept,
            "extraction_after": int(extraction) if extraction else None,
            "carried_variables": carried,
            "anchor_status": anchor_completion_status(config).get("status"),
            "routine": (config.get("source") or {}).get("selected_umat_name")
            or (config.get("source") or {}).get("detected_umat_name") or "UMAT"}


def _merged(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def format_lines(spans: list[tuple[int, int]]) -> str:
    """``[(86, 108)]`` -> ``"86-108"``, the way the screen shows line ranges."""
    return ", ".join(f"{start}-{end}" for start, end in spans) or "(none found)"


def describe_tangent_block(preview: dict[str, Any]) -> str:
    """What happens to the lines that assign DDSDDE, in one line.

    A hand-written tangent after the stress update is *replaced*. An
    assignment the stress update itself reads (an elastic stiffness used as
    the predictor) is *kept*. In both cases the OTI extraction that fills
    DDSDDE is written after the line the anchors name.
    """
    parts = []
    if preview.get("tangent_lines"):
        parts.append(f"{format_lines(preview['tangent_lines'])} replaced")
    if preview.get("kept_lines"):
        parts.append(f"{format_lines(preview['kept_lines'])} kept (read by the stress update)")
    if preview.get("extraction_after"):
        parts.append(f"extraction after line {preview['extraction_after']}")
    return "; ".join(parts) or "(none found)"
