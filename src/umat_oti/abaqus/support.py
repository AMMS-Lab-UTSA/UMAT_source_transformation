"""Building the OTI support units so Abaqus can link them into a UMAT.

``abaqus job=... user=...`` compiles exactly one source file. The transformed
UMAT is not one file: it uses modules that the transform emits beside it, and a
module has to be compiled before the code that uses it. So the support units
are built first, here, and added to the link line through a job-local
``abaqus_v6.env``.

They are built with Abaqus's own compile line, read from
``abaqus information=environment`` rather than assumed. That is the whole point
of doing it this way instead of picking a compiler: the support objects are
linked into a shared library beside objects Abaqus compiled itself, and two
Fortran objects only link if they agree about calling convention, module
format, and floating-point flags. Asking Abaqus what it uses is the only way to
agree with it, and it keeps this working on a machine whose compiler is
somewhere else.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

#: The environment file Abaqus reads from the directory a job runs in. Its
#: contents are Python, executed after the site settings, so it can extend the
#: command lines rather than replace them.
JOB_ENVIRONMENT = "abaqus_v6.env"

_SETTING = re.compile(r"^(compile_fortran|link_sl)='(.*)'$", re.MULTILINE)


@dataclass
class SupportBuild:
    """What was built, and what a job needs in order to link it."""

    objects: tuple[Path, ...] = ()
    include_dir: Optional[Path] = None
    compiler: str = ""
    ok: bool = False
    reason: str = ""
    log: str = ""

    def as_dict(self) -> dict:
        return {"objects": [str(o) for o in self.objects],
                "include_dir": str(self.include_dir) if self.include_dir else None,
                "compiler": self.compiler, "ok": self.ok, "reason": self.reason}


def abaqus_settings(abaqus: str = "abaqus", timeout: int = 300) -> dict[str, str]:
    """Abaqus's own ``compile_fortran`` and ``link_sl``, as it reports them."""
    try:
        done = subprocess.run([abaqus, "information=environment"],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    return {name: value for name, value in _SETTING.findall(done.stdout)}


def _compile_command(template: str, source: Path, include: Path) -> list[str]:
    """Abaqus's compile line, with its placeholders filled in.

    ``%I`` is where module files are searched for and written, ``%P`` is the
    source. Both are substituted rather than appended, because their position
    in the line is Abaqus's decision and not ours.

    The substitution is inside each token, not a match against a whole one:
    Abaqus writes the include as ``-I%I``, joined, so a whole-token rule leaves
    the placeholder in the command and the compiler then looks for modules in a
    directory literally named ``%I``.
    """
    parts = [token.replace("%I", str(include)).replace("%P", str(source))
             for token in shlex.split(template)]
    # -module puts the .mod files where the next unit -- and the UMAT -- looks.
    return parts + ["-module", str(include), "-o", str(include / f"{source.stem}.o")]


def compile_order(transform_dir: Path,
                  exclude: Optional[Path] = None) -> tuple[Path, ...]:
    """The support units, in the order the transform says they must be built.

    Module dependencies make the order load-bearing, and the transform is what
    knows it. Reading the order from a file it wrote is what keeps this from
    encoding a list of unit names that would go stale the moment the emitter
    gained one.

    The order includes the transformed UMAT itself, because it is the last
    thing to compile. ``exclude`` drops it, which every caller that compiles
    the UMAT separately needs: ``abaqus user=`` builds it, and so does the
    replay driver's own link line, so leaving it here builds it twice and the
    link fails on every routine in the file at once.
    """
    transform_dir = Path(transform_dir)
    listing = transform_dir / "compile_order.txt"
    if not listing.is_file():
        return ()
    skip = Path(exclude).resolve() if exclude is not None else None
    units = []
    for line in listing.read_text(errors="replace").splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        candidate = transform_dir / name
        if not candidate.is_file():
            continue
        if skip is not None and candidate.resolve() == skip:
            continue
        units.append(candidate)
    return tuple(units)


def build_support(
    units: Sequence[Path], work_dir: Path, *, abaqus: str = "abaqus",
    timeout: int = 1800,
) -> SupportBuild:
    """Compile each unit with Abaqus's own compile line, in the order given."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    build = SupportBuild(include_dir=work_dir)

    if not units:
        build.reason = "no support units were named, so none were built"
        return build
    if shutil.which(abaqus) is None:
        build.reason = f"{abaqus} is not on PATH; the support cannot be built"
        return build
    settings = abaqus_settings(abaqus)
    template = settings.get("compile_fortran")
    if not template:
        build.reason = ("abaqus did not report a compile_fortran line, so the "
                        "support cannot be built the way the UMAT will be")
        return build
    build.compiler = shlex.split(template)[0]

    # A transformed source keeps the `include 'aba_param.inc'` its original
    # had, and Abaqus's reported compile line does not carry the path to it --
    # the launcher adds that itself when it compiles a user subroutine. A unit
    # built here therefore needs it added, or the include fails to open.
    from umat_oti.abaqus.replay import abaqus_include_dir

    header = abaqus_include_dir(abaqus)
    extra_includes = [f"-I{header}"] if header is not None else []

    objects: list[Path] = []
    transcript: list[str] = []
    for unit in units:
        command = _compile_command(template, Path(unit), work_dir)
        command[1:1] = extra_includes
        try:
            done = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                                  text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            build.reason = f"{Path(unit).name}: {type(error).__name__}: {error}"
            build.log = "\n".join(transcript)
            return build
        transcript.append(f"$ {' '.join(command)}\n{done.stdout}{done.stderr}")
        produced = work_dir / f"{Path(unit).stem}.o"
        if done.returncode != 0 or not produced.is_file():
            build.reason = (f"{Path(unit).name} did not compile with Abaqus's own "
                            f"compile line (exit {done.returncode})")
            build.log = "\n".join(transcript)[-8000:]
            return build
        objects.append(produced)

    build.objects = tuple(objects)
    build.ok = True
    build.log = "\n".join(transcript)[-8000:]
    return build


def link_environment(build: SupportBuild) -> str:
    """The job-local ``abaqus_v6.env`` that links what was built.

    It extends the two command lines rather than assigning them. Abaqus's own
    flags carry the ABI the rest of the link expects, so replacing either line
    with one written here would produce a library that loads and then behaves
    differently -- the worst available failure mode.

    Paths are written out in full. Abaqus executes this file without defining
    ``__file__``, so it cannot locate itself, and resolving against the working
    directory would depend on where the solver happens to run. Both are known
    here, at the moment the file is written, so neither has to be inferred.
    """
    names = [f"    {str(object_file)!r}," for object_file in build.objects]
    include = str(build.include_dir or "")
    return (
        "# Generated by umat_oti.abaqus.support. Links the OTI support objects\n"
        "# alongside the transformed UMAT.\n"
        "#\n"
        "# Abaqus's user= takes a single source file, and the OTI support is\n"
        "# separate compilation units carrying modules. They are pre-built with\n"
        "# the compile line Abaqus reported for itself, so they share its ABI.\n"
        "# Both lines below are extended, never replaced.\n"
        "_objects = [\n" + "\n".join(names) + "\n]\n"
        "\n"
        "# The module files the support units wrote live here, so the UMAT's own\n"
        "# compile gains an include path.\n"
        f"compile_fortran = compile_fortran[:1] + ['-I{include}'] + compile_fortran[1:]\n"
        "\n"
        "# The objects go after %F, which is where Abaqus puts the object it just\n"
        "# built from user=. A module's object has to follow the code that uses it.\n"
        "link_sl = list(link_sl)\n"
        "_at = link_sl.index('%F') + 1\n"
        "link_sl[_at:_at] = _objects\n"
    )


def install_support(build: SupportBuild, job_dir: Path) -> Optional[Path]:
    """Write the environment file into the directory the job will run in."""
    if not build.ok:
        return None
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / JOB_ENVIRONMENT
    path.write_text(link_environment(build), encoding="utf-8")
    return path
