"""Peak compiler memory for the generated OTI runtime module."""
import json, resource, shutil, subprocess, sys, tempfile, time
from pathlib import Path
REPO=Path("/home/claude/repo"); sys.path.insert(0,str(REPO/"src"))
from umat_oti.oti.module_generator import generate_otilib_module
FC=shutil.which("gfortran")
SUP=[REPO/"src/umat_oti/oti/support/master_parameters.f90",
     REPO/"src/umat_oti/oti/support/real_utils.f90"]
out=[]
for n,k in [(6,1),(6,2),(6,3),(35,1)]:
    td=Path(tempfile.mkdtemp())
    try:
        generate_otilib_module(output_dir=td,ntens=n,order=k)
        p=td/f"otim{n}n{k}.f90"; obj=td/"obj"; obj.mkdir()
        for i,s in enumerate(SUP):
            subprocess.run([FC,"-c","-O1","-std=legacy","-ffree-line-length-none",str(s),
                            "-I",str(obj),"-J",str(obj),"-o",str(obj/f"s{i}.o")],check=True,capture_output=True)
        before=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        t0=time.perf_counter()
        subprocess.run([FC,"-c","-O1","-std=legacy","-ffree-line-length-none",str(p),
                        "-I",str(obj),"-J",str(obj),"-o",str(obj/"oti.o")],check=True,capture_output=True,timeout=900)
        dt=time.perf_counter()-t0
        after=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        out.append({"directions":n,"order":k,"compile_s":round(dt,2),
                    "peak_child_rss_MiB":round(max(after,before)/1024,1)})
        print(out[-1])
    finally:
        shutil.rmtree(td,ignore_errors=True)
Path("bench/bench4.json").write_text(json.dumps(out,indent=1))
