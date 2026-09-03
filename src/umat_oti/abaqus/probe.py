"""A verification-only record of what a UMAT computed, at full precision.

Abaqus stores ODB field output in single precision. Measured, not assumed: a
uniaxial-strain stress whose exact value is 2826.923076923077 comes back from
``odbAccess`` as 2826.923095703125, which is bit-exactly ``float32`` of it.
Seven digits is ample for confirming that a job ran and for comparing two
primal histories; it is not ample for a centred difference, where the answer is
the difference of two nearly equal numbers and the leading digits cancel.

So the instrumented UMAT writes its own record. Three properties make that
honest:

**It is separate.** The probe writes to its own file through its own unit. No
value is smuggled through STATEV, which belongs to the model and is compared
between the original and transformed builds like any other physical output.

**It is inert.** The probe is a subroutine call that reads its arguments and
writes text. It assigns nothing the UMAT will read, so a build carrying it
computes exactly what a build without it computes -- and that is checked, by
running both and comparing.

**It is declared.** The file it writes says which job, element, point and
increment each record belongs to, so a reader can tell what was measured
rather than inferring it from row order.
"""
from __future__ import annotations

import re

from pathlib import Path
from typing import Optional

#: The unit the probe writes on. High enough to stay clear of anything Abaqus
#: or a UMAT is likely to have opened; the probe closes it every call so no
#: state is held between increments.
PROBE_UNIT = 197

