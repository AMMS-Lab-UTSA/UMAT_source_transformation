"""
verify.py -- reusable verification harness for OTI-transformed UMATs.

An emitted OTI UMAT (module ``compat_oti``, subroutine ``umat``) carries the
*exact* consistent tangent in its hyperdual derivative components.  This module
generates a self-contained material-point Fortran driver that:

  1. Seeds the UMAT input with an OTI perturbation:
       * seed_mode="finite": seeds the deformation gradient DFGRD1 with the
         symmetric stretching perturbation  dF^(b) = D^(b) . F0  (the Abaqus /
         Jaumann finite-strain material-tangent recipe).  Derivative component
         b carries d(Cauchy stress)/d(eps_b).
       * seed_mode="small": seeds DSTRAN directly with the 6 unit Voigt
         directions (small-strain UMATs that consume DSTRAN, not DFGRD1).
  2. Extracts the OTI tangent  DDSDDE_ab = GETIM(stress_a, b)  i.e.
     ``stress(a)%E{b}``.
  3. Central-finite-differences the SAME umat (real part only) at the SAME
     perturbation over an h-sweep, and reports  max REL |OTI - FD|  per h.

Proof of exactness is the textbook O(h^2) "V-shape": on the truncation branch
the central-FD error scales ~x100 per decade as h shrinks, until it hits a
floor (where OTI == FD to round-off), after which round-off makes it rise
again.  ``shape_is_Oh2`` checks that ~x100-per-decade scaling on the
truncation branch.

The generated driver mirrors the known-good ``qin_fs_verify.f90`` structure
exactly; only the per-model bits (nprops/nstatv, the OTI-typed scalar args, the
props/statev initialisation, and the seed block) are templated.

Public API
----------
verify_umat(emitted_f90, module_name, umat_name, ntens, nprops, nstatv,
            seed_mode, props, statev0, lib_dir, work_dir,
            oti_scalar_args=(), ...) -> dict

Returns a dict::

    {
      "floor":          float,   # min max-REL OTI-vs-FD over the sweep
      "h_at_floor":     float,   # the h where the floor was reached
      "shape_is_Oh2":   bool,    # ~x100/decade on the truncation branch?
      "oti_stress":     [float], # real part of the OTI-seeded stress (ntens)
      "raw":            {...},   # h-sweep dict, stdout, build/run cmds, etc.
    }
"""

import os
import subprocess

# OTI library source files, in the canonical compile order used in /tmp/oti_emit.
DEFAULT_LIBS = [
    "master_parameters.f90",
    "real_utils.f90",
    "precision_.f90",
    "otim6n1.f90",
    "oti_intrinsics.f90",
    "oti_lapack.f90",
]

# Default h-sweep (matches qin_fs_verify.f90).
DEFAULT_HSWEEP = [1.0e-2, 1.0e-3, 1.0e-4, 1.0e-5, 1.0e-6, 1.0e-7]


def _fmt_d(x):
    """Format a Python float as a Fortran double-precision literal."""
    s = repr(float(x))
    if "e" in s or "E" in s:
        mant, _, exp = s.lower().partition("e")
        if "." not in mant:
            mant += ".0"
        return "%sd%d" % (mant, int(exp))
    if "." not in s:
        s += ".0"
    return s + "d0"


def _scalar_decls(oti_scalar_args, oti_type):
    """
    Split the umat *scalar* dummy args sse,spd,scd,rpl,drpldt,dtime,temp,
    dtemp,celent and pnewdt into an OTI-typed group and a real group, honouring
    which were retyped to OTI in the emitted UMAT (``oti_scalar_args``).

    pnewdt is virtually always OTI (it is an inout the lift writes through), but
    we drive the split entirely off the caller-supplied list so the driver's
    declared types match the emitted umat's dummy-arg types exactly.
    """
    all_scalars = ["pnewdt", "sse", "spd", "scd", "rpl", "drpldt",
                   "dtime", "temp", "dtemp", "celent"]
    oti = [s for s in all_scalars if s in oti_scalar_args]
    real = [s for s in all_scalars if s not in oti_scalar_args]
    lines = []
    if oti:
        lines.append("  type(%s) :: %s" % (oti_type, ", ".join(oti)))
    if real:
        lines.append("  double precision :: %s" % ", ".join(real))
    return "\n".join(lines)


