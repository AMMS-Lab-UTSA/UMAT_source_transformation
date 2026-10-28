"""Transform fingerprint as Linux computes it, from raw git blobs (Ada; check of Vera B1).

Reimplements umat_oti.store.transform_store._package_digest with POSIX relative paths and
LF blob contents, reading FINGERPRINTED and NOT_TRANSFORM_CODE from the commit itself.
Usage: python fingerprint_posix.py <clone> <commit>
"""
import ast, hashlib, re, subprocess, sys

clone, commit = sys.argv[1], sys.argv[2]
def show(path):
    return subprocess.run(["git", "-C", clone, "show", f"{commit}:{path}"], capture_output=True).stdout
src = show("src/umat_oti/store/transform_store.py").decode()
def const(name):
    m = re.search(rf"^{name}\s*=\s*(\([^)]*\))", src, re.M | re.S)
    return ast.literal_eval(m.group(1))
pats = [p.lstrip("*") for p in const("FINGERPRINTED")]
skip = set(const("NOT_TRANSFORM_CODE"))
files = subprocess.run(["git", "-C", clone, "ls-tree", "-r", "--name-only", commit, "src/umat_oti"],
                       capture_output=True, text=True).stdout.split()
seen = {}
for f in files:
    rel = f[len("src/umat_oti/"):]
    parts = rel.split("/")
    if "__pycache__" in parts or not any(rel.endswith(p) for p in pats) or parts[0] in skip:
        continue
    seen[rel] = f
h = hashlib.sha256()
for rel in sorted(seen):
    h.update(rel.encode()); h.update(b"\0"); h.update(show(seen[rel])); h.update(b"\0")
rec = re.search(r'"transform_fingerprint":\s*"([0-9a-f]+)"', show("src/umat_oti/contract/schemas/transform_generation.json").decode())
print(commit, "computed", h.hexdigest()[:16], "recorded", rec.group(1) if rec else None, "files", len(seen))
