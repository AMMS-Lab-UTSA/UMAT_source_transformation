"""Higher-order verification for actual UMAT sources, driven by a model spec.

Generalizes the ``code_imp`` path so any plane-strain (``NTENS = 4``) UMAT can be
verified offline with gfortran alone -- no Abaqus. For one model it builds:

  * the canonical schema transform of the original source, compiled;
  * a driver that walks a prescribed strain path through the transformed UMAT,
    carrying ``STATEV`` from increment to increment, and emits the OTI
    higher-order coefficients with factorial recovery applied;
  * an **independently compiled** executable of the *original*, untransformed
    source that replays the same path, which is the reference the OTI result is
    checked against.

The reference executable is what makes this independent: it shares no generated
code with the transformed build. Both are compiled from the same original file,
so their agreement is a statement about the transformation, not about a shared
implementation of the constitutive law.

Compilation is not verification. A model is verified only when the reference
actually resolves its rows -- see
:mod:`umat_oti.validation.higher_order_convergence`.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from umat_oti.services.transformation import (
    TransformationOptions, run_transformation,
)
from umat_oti.validation.actual_legacy_higher_order import CODE_IMP_INCREMENTS
from umat_oti.validation.actual_umat_higher_order import _read_oti_higher_order

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Relative stress agreement required between the transformed and original builds
#: before any derivative from the transformed build is treated as meaningful.
PRIMAL_RELATIVE_TOLERANCE = 1.0e-9

#: How many times the model's own local-solver tolerance a primal divergence may
#: reach and still be attributed to that solver rather than to the transformation.
#: The stated tolerance bounds the Newton *residual*, not the stress difference it
#: leaves behind, so the two are only comparable to within an order of magnitude.
#: Anything beyond this band is too large for the solver to explain.
SOLVER_TOLERANCE_MARGIN = 10.0

SELECTED_DIRECTIONS = (
    (1, 1),
    (1, 2),
    (1, 1, 1),
    (1, 1, 2),
    (1, 1, 1, 1),
    (1, 1, 2, 2),
)


@dataclass(frozen=True)
class SourceZeroProof:
    """A citable source-level reason a derivative is exactly zero.

    This is the only kind of zero argument available for a double-precision
    compiled reference, where no higher-precision recomputation exists. It is a
    statement about the model *source*, checkable by reading the cited lines --
    not an observation that some samples happened to be equal. Because it is a
    property of one constitutive branch, the classifier accepts it only when
    branch consistency has been verified across the whole stencil.
    """

    kind: str          # 'source_affine_branch' or 'source_independent'
    detail: str        # must cite the source lines that make it checkable
    branches: tuple[str, ...] = ()          # empty = every branch
    components: tuple[int, ...] = ()        # empty = every component
    seed_directions: tuple[int, ...] = ()   # empty = any seeded directions

    def applies(self, branch: str, component: int, directions: tuple[int, ...]) -> bool:
        if self.branches and branch not in self.branches:
            return False
        if self.components and component not in self.components:
            return False
        if self.seed_directions and not set(directions) <= set(self.seed_directions):
            return False
        return True


@dataclass(frozen=True)
class ModelSpec:
    """Everything model-specific about one offline higher-order verification."""

    key: str
    config: str
    source: str
    nstatv: int
    nprops: int
    props: tuple[float, ...]
    #: Strain increments per load step; component 4 is the plane-strain shear.
    increments: tuple[tuple[float, float, float, float], ...]
    #: 1-based STATEV slot whose growth marks inelastic response.
    inelastic_statev_index: int
    inelastic_threshold: float
    stress_scale: float
    stress_scale_meaning: str
    strain_scale: float
    strain_scale_meaning: str
    #: Base finite-difference step; the convergence sweep spans decades around it.
    base_step: float
    fixed_form: bool = True
    ntens: int = 4
    order: int = 4
    #: 1-based STATEV slot holding a signed yield-function value, when the model
    #: exposes one. ``None`` means no distance-to-branch-surface is available.
    branch_margin_statev_index: int | None = None
    branch_margin_meaning: str = ""
    #: Convergence tolerance of the model's own local Newton solve, with a
    #: citation. Two builds of the same source may stop at different points
    #: within this tolerance, which bounds what any verification can resolve.
    local_solver_tolerance: float | None = None
    local_solver_tolerance_citation: str = ""
    source_zero_proofs: tuple[SourceZeroProof, ...] = ()

    @classmethod
    def from_contract(cls, contract: dict, *, key: str, config: str,
                      source: str) -> "ModelSpec":
        """Build a spec from a contract's ``validation`` block.

        The registry below is a set of known-good specs, not the mechanism. A
        contract that carries its own validation block drives the same stages
        without appearing in any registry, which is what keeps the pipeline
        generic rather than a switch over model names.
        """
        block = contract.get("validation")
        if not isinstance(block, dict):
            raise ValueError(
                f"{key}: the contract has no 'validation' block, so no material-point "
                f"history is defined. Add one, or run only the stages up to compilation.")
        missing = [name for name in ("increments", "inelastic_statev_index")
                   if block.get(name) is None]
        if missing:
            raise ValueError(
                f"{key}: the validation block is missing {', '.join(missing)}. These "
                f"have no defensible default: a load path cannot be guessed and a "
                f"branch marker cannot be inferred.")
        state_variables = contract.get("state_variables") or []
        nstatv = block.get("nstatv") or max(
            (int(v.get("statev_index", 0)) for v in state_variables), default=0)
        parameters = contract.get("parameters") or []
        props = block.get("props")
        if props is None:
            ordered = sorted(parameters, key=lambda p: int(p.get("props_index", 0)))
            props = [float(p.get("value", 0.0)) for p in ordered]
        nprops = block.get("nprops") or max(len(props), 1)
        if not props:
            props = [0.0] * nprops
        return cls(
            key=key, config=config, source=source,
            nstatv=int(nstatv), nprops=int(nprops), props=tuple(float(v) for v in props),
            increments=tuple(tuple(float(v) for v in row) for row in block["increments"]),
            inelastic_statev_index=int(block["inelastic_statev_index"]),
            inelastic_threshold=float(block.get("inelastic_threshold", 1.0e-12)),
            stress_scale=float(block["stress_scale"]),
            stress_scale_meaning=str(block.get("stress_scale_meaning", "")),
            strain_scale=float(block["strain_scale"]),
            strain_scale_meaning=str(block.get("strain_scale_meaning", "")),
            base_step=float(block["base_step"]),
            fixed_form=bool(block.get("fixed_form", True)),
            ntens=int(contract.get("ntens", 4)),
            order=int(block.get("order", 4)),
            branch_margin_statev_index=block.get("branch_margin_statev_index"),
            branch_margin_meaning=str(block.get("branch_margin_meaning", "")),
            local_solver_tolerance=block.get("local_solver_tolerance"),
            local_solver_tolerance_citation=str(
                block.get("local_solver_tolerance_citation", "")),
            source_zero_proofs=tuple(
                SourceZeroProof(
                    kind=str(proof["kind"]), detail=str(proof["detail"]),
                    branches=tuple(proof.get("branches", ())),
                    components=tuple(int(c) for c in proof.get("components", ())),
                    seed_directions=tuple(int(d) for d in proof.get("seed_directions", ())),
                )
                for proof in block.get("source_zero_proofs", [])
            ),
        )

    def source_proof_for(self, branch: str, component: int,
                         directions: tuple[int, ...]) -> tuple[str, str] | None:
        for proof in self.source_zero_proofs:
            if proof.applies(branch, component, directions):
                return proof.kind, proof.detail
        return None

    @property
    def oti_object(self) -> str:
        return f"otim{self.ntens}n{self.order}.o"

    @property
    def config_path(self) -> Path:
        return REPO_ROOT / self.config


_ELASTIC_AFFINE = (
    'In the elastic branch the update is STRESS = STRESS + DDSDDE . DSTRAN with a\n'
    'DDSDDE assembled only from the constant moduli, before any yield test. The\n'
    'response is therefore exactly affine in DSTRAN on this branch, so every\n'
    'derivative of order two and above vanishes identically -- not merely at the\n'
    'points that were sampled. '
)

MODELS: dict[str, ModelSpec] = {
    "UMAT_PCL": ModelSpec(
        key="UMAT_PCL",
        config="examples/UMAT_PCL_actual_higher_order.json",
        source="UMATs/UMATs/ICP/UMAT_PCL.for",
        nstatv=9,
        nprops=6,
        props=(210000.0, 0.3, 240.0, 150.0, 0.8, 100.0),
        increments=(
            (7.5e-4, -3.2143e-4, 0.0, 0.0),
            (7.5e-4, -4.7676e-4, 0.0, 1.0e-4),
            (1.125e-3, -1.0704e-3, 0.0, 1.5e-4),
            (3.75e-4, -3.6187e-4, 0.0, 5.0e-5),
        ),
        inelastic_statev_index=9,
        inelastic_threshold=1.0e-12,
        stress_scale=240.0,
        stress_scale_meaning="initial yield stress SIG0 = PROPS(3)",
        strain_scale=1.0e-3,
        strain_scale_meaning="characteristic strain-increment magnitude of the load path",
        base_step=4.0e-5,
        local_solver_tolerance=1e-07,
        local_solver_tolerance_citation="UMAT_PCL.for line 49: TOLER=1.0D-7, tested as ABS(FGAM/FJAC).LT.TOLER at line 162",
        source_zero_proofs=(
            SourceZeroProof(
                kind="source_affine_branch",
                branches=("elastic",),
                detail=_ELASTIC_AFFINE + (
                    "UMAT_PCL.for lines 78-95 build DDSDDE from EMOD=PROPS(1) and "
                    "ENU=PROPS(2) only; the elastic update precedes the yield test."
                ),
            ),
        ),
    ),
    "UMAT_PCLK": ModelSpec(
        key="UMAT_PCLK",
        config="examples/UMAT_PCLK_actual_higher_order.json",
        source="UMATs/UMATs/ICP/UMAT_PCLK.for",
        nstatv=14,
        nprops=6,
        props=(210000.0, 0.3, 240.0, 400.0, 20.0, 1000.0),
        increments=(
            (7.5e-4, -3.2143e-4, 0.0, 0.0),
            (7.5e-4, -4.7676e-4, 0.0, 1.0e-4),
            (1.125e-3, -1.0704e-3, 0.0, 1.5e-4),
            (3.75e-4, -3.6187e-4, 0.0, 5.0e-5),
        ),
        inelastic_statev_index=13,
        inelastic_threshold=1.0e-12,
        stress_scale=240.0,
        stress_scale_meaning="initial yield stress SIG0 = PROPS(3)",
        strain_scale=1.0e-3,
        strain_scale_meaning="characteristic strain-increment magnitude of the load path",
        base_step=4.0e-5,
        local_solver_tolerance=1e-07,
        local_solver_tolerance_citation="UMAT_PCLK.for line 62: TOLER=1.0D-7, tested as ABS(FGAM/FJAC).LT.TOLER at line 172",
        source_zero_proofs=(
            SourceZeroProof(
                kind="source_affine_branch",
                branches=("elastic",),
                detail=_ELASTIC_AFFINE + (
                    "UMAT_PCLK.for lines 92-112: DDSDDE is built from EMOD=PROPS(1) "
                    "and ENU=PROPS(2), then STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*"
                    "DSTRAN(K1) is applied before SMISES and the yield test."
                ),
            ),
        ),
    ),
    "visco_imp": ModelSpec(
        key="visco_imp",
        config="examples/visco_imp_actual_higher_order.json",
        source="UMATs/UMATs/ICP/visco/visco_imp.f",
        nstatv=3,
        nprops=1,
        props=(0.0,),
        # E = 1000, YIELD = 10 are hard-coded in the source, so this model yields
        # near 1e-2 strain -- two decades above the steel-like models above.
        increments=(
            (6.0e-3, -2.5714e-3, 0.0, 0.0),
            (6.0e-3, -3.8141e-3, 0.0, 8.0e-4),
            (9.0e-3, -8.5635e-3, 0.0, 1.2e-3),
            (3.0e-3, -2.8950e-3, 0.0, 4.0e-4),
        ),
        inelastic_statev_index=1,
        inelastic_threshold=1.0e-12,
        stress_scale=10.0,
        stress_scale_meaning="hard-coded YIELD = 10 in visco_imp.f",
        strain_scale=1.0e-2,
        strain_scale_meaning="characteristic strain-increment magnitude of the load path",
        base_step=4.0e-4,
        fixed_form=False,
        local_solver_tolerance=1.0e-12,
        local_solver_tolerance_citation=(
            "visco_imp.f line 121: IF(ABS(XRES).LT.1.E-12) GOTO 10"
        ),
        branch_margin_statev_index=3,
        branch_margin_meaning=(
            "STATEV(3) = FLOW = PJ - R - YIELD, the signed trial yield function "
            "stored at visco_imp.f line 104; negative is elastic, positive yields"
        ),
        source_zero_proofs=(
            SourceZeroProof(
                kind="source_affine_branch",
                branches=("elastic",),
                detail=_ELASTIC_AFFINE + (
                    "visco_imp.f lines 88-92: CALL KMLT1(DDSDDE,DSTRAN,DSTRESS) then "
                    "STRESS(K)=STRESS(K)+DSTRESS(K), with DDSDDE from the constant "
                    "E=1000, XNUE=0.3 set at lines 42-43. The plastic correction is "
                    "reached only under IF(FLOW.GT.0.) at line 106."
                ),
            ),
        ),
    ),
    "code_imp": ModelSpec(
        key="code_imp",
        config="examples/code_imp_actual_higher_order.json",
        source="UMATs/UMATs/ICP/plasticity_imp/code_imp.f",
        nstatv=2,
        nprops=2,
        props=(0.0, 0.0),
        increments=CODE_IMP_INCREMENTS,
        inelastic_statev_index=1,
        inelastic_threshold=1.0e-12,
        stress_scale=240.0,
        stress_scale_meaning="initial yield stress SIGY0 = 240 hard-coded at code_imp.f line 46",
        strain_scale=1.0e-3,
        strain_scale_meaning="characteristic strain-increment magnitude of the load path",
        base_step=4.0e-5,
        local_solver_tolerance=1.0e-5,
        local_solver_tolerance_citation=(
            "code_imp.f line 29: TOLER=1.D-5, tested as IF(DABS(RES).LT.TOLER) at "
            "line 151. RES has stress units, so two builds may stop up to ~1e-5 MPa "
            "apart on the same increment."
        ),
        source_zero_proofs=(
            SourceZeroProof(
                kind="source_affine_branch",
                branches=("elastic",),
                detail=_ELASTIC_AFFINE + (
                    "code_imp.f lines 66-104: DDSDDE is built from E=210000 and "
                    "XNUE=0.3 (lines 44-45), CALL KMLT1(DDSDDE,DSTRAN,DSTRESS) then "
                    "STRESS(K)=STRESS(K)+DSTRESS(K); the plastic correction is "
                    "reached only under IF(ZY.GT.0.) at line 141."
                ),
            ),
            SourceZeroProof(
                kind="source_independent",
                components=(4,),
                seed_directions=(1, 2),
                detail=(
                    "The in-plane shear stress is identically zero on this load path, "
                    "in both branches, independently of the seeded directions. "
                    "code_imp.f line 81 sets DDSDDE(4,4)=EG as the only non-zero "
                    "entry in row 4, so DSTRESS(4)=EG*DSTRAN(4); every increment of "
                    "this path has DSTRAN(4)=0 and the seeds are directions 1 and 2 "
                    "only, so STRESS(4) never leaves its initial zero. The deviator "
                    "of a tensor with zero off-diagonal keeps a zero off-diagonal "
                    "(line 114), so the plastic correction DPSTRN(1,2) (line 158) is "
                    "also zero. STRESS(4) is therefore exactly zero for all "
                    "perturbations in directions 1 and 2, and all its derivatives "
                    "with respect to them vanish."
                ),
            ),
        ),
    ),
}


# --------------------------------------------------------------------------- #
# Fortran drivers
# --------------------------------------------------------------------------- #
def _declarations(spec: ModelSpec) -> str:
    return f"""  INTEGER, PARAMETER :: NTENS={spec.ntens}, NSTATV={spec.nstatv}, NPROPS={spec.nprops}
  REAL(8) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
  REAL(8) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
  REAL(8) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3)
  REAL(8) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,I
  CHARACTER(80) :: CMNAME