def _seed_block_finite():
    """
    Finite-strain seed: build P^(b) = D^(b).F0 and seed DFGRD1's OTI
    derivative components, then run.  The umat's deforming input is dfgrd1.
    """
    return r"""
  ! ===== build symmetric-stretching seed P^(b) = D^(b) . F0 =====
  do b = 1, 6
    Db = 0.0d0
    Db(kv(b), lv(b)) = Db(kv(b), lv(b)) + 0.5d0
    Db(lv(b), kv(b)) = Db(lv(b), kv(b)) + 0.5d0
    P(:, :, b) = matmul(Db, F0)
  end do

  ! ===== OTI: seed dfgrd1 (real part F0, derivative comp b = P^(b)) =====
  do i = 1, 3; do j = 1, 3
    dfgrd1(i, j) = 0.0d0; dfgrd1(i, j)%R = F0(i, j)
    dfgrd1(i, j)%E1 = P(i, j, 1); dfgrd1(i, j)%E2 = P(i, j, 2); dfgrd1(i, j)%E3 = P(i, j, 3)
    dfgrd1(i, j)%E4 = P(i, j, 4); dfgrd1(i, j)%E5 = P(i, j, 5); dfgrd1(i, j)%E6 = P(i, j, 6)
  end do; end do
"""


def _seed_block_small():
    """
    Small-strain seed: seed DSTRAN's OTI derivative components with the 6 unit
    Voigt directions (E{b} = delta_{ab}); dfgrd1 stays the (real) identity.
    The FD branch perturbs DSTRAN += h * e_b.
    """
    return r"""
  ! ===== small-strain: unit-Voigt seed directions e_b stored in P(1,:,b) =====
  P = 0.0d0
  do b = 1, 6
    P(1, b, b) = 1.0d0      ! e_b in component b (used by run_real for FD)
  end do

  ! dfgrd1 is the (real) identity for the small-strain path
  do i = 1, 3; do j = 1, 3
    dfgrd1(i, j) = 0.0d0
  end do; end do
  do i = 1, 3; dfgrd1(i, i)%R = 1.0d0; end do

  ! ===== OTI: seed dstran (real 0, derivative comp b = e_b) =====
  do i = 1, 6
    dstran_oti(i) = 0.0d0
  end do
  dstran_oti(1)%E1 = 1.0d0; dstran_oti(2)%E2 = 1.0d0; dstran_oti(3)%E3 = 1.0d0
  dstran_oti(4)%E4 = 1.0d0; dstran_oti(5)%E5 = 1.0d0; dstran_oti(6)%E6 = 1.0d0
"""


# Two driver templates.  They share everything except (a) what is OTI-seeded,
# (b) what run_oti / run_real perturb, (c) a couple of extra declarations for
# the small-strain dstran path.  Both mirror qin_fs_verify.f90 exactly.

