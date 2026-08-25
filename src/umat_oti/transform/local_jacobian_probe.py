"""Generic source injection that turns a local Newton solve into a residual probe.

A UMAT that integrates its constitutive law with a local Newton iteration

.. code-block:: fortran

   DO
     FGAM = ...            ! residual  F(g)
     FJAC = ...            ! hand-coded Jacobian  dF/dg
     GAM_PAR = GAM_PAR - FGAM/FJAC
     ...                   ! recompute auxiliaries from the new GAM_PAR
   END DO

already contains everything needed to evaluate ``F`` at an arbitrary iterate:
the loop body *is* the residual evaluator.  Overriding the Newton update with a
prescribed value therefore converts the loop into a callable ``F(g)``, and the
next trip round the loop reports ``F`` and the hand-coded ``FJAC`` at that
value.

This module performs that conversion generically from a
:class:`~umat_oti.transform.internal_jacobian.LocalSolve` record.  Two channels
carry data in and out without adding any new driver, IO or compilation
machinery:

``PROPS(seed)``
    A spare property slot supplies the prescribed iterate.  The existing
    parameter-sensitivity driver already seeds ``PROPS(k) = value + e_k``, so
    the OTI build differentiates with respect to the iterate for free and
    ``GETIM(STATEV(residual), 1)`` is exactly ``dF/dg``.

``STATEV(...)``
    Spare state slots carry the iterate, residual and hand-coded Jacobian out
    of the routine.  The driver already dumps both the real part and every
    imaginary coefficient of ``STATEV``.

The same injected source is compiled twice -- once untransformed for the
finite-difference reference, once OTI-lifted for the extracted coefficient --
so both sides observe an identical local state by construction.

Seeding is confined to a single increment selected by ``KINC``.  On every other
increment the original Newton update runs unmodified, so the state entering the
probed local solve is the unperturbed one and the extracted coefficient is the
*local* Jacobian rather than a history-contaminated total derivative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from umat_oti.transform.internal_jacobian import LocalSolve

__all__ = [
    "ProbeSlots",
    "ProbeInjection",
    "ProbeInjectionError",
    "plan_probe_slots",
    "inject_local_solve_probe",
]


class ProbeInjectionError(RuntimeError):
    """The discovered local solve cannot be probed by source injection."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


#: Written into the sentinel slot at every residual evaluation. Any exactly
#: representable, implausible value works; it is compared for bit equality.
PROBE_SENTINEL = 123456789.0


@dataclass(frozen=True)
class ProbeSlots:
    """Where the probe reads its iterate from and writes its outputs to."""

    iterate: int
    residual: int
    jacobian: int
    counter: int
    sentinel: int
    nstatv: int
    seed_props: int
    nprops: int
    offset: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "statev_iterate": self.iterate,
            "statev_residual": self.residual,
            "statev_jacobian": self.jacobian,
            "statev_counter": self.counter,
            "statev_sentinel": self.sentinel,
            "nstatv_extended": self.nstatv,
            "props_seed": self.seed_props,
            "nprops_extended": self.nprops,
            "offset_past_declared_nstatv": self.offset,
        }


