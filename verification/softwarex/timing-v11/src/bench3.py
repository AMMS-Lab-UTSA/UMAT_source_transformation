"""OTI runtime module scaling: generation cost, source size, and compile cost."""
import json, shutil, subprocess, sys, tempfile, time
from math import comb
from pathlib import Path
from statistics import median
REPO = Path("/home/claude/repo"); sys.path.insert(0, str(REPO / "src"))
from umat_oti.oti.module_generator import generate_otilib_module
FC = shutil.which("gfortran")
SUPPORT = [REPO / "src/umat_oti/oti/support/master_parameters.f90",
           REPO / "src/umat_oti/oti/support/real_utils.f90"]
rows = []
cases = [(n, 1) for n in (4, 6, 10, 20, 35)] + [(6, k) for k in (2, 3, 4)] + [(12, 2), (36, 1)]
for n, k in cases:
    td = Path(tempfile.mkdtemp())
    try:
        try:
            t0 = time.perf_counter(); generate_otilib_module(output_dir=td, ntens=n, order=k)
            gen = round(time.perf_counter() - t0, 3)
        except Exception as exc:
            rows.append({"directions": n, "order": k, "stored_coefficients": comb(n+k, k),
                         "refused": str(exc)}); print(n, k, "REFUSED", exc); continue
        p = td / f"otim{n}n{k}.f90"
        lines = len(p.read_text().splitlines()); kib = round(p.stat().st_size/1024, 1)
        obj = td / "obj"; obj.mkdir()
        comp = None
        TIMEOUT = 1200
        try:
            t0 = time.perf_counter()
            for i, sup in enumerate(SUPPORT):
                subprocess.run([FC,"-c","-O1","-std=legacy","-ffree-line-length-none",str(sup),
                                "-I",str(obj),"-J",str(obj),"-o",str(obj/f"s{i}.o")],
                               check=True,capture_output=True,timeout=300)
            t0 = time.perf_counter()
            subprocess.run([FC,"-c","-O1","-std=legacy","-ffree-line-length-none",str(p),
                            "-I",str(obj),"-J",str(obj),"-o",str(obj/"oti.o")],
                           check=True,capture_output=True,timeout=TIMEOUT)
            comp = {"compile_s": round(time.perf_counter()-t0, 2),
                    "object_KiB": round((obj/"oti.o").stat().st_size/1024, 1)}
        except subprocess.TimeoutExpired:
            comp = {"not_completed": f"gfortran 13.3.0 did not finish within {TIMEOUT} s "
                                     f"on this machine (2 vCPU, 7.8 GiB)"}
        except subprocess.CalledProcessError as e:
            comp = {"error": e.stderr.decode()[-200:]}
        rows.append({"directions": n, "order": k, "stored_coefficients": comb(n+k, k),
                     "module_lines": lines, "module_KiB": kib,
                     "generate_s": gen, "compile": comp})
        print(f"N={n:3d} K={k} coeff={comb(n+k,k):5d} lines={lines:6d} gen={gen:6.3f}s comp={comp}")
    finally:
        shutil.rmtree(td, ignore_errors=True)
Path("bench").mkdir(exist_ok=True)
Path("bench/bench3.json").write_text(json.dumps(rows, indent=1))
print("wrote bench/bench3.json")
