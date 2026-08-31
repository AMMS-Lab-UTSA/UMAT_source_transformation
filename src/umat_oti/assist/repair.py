"""A proposed edit to generated Fortran, verified in a sandbox and never trusted.

This is the most dangerous proposer in the package and is fenced accordingly.
Every other one selects among artefacts that already exist; this one would let a
model write a line of Fortran. Two decisions keep that safe.

**The transformer's own output is never modified.** The out directory is copied
to a sandbox and the edit is made there. A confirmed repair is therefore a
*finding* -- "this file compiles if that line is changed" -- and not a silent
patch of the thing the pipeline produced. ``apply_in_place`` exists for a caller
that genuinely wants the patched file, and is off everywhere in this repository.

**A repaired file is not a transformed file.** A count of sources the
transformer handled must not include ones a model patched afterwards; that would
credit the transformer with work it did not do. The triage round's
``transformed`` column is untouched by this module. What a confirmed repair
gives is the opposite of a better score: a minimal, compiler-checked statement
of a defect in the emitter, at a line number, which is a bug report.

The gates, in order, none skippable:

1. **Containment.** The path is resolved and must lie inside the sandbox and
   outside every forbidden root, so an edit cannot reach ``src/`` or the
   author's cached source. A proposal naming any other path is refused before
   it is parsed.
2. **The quoted text.** Every edit must quote the line it claims to change,
   exactly as that line appears in the file. A model that invents a line it did
   not read cannot produce a quote that matches, so a hallucinated edit is inert
   before anything is written.
3. **The compiler, then semantic invariance.** The edited copy must compile --
   gfortran's opinion, not the model's -- and the transform's text-derived
   semantic checks must not regress, and the ordered sequence of semantically
   significant lines must be unchanged, and no edited or inserted line may
   itself be one of those lines.

On the coverage of gate 3, plainly: the checks in ``_semantic_checks`` that are
pure functions of the emitted text are re-run here against the edited text. The
ordering checks are carried across the edit by requiring their subject lines to
be untouched and in the same relative order, which is strictly stronger than
re-running them -- it rejects edits that would have passed. The checks that
depend on transform state this module does not have (the role-derived stress
expression set) are *not* recomputed; instead no edit that touches a classified
line is ever accepted. That is a conservative boundary, not a complete one, and
it is the reason a confirmed repair is reported rather than shipped.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from umat_oti.assist.local_model import LocalModel
from umat_oti.assist.proposals import Proposal
from umat_oti.transform.source_transform import (
    _active_lines_with_numbers,
    _fixed_form_line_lengths_ok,
    _integer_literals_normalized_in_oti_expressions,
    _is_dstran_initialization_line,
    _is_dstran_seed_line,
    _is_finite_dfgrd1_seed_line,
    _is_real_stress_extraction_line,
    _is_stress_oti_update_line,
)

__all__ = ["Edit", "RepairPolicy", "PathNotAllowed", "propose_repair",
           "semantic_kinds", "classified_kinds_of_line", "compile_with_hint"]

REPLACE = "replace"
INSERT_AFTER = "insert_after"


class PathNotAllowed(RuntimeError):
    """A proposed edit named a file outside the sandbox."""


@dataclass(frozen=True)
class Edit:
    """One single-line change, expressed so it can be checked before it is made."""

    op: str
    line: int
    old: str
    new: str

    def describe(self) -> str:
        verb = "replace" if self.op == REPLACE else "insert after"
        return f"{verb} line {self.line}: {self.new.strip()[:70]!r}"


@dataclass(frozen=True)
class RepairPolicy:
    """Where an edit may land and how large it may be."""

    allowed_root: Path
    forbidden_roots: tuple[Path, ...] = ()
    max_edits: int = 4

    def check(self, target: Path) -> None:
        """Refuse anything outside the sandbox. Resolved, not textual.

        ``resolve()`` before comparing, so ``out/../../src/x.py`` and a symlink
        into the tree are the same refusal as naming the file outright.
        """
        resolved = Path(target).resolve()
        root = Path(self.allowed_root).resolve()
        if not resolved.is_relative_to(root):
            raise PathNotAllowed(
                f"{resolved} is not inside the permitted directory {root}")
        for forbidden in self.forbidden_roots:
            if resolved.is_relative_to(Path(forbidden).resolve()):
                raise PathNotAllowed(
                    f"{resolved} is inside the forbidden root {forbidden}")


_PROMPT = """\
This generated Fortran does not compile. Propose the smallest edit that fixes
the compiler error without changing what the routine computes.

