"""Run an Abaqus job and read its results at full precision.

Two things here are deliberate.

The job's outcome is decided by :mod:`umat_oti.abaqus.job_status`, from the
records Abaqus writes, never from the exit code -- see that module for why.

Results are read from the ODB through ``abaqus python`` and ``odbAccess``,
which returns the stored doubles. The .dat is written to a printed format and
is fine for confirming that a job ran; it is not fine for a finite-difference
comparison, where the quantity of interest is a difference between two nearly
equal numbers and every digit dropped in printing is a digit of the answer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from umat_oti.abaqus.job_status import JobStatus, classify_job

#: Read one integration point's history out of an ODB. Runs under Abaqus's own
#: Python 2, so it is written for that: no f-strings, no pathlib.
_EXTRACT = r'''
from odbAccess import openOdb
import json, sys

odb_path, out_path, element, point = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
odb = openOdb(odb_path)
history = []
for step_name in odb.steps.keys():
    step = odb.steps[step_name]
    for frame in step.frames:
        record = {"step": step_name, "frame": frame.frameValue}
        sdv = {}
        for field_name in frame.fieldOutputs.keys():
            field = frame.fieldOutputs[field_name]
            for value in field.values:
                if value.elementLabel != element:
                    continue
                if getattr(value, "integrationPoint", point) != point:
                    continue
                data = value.data
                try:
                    numbers = [float(x) for x in data]
                except TypeError:
                    numbers = [float(data)]
                # Abaqus names state variables SDV1..SDVn, one field each.
                # Gathering them back into one ordered list is what lets a
                # caller compare a state history without knowing the count.
                if field_name[:3] == "SDV" and field_name[3:].isdigit():
                    sdv[int(field_name[3:])] = numbers[0]
                else:
                    record[field_name] = numbers
                break
        if sdv:
            record["SDV"] = [sdv[key] for key in sorted(sdv)]
        history.append(record)
odb.close()
handle = open(out_path, "w")
json.dump(history, handle)
handle.close()
print("EXTRACTED %d records" % len(history))
'''


@dataclass
class JobResult:
    """One Abaqus run: what it did, and what it produced."""

    status: JobStatus
    #: One record per frame, each holding the requested field outputs at the
    #: chosen integration point, as doubles.
    history: tuple[dict, ...] = ()
    console: str = ""

    @property
    def completed(self) -> bool:
        return self.status.analysis_completed


def abaqus_command() -> Optional[str]:
    """The Abaqus launcher, or None when there is none to find."""
    return shutil.which("abaqus")


def run_job(
    work_dir: Path,
    job: str,
    deck: str,
    *,
    user_source: Optional[Path] = None,
    extra_sources: Sequence[Path] = (),
    expected_increments: Optional[int] = None,
    timeout: int = 3600,
    double: str = "both",
) -> JobResult:
    """Write the deck, run it, and classify what happened.

    ``extra_sources`` are concatenated after the entry source into the single
    file Abaqus is given, because ``abaqus job=... user=...`` takes one file. A
    UMAT whose helper routines live beside it is one compilation unit as far as
    this is concerned, and calling the bundle "the source" is what keeps a
    result from being claimed for a subroutine that could not have run alone.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / f"{job}.inp").write_text(deck, encoding="utf-8")

    command = [abaqus_command() or "abaqus", f"job={job}", f"input={job}.inp",
               "interactive", f"double={double}"]
    if user_source is not None:
        bundle = work_dir / f"{job}_user.f"
        text = Path(user_source).read_text(errors="replace")
        for extra in extra_sources:
            text += "\n" + Path(extra).read_text(errors="replace")
        bundle.write_text(text, encoding="utf-8")
        command.append(f"user={bundle.name}")

    # An absolute path, so the record lands where the caller looks for it
    # whatever directory the solver chooses to run in.
    import os
    environment = dict(os.environ)
    environment["OTIS_PROBE_FILE"] = str((work_dir / f"{job}_probe.txt").resolve())
    try:
        finished = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                                  text=True, timeout=timeout, env=environment)
        console, code = finished.stdout + finished.stderr, finished.returncode
    except subprocess.TimeoutExpired:
        console, code = "TIMEOUT", None
    except OSError as error:
        console, code = f"{type(error).__name__}: {error}", None

    status = classify_job(work_dir, job, exit_code=code, console=console,
                          expected_increments=expected_increments,
                          required_files=(f"{job}.odb",))
    return JobResult(status=status, console=console[-4000:])


def extract_history(
    work_dir: Path, job: str, *, element: int = 1, point: int = 1,
    timeout: int = 900,
) -> tuple[tuple[dict, ...], str]:
    """Every frame's field output at one integration point, as doubles."""
    work_dir = Path(work_dir)
    script = work_dir / "_extract_history.py"
    script.write_text(_EXTRACT, encoding="utf-8")
    out = work_dir / f"{job}_history.json"
    command = [abaqus_command() or "abaqus", "python", script.name,
               f"{job}.odb", out.name, str(element), str(point)]
    try:
        finished = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                                  text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as error:
        return (), f"{type(error).__name__}: {error}"
    if not out.is_file():
        return (), (finished.stdout + finished.stderr)[-2000:]
    try:
        return tuple(json.loads(out.read_text())), ""
    except (OSError, ValueError) as error:
        return (), f"{type(error).__name__}: {error}"
