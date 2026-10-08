"""Published text ALONE, solver's form (by suffix), Abaqus's compile line, for every registry row with a cached UMAT file."""
import csv, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import d28_lines as d
out_path = Path(sys.argv[1]); scratch = Path(sys.argv[2])
rows = list(csv.DictReader(open(d.REGISTRY)))
todo = [r for r in rows if r["is_umat"] != "False" or r["terminal_state"] in
        ("original_job_failed", "support_build_failed", "incomplete_or_corrupt_source")]
def one(r):
    try:
        res = d.compile_alone_solver_form(r["source_id"], scratch / r["key"][:12])
    except Exception as e:                       # noqa: BLE001
        res = {"status": "error", "reason": f"{type(e).__name__}: {e}"}
    res.update(key=r["key"], source_id=r["source_id"], terminal_state=r["terminal_state"])
    return res
with ThreadPoolExecutor(3) as ex:
    results = list(ex.map(one, todo))
out_path.write_text(json.dumps(results, indent=1, default=str))
print(len(results))