"""


def _initialization(spec: ModelSpec) -> str:
    props = ";".join(
        f"PROPS({index})={value!r}_8" for index, value in enumerate(spec.props, start=1)
    )
    return f"""  STRESS=0.0_8;STATEV=0.0_8;DDSDDE=0.0_8;STRAN=0.0_8;DSTRAN=0.0_8
  SSE=0.0_8;SPD=0.0_8;SCD=0.0_8;RPL=0.0_8;DDSDDT=0.0_8;DRPLDE=0.0_8;DRPLDT=0.0_8
  TIME=0.0_8;DTIME=1.0_8;TEMP=293.15_8;DTEMP=0.0_8;PREDEF=0.0_8;DPRED=0.0_8
  PROPS=0.0_8;{props}
  COORDS=0.0_8;DROT=0.0_8;DFGRD0=0.0_8;DFGRD1=0.0_8
  DO I=1,3
    DROT(I,I)=1.0_8;DFGRD0(I,I)=1.0_8;DFGRD1(I,I)=1.0_8
  END DO
  PNEWDT=1.0_8;CELENT=1.0_8;CMNAME='{spec.key.upper()}_HIGHER_ORDER'
  NDI=3;NSHR=1;NOEL=1;NPT=1;LAYER=1;KSPT=1;KSTEP=1
