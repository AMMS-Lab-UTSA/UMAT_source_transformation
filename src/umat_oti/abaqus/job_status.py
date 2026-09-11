"""What an Abaqus job actually did, read from its own records.

The process exit code cannot answer that on this installation. Abaqus 2021.HF5
aborts in its post-analysis wrap-up here -- ``*** buffer overflow detected ***``
and ``terminated by signal 6`` -- and exits non-zero *after* writing
``THE ANALYSIS HAS COMPLETED SUCCESSFULLY``. The abort is not caused by the
model or by a user subroutine: a control job with no user subroutine at all
aborts identically. It is Abaqus's own wrap-up against a newer glibc than the
release was built for.

So the exit code is recorded and reported, never used as the verdict, and never
quietly rewritten to zero. A job that aborts in wrap-up carries the
``post_analysis_wrapup_failure`` warning alongside whatever the records say
about the analysis.

Neither is one text marker enough. A ``.sta`` can say the analysis completed
while the increments requested were not run, or while the output the comparison
needs never reached a file. Every applicable check has to agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

#: What Abaqus/Standard writes to the .sta when the analysis itself finished.
COMPLETED_MARKER = "THE ANALYSIS HAS COMPLETED SUCCESSFULLY"

#: How much of the driver's console to keep when a job left no records.
CONSOLE_TAIL = 4000

#: Lines an ifort diagnostic starts with. Used only to pull the build's own
#: words out of the console into the reason, never to decide anything.
_COMPILER_DIAGNOSTIC = re.compile(
    r"^.*\b(?:error\s*#\d+|catastrophic error|undefined reference|"
    r"cannot open include file|can't find include file|"
    r"compilation aborted)\b.*$",
    re.IGNORECASE | re.MULTILINE)

#: The wrap-up abort seen on this installation, which is not a model failure.
_WRAPUP_SIGNATURES = (
    "buffer overflow detected",
    "terminated by signal 6",
)

_ERROR_COUNT = re.compile(r"^\s*(\d+)\s+ERROR MESSAGES\s*$", re.MULTILINE)
_WARNING_COUNT = re.compile(r"^\s*(\d+)\s+WARNING MESSAGES DURING ANALYSIS\s*$",
                            re.MULTILINE)
_INCREMENT_COUNT = re.compile(r"^\s*TOTAL OF\s+(\d+)\s+INCREMENTS\s*$", re.MULTILINE)


@dataclass
class JobStatus:
    """The verdict on one Abaqus job, and the evidence behind it."""

    job: str
    directory: Path
    #: True only when every applicable check agreed.
    analysis_completed: bool = False
    #: The process exit code, preserved exactly as the shell reported it.
    exit_code: Optional[int] = None
    error_messages: Optional[int] = None
    warning_messages: Optional[int] = None
    increments: Optional[int] = None
    #: Non-fatal observations. ``post_analysis_wrapup_failure`` lives here.
    warnings: tuple[str, ...] = ()
    #: Why the job was not counted as completed, when it was not.
    reasons: tuple[str, ...] = ()
    #: The tail of what the solver driver printed, kept ONLY when the job did
    #: not complete. Ten entries of the pass9 corpus failed with no .dat, no
    #: .msg and no .odb -- Abaqus never reached its input processor, which on
    #: this installation means the user-subroutine build failed and printed
    #: the reason to the console. The console was captured and dropped, so all
    #: ten were recorded as "original.msg was not written" and the only
    #: evidence of what actually went wrong was gone. Three of those ten were
    #: compile errors: a missing PROPS declaration, an uppercase #INCLUDE that
    #: no file on a case-sensitive filesystem matches, and a probe call this
    #: package inserted above a preprocessor directive.
    console_tail: str = ""
    checks: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "job": self.job,
            "analysis_completed": self.analysis_completed,
            "exit_code": self.exit_code,
            "error_messages": self.error_messages,
            "warning_messages": self.warning_messages,
            "increments": self.increments,
            "warnings": list(self.warnings),
            "reasons": list(self.reasons),
            "console_tail": self.console_tail,
            "checks": dict(self.checks),
        }


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


#: Fortran statements that wait for terminal input. A source containing one
#: can hang a solver indefinitely rather than failing, so a run of it is worth
#: labelling even when it completes: the statement may simply not have been
#: reached this time.
_BLOCKING_STATEMENT = re.compile(r"^\s{6,}(?:.*\b)?(PAUSE)\b", re.IGNORECASE | re.MULTILINE)


def blocking_statements(source_text: str) -> tuple[str, ...]:
    """The input-waiting statements a source carries, if any.

    Reported rather than removed. PAUSE is the model author's, and deleting it
    would be editing scientific code to make a run finish -- the failure it
    announces is real, and the fix is to give the solver no terminal to wait
    on, not to stop it announcing.
    """
    found = []
    for line in source_text.splitlines():
        if line[:1] in "cC*!":
            continue
        match = _BLOCKING_STATEMENT.match(line)
        if match:
            found.append(line.strip()[:80])
    return tuple(found)


def classify_job(
    directory: Path,
    job: str,
    *,
    exit_code: Optional[int] = None,
    console: str = "",
    expected_increments: Optional[int] = None,
    required_files: tuple[str, ...] = (),
) -> JobStatus:
    """Did this job's analysis complete, and what is the evidence?

    ``expected_increments`` is compared against the count the .msg reports, so
    a job that stopped early cannot pass by having written the completion
    marker for a shorter run than the one that was asked for.

    ``required_files`` are checked for existence and non-emptiness -- an .odb
    of zero bytes is not output, however cleanly the analysis ended.
    """
    directory = Path(directory)
    status = JobStatus(job=job, directory=directory, exit_code=exit_code)
    sta = _read(directory / f"{job}.sta")
    msg = _read(directory / f"{job}.msg")
    dat = _read(directory / f"{job}.dat")

    reasons: list[str] = []
    warnings: list[str] = []
    checks: dict = {}

    # Abaqus writes the .dat while processing the input file, which it does
    # AFTER building the user subroutine. No .dat at all therefore does not
    # mean "the analysis left no record": it means there was no analysis,
    # because the build in front of it did not produce a library. Saying
    # ".sta was not written" for that points the reader at the solver.
    # Gated on the .msg being absent too. A .dat that was cleaned away from a
    # job whose .msg records an analysis is a missing file, not a failed
    # build, and reporting a build failure for it would be exactly the kind of
    # confident wrong sentence this replaces.
    checks["input_processor_reached"] = bool(dat or msg)
    if not dat and not msg:
        diagnostics = _COMPILER_DIAGNOSTIC.findall(console)
        detail = ("; ".join(line.strip() for line in diagnostics[:3])
                  if diagnostics else
                  "the console kept no compiler diagnostic")
        reasons.append(
            f"{job}.dat was not written, so Abaqus never reached its input "
            f"processor: the user-subroutine build failed before the analysis "
            f"began ({detail})")

    checks["sta_present"] = bool(sta)
    if not sta:
        reasons.append(f"{job}.sta was not written, so the analysis left no record")

    checks["completion_marker"] = COMPLETED_MARKER in sta
    if sta and not checks["completion_marker"]:
        reasons.append(f"{job}.sta does not say {COMPLETED_MARKER!r}")

    checks["msg_present"] = bool(msg)
    if not msg:
        reasons.append(f"{job}.msg was not written")
    else:
        errors = _ERROR_COUNT.search(msg)
        status.error_messages = int(errors.group(1)) if errors else None
        checks["zero_analysis_errors"] = status.error_messages == 0
        if status.error_messages is None:
            reasons.append(f"{job}.msg does not report an error count")
        elif status.error_messages:
            reasons.append(
                f"{job}.msg reports {status.error_messages} analysis error messages")
        found = _WARNING_COUNT.search(msg)
        status.warning_messages = int(found.group(1)) if found else None
        increments = _INCREMENT_COUNT.search(msg)
        status.increments = int(increments.group(1)) if increments else None

    if expected_increments is not None:
        # FEWER increments than requested means the analysis stopped short.
        # MORE means the solver cut back and recovered, which is a solver
        # doing its job -- and on a load-controlled step it is what the two
        # builds do differently, because the converted routine returns the
        # OTI tangent rather than the author's analytic one and Newton
        # converges at a different rate. Measured on
        # BodyForce-Growth-2Stages.for: ten increments for the original and
        # sixteen for the converted build, both completing successfully.
        # Calling that a failed job hid a run that had in fact finished; what
        # it needs is histories paired by time rather than by position, which
        # is umat_oti.abaqus.compare.align_by_time.
        short = (status.increments is not None
                 and status.increments < expected_increments)
        checks["increments_completed"] = not short
        if short:
            reasons.append(
                f"the analysis ran {status.increments} increments where "
                f"{expected_increments} were requested")
        elif status.increments is not None and \
                status.increments != expected_increments:
            warnings.append(
                f"the solver cut back and recovered: {status.increments} "
                f"increments where {expected_increments} were requested")
        elif status.increments is None:
            # A job with no .msg has no increment count. Reporting "the solver
            # cut back and recovered: None increments where 30 were requested"
            # attributes a recovery to a run that never started, and it was
            # attached to all ten of the pass9 jobs that failed before Abaqus
            # wrote anything.
            checks["increments_completed"] = False

    missing = [name for name in required_files
               if not (directory / name).is_file()
               or (directory / name).stat().st_size == 0]
    checks["required_files_present"] = not missing
    if missing:
        reasons.append("expected output is missing or empty: " + ", ".join(missing))

    # Recorded, never used as the verdict, and never rewritten. A wrap-up abort
    # on this installation happens to jobs with no user subroutine too.
    haystack = f"{console}\n{_read(directory / f'{job}.log')}"
    if any(signature in haystack for signature in _WRAPUP_SIGNATURES):
        warnings.append("post_analysis_wrapup_failure")
    if exit_code not in (None, 0):
        warnings.append(f"process_exit_code_{exit_code}")

    status.analysis_completed = not reasons
    if reasons and console:
        status.console_tail = console[-CONSOLE_TAIL:]
    status.reasons = tuple(reasons)
    status.warnings = tuple(warnings)
    status.checks = checks
    return status