#: Fixed-form Fortran, because the sources it is appended to are fixed-form and
#: Abaqus compiles one bundle in one form.
PROBE_SOURCE = """
C     ==================================================================
C     OTIS-PROBE: verification-only output. Writes what the UMAT was
C     given and what it computed, at full precision, because Abaqus
C     stores ODB field output as single. Reads its arguments and writes
C     text; assigns nothing the UMAT reads, so a build carrying it
C     computes what a build without it computes.
C     Nothing here belongs to the model. STATEV is untouched.
C
C     Two records per call. The ENTRY record is what makes an offline
C     finite difference of this exact increment possible: a centred
C     difference has to re-run the increment from the state it started
C     in, and by the time the UMAT returns, STRESS and STATEV have been
C     overwritten with the answer. Recording only the answer would leave
C     the starting point unrecoverable and the derivative uncheckable.
C     ==================================================================
      SUBROUTINE OTIS_PROBE_OPEN(IUNIT,IOS)
      IMPLICIT NONE
      INTEGER IUNIT,IOS
      CHARACTER*256 FNAME
C     The runner names the file through the environment, because the
C     directory the solver runs in is its business and not ours -- writing
C     to a relative path put the record somewhere no caller could find.
      FNAME = ' '
      CALL GETENV('OTIS_PROBE_FILE',FNAME)
      IF (FNAME .EQ. ' ') FNAME = 'otis_probe.txt'
      OPEN(UNIT=IUNIT,FILE=FNAME,STATUS='UNKNOWN',
     1     POSITION='APPEND',IOSTAT=IOS)
C     A silent failure here would look exactly like a probe that was never
C     called, so say which it was. Unit 6 is the .msg/.log Abaqus captures.
      IF (IOS .NE. 0) WRITE(6,*) 'OTIS-PROBE: open failed ',IOS
      RETURN
      END

      SUBROUTINE OTIS_PROBE_IN(TAG,NOEL,NPT,KSTEP,KINC,TIME,DTIME,
     1                      STRESS,NTENS,STATEV,NSTATV,STRAN,DSTRAN,
     2                      PROPS,NPROPS,TEMP,DTEMP,DFGRD0,DFGRD1,DROT,
     3                      NDI,NSHR,CELENT,COORDS)
      IMPLICIT NONE
      CHARACTER*(*) TAG
      INTEGER NOEL,NPT,KSTEP,KINC,NTENS,NSTATV,NPROPS,NDI,NSHR,I,J,IOS
      DOUBLE PRECISION TIME,DTIME,STRESS(NTENS),STATEV(*),STRAN(NTENS)
      DOUBLE PRECISION DSTRAN(NTENS),PROPS(*),TEMP,DTEMP,CELENT
      DOUBLE PRECISION DFGRD0(3,3),DFGRD1(3,3),DROT(3,3),COORDS(3)
      CALL OTIS_PROBE_OPEN(%(unit)d,IOS)
      IF (IOS .NE. 0) RETURN
      WRITE(%(unit)d,900) TAG,NOEL,NPT,KSTEP,KINC,TIME
  900 FORMAT('ENTRY ',A,1X,I8,1X,I8,1X,I8,1X,I8,1X,E26.17E3)
      WRITE(%(unit)d,903) NTENS,NSTATV,NPROPS,NDI,NSHR
  903 FORMAT('SHAPE',5(1X,I8))
      WRITE(%(unit)d,901) 'DTIME',1
      WRITE(%(unit)d,902) DTIME
      WRITE(%(unit)d,901) 'STRESS0',NTENS
      WRITE(%(unit)d,902) (STRESS(I),I=1,NTENS)
      WRITE(%(unit)d,901) 'STATEV0',NSTATV
      WRITE(%(unit)d,902) (STATEV(I),I=1,NSTATV)
      WRITE(%(unit)d,901) 'STRAN',NTENS
      WRITE(%(unit)d,902) (STRAN(I),I=1,NTENS)
      WRITE(%(unit)d,901) 'DSTRAN',NTENS
      WRITE(%(unit)d,902) (DSTRAN(I),I=1,NTENS)
      WRITE(%(unit)d,901) 'PROPS',NPROPS
      WRITE(%(unit)d,902) (PROPS(I),I=1,NPROPS)
      WRITE(%(unit)d,901) 'TEMP',2
      WRITE(%(unit)d,902) TEMP,DTEMP
      WRITE(%(unit)d,901) 'DFGRD0',9
      WRITE(%(unit)d,902) ((DFGRD0(I,J),J=1,3),I=1,3)
      WRITE(%(unit)d,901) 'DFGRD1',9
      WRITE(%(unit)d,902) ((DFGRD1(I,J),J=1,3),I=1,3)
      WRITE(%(unit)d,901) 'DROT',9
      WRITE(%(unit)d,902) ((DROT(I,J),J=1,3),I=1,3)
      WRITE(%(unit)d,901) 'COORDS',4
      WRITE(%(unit)d,902) (COORDS(I),I=1,3),CELENT
  901 FORMAT(A,1X,I8)
  902 FORMAT(4(1X,E26.17E3))
      CLOSE(%(unit)d)
      RETURN
      END

      SUBROUTINE OTIS_PROBE(TAG,NOEL,NPT,KSTEP,KINC,TIME,
     1                      STRESS,NTENS,STATEV,NSTATV,DDSDDE)
      IMPLICIT NONE
      CHARACTER*(*) TAG
      INTEGER NOEL,NPT,KSTEP,KINC,NTENS,NSTATV,I,J,IOS
      DOUBLE PRECISION TIME,STRESS(NTENS),STATEV(*),DDSDDE(NTENS,NTENS)
      CALL OTIS_PROBE_OPEN(%(unit)d,IOS)
      IF (IOS .NE. 0) RETURN
      WRITE(%(unit)d,900) TAG,NOEL,NPT,KSTEP,KINC,TIME
  900 FORMAT('RECORD ',A,1X,I8,1X,I8,1X,I8,1X,I8,1X,E26.17E3)
      WRITE(%(unit)d,901) 'STRESS',NTENS
      WRITE(%(unit)d,902) (STRESS(I),I=1,NTENS)
      WRITE(%(unit)d,901) 'STATEV',NSTATV
      WRITE(%(unit)d,902) (STATEV(I),I=1,NSTATV)
      WRITE(%(unit)d,901) 'DDSDDE',NTENS*NTENS
      WRITE(%(unit)d,902) ((DDSDDE(I,J),J=1,NTENS),I=1,NTENS)
  901 FORMAT(A,1X,I8)
  902 FORMAT(4(1X,E26.17E3))
      CLOSE(%(unit)d)
      RETURN
      END
""" % {"unit": PROBE_UNIT}


def probe_call(tag: str, indent: str = "      ") -> str:
    """The one statement that records what an increment computed.

    Placed immediately before the UMAT's RETURN, where STRESS, STATEV and
    DDSDDE all hold the values the increment converged to.
    """
    # The continuation marker belongs in column 6, which means five spaces
    # before it and not the statement indent.
    return (
        f"{indent}CALL OTIS_PROBE('{tag}',NOEL,NPT,KSTEP,KINC,TIME(2),\n"
        f"     1     STRESS,NTENS,STATEV,NSTATV,DDSDDE)\n"
    )


