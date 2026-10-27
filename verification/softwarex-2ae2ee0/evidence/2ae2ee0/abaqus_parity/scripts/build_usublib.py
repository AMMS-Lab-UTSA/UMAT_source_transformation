"""Build a usub_lib_dir standardU.dll for one build without the Abaqus SMAUsubs SDK (Ada, 2026-10-27).

Usage (from the workspace root):
    refreeze/venv/2ae2ee0/Scripts/python.exe evidence/2ae2ee0/abaqus_parity/scripts/build_usublib.py modelA_orig
    ... modelA_oti | r1_orig | r1_oti

NON-STANDARD LINKING METHOD. This method was re-implemented from the description and the source of ABSS
`src/oracle/abaqus_usersub.cpp::directBuild` at commit 5dcef95. That repository was read only; no ABSS binary
or code is used. This machine's Abaqus 2024 has no user-subroutine development component, so the
supported `abaqus job=... user=...` route refuses to compile or link. Instead:

1. Every Fortran unit is compiled with ifx 2025.1 (ifort is not installed). The flags are Abaqus 2024's
   win86_64.env compile_fortran flags, plus /libs:dll /threads (dynamic Intel runtime, as link_sl expects) and
   with /Qpc64 removed. ifx also ignores /Qprec-sqrt and /Qfp-stack-check (warning #10148). The flags are
   identical for both builds. `aba_param.inc` is the Abaqus-documented double-precision content
   (scripts/include/aba_param.inc).
2. dumpbin lists the external symbols the objects define. Every export of Abaqus's own
   win_b64/code/bin/standardU.dll (except DllMain, _forceCRTManifestCUR and DASSAULT_SYSTEMES_*) that the
   objects define (here only `umat`) is exported from our code. Every other export is a lazy MASM thunk that
   jumps to the same-named function in an unmodified private copy of that stub (abss_abqstub.dll, loaded by
   absolute path from the DLL's own folder).
3. link.exe builds standardU.dll (/dll /noentry /nodefaultlib, with dynamic MSVC and Intel runtimes).
   The job directory's abaqus_v6.env sets usub_lib_dir to this folder, and Abaqus runs WITHOUT user=.
   The Abaqus installation is never modified.

Outputs in build/<build>/: *.obj, standardU.dll/.def, abss_thunks.asm, abss_resolver.c, abss_abqstub.dll
(copy of the stub) and build_transcript.txt (every command and its output). Binaries are not archived.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = Path(r"C:\SIMULIA\EstProducts\2024\win_b64\code\bin\standardU.dll")
VCVARS = r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
IFXVARS = r"C:\Program Files (x86)\Intel\oneAPI\compiler\2025.1\env\vars.bat"
FLAGS = ["/nologo", "/c", "/fpp", "/extend-source", "/DABQ_WIN86_64", "/DABQ_FORTRAN", "/iface:cref", "/recursive",
         "/Qauto", "/align:array64byte", "/Qprec-div", "/Qprec-sqrt", "/Qfma-", "/fp:precise",
         "/Qimf-arch-consistency:true", "/Qfp-speculation:safe", "/Qprotect-parens", "/Qfp-stack-check",
         "/reentrancy:threaded", "/QxSSE3", "/QaxAVX", "/libs:dll", "/threads"]
SUPPORT = ("master_parameters", "real_utils", "otim6n1", "oti_intrinsics")
TRANSFORM = {"modelA": "transform/j2_props", "r1": "transform/umat_j2_voce"}


def tool_env() -> dict:
    """Environment after vcvars64.bat and the ifx compiler vars.bat (not Intel setvars.bat)."""
    base = r"C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem"
    out = subprocess.run(f'cmd /d /c "set PATH={base}&& call "{VCVARS}" >nul 2>&1 && call "{IFXVARS}" intel64 >nul 2>&1 && set"',
                         capture_output=True, text=True, shell=False)
    env = {}
    for line in out.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            k, v = line.split("=", 1)
            env[k] = v
    if "VCToolsInstallDir" not in env:
        raise SystemExit("vcvars64.bat did not load")
    return env


def main(build: str) -> int:
    model, kind = build.rsplit("_", 1)
    bdir = ROOT / "build" / build
    env = tool_env()
    log = [f"# build_usublib.py {build}"]

    search = env.get("PATH") or env.get("Path") or ""

    def run(args: list[str]) -> str:
        exe = shutil.which(args[0], path=search)
        if exe is None:
            raise SystemExit(f"{args[0]} not found after loading the compiler environment")
        r = subprocess.run([exe, *args[1:]], cwd=bdir, env=env, capture_output=True, text=True)
        log.append("$ " + " ".join(args) + f"\n{r.stdout}{r.stderr}[exit {r.returncode}]")
        if r.returncode != 0:
            (bdir / "build_transcript.txt").write_text("\n".join(log) + "\n", encoding="utf-8", newline="\n")
            raise SystemExit(f"failed: {' '.join(args)}\n{r.stdout}{r.stderr}")
        return r.stdout

    inc = ["/include:" + str((ROOT / "scripts" / "include").resolve()), "/include:" + str(bdir.resolve())]
    run(["ifx", "/QV"])
    objs: list[str] = []
    if kind == "oti":
        tdir = (ROOT / TRANSFORM[model]).resolve()
        for u in SUPPORT:
            run(["ifx", *FLAGS, *inc, str(tdir / f"{u}.f90")])
            objs.append(f"{u}.obj")
    run(["ifx", *FLAGS, *inc, "user.for"])
    objs.append("user.obj")

    defined: set[str] = set()
    for o in objs:
        for line in run(["dumpbin", "/nologo", "/symbols", o]).splitlines():
            if "External" in line and "SECT" in line and "UNDEF" not in line and "|" in line:
                name = line.split("|", 1)[1].split()
                if name:
                    defined.add(name[0])
    exports = []
    in_table = False
    for line in run(["dumpbin", "/nologo", "/exports", str(STUB)]).splitlines():
        if "ordinal hint" in line:
            in_table = True
            continue
        parts = line.split()
        if in_table and len(parts) == 4 and parts[0].isdigit():
            exports.append(parts[3])
    exports = [n for n in exports if n not in ("DllMain", "_forceCRTManifestCUR")
               and not n.startswith("DASSAULT_SYSTEMES_")]
    mine = [n for n in exports if n in defined]
    thunked = [n for n in exports if n not in defined]
    if mine != ["umat"]:
        raise SystemExit(f"expected only umat to be user-defined, got {mine}")
    log.append(f"# user entry points: {mine}; thunked to Abaqus stub copy: {len(thunked)}")

    shutil.copy2(STUB, bdir / "abss_abqstub.dll")
    asm = ["; lazy thunks into abss_abqstub.dll (unmodified copy of Abaqus' own standardU.dll)",
           "EXTERN abss_resolve:PROC", "EXTERN abss_fp:QWORD", ".code"]
    for i, _ in enumerate(thunked):
        asm += [f"abss_t{i} PROC", f"  mov rax, qword ptr [abss_fp + {8 * i}]", "  test rax, rax",
                f"  jz abss_s{i}", "  jmp rax", f"abss_s{i}:", f"  mov r10d, {i}", "  jmp abss_slow", f"abss_t{i} ENDP"]
    asm += ["abss_slow PROC", "  push rcx", "  push rdx", "  push r8", "  push r9", "  sub rsp, 104",
            "  movdqu xmmword ptr [rsp+32], xmm0", "  movdqu xmmword ptr [rsp+48], xmm1",
            "  movdqu xmmword ptr [rsp+64], xmm2", "  movdqu xmmword ptr [rsp+80], xmm3",
            "  mov ecx, r10d", "  call abss_resolve",
            "  movdqu xmm0, xmmword ptr [rsp+32]", "  movdqu xmm1, xmmword ptr [rsp+48]",
            "  movdqu xmm2, xmmword ptr [rsp+64]", "  movdqu xmm3, xmmword ptr [rsp+80]",
            "  add rsp, 104", "  pop r9", "  pop r8", "  pop rdx", "  pop rcx", "  jmp rax", "abss_slow ENDP", "END"]
    names = "".join(f'"{n}",' for n in thunked)
    c = ("#include <windows.h>\nextern IMAGE_DOS_HEADER __ImageBase;\n"
         f"void* abss_fp[{max(len(thunked), 1)}];\n"
         f"static const char* const abss_names[] = {{{names}0}};\n"
         "static HMODULE abss_stub;\n"
         "void* abss_resolve(int i) {\n"
         "  if (!abss_stub) {\n"
         "    wchar_t p[4096]; DWORD n = GetModuleFileNameW((HMODULE)&__ImageBase, p, 4000);\n"
         "    while (n && p[n - 1] != L'\\\\') --n; p[n] = 0; lstrcatW(p, L\"abss_abqstub.dll\");\n"
         "    abss_stub = LoadLibraryExW(p, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);\n"
         "    if (!abss_stub) FatalAppExitA(0, \"abaqus_parity: abss_abqstub.dll could not be loaded\");\n"
         "  }\n"
         "  void* f = (void*)GetProcAddress(abss_stub, abss_names[i]);\n"
         "  if (!f) FatalAppExitA(0, \"abaqus_parity: entry point missing in abss_abqstub.dll\");\n"
         "  abss_fp[i] = f;\n  return f;\n}\n")
    deff = ["LIBRARY standardU", "EXPORTS"] + [f"  {n}" for n in mine] + [f"  {n}=abss_t{i}" for i, n in enumerate(thunked)]
    (bdir / "abss_thunks.asm").write_text("\n".join(asm) + "\n", encoding="utf-8", newline="\n")
    (bdir / "abss_resolver.c").write_text(c, encoding="utf-8", newline="\n")
    (bdir / "standardU.def").write_text("\n".join(deff) + "\n", encoding="utf-8", newline="\n")
    run(["ml64", "/nologo", "/c", "abss_thunks.asm"])
    run(["cl", "/nologo", "/c", "/O2", "/GS-", "abss_resolver.c"])
    run(["link", "/nologo", "/dll", "/noentry", "/machine:x64", "/incremental:no", "/nodefaultlib",
         "/out:standardU.dll", "/def:standardU.def", *objs, "abss_thunks.obj", "abss_resolver.obj",
         "kernel32.lib", "user32.lib", "advapi32.lib", "msvcrt.lib", "vcruntime.lib", "ucrt.lib", "oldnames.lib",
         "libifcoremd.lib", "libifportmd.lib", "libmmd.lib", "libircmt.lib", "svml_dispmd.lib"])
    (bdir / "build_transcript.txt").write_text("\n".join(log) + "\n", encoding="utf-8", newline="\n")
    print(build, "ok:", mine, len(thunked), "thunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
