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

from pathlib import Path

#: The unit the probe writes on. High enough to stay clear of anything Abaqus
#: or a UMAT is likely to have opened; the probe closes it every call so no
#: state is held between increments.
PROBE_UNIT = 197

#: Fixed-form Fortran, because the sources it is appended to are fixed-form and
#: Abaqus compiles one bundle in one form.
PROBE_SOURCE = """
C     ==================================================================
C     OTIS-PROBE: verification-only output. Writes what the UMAT computed
C     at full precision, because Abaqus stores ODB field output as single.
C     Reads its arguments and writes text; assigns nothing the UMAT reads,
C     so a build carrying it computes what a build without it computes.
C     Nothing here belongs to the model. STATEV is untouched.
C     ==================================================================
      SUBROUTINE OTIS_PROBE(TAG,NOEL,NPT,KSTEP,KINC,TIME,
     1                      STRESS,NTENS,STATEV,NSTATV,DDSDDE)
      IMPLICIT NONE
      CHARACTER*(*) TAG
      INTEGER NOEL,NPT,KSTEP,KINC,NTENS,NSTATV,I,J,IOS
      DOUBLE PRECISION TIME,STRESS(NTENS),STATEV(*),DDSDDE(NTENS,NTENS)
      CHARACTER*256 FNAME
C     The runner names the file through the environment, because the
C     directory the solver runs in is its business and not ours -- writing
C     to a relative path put the record somewhere no caller could find.
      FNAME = ' '
      CALL GETENV('OTIS_PROBE_FILE',FNAME)
      IF (FNAME .EQ. ' ') FNAME = 'otis_probe.txt'
      OPEN(UNIT=%(unit)d,FILE=FNAME,STATUS='UNKNOWN',
     1     POSITION='APPEND',IOSTAT=IOS)
C     A silent failure here would look exactly like a probe that was never
C     called, so say which it was. Unit 6 is the .msg/.log Abaqus captures.
      IF (IOS .NE. 0) THEN
        WRITE(6,*) 'OTIS-PROBE: could not open ',FNAME(1:14),' iostat=',IOS
        RETURN
      END IF
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
    """The one statement that records an increment.

    Placed immediately before the UMAT's RETURN, where STRESS, STATEV and
    DDSDDE all hold the values the increment converged to.
    """
    # The continuation marker belongs in column 6, which means five spaces
    # before it and not the statement indent.
    return (
        f"{indent}CALL OTIS_PROBE('{tag}',NOEL,NPT,KSTEP,KINC,TIME(2),\n"
        f"     1     STRESS,NTENS,STATEV,NSTATV,DDSDDE)\n"
    )


def parse_probe(path: Path) -> list[dict]:
    """The records the probe wrote, in the order it wrote them."""
    records: list[dict] = []
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return records
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("RECORD "):
            index += 1
            continue
        parts = line.split()
        record = {
            "tag": parts[1], "element": int(parts[2]), "point": int(parts[3]),
            "step": int(parts[4]), "increment": int(parts[5]),
            "time": float(parts[6].replace("E+", "e+").replace("E-", "e-")),
        }
        index += 1
        while index < len(lines):
            header = lines[index].split()
            if not header or header[0] not in ("STRESS", "STATEV", "DDSDDE"):
                break
            name, count = header[0], int(header[1])
            index += 1
            values: list[float] = []
            while index < len(lines) and len(values) < count:
                values += [float(token) for token in lines[index].split()]
                index += 1
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
    """
    converged: dict[tuple, dict] = {}
    for record in records:
        key = (record.get("element"), record.get("point"),
               record.get("step"), record.get("increment"))
        converged[key] = record          # later calls replace earlier ones
    return [converged[key] for key in sorted(converged, key=lambda k: tuple(
        -1 if part is None else part for part in k))]


def instrument(source_text: str, tag: str, entry: str = "UMAT") -> tuple[str, bool]:
    """``source_text`` with the probe called at the end of ``entry``.

    Returns the text and whether a call site was found. The probe goes before
    the last RETURN of the entry routine rather than the first: an early
    RETURN is a path the increment did not converge through, and recording it
    would put a value in the file that no comparison should see.
    """
    lines = source_text.splitlines(keepends=True)
    start = end = None
    depth_name = None
    import re

    opener = re.compile(rf"^\s{{0,5}}\S?\s*(?:\w+\s+)*SUBROUTINE\s+({entry})\b",
                        re.IGNORECASE)
    any_unit = re.compile(r"^\s{0,5}\S?\s*(?:\w+\s+)*(?:SUBROUTINE|FUNCTION)\s+(\w+)",
                          re.IGNORECASE)
    for number, line in enumerate(lines):
        if re.match(r"^[cC*!]", line):
            continue
        found = any_unit.match(line)
        if found:
            if opener.match(line):
                start, depth_name = number, found.group(1)
            elif depth_name is not None and start is not None and end is None:
                end = number
    if start is None:
        return source_text, False
    if end is None:
        end = len(lines)

    last_return = None
    for number in range(start, end):
        if re.match(r"^[cC*!]", lines[number]):
            continue
        if re.match(r"^\s{6,}RETURN\s*$", lines[number], re.IGNORECASE):
            last_return = number
    if last_return is None:
        return source_text, False
    lines.insert(last_return, probe_call(tag))
    return "".join(lines) + PROBE_SOURCE, True
