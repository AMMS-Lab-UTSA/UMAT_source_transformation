"""Instrument a UMAT's OWN loops, so "different iterate" can be tested.

``iterative_solver_different_iterate`` is a claim about what happens INSIDE one
UMAT call: that the author's convergence loop ran a different number of times,
or stopped at a different residual, in the two builds. Nothing recorded by the
ordinary probe can test it. The probe writes what went in and what came out;
the loop runs between those two records and leaves no trace.

So the hypothesis was carried on the strength of a word matching
``newton|converg|do while`` somewhere in the file. On ``huang_umat_97.for`` the
match is the word "converg" in a comment: the routine's actual iteration is
``1000 CONTINUE`` at the top and ``GO TO 1000`` at the bottom, which no search
for ``DO WHILE`` finds. Evidence about a construct that was never located is
not evidence about a run.

This module generates the instrumentation that would make it evidence: a source
in which every loop the author wrote announces, per call, how many passes it
made and what the residual it tests was on each pass, and every block branch on
stress or state announces that it was taken. Two builds instrumented this way,
run on the same deck, produce two traces comparable call by call. The hypothesis
predicts the counts differ. If they do not, it is refuted regardless of how
large the final disagreement is.

Nothing here goes into a verification build. A trace-writing source writes on
every pass of every loop, which changes the cost of a run by orders and can
change what the optimiser does with the loop body. It is for the experiment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

#: The Fortran unit the trace is written on. Clear of Abaqus's own and of the
#: probe's.
TRACE_UNIT = 197

#: A ``DO WHILE`` header: an author's convergence loop in its modern shape.
#: A counted ``DO I=1,N`` is deliberately NOT traced: its trip count is fixed by
#: its bounds and cannot differ between two builds of one source, so tracing it
#: measures nothing and costs a write per pass.
_DO_WHILE = re.compile(r"^\s*(?:\d+\s+)?DO\s+WHILE\s*\(", re.IGNORECASE)

#: The F77 shape of the same thing: a branch back to a label that appeared
#: earlier in the routine. ``huang_umat_97.for`` iterates exactly this way --
#: ``1000 CONTINUE`` at line 702, ``NITRTN=NITRTN+1`` under it, and ``GO TO
#: 1000`` at line 1352 guarded by ``IF (IDBACK.NE.0.AND.NITRTN.LT.ITRMAX)``.
_GO_TO = re.compile(r"^(\s*(?:\d+\s+)?)GO\s*TO\s+(\d+)\s*$", re.IGNORECASE)

#: A statement label, which is what a backward GO TO targets.
_LABELLED = re.compile(r"^\s{0,5}(\d+)\s")

#: A block ``IF (...) THEN`` whose test mentions a state, stress or residual
#: quantity: the branches the branch-divergence hypothesis is about. Only the
#: block form is traced. A logical IF carries its statement on the same line,
#: so a trace placed after it fires whether the branch was taken or not --
#: recording "this line was reached" while reading as "this branch was taken".
_STATE_BRANCH = re.compile(
    r"^\s*(?:\d+\s+)?IF\s*\(.*\b(STATEV|STRESS|DSTRAN|TAUSLP|GSLIP|RESIDU|"
    r"YIELD|CONVERG)\w*\b.*\)\s*THEN\s*$", re.IGNORECASE)

#: A logical IF on the same quantities. Recorded as NOT instrumented, with the
#: reason, rather than traced as though it had been.
_LOGICAL_IF = re.compile(
    r"^\s*(?:\d+\s+)?IF\s*\(.*\b(STATEV|STRESS|DSTRAN|RESIDU)\w*\b.*\)\s*\S",
    re.IGNORECASE)

#: A scalar the routine tests against a tolerance: ``IF (ABS(RESIDU).GT.GAMERR)``.
#: Its value on each pass IS the per-iteration residual norm, so it is watched
#: by default rather than left to be named by hand -- an experiment whose watch
#: list has to be filled in per file is one nobody runs over forty entries.
_RESIDUAL_TEST = re.compile(
    r"IF\s*\(\s*(?:D?ABS\s*\(\s*)?([A-Za-z]\w*)\s*\)?\s*\."
    r"(?:GT|GE|LT|LE)\.", re.IGNORECASE)


@dataclass
class TracePoint:
    """One place in the source that will announce itself at run time."""

    line: int
    kind: str            # loop_back | loop_pass | branch_taken | not traced
    label: str           # a stable name, carried in the trace
    statement: str

    def as_dict(self) -> dict:
        return {"line": self.line, "kind": self.kind, "label": self.label,
                "statement": self.statement}


@dataclass
class Instrumentation:
    """A traced source and the map from trace labels back to source lines."""

    text: str = ""
    points: list = field(default_factory=list)
    #: Places the mechanism could occur that this could NOT trace. Reported,
    #: because "the branches agreed" and "the branches this could see agreed"
    #: are different claims and only one of them is true here.
    not_instrumented: list = field(default_factory=list)
    #: Scalars whose value goes into the trace at each loop pass.
    watched: list = field(default_factory=list)
    reason: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.text) and bool(self.points)

    def as_dict(self) -> dict:
        return {"points": [p.as_dict() for p in self.points],
                "not_instrumented": [p.as_dict()
                                     for p in self.not_instrumented],
                "watched": list(self.watched),
                "point_count": len(self.points), "reason": self.reason}


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or bool(re.match(r"^[cC*!]", line)) or stripped[0] == "!"


def watched_scalars(source_text: str, routine: str = "UMAT") -> list:
    """Scalars the routine itself compares against a tolerance."""
    from umat_oti.abaqus.probe import _routine_span

    lines = source_text.splitlines()
    start, end = _routine_span(lines, routine)
    if start is None:
        return []
    found: list = []
    for number in range(start + 1, end):
        line = lines[number]
        if _is_comment(line):
            continue
        match = _RESIDUAL_TEST.search(line)
        if match:
            name = match.group(1).upper()
            # A leading N is Fortran's implicit-integer range: a count, not a
            # residual. Writing DBLE(NITRTN) into a residual column would put
            # an iteration number where a norm is read.
            if name not in found and name[0] not in "IJKLMN":
                found.append(name)
    return found


def trace_points(source_text: str, routine: str = "UMAT") -> tuple:
    """Every loop-back, DO WHILE and state-dependent block branch in a routine.

    Returns ``(points, not_instrumented)``.
    """
    from umat_oti.abaqus.probe import _routine_span

    lines = source_text.splitlines()
    start, end = _routine_span(lines, routine)
    if start is None:
        return [], []
    labels_seen: set = set()
    points: list = []
    skipped: list = []
    for number in range(start + 1, end):
        line = lines[number]
        if _is_comment(line):
            continue
        label = _LABELLED.match(line)
        if label:
            labels_seen.add(label.group(1))
        jump = _GO_TO.match(line)
        if jump:
            if jump.group(2) in labels_seen:
                points.append(TracePoint(number, "loop_back",
                                         f"G{number + 1}", line.strip()[:72]))
            continue
        if _DO_WHILE.match(line):
            points.append(TracePoint(number, "loop_pass",
                                     f"W{number + 1}", line.strip()[:72]))
            continue
        if _STATE_BRANCH.match(line):
            points.append(TracePoint(number, "branch_taken",
                                     f"B{number + 1}", line.strip()[:72]))
            continue
        if _LOGICAL_IF.match(line):
            skipped.append(TracePoint(number, "logical_if_not_traced",
                                      f"X{number + 1}", line.strip()[:72]))
    return points, skipped


#: The trace writer, appended to the instrumented file. One line per event:
#:
#:     TRACE <tag> <label> <element> <point> <increment> <ordinal> <value>
#:
#: ``ordinal`` is the pass number within this call, which is the quantity the
#: different-iterate hypothesis is about. A point with no value to give writes
#: ``not_measured`` rather than zero, because a trace that substituted zero for
#: "not measured" would read as convergence.
TRACE_WRITER = """
C     ==================================================================
C     OTIS-TRACE: experiment-only. Announces each pass of an author loop
C     and each state-dependent block branch. Present ONLY in a build made
C     to test the different-iterate hypothesis, never in a verification
C     build: it writes inside the loop, which changes both the cost of a
C     run and what the optimiser may do with the loop body.
C     ==================================================================
      SUBROUTINE OTIS_TRACE(TAG,LABEL,NOEL,NPT,KINC,IORD,VALUE,HASVAL)
      CHARACTER*(*) TAG
      CHARACTER*(*) LABEL
      INTEGER NOEL,NPT,KINC,IORD,HASVAL,IOS
      REAL*8 VALUE
      LOGICAL OPENED
      INQUIRE(UNIT=%(unit)d,OPENED=OPENED)
      IF (.NOT.OPENED) THEN
         OPEN(UNIT=%(unit)d,FILE=TAG//'_trace.txt',
     1        STATUS='UNKNOWN',POSITION='APPEND',IOSTAT=IOS)
         IF (IOS.NE.0) RETURN
      END IF
      IF (HASVAL.EQ.1) THEN
         WRITE(%(unit)d,900) TAG,LABEL,NOEL,NPT,KINC,IORD,VALUE
      ELSE
         WRITE(%(unit)d,901) TAG,LABEL,NOEL,NPT,KINC,IORD
      END IF
  900 FORMAT('TRACE ',A,1X,A,4(1X,I8),1X,E26.17E3)
  901 FORMAT('TRACE ',A,1X,A,4(1X,I8),' not_measured')
      RETURN
      END