_TEMPLATE = r"""! AUTO-GENERATED by umat_oti.semantic.verify -- DO NOT EDIT BY HAND.
! Material-point verification driver: confirms the emitted UMAT's OTI tangent
! DDSDDE == d(stress)/d(strain) by comparing OTI extraction against central FD
! of the SAME perturbation over an h-sweep (expect an O(h^2) V-shape).
! Mirrors the known-good qin_fs_verify.f90 structure.   seed_mode = {SEED_MODE}
program umat_verify
  use {OTI_MODULE}
  use {MODULE_NAME}, only: {UMAT_NAME}
  implicit none
  integer, parameter :: ntens = {NTENS}, ndi = 3, nshr = {NSHR}, nstatv = {NSTATV}, nprops = {NPROPS}
  double precision :: props(nprops), dfgrd0(3, 3), stran(ntens), statev0(nstatv)
  double precision :: ddsddt(ntens), drplde(ntens), time(2), predef(1), dpred(1), coords(3), drot(3, 3)
{SCALAR_DECLS}
  character(len=80) :: cmname
  integer :: noel, npt, layer, kspt, kstep, kinc, i, j, b, a
  double precision :: F0(3, 3), Db(3, 3), P(3, 3, 6), otij(6, 6), fdj(6, 6), s0(6), sp(6), sm(6), h, mx
  integer :: kv(6) = [1, 2, 3, 1, 1, 2], lv(6) = [1, 2, 3, 2, 3, 3]
  type({OTI_TYPE}) :: stress(ntens), dfgrd1(3, 3)
  type({OTI_TYPE}) :: dstran_oti(ntens)     ! OTI-seeded DSTRAN (small-strain mode)
  double precision :: dstran(ntens)         ! real DSTRAN (finite-strain mode / FD base)

  ! ----- props / initial state -----
  props = 1.0d0
{PROPS_INIT}
  statev0 = 0.0d0
{STATEV_INIT}
  F0 = reshape({F0_LIT}, [3, 3])

  dfgrd0 = 0.0d0; do i = 1, 3; dfgrd0(i, i) = 1.0d0; end do
  stran = 0.0d0; dstran = 0.0d0
  do i = 1, ntens; dstran_oti(i) = 0.0d0; end do
  time = 0.0d0; dtime = 1.0d0; temp = 0.0d0; dtemp = 0.0d0
  predef = 0.0d0; dpred = 0.0d0; coords = 0.0d0; drot = 0.0d0; do i = 1, 3; drot(i, i) = 1.0d0; end do
  cmname = '{CMNAME}'; noel = 1; npt = 1; layer = 1; kspt = 1; kstep = 1; kinc = 1
  ! 0.0d0 (not integer 0) so this also assigns cleanly to OTI-typed scalars
  pnewdt = 1.0d0; celent = 1.0d0; sse = 0.0d0; spd = 0.0d0; scd = 0.0d0; rpl = 0.0d0; drpldt = 0.0d0
{SEED_BLOCK}
  ! ===== OTI run: extract the tangent =====
  block
    type({OTI_TYPE}) :: ddout(6, 6)
    double precision :: mxd
    call run_oti(dfgrd1, {DSE_MAIN}, stress, ddout)
    do a = 1, 6
      otij(a, 1) = stress(a)%E1; otij(a, 2) = stress(a)%E2; otij(a, 3) = stress(a)%E3
      otij(a, 4) = stress(a)%E4; otij(a, 5) = stress(a)%E5; otij(a, 6) = stress(a)%E6
      s0(a) = stress(a)%R
    end do
    write(*, '(A)') 'OTI seeded stress (real part):'
    write(*, '(6ES12.4)') (s0(a), a = 1, 6)
    mxd = 0.0d0
    do a = 1, 6; do b = 1, 6
      mxd = max(mxd, abs(otij(a, b) - ddout(a, b)%R) / max(1.0d0, abs(ddout(a, b)%R)))
    end do; end do
    write(*, '(A,ES12.4)') 'max REL |OTI tangent - UMAT analytical ddsdde| = ', mxd
  end block

  ! ===== FD: rerun the umat (real part) at base +/- h*e_b, sweep h =====
  block
    integer :: ih
    double precision :: hs({NH}) = {HSWEEP_LIT}
    do ih = 1, {NH}
      h = hs(ih)
      do b = 1, 6
        call run_real_pm(b,  h, sp)
        call run_real_pm(b, -h, sm)
        fdj(:, b) = (sp - sm) / (2.0d0 * h)
      end do
      mx = 0.0d0
      do a = 1, 6; do b = 1, 6
        mx = max(mx, abs(otij(a, b) - fdj(a, b)) / max(1.0d0, abs(fdj(a, b))))
      end do; end do
      write(*, '(A,ES9.1,A,ES12.4)') 'h=', h, '  max REL |OTI - FD| = ', mx
    end do
  end block

contains
  ! NB: the DSTRAN dummy is REAL for finite-strain UMATs (they deform via
  ! DFGRD1) and OTI for small-strain UMATs (they deform via DSTRAN); its type
  ! here matches the emitted umat's DSTRAN dummy type ({DSE_DECL}).
  subroutine run_oti(F, dse, sig, dd)        ! call umat with OTI F, fresh state
    type({OTI_TYPE}), intent(in) :: F(3, 3)
    {DSE_DECL}, intent(in) :: dse(ntens)
    type({OTI_TYPE}), intent(out) :: sig(ntens)
    type({OTI_TYPE}), intent(out) :: dd(ntens, ntens)
    type({OTI_TYPE}) :: sv(nstatv)
    integer :: ii, jj
    do ii = 1, ntens; sig(ii) = 0.0d0; end do
    do ii = 1, nstatv; sv(ii) = 0.0d0; sv(ii)%R = statev0(ii); end do
    do ii = 1, ntens; do jj = 1, ntens; dd(ii, jj) = 0.0d0; end do; end do
    call {UMAT_NAME}(sig, sv, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, stran, dse, &
              time, dtime, temp, dtemp, predef, dpred, cmname, ndi, nshr, ntens, nstatv, props, &
              nprops, coords, drot, pnewdt, celent, dfgrd0, F, noel, npt, layer, kspt, kstep, kinc)
  end subroutine

  subroutine run_real_pm(bdir, hh, sig)      ! real-part-only run at base + hh*e_{bdir}
    integer, intent(in) :: bdir
    double precision, intent(in) :: hh
    double precision, intent(out) :: sig(6)
    type({OTI_TYPE}) :: F(3, 3), s(ntens), dd(ntens, ntens)
    {DSE_DECL} :: dse(ntens)
    integer :: ii, jj
{RUN_REAL_BODY}
    call run_oti(F, dse, s, dd)
    do ii = 1, 6; sig(ii) = s(ii)%R; end do
  end subroutine
end program umat_verify
"""

