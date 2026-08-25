"""Toolchain detection that records evidence rather than a boolean.

A reproduction report is only as good as its account of what it ran on. "Abaqus:
not installed" and "Abaqus: present but unlicensed" lead to different next
actions, and a bare truthy check cannot tell them apart -- nor can it tell either
from "a command called abaqus exists and prints something".

That last case is not hypothetical. Probing ``abaqus information=release`` and
keeping the first line of output yielded the version string ``Abaqus JOB
abaqus``, which is the launcher's banner, not a version at all. The detector
below records the resolved executable, the probe command, its exit status, the
parsed version, and, for Abaqus, whether a licence is actually obtainable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

__all__ = ["ToolReport", "detect_tool", "detect_abaqus", "detect_toolchain"]

#: Abaqus prints a launcher banner before anything useful, so the version has to
#: be matched rather than taken positionally.
_ABAQUS_VERSION_RE = re.compile(r"^\s*Abaqus\s+(\d{4}[\w.]*)\s*$", re.MULTILINE)
_LICENCE_TOTAL_RE = re.compile(
    r"Users of abaqus:\s*\(Total of (\d+) licenses? issued;\s*"
    r"Total of (\d+) licenses? in use", re.IGNORECASE)


@dataclass
class ToolReport:
    """What was found, how, and why it is or is not usable."""

    name: str
    available: bool
    executable: Optional[str] = None
    resolved_from: Optional[str] = None
    probe_command: Optional[list[str]] = None
    probe_returncode: Optional[int] = None
    version: Optional[str] = None
    reason: Optional[str] = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "name": self.name,
            "available": self.available,
            "executable": self.executable,
            "resolved_from": self.resolved_from,
            "probe_command": self.probe_command,
            "probe_returncode": self.probe_returncode,
            "version": self.version,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.details:
            payload["details"] = self.details
        return payload


def _resolve(name: str) -> tuple[Optional[str], Optional[str]]:
    found = shutil.which(name)
    if not found:
        return None, None
    try:
        target = str(Path(found).resolve())
    except OSError:
        target = found
    return found, (target if target != found else None)


def _run(command: Sequence[str], timeout: int) -> tuple[Optional[int], str]:
    try:
        proc = subprocess.run(list(command), capture_output=True, text=True,
                              timeout=timeout)
    except FileNotFoundError:
        return None, ""
    except subprocess.TimeoutExpired:
        return None, "__timeout__"
    except OSError as exc:
        return None, f"__error__ {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def detect_tool(name: str, version_args: Sequence[str], *,
                timeout: int = 30) -> ToolReport:
    """Resolve a command and read its version, recording each step."""
    executable, target = _resolve(name)
    if executable is None:
        return ToolReport(name=name, available=False,
                          reason=f"{name} is not on PATH")
    command = [executable, *version_args]
    code, output = _run(command, timeout)
    if code is None:
        return ToolReport(
            name=name, available=False, executable=executable,
            resolved_from=target, probe_command=command,
            reason=f"the version probe did not complete: {output.strip()[:200]}")
    if code != 0:
        return ToolReport(
            name=name, available=False, executable=executable,
            resolved_from=target, probe_command=command, probe_returncode=code,
            reason=f"the version probe exited {code}")
    first = next((line.strip() for line in output.splitlines() if line.strip()), None)
    return ToolReport(name=name, available=True, executable=executable,
                      resolved_from=target, probe_command=command,
                      probe_returncode=code, version=first)


def detect_abaqus(*, timeout: int = 120,
                  check_licence: bool = True) -> ToolReport:
    """Resolve Abaqus, read its real version, and see whether a licence exists.

    ``available`` means a job could plausibly be submitted: the launcher
    resolved, reported a version, and a licence server offered at least one
    ``abaqus`` feature. An installation with no reachable licence is reported as
    unavailable with that as the reason, because it cannot run anything.
    """
    name = os.environ.get("ABAQUS_COMMAND", "abaqus")
    executable, target = _resolve(name)
    if executable is None:
        return ToolReport(name="abaqus", available=False,
                          reason=f"{name} is not on PATH")

    command = [executable, "information=release"]
    code, output = _run(command, timeout)
    if code is None:
        return ToolReport(
            name="abaqus", available=False, executable=executable,
            resolved_from=target, probe_command=command,
            reason=f"the release probe did not complete: {output.strip()[:200]}")

    match = _ABAQUS_VERSION_RE.search(output)
    version = match.group(1) if match else None
    details: dict = {"probe_output_head": output.strip().splitlines()[:4]}
    if version is None:
        return ToolReport(
            name="abaqus", available=False, executable=executable,
            resolved_from=target, probe_command=command, probe_returncode=code,
            details=details,
            reason=("the release probe produced no line matching 'Abaqus "
                    "<version>'; a command named abaqus exists but did not "
                    "identify itself as an Abaqus installation"))

    if not check_licence:
        return ToolReport(name="abaqus", available=True, executable=executable,
                          resolved_from=target, probe_command=command,
                          probe_returncode=code, version=version, details=details)

    licence_command = [executable, "licensing", "lmstat", "-a"]
    licence_code, licence_output = _run(licence_command, timeout)
    details["licence_command"] = licence_command
    details["licence_returncode"] = licence_code
    if licence_code != 0:
        return ToolReport(
            name="abaqus", available=False, executable=executable,
            resolved_from=target, probe_command=command, probe_returncode=code,
            version=version, details=details,
            reason=("Abaqus is installed but its licence status could not be "
                    f"read (lmstat exited {licence_code}); no job can be "
                    "submitted without a licence"))
    licence = _LICENCE_TOTAL_RE.search(licence_output)
    if not licence:
        return ToolReport(
            name="abaqus", available=False, executable=executable,
            resolved_from=target, probe_command=command, probe_returncode=code,
            version=version, details=details,
            reason=("Abaqus is installed but no 'abaqus' licence feature was "
                    "offered by the licence server"))
    issued, in_use = int(licence.group(1)), int(licence.group(2))
    details["licences_issued"] = issued
    details["licences_in_use"] = in_use
    if issued <= 0:
        return ToolReport(
            name="abaqus", available=False, executable=executable,
            resolved_from=target, probe_command=command, probe_returncode=code,
            version=version, details=details,
            reason="the licence server offers zero abaqus licences")
    return ToolReport(name="abaqus", available=True, executable=executable,
                      resolved_from=target, probe_command=command,
                      probe_returncode=code, version=version, details=details)


def detect_toolchain(*, include_abaqus: bool = True) -> dict[str, dict]:
    reports = {
        "gfortran": detect_tool("gfortran", ["--version"]),
        "make": detect_tool("make", ["--version"]),
        "git": detect_tool("git", ["--version"]),
    }
    if include_abaqus:
        reports["abaqus"] = detect_abaqus()
    return {name: report.to_dict() for name, report in reports.items()}
