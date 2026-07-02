"""Build the multi-file OTI transform plan from the semantic model.

This is the analysis half of the pipeline: given the boundary the user declared
(seed / output / target on the entry UMAT) it resolves, across files and call
boundaries, where each one actually lives, which procedures must be lifted, and
which files get edited. The result is a TransformPlan the emitter consumes.

No physics: only call-argument-to-dummy binding, assignment locations, and call
graph reachability - all structural facts from FortranProject.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .fortran_model import FortranProject


@dataclass
class Site:
    """Where a boundary variable resolves: its internal name, procedure, file."""
    boundary: str          # the name the user declared (e.g. DDSDDE)
    internal: str          # the resolved internal name (e.g. dds_dde)
    procedure: str
    file: str
    lines: list[tuple[int, int]] = field(default_factory=list)  # assignment spans (target/output)


@dataclass
class TransformPlan:
    entry: str
    seed: Optional[Site]
    output: Optional[Site]
    target: Optional[Site]
    lift: list[str] = field(default_factory=list)          # procedures to OTI-lift
    files: list[str] = field(default_factory=list)         # files the transform touches
    oti_types: list[str] = field(default_factory=list)     # derived types needing OTI variants
    notes: list[str] = field(default_factory=list)


def _resolve_through_calls(proj: FortranProject, proc_name: str, var: str,
                           depth: int = 0) -> tuple[str, str]:
    """Follow `var` from `proc_name` down through CALLs until it is assigned,
    returning (procedure, internal-name) of the assignment site. Stops at the
    first procedure that assigns the (possibly renamed) variable."""
    proc = proj.procedures.get(proc_name)
    if proc is None or depth > 12:
        return proc_name, var
    if var in proc.assigns:                      # assigned right here
        return proc_name, var
    # otherwise follow a call that passes `var`, mapping arg position -> dummy
    for callee, args in proc.call_sites:
        callee_proc = proj.procedures.get(callee)
        if callee_proc is None or var not in args:
            continue
        idx = args.index(var)
        if idx < len(callee_proc.dummy_args):
            inner = callee_proc.dummy_args[idx]
            return _resolve_through_calls(proj, callee, inner, depth + 1)
    return proc_name, var


def _resolve_to_proc(proj: FortranProject, proc_name: str, var: str,
                     stop_proc: str, depth: int = 0) -> tuple[str, str]:
    """Follow `var` from `proc_name` down through CALLs until it reaches
    `stop_proc`, returning the renamed variable there. Used for the seed, which
    is an input (never assigned) and is seeded at the top of the work routine."""
    if proc_name == stop_proc or depth > 12:
        return proc_name, var
    proc = proj.procedures.get(proc_name)
    if proc is None:
        return proc_name, var
    for callee, args in proc.call_sites:
        cp = proj.procedures.get(callee)
        if cp is None or var not in args:
            continue
        idx = args.index(var)
        if idx < len(cp.dummy_args):
            inner = cp.dummy_args[idx]
            hit = _resolve_to_proc(proj, callee, inner, stop_proc, depth + 1)
            if hit[0] == stop_proc:
                return hit
    return proc_name, var


def _site(proj: FortranProject, entry: str, boundary_var: str,
          stop_proc: Optional[str] = None) -> Optional[Site]:
    boundary_var = boundary_var.lower()
    if stop_proc is not None:                      # seed: stop at the work routine
        proc_name, internal = _resolve_to_proc(proj, entry, boundary_var, stop_proc)
    else:                                          # output/target: stop where assigned
        proc_name, internal = _resolve_through_calls(proj, entry, boundary_var)
    proc = proj.procedures.get(proc_name)
    if proc is None:
        return None
    lines = proc.assigns.get(internal, [])
    return Site(boundary=boundary_var.upper(), internal=internal,
                procedure=proc.name, file=proc.file,
                lines=[s for s in lines if s != (0, 0)])


def build_plan(proj: FortranProject, entry: str, seed: str, output: str, target: str) -> TransformPlan:
    entry = entry.lower()
    # target/output resolve to where they are assigned (the "work" routine);
    # the seed is then seeded at the top of that same work routine.
    tgt_site = _site(proj, entry, target)
    out_site = _site(proj, entry, output)
    work_proc = (tgt_site.procedure if tgt_site else (out_site.procedure if out_site else entry)).lower()
    seed_site = _site(proj, entry, seed, stop_proc=work_proc)

    # OTI-lift = the call-graph reachable set from the work routine (conservative).
    lift = proj.reachable(work_proc)

    files, seen = [], set()
    for p in lift:
        f = proj.procedures[p].file
        if f not in seen:
            seen.add(f); files.append(f)

    # derived types that appear as the declared type of any variable in the lift
    # set need an OTI variant (conservative: any derived type touched).
    oti_types, tseen = [], set()
    for p in lift:
        for d in proj.procedures[p].decls.values():
            if d.base in ("TYPE", "CLASS") and d.derived and d.derived.lower() in proj.types:
                key = d.derived.lower()
                if key not in tseen:
                    tseen.add(key); oti_types.append(proj.types[key].name)

    notes = []
    if tgt_site and tgt_site.file != proj.procedures[entry].file:
        notes.append(f"replace site is in {os.path.basename(tgt_site.file)}, not the entry file "
                     f"{os.path.basename(proj.procedures[entry].file)} (file-qualified replace).")
    if oti_types:
        notes.append(f"{len(oti_types)} derived type(s) need OTI variants: {oti_types}")
    return TransformPlan(entry=entry, seed=seed_site, output=out_site, target=tgt_site,
                         lift=lift, files=files, oti_types=oti_types, notes=notes)
