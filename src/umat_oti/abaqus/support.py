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


#: What ifort says when the file it was given is not the problem. A source
#: that USEs a module compiled elsewhere, or includes a header that is not on
#: the path, fails to compile without being malformed -- so a compile failure
#: is only evidence about the AUTHOR's source when none of these appear.
DEPENDENCY_DIAGNOSTICS = (
    "cannot open include file",
    # The -fpp preprocessor's own spelling, which is not the compiler's. Nine
    # sources reporting "can't find include file: Abaqus_Definitions.f90" were
    # classified as malformed because only the compiler's wording was matched;
    # they are perfectly well-formed files whose companion was not beside them.
    "can't find include file",
    "error in opening the compiled module file",
    "error in opening the Library module file",
    "catastrophic error: cannot open source file",
)


def include_case_variants(header: Optional[Path],
                          into: Path) -> Optional[Path]:
    """A directory of Abaqus's include files under every case they are written in.

    ``INCLUDE 'ABA_PARAM.INC'`` is how most of this corpus spells it and
    ``aba_param.inc`` is what is on disk, and a Linux filesystem does not
    consider those the same file. Abaqus's own launcher papers over that when
    it compiles a user subroutine; a compile driven from here does not, so 227
    of the corpus's 391 sources reported "cannot open include file" and were
    read as unreachable when they compile perfectly.

    Symbolic links, so nothing is copied and the originals stay where they are.
    Returns None when there is no include directory to link.
    """
    if header is None or not Path(header).is_dir():
        return None
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    for entry in sorted(Path(header).iterdir()):
        if not entry.is_file():
            continue
        for spelling in {entry.name, entry.name.upper(), entry.name.lower()}:
            link = into / spelling
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(entry)
            except OSError:                       # pragma: no cover - defensive
                pass
    return into


@dataclass
class CompileCheck:
    """Whether one source compiles on its own, and what the compiler said."""

    ok: bool = False
    #: The compiler's diagnostics, trimmed. Kept whether or not it compiled:
    #: a warning on a unit that built is still what the compiler thought of it.
    log: str = ""
    #: Diagnostics that name a dependency this compile could not reach, rather
    #: than a defect in the file. Non-empty means the failure is about what is
    #: missing beside the file, not about the file.
    missing_dependencies: tuple[str, ...] = ()
    #: Diagnostics that are about the text of this file.
    defects: tuple[str, ...] = ()
    reason: str = ""

    @property
    def source_is_malformed(self) -> bool:
        """The compiler rejected the file itself, not something beside it."""
        return bool(self.defects) and not self.missing_dependencies

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason,
                "defects": list(self.defects),
                "missing_dependencies": list(self.missing_dependencies),
                "log": self.log[-4000:]}


_DIAGNOSTIC = re.compile(r"^(.*?)\((\d+)\):\s*(error|catastrophic error)[^\n]*",
                         re.IGNORECASE | re.MULTILINE)