@dataclass(frozen=True)
class ProbeInjection:
    """An injected source plus the provenance needed to reproduce it."""

    source: str
    slots: ProbeSlots
    solve: LocalSolve
    target_increment: int
    override_iterate: bool
    forced_exit: bool
    enclosing_routine: str
    edits: tuple[tuple[int, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "enclosing_routine": self.enclosing_routine,
            "target_increment": self.target_increment,
            "override_iterate": self.override_iterate,
            "forced_exit": self.forced_exit,
            "slots": self.slots.as_dict(),
            "solve": self.solve.as_dict(),
            "edits": [{"line": ln, "kind": kind} for ln, kind in self.edits],
        }


def plan_probe_slots(*, nstatv: int, nprops: int, offset: int = 0) -> ProbeSlots:
    """Append probe slots past the contract's declared state and property sizes.

    ``offset`` pushes the block further out.  A contract's declared ``NSTATV``
    is not always an upper bound on the indices a source addresses -- a UMAT
    whose back-stress block runs to ``2*NTENS+NTENS+1`` writes past a declared
    size that only counted the slots Abaqus is told about -- and such a source
    silently overwrites probe slots placed immediately after it.  The sentinel
    slot detects that at run time so the caller can retry further out.
    """
    if nstatv < 0 or nprops < 0:
        raise ValueError("nstatv and nprops must be non-negative")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    base = nstatv + offset
    return ProbeSlots(
        iterate=base + 1,
        residual=base + 2,
        jacobian=base + 3,
        counter=base + 4,
        sentinel=base + 5,
        nstatv=base + 5,
        seed_props=nprops + 1,
        nprops=nprops + 1,
        offset=offset,
    )


_LABELLED = re.compile(r"^\s*\d+\s+\S")
_SUBPROGRAM = re.compile(
    r"^\s*(?:\d+\s+)?(?:(?:RECURSIVE|PURE|ELEMENTAL|IMPURE)\s+)*"
    r"(?:SUBROUTINE|(?:[A-Z0-9_()*\s]*?\s)?FUNCTION)\s+([A-Za-z_]\w*)",
    re.IGNORECASE,
)


def _is_comment(line: str, *, fixed: bool) -> bool:
    if fixed and line[:1] in {"C", "c", "*", "!"}:
        return True
    return line.lstrip().startswith("!")


def _enclosing_routine(lines: list[str], index: int, *, fixed: bool) -> tuple[str, int]:
    """Return the (name, header_line_index) of the subprogram containing ``index``."""
    for back in range(index, -1, -1):
        line = lines[back]
        if _is_comment(line, fixed=fixed):
            continue
        match = _SUBPROGRAM.match(line)
        if match:
            return match.group(1).upper(), back
    return "", -1


def _header_arguments(lines: list[str], header: int, *, fixed: bool) -> set[str]:
    """Collect dummy-argument names from a subprogram header and its continuations."""
    collected = [lines[header]]
    for cursor in range(header + 1, min(header + 40, len(lines))):
        line = lines[cursor]
        if _is_comment(line, fixed=fixed):
            continue
        if fixed:
            # Column 6 holds the continuation marker; columns 1-5 hold a label
            # field.  Both must be dropped or the marker fuses onto the first
            # argument name on the line ("1 DDSDDT").
            if len(line) > 5 and line[5] not in {" ", "0"}:
                collected.append(line[6:])
                continue
            break
        if collected[-1].rstrip().endswith("&"):
            collected.append(line)
            continue
        break
    text = " ".join(collected)
    if "(" not in text:
        return set()
    args = text[text.index("(") + 1:]
    return {token.strip().upper() for token in re.split(r"[(),&]", args) if token.strip()}


def _stmt(body: str, *, fixed: bool, indent: int = 0) -> str:
    """Format one statement for the detected source form."""
    pad = " " * indent
    return ("      " if fixed else "  ") + pad + body


def inject_local_solve_probe(
    source_text: str,
    solve: LocalSolve,
    slots: ProbeSlots,
    *,
    target_increment: int,
    override_iterate: bool,
    force_exit: bool = True,
    fixed_form: Optional[bool] = None,
) -> ProbeInjection:
    """Return ``source_text`` instrumented to report the local solve's residual.

    With ``override_iterate=False`` the routine is only *observed*: the three
    record assignments are added and the Newton update is untouched, so the
    primal response must be bit-identical to the original.  That pass supplies
    the converged iterate about which the probe is centred, and is the control
    that proves the recording itself is non-perturbing.

    With ``override_iterate=True`` the Newton update on increment
    ``target_increment`` is replaced by ``iterate = PROPS(seed)``, turning the
    loop into an evaluator of the residual at a prescribed iterate.
    """
    lines = source_text.splitlines()
    fixed = _guess_fixed_form(source_text) if fixed_form is None else fixed_form

    update_index = solve.update_line - 1
    loop_index = solve.loop_start_line - 1
    if not (0 <= update_index < len(lines)) or not (0 <= loop_index < len(lines)):
        raise ProbeInjectionError(
            "local_solve_line_out_of_range",
            f"update_line={solve.update_line} loop_start_line={solve.loop_start_line} "
            f"outside a {len(lines)}-line source",
        )

    update_line = lines[update_index]
    if _LABELLED.match(update_line):
        raise ProbeInjectionError(
            "labelled_newton_update",
            f"line {solve.update_line} carries a statement label; moving it into an "
            "IF construct would make any branch to that label a jump into a block",
        )

    routine, header = _enclosing_routine(lines, update_index, fixed=fixed)
    if header < 0:
        raise ProbeInjectionError(
            "enclosing_routine_not_found",
            f"no SUBROUTINE/FUNCTION header found above line {solve.update_line}",
        )
    if override_iterate:
        args = _header_arguments(lines, header, fixed=fixed)
        for required in ("KINC", "STATEV", "PROPS"):
            if required not in args:
                raise ProbeInjectionError(
                    "probe_channel_not_in_scope",
                    f"{required} is not a dummy argument of {routine}; the probe "
                    "cannot select an increment or exchange values there",
                )
    elif "STATEV" not in _header_arguments(lines, header, fixed=fixed):
        raise ProbeInjectionError(
            "probe_channel_not_in_scope",
            f"STATEV is not a dummy argument of {routine}; the probe cannot "
            "report the residual from there",
        )

    it, res, jac = solve.iterate, solve.residual, solve.jacobian
    # The counter is unconditional and resets once per entry to the loop, so it
    # reports how many times the residual was evaluated on *this* increment.
    # That distinguishes an increment that genuinely ran the solve from one that
    # merely inherited a stale iterate: STATEV persists across increments, so
    # the recorded iterate alone cannot tell those apart.
    record = [
        _stmt(f"STATEV({slots.counter})=STATEV({slots.counter})+1.0D0", fixed=fixed),
        _stmt(f"STATEV({slots.iterate})={it}", fixed=fixed),
        _stmt(f"STATEV({slots.residual})={res}", fixed=fixed),
        _stmt(f"STATEV({slots.jacobian})={jac}", fixed=fixed),
        _stmt(f"STATEV({slots.sentinel})={PROBE_SENTINEL!r}D0".replace(".0D0", ".0D0"),
              fixed=fixed),
    ]
    reset = [_stmt(f"STATEV({slots.counter})=0.0D0", fixed=fixed)]

    edits: list[tuple[int, list[str], str]] = []
    if override_iterate:
        block = list(record)
        block.append(_stmt(f"IF (KINC.EQ.{target_increment}) THEN", fixed=fixed))
        if force_exit:
            # The residual has already been recorded above.  Zeroing it after the
            # probe evaluation makes the solve's own convergence test succeed, so
            # the loop terminates on the probe iterate regardless of the model's
            # tolerance.  Nothing downstream of the update consumes the residual.
            block.append(
                _stmt(f"IF (STATEV({slots.counter}).GE.2.0D0) {res}=0.0D0",
                      fixed=fixed, indent=2)
            )
        block.append(_stmt(f"{it}=PROPS({slots.seed_props})", fixed=fixed, indent=2))
        block.append(_stmt("ELSE", fixed=fixed))
        block.append(update_line)
        block.append(_stmt("END IF", fixed=fixed))
        edits.append((update_index, block, "record+seed"))
    else:
        edits.append((update_index, record + [update_line], "record"))
    edits.append((loop_index, reset, "counter-reset"))

    out = list(lines)
    for index, block, _kind in sorted(edits, key=lambda e: e[0], reverse=True):
        if _kind_is_prefix(index, edits):
            out[index:index] = block
        else:
            out[index:index + 1] = block
    return ProbeInjection(
        source="\n".join(out) + "\n",
        slots=slots,
        solve=solve,
        target_increment=target_increment,
        override_iterate=override_iterate,
        forced_exit=bool(override_iterate and force_exit),
        enclosing_routine=routine,
        edits=tuple((ln + 1, kind) for ln, _block, kind in sorted(edits)),
    )


def _kind_is_prefix(index: int, edits: list[tuple[int, list[str], str]]) -> bool:
    for edit_index, _block, kind in edits:
        if edit_index == index:
            return kind == "counter-reset"
    return False


def _guess_fixed_form(text: str) -> bool:
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[:1] in {"C", "c", "*"}:
            return True
        if line.lstrip().startswith("!"):
            continue
        if len(line) > 5 and line[5] not in {" ", "0"} and line[:5].strip() == "":
            return True
    return True
