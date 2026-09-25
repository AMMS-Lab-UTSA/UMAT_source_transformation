"""Load explicit experiment settings for a generated, unverified trial deck."""

from dataclasses import fields
import argparse
import json
import math
from pathlib import Path

from umat_oti.abaqus.deck import generate_deck
from umat_oti.abaqus.manifest import LoadingSegment, VerificationManifest


def generate_trial_deck(settings: Path | None, *, source: Path, ntens: int,
                        discovery_root: Path | None = None,
                        discovery_report: Path | None = None) -> tuple[str, dict]:
    raw = json.loads(settings.read_text(encoding="utf-8")) if settings else {}
    if not isinstance(raw, dict):
        raise ValueError("Abaqus experiment must be a JSON object.")
    allowed = {field.name for field in fields(VerificationManifest)} - {"source", "bundle"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown Abaqus experiment fields: {', '.join(sorted(unknown))}")
    required = {"props", "material_provenance", "nstatv", "kinematics", "element_type", "loading"}
    incomplete = {key for key in required if raw.get(key) is None
                  or (key != "nstatv" and not raw.get(key))}
    if incomplete and discovery_root is not None:
        from umat_oti.abaqus.experiment import plan

        planned = plan(source.resolve(), discovery_root.resolve())
        if discovery_report is not None:
            discovery_report.parent.mkdir(parents=True, exist_ok=True)
            discovery_report.write_text(json.dumps(planned.as_dict(), indent=2) + "\n")
        if not planned.found or planned.manifest is None:
            reason = planned.experiment.refusal or "No usable material experiment was discovered."
            raise ValueError("Automatic Abaqus material discovery failed: " + reason
                             + ". Property reads identify slots, not their numerical values; "
                             "provide a matching material deck or explicit experiment settings.")
        discovered = planned.manifest.as_dict()
        discovered["props"] = list(discovered["props"])
        discovered.pop("source", None)
        discovered.pop("bundle", None)
        raw = {**discovered, **{key: value for key, value in raw.items() if key not in incomplete}}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"Missing Abaqus experiment fields: {', '.join(sorted(missing))}")
    if raw.get("ntens", ntens) != ntens:
        raise ValueError("Experiment NTENS must match --ntens.")
    if raw["kinematics"] not in {"small strain", "finite"}:
        raise ValueError("Experiment kinematics must be 'small strain' or 'finite'.")
    if type(raw["nstatv"]) is not int or raw["nstatv"] < 0:
        raise ValueError("Experiment nstatv must be a nonnegative integer.")
    if not isinstance(raw["props"], list) or not all(_finite(value) for value in raw["props"]):
        raise ValueError("Experiment props must be a list of finite numbers.")
    if raw.get("nprops", len(raw["props"])) != len(raw["props"]):
        raise ValueError("Experiment nprops must match the number of props.")
    if not isinstance(raw["loading"], list) or not raw["loading"]:
        raise ValueError("Experiment loading must be a nonempty list of segments.")
    segments = []
    for item in raw["loading"]:
        if not isinstance(item, dict):
            raise ValueError("Each loading segment must be an object.")
        try:
            segment = LoadingSegment(**item)
        except TypeError as error:
            raise ValueError(f"Invalid loading segment: {error}") from error
        if (type(segment.increments) is not int or segment.increments < 1
                or not _finite(segment.period) or segment.period <= 0):
            raise ValueError("Loading increments and period must be positive.")
        if (not isinstance(segment.strain, (list, tuple)) or len(segment.strain) != 6
                or not all(_finite(value) for value in segment.strain)):
            raise ValueError("Loading strain must contain six finite engineering-strain components.")
        segments.append(segment)
    data = {**raw, "name": raw.get("name", source.stem), "source": source.resolve(),
            "ntens": ntens, "nprops": len(raw["props"]), "loading": tuple(segments)}
    manifest = VerificationManifest(**data)
    missing_requirements = manifest.missing_requirements()
    if missing_requirements:
        raise ValueError("Incomplete Abaqus experiment: " + "; ".join(missing_requirements))
    return generate_deck(manifest), manifest.as_dict()


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def generate_workflow_deck(settings: Path, *, source: Path, ntens: int) -> tuple[str, dict]:
    from umat_oti.services.complete_workflow import _material_settings
    from umat_oti.validation.parameter_sensitivity_provider import check_path

    material = _material_settings(settings)
    if ntens != 6:
        raise ValueError("The complete workflow requires NTENS=6.")
    increments, _ = check_path({"validation": {"check_path": material["check_path"]}}, ntens)
    targets = increments.cumsum(axis=0)
    manifest = VerificationManifest(
        name=source.stem, source=source.resolve(), element_type="C3D8",
        kinematics="small strain", ntens=ntens, props=tuple(material["props_values"]),
        nprops=len(material["props_values"]), nstatv=material["nstatev"],
        material_provenance=f"Explicit complete-workflow settings: {settings.resolve()}",
        loading=tuple(LoadingSegment(f"increment_{index}", tuple(float(value) for value in target),
                                     increments=1, period=1.0)
                      for index, target in enumerate(targets, start=1)))
    deck = generate_deck(manifest)
    deck = deck.replace("*STEP,", "*INITIAL CONDITIONS, TYPE=TEMPERATURE\nALL, 293.15\n*STEP,", 1)
    record = manifest.as_dict()
    record["trial_temperature"] = 293.15
    record["notice"] = ("Prescribed cumulative strain targets from the standalone check path; "
                        "Abaqus may cut back increments. This is an execution trial, not a sensitivity comparison.")
    return deck, record


