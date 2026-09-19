"""Files a UMAT opens by name, and where to find them.

Some constitutive models are not written entirely in Fortran. A growth law may
read its target shape from a table, a crystal-plasticity model its
orientations, a fitted model its coefficients -- and the routine opens the file
by name and reads it.

The name is usually the author's own path. ``Growth-Alex.for`` opens

    open(301, FILE='T:\\Abaqus-Temp\\20231205AlexCoarse\\'//'Lambda10.csv',
         status="old")

which named a drive on the author's Windows machine. Run anywhere else, the
Fortran runtime aborts inside the element loop -- and the job leaves a ``.msg``
whose last legible line is the file name it wanted. Eleven corpus entries
failed that way and were recorded as the ORIGINAL failing to run.

The data is not missing. ``Lambda10.csv`` is in the repository, beside the
source, published by the same author. What is missing is the path. So the file
is staged into the job's own directory under the exact literal name the source
asks for -- backslashes and all, which are ordinary characters in a POSIX file
name -- and the routine opens it where it looks for it.

Only a file the source REQUIRES is looked for. ``status='old'`` says the file
must exist; ``status='unknown'`` or ``'replace'`` says the routine is writing
it, and a routine's own output is not a dependency. And only a file published
in the same repository is staged, matched on its base name: supplying a table
from somewhere else would be inventing the data the model runs on.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

#: An OPEN with a literal file name. Fortran lets the name be built by
#: concatenation -- ``'dir\\'//'name.csv'`` -- so the pieces are joined before
#: the name is read out.
_OPEN = re.compile(r"OPEN\s*\((?P<body>[^)]*)\)", re.IGNORECASE | re.DOTALL)
_FILE = re.compile(r"FILE\s*=\s*(?P<name>(?:'[^']*'|\"[^\"]*\")"
                   r"(?:\s*//\s*(?:'[^']*'|\"[^\"]*\"))*)", re.IGNORECASE)
_STATUS = re.compile(r"STATUS\s*=\s*['\"]([A-Za-z]+)['\"]", re.IGNORECASE)
_PIECE = re.compile(r"'([^']*)'|\"([^\"]*)\"")

#: Statuses that say the file has to be there already. Anything else is the
#: routine writing its own output, which is not a dependency.
REQUIRED_STATUS = frozenset({"old"})


@dataclass(frozen=True)
class Opened:
    """One file the source opens, as it names it."""

    name: str
    status: str
    required: bool

    @property
    def basename(self) -> str:
        """The last component, under either separator.

        The name is the author's, and authors write Windows paths. Splitting on
        both is what lets ``T:\\Abaqus-Temp\\x\\Lambda10.csv`` be recognised as
        ``Lambda10.csv``.
        """
        return re.split(r"[\\/]", self.name)[-1]

    def as_dict(self) -> dict:
        return {"name": self.name, "basename": self.basename,
                "status": self.status, "required": self.required}


def _joined(literal: str) -> str:
    pieces = [single or double for single, double in _PIECE.findall(literal)]
    return "".join(pieces)


def joined_statements(text: str) -> str:
    """The source with its continuation lines joined onto the statement above.

    A name built by concatenation is routinely split across a continuation --

        open(301,FILE='T:\\Abaqus-Temp\\20231205AlexCoarse\\'//
     &  'Lambda10.csv',status="old")

    -- and reading the first line alone gives a directory and no file. Both
    forms: fixed marks the continuation in column 6, free ends the line above
    with an ampersand.
    """
    out: list = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] == "!" or line[:1] in "cC*":
            continue
        fixed = (len(line) > 5 and line[5] not in " \t0"
                 and not line[:5].strip())
        free = bool(out) and out[-1].rstrip().endswith("&")
        if fixed:
            out[-1] = out[-1].rstrip() + line[6:].strip() if out else line[6:]
            continue
        if free:
            out[-1] = out[-1].rstrip().rstrip("&") + line.lstrip().lstrip("&")
            continue
        out.append(line)
    return "\n".join(out)


def opened_files(text: str) -> tuple:
    """Every file this source opens by a literal name, and whether it needs it."""
    text = joined_statements(text)
    found: list = []
    seen: set = set()
    for match in _OPEN.finditer(text):
        body = match.group("body")
        named = _FILE.search(body)
        if not named:
            continue
        name = _joined(named.group("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        status = ""
        found_status = _STATUS.search(body)
        if found_status:
            status = found_status.group(1).lower()
        found.append(Opened(name=name, status=status,
                            required=status in REQUIRED_STATUS))
    return tuple(found)



#: Fixed-form statements end at column 72 unless the compiler is told
#: otherwise. Abaqus always passes ``-extend_source``, but the replay driver
#: builds with whatever compiler it finds, so the rewrite wraps at the
#: standard column rather than relying on an extension.
FIXED_LIMIT = 72
FREE_LIMIT = 132


def _chunks(value: str, first: int, rest: int) -> list:
    """Split a string into pieces that fit the widths given, largest first."""
    out: list = []
    remaining = value
    width = max(1, first)
    while len(remaining) > width:
        out.append(remaining[:width])
        remaining = remaining[width:]
        width = max(1, rest)
    out.append(remaining)
    return out


def _rewrite_line(line: str, literal: str, value: str, form: str) -> list:
    """Replace one quoted literal in one physical line, wrapping if needed.

    A long absolute path does not fit in what is left of a fixed-form
    statement, and a character literal cannot simply be continued: the
    standard pads the line to column 72 with blanks, which would put those
    blanks INSIDE the name. So an over-long value is emitted as concatenated
    pieces -- ``'/long/pa'//`` then ``'th/file.csv'`` -- which is the same
    string by any compiler's reading of it.

    The TAIL is wrapped too, and separately. A value that fits in one piece
    can still leave a line too long once ``,status="old")`` is put back after
    it; this used to emit the single piece twice, producing a name
    concatenated with itself.
    """
    free = form == "free"
    limit = FREE_LIMIT if free else FIXED_LIMIT
    head, _, tail = line.partition(literal)
    if not _:
        return [line]
    single = f"{head}'{value}'{tail}"
    if len(single) <= limit:
        return [single]
    joiner = "// &" if free else "//"
    marker = "     &"
    first = limit - len(head) - 2 - len(joiner)
    rest = limit - len(marker) - 2 - len(joiner)
    if first < 1 or rest < 1:                      # pragma: no cover - defensive
        return [single]
    pieces = _chunks(value, first, rest)
    lines: list = []
    for index, piece in enumerate(pieces):
        opening = head if index == 0 else marker
        last = index == len(pieces) - 1
        lines.append(f"{opening}'{piece}'" + ("" if last else joiner))
    # The tail goes on the last line if it fits there, and on a continuation
    # of its own if it does not. Either way it is written once.
    if len(lines[-1]) + len(tail) <= limit:
        lines[-1] = lines[-1] + tail
    else:
        lines.append(f"{marker}{tail}")
    return lines


def _pieces_of(text: str, opened: Opened) -> list:
    """The literal fragments this OPEN concatenates to name its file.

    Read from the joined statement, so a name split across a continuation is
    seen whole -- and returned in order, because the rewrite empties every
    fragment but the last.
    """
    for match in _OPEN.finditer(joined_statements(text)):
        named = _FILE.search(match.group("body"))
        if not named or _joined(named.group("name")) != opened.name:
            continue
        return [single or double
                for single, double in _PIECE.findall(named.group("name"))]
    return []


def redirect(text: str, directory: Path, *, staged: Sequence[str] = (),
             form: str = "") -> tuple:
    r"""Point every literal OPEN name at ``directory``.

    Abaqus/Standard does not run in the job directory. It runs in a scratch
    directory of its own making -- ``/tmp/<user>_<job>_<pid>`` -- so a routine
    that opens a file by a name with no directory in it, or by the author's
    own Windows path, looks there and not where the file was staged. Measured
    on Growth-Alex.for, which aborts in the element loop of its first
    increment with::

        forrtl: severe (29): file not found, unit 301, file
        /tmp/ammslab3_original_1902146/T:\Abaqus-Temp\...\Lambda10.csv

    with the file present, under exactly that name, in the job directory.
    Thirteen entries failed their original job this way and were reported as
    the model's failure rather than the harness's.

    So the name is made absolute. Only names in ``staged`` are touched, so the
    rewrite can never point at a file that is not there, and only the path is
    changed -- a literal is a literal in both builds, and the same rewrite is
    applied to both, so nothing about the arithmetic moves.

    Returns the rewritten text and what was pointed where.
    """
    directory = Path(directory).resolve()
    allowed = set(staged) if staged else None
    wanted = [opened for opened in opened_files(text)
              if allowed is None or opened.name in allowed]
    if not wanted:
        return text, {}

    # Longest first, so 'dir\name.csv' is not half-matched by 'name.csv'.
    pointed: dict = {}
    lines = text.splitlines()
    for opened in sorted(wanted, key=lambda o: -len(o.name)):
        target = str(directory / opened.name)
        pieces = re.split(r"([\\/])", opened.name)
        # Rewritten piece by piece, wherever the author split the name.
        #
        # This used to handle only two shapes: the whole path in one literal,
        # or a directory literal plus the bare basename. A concatenation can
        # split ANYWHERE, and five corpus entries split it mid-directory --
        #
        #     open(301,FILE='C:\\Users\\12872\\Desktop\\'//
        #    &  'Bunny\\part1\\E0.CSV',status="old")
        #
        # -- where the tail is 'Bunny\\part1\\E0.CSV', a sub-path and not the
        # basename. Neither shape matched, nothing was rewritten, and all five
        # died in for_open on the first UMAT call with the staged file sitting
        # unread in the job directory.
        #
        # The general rule needs no shapes: every piece but the last becomes
        # an empty literal and the last carries the absolute path, so the
        # concatenation still evaluates to one name however it was divided.
        pieces = _pieces_of(text, opened)
        replaced = False
        if pieces:
            last = pieces[-1]
            for index, line in enumerate(lines):
                quoted = [f"'{last}'", f'"{last}"']
                hit = next((q for q in quoted if q in line), None)
                if hit is None:
                    continue
                lines[index:index + 1] = _rewrite_line(line, hit, target, form)
                # Every earlier piece is now redundant. Emptying rather than
                # deleting keeps the // operators and the line structure
                # exactly as the author wrote them.
                for earlier in pieces[:-1]:
                    for other in range(max(0, index - 6),
                                       min(len(lines), index + 6)):
                        for q in (f"'{earlier}'", f'"{earlier}"'):
                            if q in lines[other]:
                                lines[other] = lines[other].replace(
                                    q, q[0] + q[0], 1)
                                break
                        else:
                            continue
                        break
                replaced = True
                break
        if replaced:
            pointed[opened.name] = target
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), pointed


@dataclass
class Staging:
    """What was put beside the job, and what could not be found."""

    staged: dict = field(default_factory=dict)
    missing: tuple = ()
    optional_missing: tuple = ()
    searched: str = ""

    @property
    def complete(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict:
        return {"staged": dict(self.staged), "missing": list(self.missing),
                "optional_missing": list(self.optional_missing),
                "searched": self.searched}

    def reason(self) -> str:
        if self.missing:
            return (f"this source opens {len(self.missing)} file(s) it "
                    f"requires and that nothing in its repository publishes: "
                    f"{', '.join(self.missing)}. The data the model runs on is "
                    f"not here, and supplying a table from somewhere else "
                    f"would be inventing it")
        if self.staged:
            return (f"{len(self.staged)} data file(s) the source opens were "
                    f"staged beside the job under the exact name it asks for: "
                    f"{', '.join(sorted(self.staged))}")
        return "this source opens no file it needs beside it"


def stage(source: Path, job_dir: Path, *, roots: Sequence[Path] = ()) -> Staging:
    """Put every required data file where the source will look for it.

    Searched beside the source first and then through its repository, matched
    on base name. Written under the LITERAL name the source uses, so a Windows
    path becomes a POSIX file name containing backslashes and the OPEN finds
    it where it asks.
    """
    source = Path(source)
    job_dir = Path(job_dir)
    try:
        text = source.read_text(errors="replace")
    except OSError as error:                       # pragma: no cover
        return Staging(searched=f"the source could not be read: {error}")

    wanted = opened_files(text)
    if not wanted:
        return Staging(searched="the source opens no file by a literal name")

    places = [source.parent, *[Path(root) for root in roots]]
    staging = Staging(searched="; ".join(str(place) for place in places))
    missing: list = []
    optional: list = []
    for opened in wanted:
        found = None
        for place in places:
            candidate = Path(place) / opened.basename
            if candidate.is_file():
                found = candidate
                break
            matches = sorted(Path(place).rglob(opened.basename))
            if matches:
                found = matches[0]
                break
        if found is None:
            (missing if opened.required else optional).append(opened.name)
            continue
        target = job_dir / opened.name
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(found, target)
        except OSError as error:                   # pragma: no cover
            (missing if opened.required else optional).append(
                f"{opened.name} ({error})")
            continue
        staging.staged[opened.name] = str(found)
    staging.missing = tuple(missing)
    staging.optional_missing = tuple(optional)
    return staging
