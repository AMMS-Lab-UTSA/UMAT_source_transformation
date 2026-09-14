"""Spawning and signalling, narrowly.

The whole safety argument of the job manager is in this module, so it is short
and it has no branches that widen what gets signalled.

**Nothing here matches on a name.** There is no ``pkill``, no ``killall``, no
``shell=True``, no scan of ``ps`` output, no command-line comparison. There is
one function that sends a signal and it takes an integer pid. This is not a
style preference: this machine runs other people's Abaqus jobs, a pattern kill
would take them down, and 150 licence tokens are held by someone else.

**A pid is not an identity.** Pids are recycled, and a record written an hour
ago may name a pid that now belongs to a stranger. So a pid is tracked together
with the kernel's own start-time for that process (``/proc/<pid>/stat`` field
22, the 22nd whitespace field after the comm field, in clock ticks since boot),
which the kernel will not reissue for a different process at the same pid.
:func:`identity_of` reads it; :func:`signal_exact_pid` re-reads it and refuses
to signal when it has changed.

On a platform without ``/proc``, :func:`identity_of` returns ``None`` and
:func:`signal_exact_pid` refuses to signal any job whose record carries an
identity, rather than signalling without the guard.
"""

from __future__ import annotations

import errno
import os
import signal as signal_module
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

__all__ = [
    "PROC",
    "ZOMBIE",
    "SpawnResult",
    "SignalOutcome",
    "identity_of",
    "is_alive",
    "process_state",
    "signal_exact_pid",
    "spawn_detached",
]

#: Overridable for tests only. Nothing else in this package reads /proc.
PROC = Path("/proc")

#: The kernel's state letter for a process that has exited and whose parent has
#: not yet reaped it. It still has a pid and ``os.kill(pid, 0)`` still succeeds,
#: so a liveness check that asks only that question reports a finished job as a
#: running one. It is finished.
ZOMBIE = "Z"


@dataclass(frozen=True)
class SpawnResult:
    pid: int
    #: The kernel's start-time for that pid, or None where it is unreadable.
    identity: Optional[str]
    #: True when we called ``setsid`` ourselves, so the group is ours and its
    #: id equals ``pid``. Never inferred from the pid alone.
    owns_process_group: bool
    log_path: str


@dataclass(frozen=True)
class SignalOutcome:
    """What was signalled, or precisely why nothing was.

    ``pid`` is the pid a signal was *delivered to* and is ``None`` whenever
    nothing was delivered. The pid that was considered and refused is in
    ``pid_considered``. Keeping those apart matters: a field that means "the
    pid involved" lets a reader believe a refusal signalled something.
    """

    signalled: bool
    pid: Optional[int]
    signal: Optional[int]
    #: "exact_pid" or "process_group_we_created". There is no value of this
    #: field that means a name match, because no such code path exists.
    scope: str
    reason: str
    pid_considered: Optional[int] = None


def _refused(pid: Optional[int], scope: str, reason: str) -> SignalOutcome:
    """No signal was sent. ``pid`` is recorded as considered, never as sent."""
    return SignalOutcome(signalled=False, pid=None, signal=None, scope=scope,
                         reason=reason, pid_considered=pid)


def _stat_fields(pid: int) -> Optional[list[str]]:
    """``/proc/<pid>/stat`` from the state field onward, or None."""
    try:
        raw = (PROC / str(int(pid)) / "stat").read_text(encoding="utf-8",
                                                        errors="replace")
    except (OSError, ValueError):
        return None
    # The comm field is parenthesised and may itself contain spaces and
    # parentheses, so split after the LAST ')' rather than on whitespace.
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 2:].split()
    # fields[0] is state (field 3); starttime is field 22, so index 19 here.
    return fields if len(fields) >= 20 else None


def process_state(pid: int) -> Optional[str]:
    """The kernel's one-letter state for ``pid`` (``R``, ``S``, ``Z``, ...)."""
    fields = _stat_fields(pid)
    return fields[0] if fields else None


def identity_of(pid: int) -> Optional[str]:
    """The kernel's start-time for ``pid``, as a string, or None.

    None means "this platform will not tell us", not "the process is gone" --
    a caller must not read None as permission to signal.
    """
    fields = _stat_fields(pid)
    return fields[19] if fields else None


def is_alive(pid: Optional[int], identity: Optional[str] = None) -> bool:
    """Whether ``pid`` is a live process that is still the one we tracked.

    A live pid whose start-time no longer matches ``identity`` is a *different*
    process and this returns False, because the job we tracked is over.
    """
    if not pid or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        if error.errno == errno.EPERM:
            # It exists and is not ours. Alive, but not ours to signal; the
            # identity check below is what decides whether it is our job.
            pass
        else:
            return False
    fields = _stat_fields(int(pid))
    if fields is not None and fields[0] == ZOMBIE:
        # Exited, not yet reaped. A job in this state is over; reporting it as
        # running would be reporting an attempt as a run still in progress.
        return False
    if identity is None:
        return True
    current = fields[19] if fields else None
    if current is None:
        # Cannot confirm. Report not-alive rather than claim a match we did
        # not make: an unconfirmed identity must never widen what we signal.
        return False
    return current == identity