"""


def _umat_call() -> str:
    return """    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV, &
      PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
"""


def _path_data(spec: ModelSpec) -> str:
    return ", ".join(
        f"{value!r}_8" for increment in spec.increments for value in increment
    )


def _abaqus_utility_stubs() -> str:
    """Abaqus-supplied utilities the solver would provide at run time.

    ``GETOUTDIR`` is genuinely inert offline. ``XIT`` is Abaqus's abort: the
    models call it when their local Newton loop fails to converge, so it must
    stop the run with a non-zero status. A silent stub would let a
    non-converged increment flow into the evidence as if it were a converged
    one.
    """
    return """SUBROUTINE GETOUTDIR(PATH,NCHAR)
  CHARACTER(*) :: PATH
  INTEGER :: NCHAR
  PATH='.';NCHAR=1
END SUBROUTINE GETOUTDIR
SUBROUTINE XIT
  WRITE(0,'(A)') 'UMAT called XIT: the model aborted (local Newton did not converge).'
  STOP 3
END SUBROUTINE XIT
SUBROUTINE SPRINC(S,PS,LSTR,NDI,NSHR)
  ! Principal values of a symmetric tensor, Abaqus storage order.
  ! Only the plane-strain shape these models use is implemented: NDI=3, NSHR=1,
  ! S = (s11, s22, s33, s12), where s33 is already principal because s13=s23=0.
  ! Any other shape aborts rather than returning a plausible wrong answer.
  IMPLICIT NONE
  INTEGER :: LSTR, NDI, NSHR
  REAL(8) :: S(*), PS(3)
  REAL(8) :: SHEAR, CENTRE, RADIUS
  IF (NDI /= 3 .OR. NSHR /= 1) THEN
    WRITE(0,'(A)') 'SPRINC stub: only NDI=3, NSHR=1 (plane strain) is implemented.'
    STOP 4
  END IF
  SHEAR = S(4)
  ! LSTR=2 means strain, whose off-diagonal entries are engineering shear.
  IF (LSTR == 2) SHEAR = 0.5D0*S(4)
  CENTRE = 0.5D0*(S(1) + S(2))
  RADIUS = SQRT((0.5D0*(S(1) - S(2)))**2 + SHEAR**2)
  PS(1) = CENTRE + RADIUS
  PS(2) = CENTRE - RADIUS
  PS(3) = S(3)