def entry_call(tag: str, indent: str = "      ") -> str:
    """The statement that records what an increment was given.

    Placed before the UMAT's first executable statement, where STRESS and
    STATEV still hold the state the increment starts from. Without this the
    starting point is gone by the time the routine returns, and an offline
    finite difference has nothing to re-run the increment from.
    """
    return (
        f"{indent}CALL OTIS_PROBE_IN('{tag}',NOEL,NPT,KSTEP,KINC,TIME(2),DTIME,\n"
        f"     1     STRESS,NTENS,STATEV,NSTATV,STRAN,DSTRAN,\n"
        f"     2     PROPS,NPROPS,TEMP,DTEMP,DFGRD0,DFGRD1,DROT,\n"
        f"     3     NDI,NSHR,CELENT,COORDS)\n"
    )


#: The value blocks a record may carry. Named rather than inferred, so a
#: corrupt or truncated file ends a record instead of being read as one.
_BLOCKS = ("STRESS", "STATEV", "DDSDDE", "STRESS0", "STATEV0", "STRAN",
           "DSTRAN", "PROPS", "DTIME", "TEMP", "DFGRD0", "DFGRD1", "DROT",
           "COORDS")


def _whole(token: str) -> Optional[int]:
    """One integer field, or None when Fortran could not fit it.

    A Fortran ``I8`` field that the value does not fit writes ``********``
    instead of digits. That is not a formatting curiosity here: NSTATV is
    passed in by Abaqus and never changed, so a record whose NSTATV reads
    ``********`` is a record written after the subroutine overwrote its own
    argument list -- a UMAT writing past the end of a state array smaller than
    it needs. Seen on the first batch: one source's first record said NSTATV 0
    and a later one said ``********``.

    Worth reporting rather than crashing on, and worth reporting as what it is
    rather than as a parse problem.
    """
    try:
        return int(token)
    except (TypeError, ValueError):
        return None


#: What a record says when a field could not be read. A caller that sees this
#: is looking at a run whose subroutine damaged its own interface, and must not
#: treat the numbers beside it as measurements.
CORRUPT = "corrupt_record"


def parse_probe(path: Path) -> list[dict]:
    """The records the probe wrote, in the order it wrote them.

    A field Fortran could not fit into its format is reported, never crashed
    on. The record carries ``CORRUPT`` with what could not be read, and every
    later block of that record is abandoned: once NSTATV is unreadable there is
    no way to know how many values follow it, so anything parsed past that
    point would be guesswork dressed as a measurement.
    """
    records: list[dict] = []
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return records
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith(("RECORD ", "ENTRY ")):
            index += 1
            continue
        parts = line.split()
        header_numbers = [_whole(token) for token in parts[2:6]]
        record: dict = {
            "kind": "entry" if parts[0] == "ENTRY" else "result",
            "tag": parts[1],
        }
        if any(value is None for value in header_numbers):
            record[CORRUPT] = (
                f"the record header could not be read: {line[:80]!r}. A "
                f"Fortran integer field that does not fit writes asterisks, "
                f"and these are passed in by Abaqus -- so this run overwrote "
                f"its own argument list")
            records.append(record)
            index += 1
            continue
        record.update({
            "element": header_numbers[0], "point": header_numbers[1],
            "step": header_numbers[2], "increment": header_numbers[3],
            "time": float(parts[6].replace("E+", "e+").replace("E-", "e-")),
        })
        index += 1
        while index < len(lines):
            header = lines[index].split()
            if not header:
                break
            if header[0] == "SHAPE":
                shape = [_whole(value) for value in header[1:6]]
                if any(value is None for value in shape):
                    record[CORRUPT] = (
                        f"the shape line could not be read: "
                        f"{lines[index].strip()[:80]!r}. NSTATV and NTENS are "
                        f"passed in by Abaqus and never changed, so a run that "
                        f"cannot print them has written past the end of an "
                        f"array and damaged its own interface")
                    break
                record.update(zip(("NTENS", "NSTATV", "NPROPS", "NDI", "NSHR"),
                                  shape))
                index += 1
                continue
            if header[0] not in _BLOCKS:
                break
            count = _whole(header[1]) if len(header) > 1 else None
            if count is None:
                record[CORRUPT] = (
                    f"the {header[0]} block declares a length that could not "
                    f"be read: {lines[index].strip()[:60]!r}")
                break
            name = header[0]
            index += 1
            values: list[float] = []
            unreadable = ""
            while index < len(lines) and len(values) < count:
                try:
                    values += [float(token) for token in lines[index].split()]
                except ValueError:
                    unreadable = (
                        f"the {name} block holds a number that could not be "
                        f"read: {lines[index].strip()[:60]!r}")
                    break
                index += 1
            if unreadable:
                record[CORRUPT] = unreadable
                break
            record[name] = values[:count]
        records.append(record)
    return records


