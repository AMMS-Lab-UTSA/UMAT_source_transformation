#!/usr/bin/env bash
# Run the paired jobs one at a time (Ada, 2026-10-27). Before each job, check that at least 5 abaqus
# licence tokens are free; wait up to 1 h in 2-minute polls, then stop. After each job, convert .fil to ASCII (.fin).
# Usage: bash evidence/2ae2ee0/abaqus_parity/scripts/run_all.sh [job ...]   (default: all 16 jobs)
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ABQ=C:/SIMULIA/Commands/abaqus.bat
LOG="$HERE/run_all_transcript.txt"
jobs=("$@")
if [ ${#jobs[@]} -eq 0 ]; then
  for m in modelA r1; do for c in ext shear mixed uniax; do for b in orig oti; do jobs+=("${m}_${c}_${b}"); done; done; done
fi
free_tokens() {
  timeout 120 "$ABQ" licensing lmstat -a 2>&1 | tr -d '\r' |
    sed -n 's/^Users of abaqus:  (Total of \([0-9]*\) licenses issued;  Total of \([0-9]*\) licenses in use)/\1 \2/p' |
    awk '{print $1-$2}'
}
for j in "${jobs[@]}"; do
  waited=0
  while :; do
    f=$(free_tokens); f=${f:-0}
    echo "$(date -u +%FT%TZ) $j licence free=$f" | tee -a "$LOG"
    [ "$f" -ge 5 ] && break
    [ $waited -ge 3600 ] && { echo "licence unavailable >1 h; stopping" | tee -a "$LOG"; exit 3; }
    sleep 120; waited=$((waited + 120))
  done
  d="$HERE/jobs/$j"
  ( cd "$d" && rm -f "$j".{com,dat,fil,fin,msg,odb,prt,sta,sim,log} "${j}_calls.txt" console.txt )
  t0=$(date +%s)
  cmd //c "$(cygpath -w "$d/run.bat")"; rc=$?
  ( cd "$d" && timeout 300 "$ABQ" ascfil job="$j" > ascfil_console.txt 2>&1 )
  echo "$(date -u +%FT%TZ) $j exit=$rc seconds=$(( $(date +%s) - t0 )) $(tail -1 "$d/$j.sta" 2>/dev/null | tr -s ' ')" | tee -a "$LOG"
done