END SUBROUTINE SPRINC
"""


def _transformed_driver_source(spec: ModelSpec) -> str:
    n = len(spec.increments)
    statev_header = ",".join(f"statev_{i}" for i in range(1, spec.nstatv + 1))
    fields = spec.ntens + spec.nstatv
    return f"""PROGRAM higher_order_driver
  IMPLICIT NONE
{_declarations(spec)}  REAL(8) :: PATH(NTENS,{n})
  INTEGER :: INC,U,UT,IR,IC
  DATA PATH / {_path_data(spec)} /
{_initialization(spec)}  OPEN(NEWUNIT=U,FILE='{spec.key}_primal.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(U,'(A)') 'increment,stress_1,stress_2,stress_3,stress_4,{statev_header}'
  OPEN(NEWUNIT=UT,FILE='{spec.key}_ddsdde.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(UT,'(A)') 'increment,row,column,value'
  DO INC=1,{n}
    DSTRAN=PATH(:,INC);KINC=INC
{_umat_call()}    WRITE(U,'(I0,{fields}(",",ES24.16))') INC,STRESS,STATEV
    DO IR=1,NTENS
      DO IC=1,NTENS
        WRITE(UT,'(I0,",",I0,",",I0,",",ES24.16)') INC,IR,IC,DDSDDE(IR,IC)
      END DO
    END DO
    STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
  END DO
  CLOSE(U)
  CLOSE(UT)
END PROGRAM higher_order_driver
{_abaqus_utility_stubs()}"""


def _reference_driver_source(spec: ModelSpec) -> str:
    """Original, untransformed UMAT replaying an arbitrary path read from stdin."""
    return f"""PROGRAM reference_driver
  IMPLICIT NONE
{_declarations(spec)}  INTEGER :: INC,NINC_RUN
  REAL(8) :: STATEV_PREV(NSTATV)
{_initialization(spec)}  STATEV_PREV=0.0_8
  READ(*,*) NINC_RUN
  DO INC=1,NINC_RUN
    READ(*,*) DSTRAN;KINC=INC
    IF (INC == NINC_RUN) STATEV_PREV=STATEV
{_umat_call()}    STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
  END DO
  WRITE(*,'({spec.ntens + 2 * spec.nstatv}(ES25.17,1X))') STRESS,STATEV,STATEV_PREV
END PROGRAM reference_driver
{_abaqus_utility_stubs()}"""


# --------------------------------------------------------------------------- #
# Build and run
# --------------------------------------------------------------------------- #
def _generated_objects(work_dir: Path) -> list[Path]:
    """Object files named by the transform's own compile order.

    Hard-coding this list silently drops generated units -- lifted helper
    routines land in ``umat_oti_helpers.f90``, which only some models produce.
    """
    order_file = work_dir / "compile_order.txt"
    if not order_file.exists():
        raise RuntimeError(f"transform produced no compile_order.txt in {work_dir}")
    objects: list[Path] = []
    entries = [line.strip() for line in order_file.read_text().splitlines() if line.strip()]
    for index, entry in enumerate(entries):
        # The final entry is the transformed UMAT itself, compiled to a fixed name.
        name = "transformed_umat.o" if index == len(entries) - 1 else Path(entry).stem + ".o"
        candidate = work_dir / name
        if not candidate.exists():
            raise RuntimeError(f"expected object {candidate} from compile order was not built")
        objects.append(candidate)
    return objects


def _run(command: Sequence[str], cwd: Path, what: str, stdin: str | None = None):
    result = subprocess.run(
        [str(part) for part in command], cwd=cwd, input=stdin,
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed (rc={result.returncode}):\n{result.stderr[:4000]}")
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_model_artifacts(spec: ModelSpec, work_dir: Path) -> dict[str, Any]:
    """Transform, compile, run OTI, and compile the independent original reference."""
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    summary, exit_code = run_transformation(spec.config_path, work_dir,
                                          TransformationOptions(compile_generated=True))
    if exit_code != 0:
        raise RuntimeError(f"canonical transform failed for {spec.key}: {summary}")

    transformed_source = Path(summary["transformed_source"])
    generated_module = work_dir / f"otim{spec.ntens}n{spec.order}.f90"

    driver = work_dir / f"{spec.key}_higher_order_driver.f90"
    driver.write_text(_transformed_driver_source(spec), encoding="utf-8")
    executable = work_dir / f"{spec.key}_higher_order_driver"
    _run(
        ["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none", "-I", str(work_dir),
         str(driver), *[str(obj) for obj in _generated_objects(work_dir)],
         "-o", str(executable)],
        work_dir, f"{spec.key} transformed driver compile",
    )

    oti_output = work_dir / "oti_hjac.dat"
    oti_output.unlink(missing_ok=True)
    _run([executable], work_dir, f"{spec.key} transformed driver run")
    oti_values = _read_oti_higher_order(oti_output)

    # Independent reference: the ORIGINAL source, compiled on its own.
    original_source = Path(summary["source"])
    original_object = work_dir / f"original_{spec.key}.o"
    form = ["-ffixed-form", "-ffixed-line-length-none"] if spec.fixed_form else \
        ["-ffree-line-length-none"]
    _run(
        ["gfortran", "-O1", "-std=legacy", *form, "-I", str(work_dir),
         "-c", str(original_source), "-o", str(original_object)],
        work_dir, f"{spec.key} original UMAT compile",
    )
    reference_driver = work_dir / f"{spec.key}_reference_driver.f90"
    reference_driver.write_text(_reference_driver_source(spec), encoding="utf-8")
    reference_executable = work_dir / f"{spec.key}_reference_driver"
    _run(
        ["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none",
         str(reference_driver), str(original_object), "-o", str(reference_executable)],
        work_dir, f"{spec.key} reference driver compile",
    )

    with (work_dir / f"{spec.key}_primal.csv").open(newline="", encoding="utf-8") as handle:
        primal_rows = [dict(row) for row in csv.DictReader(handle)]

    branch_history = []
    for row in primal_rows:
        marker = float(row[f"statev_{spec.inelastic_statev_index}"])
        branch_history.append({
            "increment": int(row["increment"]),
            "branch": "inelastic" if abs(marker) > spec.inelastic_threshold else "elastic",
            "inelastic_marker": marker,
            "statev": [float(row[f"statev_{i}"]) for i in range(1, spec.nstatv + 1)],
            "stress": [float(row[f"stress_{i}"]) for i in range(1, spec.ntens + 1)],
        })

    # Primal consistency gate. Before any derivative is believed, the transformed
    # model must reproduce the ORIGINAL model's stress along the same path. If the
    # primal responses differ, a derivative disagreement downstream says nothing
    # about differentiation -- the two builds are simply not the same model there.
    primal_check = []
    for index, row in enumerate(branch_history):
        original = evaluator(reference_executable, spec, index)(spec.increments[index]).values
        transformed = row["stress"]
        deltas = [abs(t - o) for t, o in zip(transformed, original)]
        scale = max([abs(o) for o in original] + [spec.stress_scale])
        largest = max(deltas)
        if spec.local_solver_tolerance is None:
            ratio = None
            within_solver = None
        else:
            ratio = largest / spec.local_solver_tolerance
            within_solver = ratio <= SOLVER_TOLERANCE_MARGIN
        primal_check.append({
            "increment": row["increment"],
            "branch": row["branch"],
            "transformed_stress": list(transformed),
            "original_stress": list(original),
            "max_absolute_difference": largest,
            "max_relative_difference": largest / scale,
            "agrees": largest / scale <= PRIMAL_RELATIVE_TOLERANCE,
            # A divergence no larger than the model's own local Newton tolerance
            # means the two builds simply stopped at different admissible points,
            # which bounds what any verification of this model can resolve. A
            # divergence LARGER than that tolerance is a transformation defect.
            "within_model_solver_tolerance": within_solver,
            "divergence_over_model_solver_tolerance": ratio,
            "model_solver_tolerance": spec.local_solver_tolerance,
        })

    return {
        "spec": spec,
        "oti_values": oti_values,
        "primal_check": primal_check,
        "primal_agrees": all(entry["agrees"] for entry in primal_check),
        "reference_executable": reference_executable,
        "primal_rows": primal_rows,
        "branch_history": branch_history,
        "hashes": {
            "original_source": _sha256(original_source),
            "transformed_source": _sha256(transformed_source),
            "generated_module": _sha256(generated_module),
            "transformed_driver": _sha256(driver),
            "reference_driver": _sha256(reference_driver),
            "oti_higher_order_output": _sha256(oti_output),
        },
        "paths": {
            "original_source": str(original_source),
            "transformed_source": str(transformed_source),
            "generated_module": str(generated_module),
        },
        "canonical_manifest": summary["manifest"],
        "normalized_request": summary["derivative_requests"],
        "compilation": summary["compilation"],
    }


def evaluator(reference_executable: Path, spec: ModelSpec, increment_index: int):
    """Replay the original UMAT to the given increment with a perturbed final step.

    Returns the stress components together with the constitutive branch the
    final increment actually took, so the sweep can reject stencils that
    straddle a yield or unloading boundary. The branch is decided by whether the
    inelasticity marker *grew during this increment* -- not by its absolute
    value, which stays positive once the material has yielded earlier on the
    path and would otherwise mislabel a later elastic step.
    """
    from umat_oti.validation.higher_order_convergence_study import Evaluation

    history = [list(values) for values in spec.increments[: increment_index + 1]]
    ntens, nstatv = spec.ntens, spec.nstatv

    def evaluate(perturbed: Sequence[float]) -> "Evaluation":
        increments = [list(row) for row in history]
        increments[increment_index] = list(perturbed)
        text = str(len(increments)) + "\n" + "\n".join(
            " ".join(f"{value:.17e}" for value in row) for row in increments
        ) + "\n"
        result = subprocess.run(
            [str(reference_executable)], input=text, check=False,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{spec.key} reference execution failed: {result.stderr}")
        numbers = [float(value) for value in result.stdout.split()]
        expected = ntens + 2 * nstatv
        if len(numbers) != expected:
            raise RuntimeError(
                f"{spec.key} reference returned {len(numbers)} values, expected {expected}"
            )
        stress = tuple(numbers[:ntens])
        after = numbers[ntens : ntens + nstatv]
        before = numbers[ntens + nstatv :]
        index = spec.inelastic_statev_index - 1
        grew = after[index] - before[index]
        branch = "inelastic" if grew > spec.inelastic_threshold else "elastic"
        if spec.branch_margin_statev_index is not None:
            margin = after[spec.branch_margin_statev_index - 1]
            reason = None
        else:
            margin = None
            reason = (
                f"{spec.key} does not store a signed yield-function value in STATEV, "
                "so no distance to the branch surface is available"
            )
        return Evaluation(values=stress, branch=branch, margin=margin,
                          margin_unavailable_reason=reason)

    return evaluate


def probe_load_path(spec: ModelSpec, work_dir: Path) -> list[dict[str, Any]]:
    """Build the model and report the branch reached at each increment.

    Used to check that a proposed load path actually exercises both an elastic
    and an inelastic response before it is committed to as evidence.
    """
    artifacts = build_model_artifacts(spec, work_dir)
    return artifacts["branch_history"]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=sorted(MODELS), required=True)
    parser.add_argument("--probe", action="store_true",
                        help="report the branch reached at each increment and exit")
    args = parser.parse_args(argv)

    spec = MODELS[args.model]
    with tempfile.TemporaryDirectory(prefix=f"{spec.key}_ho_") as scratch:
        history = probe_load_path(spec, Path(scratch) / "work")
    print(json.dumps(history, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