def converged_only(records: list[dict]) -> list[dict]:
    """One record per increment: the last call, which is the converged one.

    A UMAT is called once per equilibrium iteration, and the probe records
    every call. How many iterations an increment needs is a property of the
    solve, not of the material -- two builds that agree exactly about the
    stress can still take a different number of passes to get there, and
    comparing the raw sequences would report that as a disagreement about the
    model. The last call for an increment is the one whose values Abaqus
    accepted and carried forward, so it is the one worth comparing.

    Each returned record carries the entry record of the same call under
    ``"entry"``, so the increment can be replayed from the state it started
    in. A result with no entry keeps the key absent rather than an empty one:
    a finite difference must be able to tell "not recorded" from "recorded as
    nothing".
    """
    results: dict[tuple, dict] = {}
    entries: dict[tuple, dict] = {}
    for record in records:
        key = (record.get("element"), record.get("point"),
               record.get("step"), record.get("increment"))
        target = entries if record.get("kind") == "entry" else results
        target[key] = record          # later calls replace earlier ones

    ordered = sorted(results, key=lambda k: tuple(
        -1 if part is None else part for part in k))
    paired = []
    for key in ordered:
        record = dict(results[key])
        if key in entries:
            record["entry"] = entries[key]
        paired.append(record)
    return paired


def instrument(source_text: str, tag: str, entry: str = "UMAT") -> tuple[str, bool]:
    """``source_text`` with the probe called at the start and end of ``entry``.

    Returns the text and whether both call sites were found. The exit call goes
    before the *last* RETURN of the entry routine rather than the first: an
    early RETURN is a path the increment did not converge through, and
    recording it would put a value in the file that no comparison should see.

    The entry call goes before the first statement that runs, which is where
    STRESS and STATEV still hold the state the increment starts from. Placing
    it any later would record a starting point the UMAT had already begun to
    overwrite.
    """
    lines = source_text.splitlines(keepends=True)
    start, end = _routine_span(lines, entry)
    if start is None:
        return source_text, False

    last_return = None
    for number in range(start, end):
        if _is_comment(lines[number]):
            continue
        if re.match(r"^\s{6,}RETURN\s*$", lines[number], re.IGNORECASE):
            last_return = number
    if last_return is None:
        return source_text, False

    first_executable = _first_executable(lines, start, end)
    if first_executable is None:
        return source_text, False

    # Insert from the bottom up, so the earlier index stays valid.
    lines.insert(last_return, probe_call(tag))
    lines.insert(first_executable, entry_call(tag))
    return "".join(lines) + PROBE_SOURCE, True


def _is_comment(line: str) -> bool:
    return bool(re.match(r"^[cC*!]", line)) or not line.strip()


def _routine_span(lines: list[str], entry: str) -> tuple[Optional[int], int]:
    """Where the named routine begins, and where the next program unit does."""
    opener = re.compile(rf"^\s{{0,5}}\S?\s*(?:\w+\s+)*SUBROUTINE\s+({entry})\b",
                        re.IGNORECASE)
    any_unit = re.compile(r"^\s{0,5}\S?\s*(?:\w+\s+)*(?:SUBROUTINE|FUNCTION)\s+(\w+)",
                          re.IGNORECASE)
    start = end = None
    for number, line in enumerate(lines):
        if re.match(r"^[cC*!]", line):
            continue
        if not any_unit.match(line):
            continue
        if opener.match(line):
            start = number
        elif start is not None and end is None:
            end = number
    return start, len(lines) if end is None else end


def _first_executable(lines: list[str], start: int, end: int) -> Optional[int]:
    """The first line of the routine that runs rather than declares.

    A continuation line is skipped rather than tested: it carries the tail of
    the statement above it, and inserting a call between a statement and its
    own continuation would split it in half.
    """
    from umat_oti.fortran.regions import _is_executable_line

    for number in range(start + 1, end):
        line = lines[number]
        if _is_comment(line):
            continue
        if len(line) > 5 and line[5] not in " \t":     # column 6: a continuation
            continue
        if _is_executable_line(line[6:] if len(line) > 6 else ""):
            return number
    return None
