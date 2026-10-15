"""The LAPACK/BLAS a stand-alone build of an ORIGINAL UMAT links.

Inside Abaqus a UMAT's calls to DGESV, DSYEV, DGEMM and the like go to the
solver's own MKL. A stand-alone build (the provider verifier's reference, the
six-check gate's offline replays, the routine-level harness) has to supply a
library itself. In order of preference, the first one that links and runs a
probe program on this machine:

``mkl``        Intel MKL from a oneAPI installation ($MKLROOT, or
               /opt/intel/oneapi/mkl/latest), sequential layer. Not the copy
               bundled inside Abaqus, which is licensed for use by Abaqus.
``openblas``   a system OpenBLAS.
``reference``  the system reference LAPACK and BLAS (liblapack.so.3, libblas.so.3).
``twins``      none of these: the transform's own real bodies of the routines it
               supplies (umat_oti.transform.abaqus_utility_definitions), which
               follow reference-LAPACK semantics but are not LAPACK.

``UMAT_OTI_LAPACK`` overrides the choice: one of the names above, or
``flags:<link flags>`` for a library given explicitly. Every build that uses
this records :meth:`HostLapack.as_dict` beside its result.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ENVIRONMENT = "UMAT_OTI_LAPACK"
KINDS = ("mkl", "openblas", "reference", "twins")

_PROBE = """      PROGRAM P
      DOUBLE PRECISION A(2,2), B(2), S(2,2), W(2), WORK(10)
      INTEGER IPIV(2), INFO
      A(1,1) = 4.0D0
      A(2,1) = 1.0D0
      A(1,2) = 2.0D0
      A(2,2) = 3.0D0
      B(1) = 1.0D0
      B(2) = 2.0D0
      CALL DGESV(2, 1, A, 2, IPIV, B, 2, INFO)
      IF (INFO .NE. 0) STOP 2
      S(1,1) = 2.0D0
      S(2,1) = 1.0D0
      S(1,2) = 1.0D0
      S(2,2) = 2.0D0
      CALL DSYEV('V', 'U', 2, S, 2, W, WORK, 10, INFO)
      IF (INFO .NE. 0) STOP 3
      IF (ABS(W(2) - 3.0D0) .GT. 1.0D-12) STOP 4
      END
"""


@dataclass(frozen=True)
class HostLapack:
    """One LAPACK/BLAS choice and how a given compiler links it."""

    kind: str
    description: str
    flags: tuple = ()
    libraries: tuple = ()
    rejected: tuple = field(default=(), compare=False)

    @property
    def is_library(self) -> bool:
        return self.kind != "twins"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "description": self.description,
                "link_flags": list(self.flags), "libraries": list(self.libraries),
                **({"not_used": list(self.rejected)} if self.rejected else {})}


def _ldconfig(name: str) -> list:
    try:
        listed = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True,
                                timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split("=>")[-1].strip() for line in listed.splitlines()
            if line.strip().startswith(name) and "x86-64" in line]


def _mkl_dir() -> Path | None:
    roots = [os.environ.get("MKLROOT", ""), "/opt/intel/oneapi/mkl/latest"]
    for root in roots:
        if not root:
            continue
        for sub in ("lib/intel64", "lib"):
            directory = Path(root) / sub
            if (directory / "libmkl_core.so").is_file():
                return directory.resolve()
    return None


def _candidates(compiler: str) -> list:
    out = []
    mkl = _mkl_dir()
    if mkl is not None:
        interface = "mkl_gf_lp64" if Path(compiler).name.startswith("gfortran") else "mkl_intel_lp64"
        out.append(HostLapack("mkl", f"Intel MKL (sequential) in {mkl}",
                              (f"-L{mkl}", f"-Wl,-rpath,{mkl}", f"-l{interface}", "-lmkl_sequential",
                               "-lmkl_core", "-lpthread", "-lm", "-ldl"),
                              (str(mkl / f"lib{interface}.so"), str(mkl / "libmkl_core.so"))))
    for path in _ldconfig("libopenblas.so"):
        out.append(HostLapack("openblas", f"OpenBLAS {path}", (path,), (path,)))
        break
    lapack, blas = _ldconfig("liblapack.so"), _ldconfig("libblas.so")
    if lapack and blas:
        out.append(HostLapack("reference", f"reference LAPACK {lapack[0]} with BLAS {blas[0]}",
                              (lapack[0], blas[0]), (lapack[0], blas[0])))
    return out


def _links(candidate: HostLapack, compiler: str) -> str:
    """"" when a probe program calling DGESV and DSYEV links and runs; else why not."""
    if shutil.which(compiler) is None:
        return f"{compiler} is not on PATH"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "probe.f"
        source.write_text(_PROBE)
        built = subprocess.run([compiler, str(source), *candidate.flags, "-o", str(Path(tmp) / "probe")],
                               capture_output=True, text=True, cwd=tmp)
        if built.returncode != 0:
            return f"does not link: {(built.stderr or built.stdout).strip()[-300:]}"
        ran = subprocess.run([str(Path(tmp) / "probe")], capture_output=True, text=True, cwd=tmp)
        if ran.returncode != 0:
            return f"probe exited {ran.returncode}: {(ran.stderr or ran.stdout).strip()[-300:]}"
    return ""


@lru_cache(maxsize=None)
def host_lapack(compiler: str = "gfortran") -> HostLapack:
    """The LAPACK/BLAS ``compiler`` links on this machine (see the module text)."""
    wanted = os.environ.get(ENVIRONMENT, "auto").strip() or "auto"
    twins = HostLapack("twins", "no LAPACK library found: the transform's real twins of the supplied "
                                "routines (reference-LAPACK semantics, not LAPACK)")
    if wanted == "twins":
        return HostLapack("twins", "the transform's real twins, as requested by " + ENVIRONMENT)
    if wanted.startswith("flags:"):
        flags = tuple(wanted[len("flags:"):].split())
        chosen = HostLapack("explicit", f"link flags from {ENVIRONMENT}", flags, flags)
        why = _links(chosen, compiler)
        if why:
            raise RuntimeError(f"{ENVIRONMENT}={wanted!r}: {why}")
        return chosen
    rejected = []
    for candidate in _candidates(compiler):
        if wanted not in ("auto", candidate.kind):
            continue
        why = _links(candidate, compiler)
        if not why:
            return HostLapack(candidate.kind, candidate.description, candidate.flags,
                              candidate.libraries, tuple(rejected))
        rejected.append(f"{candidate.description}: {why}")
    if wanted not in ("auto",):
        raise RuntimeError(f"{ENVIRONMENT}={wanted!r}: no such library links here ({'; '.join(rejected)})")
    return HostLapack(twins.kind, twins.description, rejected=tuple(rejected))