The compiler said:
{error}

The file, with line numbers:
{window}

Answer with at most {max_edits} lines, each in one of these two forms:

REPLACE|||LINE|||OLD|||NEW
INSERT_AFTER|||LINE|||OLD|||NEW

LINE is the line number. OLD is that line copied exactly as it appears above,
without its number. NEW is the replacement line, or the line to insert. This is
fixed-form Fortran: a statement must begin at column 7, so keep six leading
spaces. Do not delete a statement and do not comment one out. If you cannot fix
it this way, answer NONE.
"""


def classified_kinds_of_line(line: str, *, dstran: str = "DSTRAN",
                             stress: str = "STRESS") -> tuple[str, ...]:
    """Which semantic checks, if any, care about this line."""
    kinds: list[str] = []
    if _is_dstran_initialization_line(line, dstran):
        kinds.append("dstran_init")
    if _is_dstran_seed_line(line, dstran):
        kinds.append("dstran_seed")
    if _is_finite_dfgrd1_seed_line(line):
        kinds.append("dfgrd1_seed")
    if _is_stress_oti_update_line(line, stress):
        kinds.append("stress_update")
    if _is_real_stress_extraction_line(line, stress):
        kinds.append("stress_extraction")
    return tuple(kinds)


def semantic_kinds(text: str, *, dstran: str = "DSTRAN",
                   stress: str = "STRESS") -> tuple[str, ...]:
    """The classified lines in order, without their positions.

    Relative order is what the ordering checks compare, and it is what has to
    survive an edit. Positions are deliberately excluded so that inserting a
    declaration -- which shifts every line below it without reordering anything
    -- is not mistaken for a semantic change.
    """
    kinds: list[str] = []
    for _number, line in _active_lines_with_numbers(text):
        kinds.extend(classified_kinds_of_line(line, dstran=dstran, stress=stress))
    return tuple(kinds)


def _text_checks(text: str, *, form: str) -> dict[str, bool]:
    """The semantic checks that are functions of the emitted text alone."""
    upper = text.upper()
    return {
        "dstran_oti_present": "DSTRAN_OTI" in upper,
        "stress_oti_present": "STRESS_OTI" in upper,
        "subroutine_umat_present": "SUBROUTINE UMAT" in upper,
        "use_oti_module_present": "USE OTIM" in upper,
        "fixed_form_line_lengths_ok": _fixed_form_line_lengths_ok(text, form),
        "integer_literals_normalized_in_oti_expressions":
            _integer_literals_normalized_in_oti_expressions(text),
    }


def _regressions(before: dict[str, bool], after: dict[str, bool]) -> list[str]:
    """Checks that passed before the edit and do not pass after it."""
    return sorted(name for name, passed in before.items()
                  if passed and not after.get(name, False))


def compile_with_hint(out_dir: Path) -> tuple[bool, str]:
    """Run the compile the transform itself would run. Same script, same flags."""
    script = Path(out_dir) / "compile_hint.sh"
    if not script.is_file():
        return False, f"no compile_hint.sh in {out_dir}"
    finished = subprocess.run([str(script)], cwd=str(out_dir), check=False,
                              capture_output=True, text=True)
    return finished.returncode == 0, (finished.stderr or finished.stdout)[:4000]


def _parse_edits(answer: str, *, max_edits: int) -> list[Edit]:
    edits: list[Edit] = []
    for raw in (answer or "").splitlines():
        parts = raw.split("|||")
        if len(parts) == 4:
            op_text, number, old, new = parts
        elif len(parts) == 3:
            op_text, (number, old, new) = "REPLACE", parts
        else:
            continue
        op_text = op_text.strip().upper()
        if "INSERT" in op_text:
            op = INSERT_AFTER
        elif "REPLACE" in op_text:
            op = REPLACE
        else:
            continue
        match = re.search(r"(\d+)", number)
        if not match:
            continue
        edits.append(Edit(op=op, line=int(match.group(1)), old=old, new=new))
        if len(edits) >= max_edits:
            break
    return edits


def _is_comment_line(line: str, *, form: str) -> bool:
    if form == "fixed":
        return line[:1] in ("C", "c", "*", "!")
    return line.lstrip().startswith("!")


def _validate_against_text(edits: Sequence[Edit], lines: list[str], *,
                           form: str) -> tuple[bool, str]:
    """Every edit must match the file it claims to edit, before anything moves.

    This is the gate that makes a hallucinated edit inert: a model that invents
    a line it did not read cannot produce an ``old`` that equals the real one.
    It is also where an edit that would disturb a line the semantic checks
    depend on is refused outright.
    """
    if not edits:
        return False, "the model proposed no edit in the required form"
    seen: set[int] = set()
    for edit in edits:
        if not (1 <= edit.line <= len(lines)):
            return False, f"line {edit.line} is outside the file (1..{len(lines)})"
        if edit.line in seen:
            return False, f"line {edit.line} is edited more than once"
        seen.add(edit.line)
        actual = lines[edit.line - 1]
        if actual.rstrip() != edit.old.rstrip():
            return False, (f"line {edit.line} is not what the model quoted: "
                           f"file has {actual.strip()[:60]!r}, "
                           f"model quoted {edit.old.strip()[:60]!r}")
        if "\n" in edit.new or "\r" in edit.new:
            return False, f"line {edit.line}: a replacement must be a single line"
        if not edit.new.strip():
            return False, f"line {edit.line}: an edit must not delete the statement"
        if (_is_comment_line(edit.new, form=form)
                and not _is_comment_line(actual, form=form)):
            return False, f"line {edit.line}: an edit must not comment out a statement"
        # A line any semantic check is about is not available for editing. The
        # ordering checks are carried across the edit by leaving their subjects
        # exactly where they were.
        touched = classified_kinds_of_line(actual)
        if edit.op == REPLACE and touched:
            return False, (f"line {edit.line} is a {'/'.join(touched)} line, "
                           f"which a semantic check depends on")
        introduced = classified_kinds_of_line(edit.new)
        if introduced:
            return False, (f"line {edit.line}: the replacement would introduce a "
                           f"{'/'.join(introduced)} line")
    return True, f"{len(edits)} edit(s) match the file exactly"


def _apply(lines: list[str], edits: Sequence[Edit]) -> list[str]:
    """Apply edits bottom-up, so an insertion cannot move a later line number."""
    out = list(lines)
    for edit in sorted(edits, key=lambda e: e.line, reverse=True):
        if edit.op == REPLACE:
            out[edit.line - 1] = edit.new
        else:
            out.insert(edit.line, edit.new)
    return out


def propose_repair(
    generated_name: str,
    out_dir: Path,
    compiler_error: str,
    *,
    model: Optional[LocalModel] = None,
    forbidden_roots: Sequence[Path] = (),
    compile_check: Optional[Callable[[Path], tuple[bool, str]]] = None,
    window_lines: int = 300,
    max_edits: int = 4,
    apply_in_place: bool = False,
) -> Proposal:
    """Look for a minimal edit that makes one generated file compile.

    The out directory is copied to a sandbox and everything happens there, so
    this returns a finding and changes nothing the pipeline produced unless
    ``apply_in_place`` is set. With no model reachable it returns an UNVERIFIED
    proposal having read nothing and written nothing.
    """
    out_dir = Path(out_dir)
    proposal = Proposal(
        subject=f"compile repair for {generated_name}",
        proposed=None,
        model=model.name if model else "none (no model reachable)",
    )
    proposal.metadata["compiler_error"] = str(compiler_error)[:300]
    if model is None:
        proposal.evidence = "no model was reachable; nothing was read or written"
        return proposal

    compile_check = compile_check or compile_with_hint
    sandbox_parent = Path(tempfile.mkdtemp(prefix="umat_oti_repair_"))
    try:
        sandbox = sandbox_parent / "out"
        shutil.copytree(out_dir, sandbox, symlinks=False)
        target = sandbox / generated_name
        policy = RepairPolicy(allowed_root=sandbox,
                              forbidden_roots=tuple(forbidden_roots),
                              max_edits=max_edits)
        # Gate 1, before anything is read.
        try:
            policy.check(target)
        except PathNotAllowed as exc:
            return proposal.contradict(
                checked_by="umat_oti.assist.repair (containment)",
                evidence=str(exc))
        if not target.is_file():
            return proposal.contradict(
                checked_by="umat_oti.assist.repair (containment)",
                evidence=f"{generated_name} is not in the output directory")

        form = "free" if target.suffix.lower() in {".f90", ".f95"} else "fixed"
        text = target.read_text(errors="replace")
        lines = text.splitlines()
        before_checks = _text_checks(text, form=form)
        before_kinds = semantic_kinds(text)

        window = "\n".join(f"{n}:{line}" for n, line in
                           enumerate(lines[:window_lines], start=1))
        prompt = _PROMPT.format(error=str(compiler_error)[:1500], window=window,
                                max_edits=max_edits)
        try:
            answer, digest = model.ask(prompt, max_tokens=400)
        except Exception:
            proposal.evidence = "the model did not answer; nothing was written"
            return proposal
        proposal.prompt_sha256 = digest
        proposal.metadata["model_answer"] = (answer or "").strip()[:400]

        edits = _parse_edits(answer, max_edits=max_edits)
        # Gate 2.
        ok, detail = _validate_against_text(edits, lines, form=form)
        if not ok:
            return proposal.contradict(
                checked_by="umat_oti.assist.repair (quoted text)", evidence=detail)
        proposal.proposed = [edit.describe() for edit in edits]

        edited_text = "\n".join(_apply(lines, edits)) + "\n"
        target.write_text(edited_text, encoding="utf-8")

        # Gate 3.
        compiled, compiler_said = compile_check(sandbox)
        after_checks = _text_checks(edited_text, form=form)
        regressions = _regressions(before_checks, after_checks)
        kinds_held = semantic_kinds(edited_text) == before_kinds

        proposal.metadata["compiled_after_edit"] = bool(compiled)
        proposal.metadata["semantic_regressions"] = regressions
        proposal.metadata["semantic_kinds_unchanged"] = bool(kinds_held)

        if not (compiled and not regressions and kinds_held):
            reasons = []
            if not compiled:
                reasons.append(
                    f"it still does not compile: {compiler_said.strip()[:200]}")
            if regressions:
                reasons.append(
                    f"semantic checks regressed: {', '.join(regressions)}")
            if not kinds_held:
                reasons.append("the sequence of semantically significant lines "
                               "changed, so an ordering check the transform "
                               "makes is no longer the one it made")
            return proposal.contradict(
                checked_by="gfortran + umat_oti.assist.repair",
                evidence="; ".join(reasons))

        if apply_in_place:
            destination = out_dir / generated_name
            RepairPolicy(allowed_root=out_dir,
                         forbidden_roots=tuple(forbidden_roots)).check(destination)
            destination.write_text(edited_text, encoding="utf-8")
            proposal.metadata["applied_in_place"] = True
        return proposal.confirm(
            checked_by="gfortran + umat_oti.assist.repair",
            evidence=(f"{len(edits)} edit(s) confined to {generated_name}; the "
                      f"file compiles; no semantic check regressed and the "
                      f"sequence of semantically significant lines is unchanged"))
    finally:
        shutil.rmtree(sandbox_parent, ignore_errors=True)