def signal_exact_pid(pid: int, *, expected_identity: Optional[str],
                     sig: int = signal_module.SIGTERM,
                     process_group: bool = False,
                     owns_process_group: bool = False) -> SignalOutcome:
    """Send ``sig`` to exactly ``pid``, or refuse and say why.

    ``process_group`` is only honoured when ``owns_process_group`` is true AND
    the process group id of ``pid`` equals ``pid`` -- that is, when this
    workflow created that group with ``setsid`` and the group therefore
    contains this job's processes and nothing else. A group somebody else made
    is never signalled, and there is no way to ask for one.
    """
    pid = int(pid)
    if pid <= 0:
        return _refused(pid, "",
                        "the record carries no usable pid, so there is "
                        "nothing to signal")
    if pid == os.getpid():
        return _refused(pid, "",
                        "that pid is this process; refusing to signal "
                        "the manager itself")

    if expected_identity is not None:
        current = identity_of(pid)
        if current is None:
            return _refused(
                pid, "",
                f"pid {pid} cannot be confirmed as the process this job "
                f"started (its start-time is unreadable), so it is not "
                f"signalled. A pid alone is not an identity and this one may "
                f"have been reused.")
        if current != expected_identity:
            return _refused(
                pid, "",
                f"pid {pid} is no longer the process this job started: its "
                f"start-time reads {current} and the record says "
                f"{expected_identity}. The pid was recycled and now belongs to "
                f"another process, which is not ours to signal. Nothing was "
                f"signalled.")

    scope = "exact_pid"
    target = pid
    use_group = False
    if process_group:
        if not owns_process_group:
            return _refused(
                pid, "",
                "a process-group stop was asked for on a group this workflow "
                "did not create; refusing, because that group may contain "
                "processes that are not this job's")
        try:
            pgid = os.getpgid(pid)
        except OSError as error:
            return _refused(pid, "",
                            f"the process group of pid {pid} could not be "
                            f"read ({error}); nothing was signalled")
        if pgid != pid:
            return _refused(
                pid, "",
                f"pid {pid} is not the leader of its process group ({pgid}), "
                f"so that group is not the one this workflow created; "
                f"refusing to signal it")
        use_group = True
        scope = "process_group_we_created"

    try:
        if use_group:
            os.killpg(target, sig)
        else:
            os.kill(target, sig)
    except OSError as error:
        if error.errno == errno.ESRCH:
            return _refused(pid, scope,
                            f"pid {pid} no longer exists; the process had "
                            f"already ended when the stop was delivered")
        return _refused(pid, scope,
                        f"signalling pid {pid} failed: {error}")
    return SignalOutcome(signalled=True, pid=target, signal=int(sig),
                         scope=scope, pid_considered=pid,
                         reason=(f"signal {int(sig)} delivered to "
                                 f"{'process group' if use_group else 'pid'} "
                                 f"{target}"))


def spawn_detached(command: Sequence[str], *, cwd: Path, log_path: Path,
                   env: Optional[dict] = None) -> SpawnResult:
    """Start ``command`` so that it outlives this process.

    ``start_new_session=True`` puts the child in a session of its own, which is
    what lets the run survive the interface being closed: it is no longer in
    the terminal's foreground group and a hangup aimed at the interface does
    not reach it. It also means the group id equals the child's pid, and that
    the group contains this job and nothing else -- which is the only condition
    under which a group stop is permitted at all.

    ``shell=False`` always. ``command`` is a list of arguments; there is no
    string form and nothing is interpolated into a shell.
    """
    command = [str(part) for part in command]
    if not command:
        raise ValueError("a job needs a command to run")
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    environment = dict(os.environ if env is None else env)
    # The import trap: the editable install points at a different checkout, so
    # a child that imports umat_oti would get the OTHER tree's code. Pin the
    # child to the tree this module was actually loaded from.
    package_parent = str(Path(__file__).resolve().parents[2])
    existing = environment.get("PYTHONPATH", "")
    if package_parent not in existing.split(os.pathsep):
        environment["PYTHONPATH"] = (
            f"{package_parent}{os.pathsep}{existing}" if existing
            else package_parent)

    with open(log_path, "ab", buffering=0) as log:
        process = subprocess.Popen(  # noqa: S603 - list form, shell=False
            command,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=environment,
            close_fds=True,
        )
    return SpawnResult(pid=int(process.pid), identity=identity_of(process.pid),
                       owns_process_group=True, log_path=str(log_path))


def python_executable() -> str:
    return sys.executable or "python3"