def workflow_settings_from_experiment(record: dict) -> dict:
    if record["kinematics"] != "small strain" or record["ntens"] != 6:
        raise ValueError("Discovered model is not supported by the small-strain NTENS=6 sensitivity provider.")
    unsupported = [key for key in ("initial_state_from_user_subroutine", "orientation",
                                   "orientation_axes", "orientation_rotation") if record.get(key)]
    if any(record.get("initial_statev", ())):
        unsupported.append("nonzero initial_statev")
    if record.get("isothermal_temperature") not in (None, 293.15):
        unsupported.append("isothermal_temperature")
    if unsupported:
        raise ValueError("Discovered settings cannot be represented by the standalone provider: "
                         + ", ".join(unsupported))
    increments = []
    previous = [0.0] * 6
    for segment in record["loading"]:
        if any(segment.get(key) for key in ("body_force", "separation", "time_only",
                                           "rotation", "clamped_face")):
            raise ValueError("Discovered loading is not a prescribed strain history supported by the provider.")
        target = segment["strain"]
        count = segment["increments"]
        increment = [(end - start) / count for start, end in zip(previous, target)]
        increments.extend([increment.copy() for _ in range(count)])
        previous = target
    return {"kinematics": "small_strain", "ntens": 6, "nstatev": record["nstatv"],
            "props_values": list(record["props"]), "check_path": {"increments": increments}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    settings_group = parser.add_mutually_exclusive_group()
    settings_group.add_argument("--settings", type=Path)
    settings_group.add_argument("--material-config", type=Path)
    parser.add_argument("--discover-workflow", action="store_true")
    parser.add_argument("--discovery-root", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ntens", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.discover_workflow and args.material_config is not None:
        parser.error("--discover-workflow cannot be combined with --material-config")
    try:
        if args.material_config is not None:
            deck, manifest = generate_workflow_deck(args.material_config, source=args.source, ntens=args.ntens)
        else:
            deck, manifest = generate_trial_deck(
                args.settings, source=args.source, ntens=args.ntens,
                discovery_root=args.discovery_root or args.source.resolve().parent,
                discovery_report=args.out / "abaqus_discovery.json")
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "abaqus_trial.inp").write_text(deck, encoding="utf-8")
        (args.out / "abaqus_experiment.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if args.discover_workflow:
            material = workflow_settings_from_experiment(manifest)
            manifest["workflow_notice"] = (
                "Material values and state size come from the recorded experiment. "
                "Strain targets are interpolated using its increment counts, but the standalone "
                "diagnostic uses unit time increments, temperature 293.15 and zero initial stress/state; "
                "it does not reproduce the original experiment's timing or prove model activation.")
            (args.out / "abaqus_experiment.json").write_text(json.dumps(manifest, indent=2) + "\n")
            (args.out / "material_workflow.json").write_text(json.dumps(material, indent=2) + "\n")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())