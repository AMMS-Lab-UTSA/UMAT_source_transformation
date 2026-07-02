"""Optional LLM advisor (Ollama) for the *fuzzy* decisions in the OTI transform.

Design rule, non-negotiable: **the LLM proposes, the deterministic verification
disposes.** It never performs the exact transform (parse / retype / library) -
that stays deterministic so the result keeps its machine-precision guarantee. The
advisor is consulted only at the judgment boundary the heuristics can't settle
(ambiguous activeness, seed mode, idiosyncratic compile repairs), and *every*
thing it touches is re-checked by `compile + OTI-vs-FD`. A rejected proposal
falls back to the deterministic default.

No third-party deps: talks to Ollama's HTTP API via urllib. If no backend is
reachable, every method returns None and callers use their deterministic path,
so the pipeline behaves exactly as before when Ollama is absent.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from .umat_domain import UMAT_DOMAIN


class LLMAdvisor:
    def __init__(self, model: str | None = None, host: str | None = None,
                 timeout: int = 180, enabled: bool = True):
        # Offline-friendly defaults: a local code model on a local Ollama server.
        # Override via OTI_LLM_MODEL / OLLAMA_HOST (no cloud, no API key).
        self.model = model or os.environ.get("OTI_LLM_MODEL", "qwen2.5-coder:7b")
        host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith("http"):
            host = "http://" + host
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.enabled = enabled
        self._ok: bool | None = None

    def available(self) -> bool:
        """True iff an Ollama server is reachable (cached)."""
        if not self.enabled:
            return False
        if self._ok is None:
            try:
                with urllib.request.urlopen(self.host + "/api/tags", timeout=5) as r:
                    self._ok = (r.status == 200)
            except Exception:
                self._ok = False
        return self._ok

    def _generate(self, prompt: str, system: str = "") -> str | None:
        if not self.available():
            return None
        body = json.dumps({"model": self.model, "prompt": prompt, "system": system,
                           "stream": False, "options": {"temperature": 0.0}}).encode()
        try:
            req = urllib.request.Request(self.host + "/api/generate", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read()).get("response", "").strip()
        except Exception:
            return None

    # ---- decision boundary: pick among allowed options (constrained = gated) ----
    def decide(self, question: str, options: list, context: str = ""):
        """Return one of `options` (or None). Output is constrained to the option
        set, so a wrong/garbled answer can't inject anything unexpected."""
        ans = self._generate(
            f"{context}\n\nQuestion: {question}\nAllowed answers: {list(options)}\n"
            f"Reply with exactly one allowed answer and nothing else.\nAnswer:",
            system=UMAT_DOMAIN + "\n\nAnswer with exactly one of the allowed options, nothing else.")
        if not ans:
            return None
        tok = ans.strip().split()[0].strip(".,'\"").lower() if ans.strip() else ""
        for o in options:
            if str(o).lower() == tok or str(o).lower() in ans.lower():
                return o
        return None

    # ---- repair boundary: propose corrected code; caller MUST recompile+verify ----
    def repair(self, errors: str, code: str, instructions: str = "") -> str | None:
        """Propose corrected Fortran given compiler errors. The result is only a
        proposal - the pipeline recompiles and FD-verifies it before accepting."""
        out = self._generate(
            f"{instructions}\nCompiler errors:\n{errors}\n\nCode:\n```fortran\n{code}\n```\n"
            f"\nReturn the full corrected procedure in one ```fortran block, no prose.",
            system=UMAT_DOMAIN + "\n\nReturn ONLY one ```fortran code block with the corrected procedure.")
        if not out:
            return None
        m = re.search(r"```(?:fortran|f90|f)?\s*(.*?)```", out, re.S | re.I)
        return (m.group(1) if m else out).strip()


_PROC_START = re.compile(r"(?i)^\s*(?:pure\s+|elemental\s+|recursive\s+)*(?:function|subroutine)\s+\w+")
_PROC_END = re.compile(r"(?i)^\s*end\s+(?:function|subroutine)\b")


def _enclosing_proc(lines, line_no):
    """0-indexed (start, end) span of the procedure containing 1-indexed line_no."""
    i = min(line_no - 1, len(lines) - 1)
    start = next((j for j in range(i, -1, -1) if _PROC_START.match(lines[j])), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if _PROC_END.match(lines[j])), None)
    return (start, end) if end is not None else None


def repair_loop(source_path: str, compile_cmd, advisor: LLMAdvisor, max_rounds: int = 4,
                logger=print, cwd: str | None = None) -> bool:
    """Compile; on failure, repair PER PROCEDURE: localize each error to its
    enclosing procedure, send only that procedure (+ its errors) to the advisor,
    splice the fix back, recompile. The compiler is the gate - if a round doesn't
    reduce errors to zero after max_rounds, revert to the deterministic output."""
    import subprocess

    def compile_errors():
        r = subprocess.run(compile_cmd, capture_output=True, text=True, cwd=cwd)
        errs, cur = [], None
        for ln in (r.stderr or "").splitlines():
            m = re.match(r".+\.(?:f90|f|for):(\d+):\d+:", ln)
            if m:
                cur = int(m.group(1))
            if "Error:" in ln:
                errs.append((cur, ln.strip()))
        return errs

    errs = compile_errors()
    if not errs:
        return True
    if not advisor.available():
        logger(f"[llm] {len(errs)} compile errors; no LLM backend - leaving to deterministic path.")
        return False
    original = open(source_path, encoding="utf-8", errors="replace").read()
    baseline_n = len(errs)
    best_text, best_n = original, baseline_n          # never end up worse than deterministic
    for rnd in range(1, max_rounds + 1):
        lines = open(source_path, encoding="utf-8", errors="replace").read().split("\n")
        by_proc: dict = {}
        for line_no, msg in errs:
            if line_no is None:
                continue
            span = _enclosing_proc(lines, line_no)
            if span:
                by_proc.setdefault(span, []).append(msg)
        if not by_proc:
            break
        logger(f"[llm] repair round {rnd}: {len(errs)} errors in {len(by_proc)} procedure(s) -> {advisor.model}")
        # splice from the bottom so earlier spans keep their indices
        for (start, end), msgs in sorted(by_proc.items(), reverse=True):
            proc_text = "\n".join(lines[start:end + 1])
            fixed = advisor.repair("\n".join(msgs[:15]), proc_text,
                                   instructions="Fix ONLY this one procedure for the errors shown. "
                                   "Keep its name, arguments and all real computations identical; "
                                   "only adjust types/intrinsics so OTI (ONUMM6N1) and real interoperate.")
            if fixed:
                lines[start:end + 1] = fixed.split("\n")
        open(source_path, "w").write("\n".join(lines))
        errs = compile_errors()
        if len(errs) < best_n:                       # keep the best partial seen
            best_text, best_n = "\n".join(lines), len(errs)
        if not errs:
            logger(f"[llm] repaired under the compile gate in {rnd} round(s).")
            return True
        logger(f"[llm]   -> {len(errs)} errors remain (best so far: {best_n})")
    open(source_path, "w").write(best_text)          # best partial (>= deterministic baseline)
    logger(f"[llm] not fully repaired; kept best partial = {best_n} errors "
           f"(deterministic baseline was {baseline_n}).")
    return best_n == 0
