#!/usr/bin/env bash
# Obtain the pinned external corpus sources into a directory of your choosing.
#
# The corpus round reads sources that live outside this repository. Rather than
# assuming a sibling checkout, this clones each pinned repository at its exact
# commit into a snapshot root you pass to --snapshot-root.
#
# Usage:
#   scripts/bootstrap_corpus.sh [DESTINATION]
#
# Then:
#   python tools/run_corpus_round.py --snapshot-root DESTINATION

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/parameter_sensitivity/cross_repository_reproduction.json"
DEST="${1:-$REPO_ROOT/build/corpus_snapshot}"
PYTHON="${PYTHON:-python3}"

[[ -f "$MANIFEST" ]] || { echo "missing $MANIFEST" >&2; exit 1; }

mkdir -p "$DEST"
echo "==> bootstrapping the pinned corpus into $DEST"

"$PYTHON" - "$MANIFEST" <<'PYEOF' | while IFS=$'\t' read -r id url sha; do
import json, sys
manifest = json.load(open(sys.argv[1]))
for entry in manifest["corpus_repositories"]:
    print(f"{entry['id']}\t{entry['url']}\t{entry['commit_sha']}")
PYEOF
  target="$DEST/$id"
  if [[ -d "$target/.git" ]]; then
    current="$(git -C "$target" rev-parse HEAD)"
    if [[ "$current" == "$sha" ]]; then
      echo "    ok (already at pinned commit)  $id"
      continue
    fi
  fi
  echo "    fetching $id at ${sha:0:12}"
  rm -rf "$target"
  git clone --quiet "$url" "$target"
  # Detach at the exact commit. A branch name here would reintroduce exactly
  # the moving reference the pinned manifest exists to eliminate.
  git -C "$target" checkout --quiet --detach "$sha"
  actual="$(git -C "$target" rev-parse HEAD)"
  if [[ "$actual" != "$sha" ]]; then
    echo "    FAILED: $id landed on $actual, expected $sha" >&2
    exit 1
  fi
done

echo
echo "==> corpus bootstrapped. Run the round with:"
echo "    python tools/run_corpus_round.py --snapshot-root $DEST"