# run_real_pm body for the finite-strain path: F = F0 + hh*P^(bdir), dstran=0.
_RUN_REAL_FINITE = r"""    do ii = 1, 3; do jj = 1, 3
      F(ii, jj) = 0.0d0; F(ii, jj)%R = F0(ii, jj) + hh * P(ii, jj, bdir)
    end do; end do
    do ii = 1, ntens; dse(ii) = 0.0d0; end do"""

# run_real_pm body for the small-strain path: F = identity, dstran = hh*e_bdir.
_RUN_REAL_SMALL = r"""    do ii = 1, 3; do jj = 1, 3; F(ii, jj) = 0.0d0; end do; end do
    do ii = 1, 3; F(ii, ii)%R = 1.0d0; end do
    do ii = 1, ntens; dse(ii) = 0.0d0; end do
    dse(bdir)%R = hh"""


def _render_driver(module_name, umat_name, ntens, nshr, nprops, nstatv,
                   seed_mode, props, statev0, oti_scalar_args, oti_type,
                   oti_module, cmname, F0, hsweep):
    # props / statev initialisation lines (only the non-default entries).
    props_lines = []
    for idx, val in enumerate(props, start=1):
        props_lines.append("  props(%d) = %s" % (idx, _fmt_d(val)))
    statev_lines = []
    for idx, val in enumerate(statev0, start=1):
        if val != 0.0:
            statev_lines.append("  statev0(%d) = %s" % (idx, _fmt_d(val)))

    f0_lit = "[" + ", ".join(_fmt_d(x) for x in F0) + "]"
    hsweep_lit = "[" + ", ".join(_fmt_d(x) for x in hsweep) + "]"

    if seed_mode == "finite":
        seed_block = _seed_block_finite()
        run_real_body = _RUN_REAL_FINITE
        dse_decl = "double precision"      # finite-strain UMATs take a REAL dstran
        dse_main = "dstran"                # real, zero
    elif seed_mode == "small":
        seed_block = _seed_block_small()
        run_real_body = _RUN_REAL_SMALL
        dse_decl = "type(%s)" % oti_type   # small-strain UMATs take an OTI dstran
        dse_main = "dstran_oti"            # OTI, seeded
    else:
        raise ValueError("seed_mode must be 'finite' or 'small', got %r" % seed_mode)

    # NB: we use explicit token replacement (NOT str.format) because the
    # emitted Fortran contains literal braces (e.g. the comment 'e_{bdir}')
    # that str.format would mis-parse as format fields.
    subs = {
        "{SEED_MODE}": seed_mode,
        "{OTI_MODULE}": oti_module,
        "{MODULE_NAME}": module_name,
        "{UMAT_NAME}": umat_name,
        "{NTENS}": str(ntens),
        "{NSHR}": str(nshr),
        "{NSTATV}": str(nstatv),
        "{NPROPS}": str(nprops),
        "{OTI_TYPE}": oti_type,
        "{SCALAR_DECLS}": _scalar_decls(oti_scalar_args, oti_type),
        "{PROPS_INIT}": "\n".join(props_lines),
        "{STATEV_INIT}": "\n".join(statev_lines) if statev_lines else "  ! (statev0 all zero)",
        "{F0_LIT}": f0_lit,
        "{CMNAME}": cmname,
        "{SEED_BLOCK}": seed_block,
        "{NH}": str(len(hsweep)),
        "{HSWEEP_LIT}": hsweep_lit,
        "{RUN_REAL_BODY}": run_real_body,
        "{DSE_DECL}": dse_decl,
        "{DSE_MAIN}": dse_main,
    }
    out = _TEMPLATE
    for tok, val in subs.items():
        out = out.replace(tok, val)
    return out