def compile_one(source: Path, work_dir: Path, *, abaqus: str = "abaqus",
                extra_sources: Sequence[Path] = (), timeout: int = 900,
                form: str = "",
                include_dirs: Sequence[Path] = ()) -> CompileCheck:
    """Compile one source with Abaqus's own compile line, and say what happened.

    This is what separates "the author published a file that does not compile"
    from "our harness could not run it". The first is a fact about the corpus
    and a terminal answer; the second is work to do. They were indistinguishable
    in the record, because a job whose compile aborts writes no .sta, no .msg
    and no .odb -- and the ladder read that as ``original_job_failed``, which
    reads like the harness's fault whichever it was.

    The source is compiled UNMODIFIED. Nothing this pipeline adds -- not the
    probe, not a widened declaration -- is present, so a failure here cannot be
    ours. That is the whole reason the check exists separately from the job.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    check = CompileCheck()
    if shutil.which(abaqus) is None:
        check.reason = f"{abaqus} is not on PATH, so nothing was compiled"
        return check
    template = abaqus_settings(abaqus).get("compile_fortran")
    if not template:
        check.reason = "abaqus did not report a compile_fortran line"
        return check

    from umat_oti.abaqus.replay import abaqus_include_dir
    header = abaqus_include_dir(abaqus)
    case_variants = include_case_variants(header, work_dir / "_includes")

    bundle = Path(source)
    if extra_sources:
        # `abaqus user=` compiles one file, so a UMAT whose helpers live beside
        # it is one compilation unit here too, exactly as the job would build it.
        text = Path(source).read_text(errors="replace")
        for extra in extra_sources:
            text += "\n" + Path(extra).read_text(errors="replace")
        bundle = work_dir / f"bundle{Path(source).suffix or '.f'}"
        bundle.write_text(text, encoding="utf-8")

    # The form is stated rather than left to the suffix. Eight corpus sources
    # are free-form Fortran in a file named .for, and ifort reads the suffix:
    # compiled fixed, every continuation in them is a syntax error and the file
    # looks malformed when it is not.
    from umat_oti.fortran.normalize import detect_source_form

    resolved = (str(form).lower()
                or detect_source_form(Path(source),
                                      Path(source).read_text(errors="replace")))
    command = _compile_command(template, bundle, work_dir)
    command[1:1] = ["-free" if resolved.startswith("free") else "-fixed"]
    includes = [f"-I{path}" for path in include_dirs]
    if case_variants is not None:
        includes.append(f"-I{case_variants}")
    if header is not None:
        includes.append(f"-I{header}")
    command[1:1] = includes
    try:
        done = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        check.reason = f"{type(error).__name__}: {error}"
        return check

    check.log = (done.stdout + done.stderr)[-8000:]
    produced = work_dir / f"{bundle.stem}.o"
    check.ok = done.returncode == 0 and produced.is_file()
    if check.ok:
        check.reason = "compiled with Abaqus's own compile line"
        return check

    lowered = check.log.lower()
    check.missing_dependencies = tuple(
        marker for marker in DEPENDENCY_DIAGNOSTICS if marker.lower() in lowered)
    check.defects = tuple(
        line.strip() for line in check.log.splitlines()
        if re.search(r"\b(error|catastrophic error)\b", line, re.IGNORECASE)
        and not any(marker.lower() in line.lower()
                    for marker in DEPENDENCY_DIAGNOSTICS))[:8]
    if check.missing_dependencies:
        check.reason = (
            f"the compile could not reach something beside the file "
            f"({'; '.join(check.missing_dependencies)}), so this says nothing "
            f"about the file itself")
    elif check.defects:
        check.reason = (
            f"the unmodified source does not compile with Abaqus's own compile "
            f"line: {check.defects[0][:200]}")
    else:
        check.reason = (f"the compile failed (exit {done.returncode}) with no "
                        f"diagnostic this could attribute")
    return check


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


#: Flags that keep the arithmetic valid and change the ORDER it is done in.
#: Abaqus compiles user subroutines with ``-fp-model precise`` and
#: ``-fprotect-parens``, which forbid reassociation; ``fast=2`` permits it.
#: Neither is more correct than the other -- they are two orderings of the same
#: expression -- and the difference between what a source computes under them
#: is that source's own sensitivity to the order its operations are done in.
ASSOCIATION_FLAGS = ("-fp-model", "fast=2", "-no-prec-div", "-no-prec-sqrt")


def association_environment(job_dir: Path,
                            flags: Sequence[str] = ASSOCIATION_FLAGS) -> Path:
    """A job-local env that recompiles the user subroutine with reassociation.

    Written so a source can be run against ITSELF under a different but
    equally valid floating-point model. The difference that comes back is what
    that model's own conditioning does to a change in operation order -- which
    is the only defensible bound on how closely any two implementations of it
    can be expected to agree.

    Extends the compile line rather than replacing it: Abaqus's own flags
    carry the ABI the rest of the link expects.
    """
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / JOB_ENVIRONMENT
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    addition = (
        "\n# Generated by umat_oti.abaqus.support.association_environment.\n"
        "# The same source, compiled with a different but equally valid\n"
        "# floating-point model: reassociation permitted where Abaqus's own\n"
        "# line forbids it. Extends, never replaces.\n"
        "# Appended AFTER Abaqus's own flags and before the source, because\n"
        "# the last -fp-model on an ifort command line is the one that wins:\n"
        "# inserted before them, 'fast=2' was overridden by the 'precise' that\n"
        "# followed it and the control silently measured nothing.\n"
        f"compile_fortran = compile_fortran[:-1] + {list(flags)!r} "
        f"+ compile_fortran[-1:]\n")
    path.write_text(existing + addition, encoding="utf-8")
    return path


def install_support(build: SupportBuild, job_dir: Path) -> Optional[Path]:
    """Write the environment file into the directory the job will run in."""
    if not build.ok:
        return None
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / JOB_ENVIRONMENT
    path.write_text(link_environment(build), encoding="utf-8")
    return path
