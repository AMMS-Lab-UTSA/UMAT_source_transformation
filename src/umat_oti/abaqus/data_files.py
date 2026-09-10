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