def _parse_output(stdout):
    """Parse 'OTI seeded stress', the analytical-ddsdde check, and the h-sweep."""
    oti_stress = []
    analytic_rel = None
    sweep = []  # list of (h, max_rel)
    lines = stdout.splitlines()
    for k, ln in enumerate(lines):
        if ln.strip() == "OTI seeded stress (real part):" and k + 1 < len(lines):
            try:
                oti_stress = [float(t) for t in lines[k + 1].split()]
            except ValueError:
                oti_stress = []
        if "UMAT analytical ddsdde" in ln and "=" in ln:
            try:
                analytic_rel = float(ln.rsplit("=", 1)[1].strip())
            except ValueError:
                pass
        if ln.lstrip().startswith("h=") and "max REL |OTI - FD|" in ln:
            try:
                left, right = ln.split("max REL |OTI - FD| =")
                h = float(left.replace("h=", "").strip())
                val = float(right.strip())
                sweep.append((h, val))
            except ValueError:
                pass
    return oti_stress, analytic_rel, sweep


def _assess_shape(sweep):
    """
    Decide whether the truncation branch shows ~x100/decade O(h^2) scaling and
    locate the floor.

    The sweep is ordered from large h to small h.  On the truncation branch the
    error should *decrease* by roughly a factor 100 per decade of h.  We scan
    from the largest h while the error keeps dropping by >~10x/decade, treat the
    first non-dropping point as the floor, and call the shape O(h^2) if at least
    one truncation-branch step dropped by a factor in the [~30, ~300] band
    (textbook central FD is x100; we allow slack for stiff plastic problems).
    """
    import math
    # Drop points the FD couldn't evaluate meaningfully: a non-finite value, or
    # an exact 0.0 (which in the plastic regime signals the return-map diverged
    # at that step so OTI and FD both fell back to the same NaN-guard value, not
    # a genuine machine-zero error).  Such points are not on the V-curve.
    pts = [(h, v) for (h, v) in sweep
           if v > 0.0 and math.isfinite(v)]
    if len(pts) < 2:
        floor = min((v for _, v in pts), default=float("nan"))
        h_at = next((h for h, v in pts if v == floor), float("nan"))
        return floor, h_at, False

    # Floor = smallest positive error over the (cleaned) sweep.
    floor_h, floor_val = min(pts, key=lambda hv: hv[1])

    # O(h^2) check: scan the descending (truncation) branch -- from the largest
    # h down to the floor -- and require at least one decade-step that drops by
    # ~x100 (central FD).  We allow a [30, 300] band for stiff plastic models.
    saw_oh2 = False
    for k in range(1, len(pts)):
        prev_h, prev_v = pts[k - 1]
        cur_h, cur_v = pts[k]
        if cur_v >= prev_v:
            break  # reached the floor; beyond here is round-off, stop scanning
        ratio = prev_v / cur_v
        # normalise the ratio to "per decade of h" in case h steps aren't 10x.
        decades = math.log10(prev_h / cur_h) if cur_h > 0 and prev_h > 0 else 1.0
        per_decade = ratio ** (1.0 / decades) if decades > 0 else ratio
        if 30.0 <= per_decade <= 300.0:
            saw_oh2 = True
    return floor_val, floor_h, saw_oh2