"""


def instrument_internal_loops(source_text: str, tag: str,
                              routine: str = "UMAT",
                              watch: Sequence[str] = ()) -> Instrumentation:
    """Trace the author's own loops: passes per call, and the residual on each.

    A counter per trace point is declared and zeroed at the top of the routine,
    so the ordinal restarts every call: the hypothesis is about how many passes
    THIS call took, not how many the run took.

    ``usable=False`` with a reason when the routine has no loop-back, no
    DO WHILE and no state-dependent block branch. That is worth saying out
    loud: a routine with nothing to trace has no internal iteration, and
    ``iterative_solver_different_iterate`` should never have been raised for it.
    """
    from umat_oti.abaqus.probe import _routine_span, _first_executable

    lines = source_text.splitlines()
    start, end = _routine_span(lines, routine)
    if start is None:
        return Instrumentation(reason=f"no SUBROUTINE {routine} in this source")
    points, skipped = trace_points(source_text, routine)
    if not points:
        return Instrumentation(
            reason=f"{routine} contains no backward GO TO, no DO WHILE and no "
                   f"block IF on stress or state, so it has no internal "
                   f"iteration for a 'different iterate' to happen in",
            not_instrumented=skipped)

    insert_at = _first_executable(lines, start, end)
    if insert_at is None:
        return Instrumentation(
            reason=f"{routine} has no executable statement to place the "
                   f"counters before", not_instrumented=skipped)

    names = [name.upper() for name in watch] or watched_scalars(
        source_text, routine)
    counters = [f"OTI_TC{index}" for index, _ in enumerate(points)]
    declarations = ["      INTEGER " + ", ".join(counters[chunk:chunk + 6])
                    for chunk in range(0, len(counters), 6)]
    resets = [f"      {name} = 0" for name in counters]
    by_line: dict = {}
    for index, point in enumerate(points):
        by_line.setdefault(point.line, []).append((index, point))

    out: list = []
    for number, line in enumerate(lines):
        if number == insert_at:
            out.extend(declarations)
            out.extend(resets)
        here = by_line.get(number, ())
        emitted: list = []
        before = False
        for index, point in here:
            counter = counters[index]
            emitted.append(f"      {counter} = {counter} + 1")
            if names and point.kind in ("loop_back", "loop_pass"):
                for watched in names:
                    emitted.append(
                        f"      CALL OTIS_TRACE('{tag}','{point.label}."
                        f"{watched[:8]}',NOEL,NPT,KINC,{counter},"
                        f"DBLE({watched}),1)")
            else:
                emitted.append(
                    f"      CALL OTIS_TRACE('{tag}','{point.label}',"
                    f"NOEL,NPT,KINC,{counter},0.0D0,0)")
            # A loop-back must be counted BEFORE the jump: a statement placed
            # after `GO TO` is unreachable.
            before = before or point.kind == "loop_back"
        if before:
            out.extend(emitted)
            out.append(line)
        else:
            out.append(line)
            out.extend(emitted)
    text = "\n".join(out) + "\n" + (TRACE_WRITER % {"unit": TRACE_UNIT})
    return Instrumentation(text=text, points=points, not_instrumented=skipped,
                           watched=list(names))


# ---------------------------------------------------------------------------
# reading a trace back
# ---------------------------------------------------------------------------
@dataclass
class TraceRecord:
    tag: str
    label: str
    element: int
    point: int
    increment: int
    ordinal: int
    value: Optional[float]


def parse_trace(path) -> list:
    """The trace records a run wrote, in order."""
    from pathlib import Path

    records: list = []
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return records
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7 or parts[0] != "TRACE":
            continue
        try:
            numbers = [int(token) for token in parts[3:7]]
        except ValueError:
            continue
        value: Optional[float] = None
        if len(parts) > 7 and parts[7] != "not_measured":
            try:
                value = float(parts[7].replace("E+", "e+").replace("E-", "e-"))
            except ValueError:
                value = None
        records.append(TraceRecord(parts[1], parts[2], *numbers, value))
    return records


def passes_per_call(records: Sequence[TraceRecord]) -> dict:
    """The highest ordinal each trace point reached in each call.

    This is the number the different-iterate hypothesis says must differ
    between the two builds. Compared point by point and call by call, so a
    difference cannot be hidden inside a total.
    """
    highest: dict = {}
    for record in records:
        key = (record.label, record.element, record.point, record.increment)
        highest[key] = max(highest.get(key, 0), record.ordinal)
    return highest


def residuals_per_call(records: Sequence[TraceRecord]) -> dict:
    """Every residual value each trace point wrote, in pass order."""
    series: dict = {}
    for record in records:
        if record.value is None:
            continue
        key = (record.label, record.element, record.point, record.increment)
        series.setdefault(key, []).append((record.ordinal, record.value))
    return {key: [value for _, value in sorted(pairs)]
            for key, pairs in series.items()}


def compare_passes(original: Sequence[TraceRecord],
                   transformed: Sequence[TraceRecord]) -> dict:
    """Where two traces disagree about how many passes a loop took.

    An empty ``differ`` is what refutes the hypothesis: two builds that ran
    every loop the same number of times in every call did not converge to
    different iterates, whatever their outputs say.
    """
    left, right = passes_per_call(original), passes_per_call(transformed)
    keys = set(left) | set(right)
    differ = {key: (left.get(key, 0), right.get(key, 0))
              for key in keys if left.get(key, 0) != right.get(key, 0)}
    return {
        "calls_traced": len(keys),
        "points_original": len(left),
        "points_transformed": len(right),
        "differ": {str(key): value
                   for key, value in sorted(differ.items(), key=str)},
        "verdict": ("the two builds ran every traced loop the same number of "
                    "times in every call, which is what this hypothesis says "
                    "must differ"
                    if not differ else
                    f"{len(differ)} of {len(keys)} traced (point, call) pairs "
                    f"ran a different number of passes"),
    }
