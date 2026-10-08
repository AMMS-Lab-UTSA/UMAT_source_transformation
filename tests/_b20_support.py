"""Shared helpers for the B20 transform tests: the corpus recipe on a text, offline."""
import json


def transform_text(tmp_path, text, suffix=".for", ntens=6, include=True):
    """Stage ``text``, scaffold the contract from the scan, transform; returns the report."""
    from umat_oti.app.engine import _build_contract
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / f"material{suffix}"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    config, _finite = _build_contract("material", "auto", "STRESS", "DDSDDE", ntens, 1, source)
    (tmp_path / "contract.json").write_text(json.dumps(config))
    report, _code = run_transformation(tmp_path / "contract.json", tmp_path / "out")
    return report


def failed_checks(report):
    """Names of the semantic checks that failed, plus the blockers' text."""
    failed = sorted(name for name, ok in (report.get("semantic_checks") or {}).items() if ok is False)
    return " ".join(failed + [str(b) for b in report.get("blockers") or []])
