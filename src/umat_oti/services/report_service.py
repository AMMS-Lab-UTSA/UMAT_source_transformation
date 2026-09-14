"""ReportService: Markdown, HTML and JSON export of any service result.

One renderer for all three formats, over the same
:class:`~umat_oti.services.results.ServiceResult`, so a Markdown report and the
JSON beside it cannot disagree about a number: they are the same dictionary
rendered twice.

The renderers are deliberately dumb. They format; they do not compute. There is
no place in this module where a count is taken, a gate is read, or a verdict is
decided -- if a number is not already in the result, the report does not have it.
"""

from __future__ import annotations

import html as html_module
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.records import utc_now

__all__ = ["FORMATS", "RenderedReport", "ReportService"]

SERVICE = "report"

FORMATS = ("markdown", "html", "json")


@dataclass
class RenderedReport:
    format: str
    path: str = ""
    text: str = ""
    sections: list[str] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return len(self.text.encode("utf-8"))

    def as_dict(self) -> dict:
        return {"format": self.format, "path": self.path,
                "bytes": self.bytes, "sections": list(self.sections)}


def _rows(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a payload into (name, value) rows, keeping nulls visible.

    ``None`` renders as ``not established`` rather than as an empty cell,
    because an empty cell in a table reads as "nothing to report" and a null in
    this project means "nobody established it".
    """
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, (dict, list)):
                out.extend(_rows(item, name))
            else:
                out.append((name, "not established" if item is None else str(item)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            name = f"{prefix}[{index}]"
            if isinstance(item, (dict, list)):
                out.extend(_rows(item, name))
            else:
                out.append((name, "not established" if item is None else str(item)))
    else:
        out.append((prefix or "value",
                    "not established" if value is None else str(value)))
    return out


class ReportService:
    """Render a service result to Markdown, HTML or JSON."""

    def __init__(self, *, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def render(self, source: ServiceResult, fmt: str, *, title: str = "",
               destination: Optional[Path] = None) -> ServiceResult:
        result = ServiceResult(service=SERVICE, outcome=fmt,
                               provenance=self._provenance(
                                   rendered=source.service, format=fmt))
        if fmt not in FORMATS:
            result.add("unknown_format",
                       f"{fmt!r} is not one of {', '.join(FORMATS)}")
            result.outcome = "refused"
            return result
        payload = source.as_dict()
        title = title or f"{source.service}: {source.outcome}"
        if fmt == "json":
            text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
            sections = ["json"]
        elif fmt == "markdown":
            text, sections = self._markdown(title, payload)
        else:
            text, sections = self._html(title, payload)

        rendered = RenderedReport(format=fmt, text=text, sections=sections)
        if destination is not None:
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
            rendered.path = str(destination)
            result.evidence_paths["report"] = str(destination)
        result.data = rendered
        return result

    def markdown(self, source: ServiceResult, **kwargs) -> ServiceResult:
        return self.render(source, "markdown", **kwargs)

    def html(self, source: ServiceResult, **kwargs) -> ServiceResult:
        return self.render(source, "html", **kwargs)

    def json(self, source: ServiceResult, **kwargs) -> ServiceResult:
        return self.render(source, "json", **kwargs)

    # -- renderers ---------------------------------------------------------

    @staticmethod
    def _markdown(title: str, payload: dict) -> tuple[str, list[str]]:
        lines = [f"# {title}", ""]
        sections = ["provenance"]
        provenance = payload.get("provenance") or {}
        lines += [
            "## Provenance", "",
            f"- commit: `{provenance.get('commit') or 'not established'}`",
            f"- working tree dirty: "
            f"{'not established' if provenance.get('commit_dirty') is None else provenance['commit_dirty']}",
            f"- generated: {provenance.get('generated_at') or 'not established'}",
            f"- service ran: {payload.get('ok')}",
            f"- outcome: `{payload.get('outcome')}`", "",
        ]
        problems = payload.get("problems") or []
        sections.append("problems")
        lines += ["## Problems", ""]
        if not problems:
            lines += ["None recorded.", ""]
        else:
            lines += ["| severity | code | message |", "|---|---|---|"]
            for problem in problems:
                message = str(problem.get("message", "")).replace("|", "\\|")
                lines.append(f"| {problem.get('severity')} | "
                             f"`{problem.get('code')}` | {message} |")
            lines.append("")
        sections.append("data")
        lines += ["## Result", "", "| field | value |", "|---|---|"]
        for name, value in _rows(payload.get("data")):
            lines.append(f"| `{name}` | {str(value).replace('|', chr(92) + '|')} |")
        lines.append("")
        evidence = payload.get("evidence_paths") or {}
        sections.append("evidence")
        lines += ["## Evidence", ""]
        if not evidence:
            lines += ["No evidence file was produced.", ""]
        else:
            for name, path in sorted(evidence.items()):
                lines.append(f"- {name}: `{path}`")
            lines.append("")
        return "\n".join(lines), sections

    @staticmethod
    def _html(title: str, payload: dict) -> tuple[str, list[str]]:
        esc = html_module.escape
        provenance = payload.get("provenance") or {}
        parts = [
            "<!doctype html>", '<meta charset="utf-8">',
            f"<title>{esc(title)}</title>",
            "<style>body{font-family:system-ui,sans-serif;margin:2rem;"
            "max-width:60rem}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #ccc;padding:.35rem .5rem;text-align:left;"
            "font-size:.9rem}code{background:#f4f4f4;padding:0 .2rem}"
            ".na{color:#8a6d00}</style>",
            f"<h1>{esc(title)}</h1>",
            "<h2>Provenance</h2><ul>",
            f"<li>commit: <code>{esc(str(provenance.get('commit') or 'not established'))}</code></li>",
            f"<li>working tree dirty: {esc('not established' if provenance.get('commit_dirty') is None else str(provenance['commit_dirty']))}</li>",
            f"<li>generated: {esc(str(provenance.get('generated_at') or 'not established'))}</li>",
            f"<li>outcome: <code>{esc(str(payload.get('outcome')))}</code></li>",
            "</ul>",
        ]
        problems = payload.get("problems") or []
        parts.append("<h2>Problems</h2>")
        if not problems:
            parts.append("<p>None recorded.</p>")
        else:
            parts.append("<table><tr><th>severity</th><th>code</th>"
                         "<th>message</th></tr>")
            for problem in problems:
                parts.append(
                    f"<tr><td>{esc(str(problem.get('severity')))}</td>"
                    f"<td><code>{esc(str(problem.get('code')))}</code></td>"
                    f"<td>{esc(str(problem.get('message')))}</td></tr>")
            parts.append("</table>")
        parts.append("<h2>Result</h2><table><tr><th>field</th><th>value</th></tr>")
        for name, value in _rows(payload.get("data")):
            css = ' class="na"' if value == "not established" else ""
            parts.append(f"<tr><td><code>{esc(name)}</code></td>"
                         f"<td{css}>{esc(str(value))}</td></tr>")
        parts.append("</table>")
        evidence = payload.get("evidence_paths") or {}
        parts.append("<h2>Evidence</h2>")
        if not evidence:
            parts.append("<p>No evidence file was produced.</p>")
        else:
            parts.append("<ul>")
            for name, path in sorted(evidence.items()):
                parts.append(f"<li>{esc(name)}: <code>{esc(str(path))}</code></li>")
            parts.append("</ul>")
        return "\n".join(parts) + "\n", ["provenance", "problems", "data",
                                         "evidence"]
