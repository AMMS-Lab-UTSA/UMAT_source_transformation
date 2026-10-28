"""Windows harness shim for the UMAT-OTI re-freeze runs (not part of UMAT-OTI).

UMAT-OTI declares Linux as its platform and executes generated POSIX shell
scripts (for example ``compile_hint.sh``) directly with ``subprocess``. Windows
cannot execute a script by itself, so this shim, loaded through a ``.pth`` file
in the candidate's virtual environment only, prefixes Git-for-Windows bash when
the program to run is a shell script. It changes no UMAT-OTI source and no
numerical code path; every run made with it is labelled "Windows + shim".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BASH = os.environ.get("REFREEZE_BASH", r"C:\Program Files\Git\usr\bin\bash.exe")
_original_init = subprocess.Popen.__init__


def _is_script(program: str) -> bool:
    """Return True when ``program`` names a shell script rather than a binary."""
    if program.lower().endswith(".sh"):
        return True
    path = Path(program)
    if path.suffix.lower() in {".exe", ".bat", ".cmd", ".com"} or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return False
    return head.startswith(b"#!") and (b"sh" in head.split(b"\n", 1)[0])


def _patched_init(self, args, *pargs, **kwargs):  # type: ignore[no-untyped-def]
    if not kwargs.get("shell", False):
        if isinstance(args, (list, tuple)) and args:
            first = os.fspath(args[0])
            if _is_script(first):
                args = [BASH, first, *[os.fspath(a) for a in args[1:]]]
        elif isinstance(args, (str, os.PathLike)):
            first = os.fspath(args)
            if _is_script(first):
                args = [BASH, first]
    _original_init(self, args, *pargs, **kwargs)


subprocess.Popen.__init__ = _patched_init  # type: ignore[method-assign]

# Generated Makefiles embed the compiler path found by shutil.which; a Windows
# path with backslashes is mangled by make's POSIX shell. Return forward slashes.
import shutil  # noqa: E402

_original_which = shutil.which


def _patched_which(cmd, mode=os.F_OK | os.X_OK, path=None):  # type: ignore[no-untyped-def]
    found = _original_which(cmd, mode, path)
    return found.replace("\\", "/") if isinstance(found, str) else found


shutil.which = _patched_which

# MinGW gfortran writes "-o prog" as prog.exe. UMAT-OTI then checks that
# "prog" exists. Treat an extensionless path as existing when prog.exe does;
# CreateProcess already appends .exe when it runs an extensionless name.
import os.path  # noqa: E402

_orig_path_exists = Path.exists
_orig_path_is_file = Path.is_file
_orig_os_exists = os.path.exists
_orig_os_isfile = os.path.isfile


def _exe_twin(p) -> bool:  # type: ignore[no-untyped-def]
    return (
        isinstance(p, str)
        and os.name == "nt"
        and not os.path.splitext(p)[1]
        and _orig_os_isfile(p + ".exe")
    )


def _path_exists(self, *a, **k):  # type: ignore[no-untyped-def]
    return _orig_path_exists(self, *a, **k) or _exe_twin(str(self))


def _path_is_file(self, *a, **k):  # type: ignore[no-untyped-def]
    return _orig_path_is_file(self, *a, **k) or _exe_twin(str(self))


def _os_exists(p):  # type: ignore[no-untyped-def]
    return _orig_os_exists(p) or (isinstance(p, (str, os.PathLike)) and _exe_twin(os.fspath(p)))


def _os_isfile(p):  # type: ignore[no-untyped-def]
    return _orig_os_isfile(p) or (isinstance(p, (str, os.PathLike)) and _exe_twin(os.fspath(p)))


Path.exists = _path_exists  # type: ignore[method-assign]
Path.is_file = _path_is_file  # type: ignore[method-assign]
os.path.exists = _os_exists
os.path.isfile = _os_isfile

# Python 3.8+ on Windows no longer resolves a DLL's dependencies through PATH.
# A ctypes-loaded provider built by MinGW gfortran needs libgfortran and its
# runtime from the compiler's bin directory.
if os.name == "nt":
    _gf = _original_which("gfortran")
    if _gf:
        try:
            os.add_dll_directory(os.path.dirname(_gf))
        except (OSError, AttributeError):
            pass

# Artefact hashing reads the extensionless driver path; read the .exe twin.
_orig_read_bytes = Path.read_bytes


def _path_read_bytes(self):  # type: ignore[no-untyped-def]
    if not _orig_path_exists(self) and _exe_twin(str(self)):
        return _orig_read_bytes(Path(str(self) + ".exe"))
    return _orig_read_bytes(self)


Path.read_bytes = _path_read_bytes  # type: ignore[method-assign]