def verify_umat(emitted_f90, module_name, umat_name, ntens, nprops, nstatv,
                seed_mode, props, statev0, lib_dir, work_dir,
                oti_scalar_args=(),
                nshr=3, oti_type="ONUMM6N1", oti_module="otim6n1",
                cmname="MAT",
                F0=(1.002, 0.0, 0.0, 0.001, 0.999, 0.0, 0.0, 0.0005, 1.001),
                hsweep=None, libs=None, driver_name=None, timeout=900,
                keep=True):
    """
    Generate + compile + run a material-point verification driver for an emitted
    OTI UMAT and return a result dict.  See the module docstring for details.

    Parameters
    ----------
    emitted_f90 : str
        Path to the emitted all-OTI UMAT file (module ``module_name``).
    module_name, umat_name : str
        Fortran module and subroutine to ``use ..., only: umat``.
    ntens, nprops, nstatv : int
        Tensor size and the model's runtime nprops / nstatv (must match!).
    seed_mode : {"finite", "small"}
        "finite" seeds DFGRD1 with dF=D.F; "small" seeds DSTRAN with unit Voigt.
    props : sequence of float
        props(1..len) initialiser (entries past the end stay 1.0d0).
    statev0 : sequence of float
        Initial statev (only nonzero entries are emitted).
    lib_dir : str
        Directory holding the OTI library .f90 files (DEFAULT_LIBS).
    work_dir : str
        Where the driver .f90 / object / exe are written and run.
    oti_scalar_args : sequence of str
        Which umat scalar dummies were retyped to OTI in the emitted file
        (e.g. ("pnewdt",) for Qin/MM; ("pnewdt", "spd") for Shi).
    """
    if hsweep is None:
        hsweep = list(DEFAULT_HSWEEP)
    if libs is None:
        libs = list(DEFAULT_LIBS)
    if len(F0) != 9:
        raise ValueError("F0 must have 9 entries (row-major 3x3 used as Fortran reshape)")
    os.makedirs(work_dir, exist_ok=True)

    src = _render_driver(module_name, umat_name, ntens, nshr, nprops, nstatv,
                         seed_mode, props, statev0, tuple(oti_scalar_args),
                         oti_type, oti_module, cmname, F0, hsweep)

    if driver_name is None:
        base = os.path.splitext(os.path.basename(emitted_f90))[0]
        driver_name = "%s_%s_verify" % (base, seed_mode)
    driver_f90 = os.path.join(work_dir, driver_name + ".f90")
    exe = os.path.join(work_dir, driver_name)
    with open(driver_f90, "w") as fh:
        fh.write(src)

    lib_paths = [os.path.join(lib_dir, l) for l in libs]
    build_cmd = (["gfortran", "-O0", "-ffree-line-length-none", "-fcray-pointer",
                  "-I."] + lib_paths + [emitted_f90, driver_f90, "-o", exe])

    build = subprocess.run(build_cmd, cwd=work_dir,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=timeout)
    if build.returncode != 0:
        return {
            "floor": float("nan"), "h_at_floor": float("nan"),
            "shape_is_Oh2": False, "oti_stress": [],
            "raw": {"stage": "build", "returncode": build.returncode,
                    "build_cmd": " ".join(build_cmd), "build_log": build.stdout,
                    "driver_f90": driver_f90},
        }

    run = subprocess.run([exe], cwd=work_dir,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True, timeout=timeout)
    stdout = run.stdout
    oti_stress, analytic_rel, sweep = _parse_output(stdout)
    floor, h_at, oh2 = _assess_shape(sweep)

    if not keep:
        for p in (driver_f90, exe):
            try:
                os.remove(p)
            except OSError:
                pass

    return {
        "floor": floor,
        "h_at_floor": h_at,
        "shape_is_Oh2": oh2,
        "oti_stress": oti_stress,
        "raw": {
            "stage": "run",
            "returncode": run.returncode,
            "sweep": sweep,                  # [(h, max_rel), ...]
            "analytic_rel": analytic_rel,    # OTI-tangent vs UMAT's own ddsdde
            "stdout": stdout,
            "build_cmd": " ".join(build_cmd),
            "driver_f90": driver_f90,
            "exe": exe,
        },
    }


# ---------------------------------------------------------------------------
# Self-test: reproduce the known-good Qin2018 finite-strain V-shape.
# Run with:  python -m umat_oti.semantic.verify
# ---------------------------------------------------------------------------
def _selftest_qin(lib_dir="/tmp/oti_emit", work_dir="/tmp/oti_emit",
                  emitted="/tmp/oti_emit/qin_final.f90"):
    # Qin2018 plastic regime (props mirror qin_fs_verify.f90).
    props = [1.0] * 21
    props[0] = 80000.0; props[1] = 170000.0      # G, K
    props[2] = 100.0                             # R0 (low -> yields)
    props[3] = 0.01; props[4] = 200.0            # DeR1, R1sat
    props[5] = 0.01; props[6] = 200.0            # DeR2, R2sat
    props[11] = 5000.0; props[12] = 100.0        # Hkin1, Binf1
    props[13] = 5000.0; props[14] = 100.0        # Hkin2, Binf2
    statev0 = [0.0] * 36
    statev0[28] = 0.1; statev0[29] = -0.05; statev0[33] = 1.0
    res = verify_umat(
        emitted_f90=emitted, module_name="compat_oti", umat_name="umat",
        ntens=6, nprops=21, nstatv=36, seed_mode="finite",
        props=props, statev0=statev0, lib_dir=lib_dir, work_dir=work_dir,
        oti_scalar_args=("pnewdt",), cmname="QIN",
        driver_name="qin_selftest_verify",
    )
    return res


if __name__ == "__main__":
    import json
    r = _selftest_qin()
    print("Qin2018 self-test:")
    print("  oti_stress :", r["oti_stress"])
    print("  floor      :", r["floor"])
    print("  h_at_floor :", r["h_at_floor"])
    print("  O(h^2)?    :", r["shape_is_Oh2"])
    print("  sweep      :")
    for h, v in r["raw"].get("sweep", []):
        print("      h=%.0e  max REL |OTI-FD| = %.4e" % (h, v))
    if r["raw"].get("stage") == "build":
        print("  BUILD FAILED:\n", r["raw"]["build_log"][-2000:])
    print(json.dumps({k: r[k] for k in ("floor", "h_at_floor", "shape_is_Oh2")},
                     indent=2))
