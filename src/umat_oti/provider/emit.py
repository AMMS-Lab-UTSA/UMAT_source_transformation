"""Legacy replay ABI wrappers around the generic, fully lifted UMAT."""

from umat_oti.oti.oti_directions import member_name
from umat_oti.transform.parameter_sensitivity_transform import GenericPSLayout


EVAL_ARGUMENTS = (
    "STRESS,STATEV,DDSDDE,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PROPS,"
    "NPROPS,NTENS,NSTATV,NPARAM,DSIGMA_DP,DSTATEV_DP"
)
CARRY_ARGUMENTS = ",DSIGMA_DP_IN,DSTATEV_DP_IN"
EVAL_SIGNATURE = [
    "STRESS(NTENS)", "STATEV(NSTATV)", "DDSDDE(NTENS,NTENS)",
    "STRAN(NTENS)", "DSTRAN(NTENS)", "TIME(2)", "DTIME", "TEMP", "DTEMP",
    "PROPS(NPROPS)", "NPROPS", "NTENS", "NSTATV", "NPARAM",
    "DSIGMA_DP(NTENS,NPARAM)", "DSTATEV_DP(NSTATV,NPARAM)",
]
CARRY_SIGNATURE = ["DSIGMA_DP_IN(NTENS,NPARAM)", "DSTATEV_DP_IN(NSTATV,NPARAM)"]
MARCH_SIGNATURE = [
    "PROPS(NPROPS)", "NPROPS", "PATH(NTENS,NPATH)", "NPATH", "DTARR(NPATH)",
    "NTENS", "NSTATV", "NPARAM", "DSIG(NTENS,NPARAM,NPATH)", "STROUT(NTENS)",
    "DDOUT(NTENS,NTENS,NPATH)",
]
# Total-derivative entry point for whole-model history replay (any UMAT).
# Besides the incoming stress/state derivatives it seeds the parameter
# derivatives of the strain at the start of the increment (STRAN_DP_IN) and of
# the strain increment (DSTRAN_DP_IN), so DSIGMA_DP/DSTATEV_DP are the full
# first-order chain rule through the update, whatever the UMAT does with
# STRAN/DSTRAN. It also returns dSTATEV/dDSTRAN (the state half of the
# consistent tangent, from the same DSTRAN seed directions that give DDSDDE),
# passes COORDS/CELENT/NOEL/NPT/KSTEP/KINC through and reports PNEWDT instead
# of stopping, so a caller can refuse a cut-back request with a message.
TOTAL_ARGUMENTS = (
    EVAL_ARGUMENTS + CARRY_ARGUMENTS
    + ",STRAN_DP_IN,DSTRAN_DP_IN,DSTATEV_DDSTRAN,COORDS,CELENT,NOEL,NPT,KSTEP,KINC,PNEWDT"
)
TOTAL_SIGNATURE = EVAL_SIGNATURE + CARRY_SIGNATURE + [
    "STRAN_DP_IN(NTENS,NPARAM)", "DSTRAN_DP_IN(NTENS,NPARAM)",
    "DSTATEV_DDSTRAN(NSTATV,NTENS)", "COORDS(3)", "CELENT", "NOEL", "NPT",
    "KSTEP", "KINC", "PNEWDT",
]


def emit_wrappers(layout: GenericPSLayout, *, ntens: int, nprops: int,
                  nstatev: int, parameters: tuple[tuple[str, int], ...],
                  path_dependent: bool) -> str:
    nparam = len(parameters)
    declarations = """
  INTEGER, INTENT(IN) :: NPROPS,NTENS,NSTATV,NPARAM
  REAL(8), INTENT(INOUT) :: STRESS(NTENS),STATEV(NSTATV)
  REAL(8), INTENT(OUT) :: DDSDDE(NTENS,NTENS)
  REAL(8), INTENT(IN) :: STRAN(NTENS),DSTRAN(NTENS),TIME(2),DTIME,TEMP,DTEMP,PROPS(NPROPS)
  REAL(8), INTENT(OUT) :: DSIGMA_DP(NTENS,NPARAM),DSTATEV_DP(NSTATV,NPARAM)
"""
    carry_declarations = """
  REAL(8), INTENT(IN) :: DSIGMA_DP_IN(NTENS,NPARAM),DSTATEV_DP_IN(NSTATV,NPARAM)
"""
    seeds = []
    for direction, (_, slot) in enumerate(parameters, 1):
        member = member_name([direction])
        seeds.extend([
            f"  PROPS_OTI({slot})%{member}=1.0_8",
            f"  STRESS_OTI%{member}=DSIGMA_DP_IN(:,{direction})",
            f"  STATEV_OTI%{member}=DSTATEV_DP_IN(:,{direction})",
        ])
    for component in range(1, ntens + 1):
        seeds.append(f"  DSTRAN_OTI({component})%{member_name([nparam + component])}=1.0_8")
    seed_text = "\n".join(seeds)
    guard = (
        f"  IF (NTENS /= {ntens} .OR. NPROPS /= {nprops} .OR. "
        f"NSTATV /= {nstatev} .OR. NPARAM /= {nparam}) &\n"
        "    ERROR STOP 'provider ABI dimensions do not match the built contract'\n"
    )
    public_arguments = EVAL_ARGUMENTS + (CARRY_ARGUMENTS if path_dependent else "")
    public_carry = carry_declarations if path_dependent else """
  REAL(8) :: DSIGMA_DP_IN(NTENS,NPARAM),DSTATEV_DP_IN(NSTATV,NPARAM)
"""
    zero_carry = "" if path_dependent else "  DSIGMA_DP_IN=0.0_8;DSTATEV_DP_IN=0.0_8\n"
    total = _emit_total(layout, parameters=parameters, ntens=ntens, guard=guard,
                        declarations=declarations, carry_declarations=carry_declarations)
    return f"""SUBROUTINE UMAT_OTI_INTERNAL({EVAL_ARGUMENTS}{CARRY_ARGUMENTS},INCREMENT)
  USE {layout.module_name}, ONLY: {layout.type_name}, ASSIGNMENT(=), GETIM
  USE umat_oti_lifted_mod, ONLY: umat_oti
  IMPLICIT NONE
{declarations}{carry_declarations}
  INTEGER, INTENT(IN) :: INCREMENT
  INTEGER :: COMPONENT,PARAMETER_INDEX,AXIS
  TYPE({layout.type_name}) :: STRESS_OTI(NTENS),STATEV_OTI(NSTATV),PROPS_OTI(NPROPS)
  TYPE({layout.type_name}) :: STRAN_OTI(NTENS),DSTRAN_OTI(NTENS),DDSDDE_OTI(NTENS,NTENS)
  TYPE({layout.type_name}) :: SSE,SPD,SCD,RPL,DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT
  TYPE({layout.type_name}) :: TIME_OTI(2),DTIME_OTI,TEMP_OTI,DTEMP_OTI,PREDEF(1),DPRED(1)
  TYPE({layout.type_name}) :: COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3),PNEWDT,CELENT
  CHARACTER(80) :: CMNAME
{guard}
  STRESS_OTI=STRESS;STATEV_OTI=STATEV;PROPS_OTI=PROPS
  STRAN_OTI=STRAN;DSTRAN_OTI=DSTRAN;DDSDDE_OTI=0.0_8
  TIME_OTI=TIME;DTIME_OTI=DTIME;TEMP_OTI=TEMP;DTEMP_OTI=DTEMP
  SSE=0.0_8;SPD=0.0_8;SCD=0.0_8;RPL=0.0_8;DDSDDT=0.0_8;DRPLDE=0.0_8;DRPLDT=0.0_8
  PREDEF=0.0_8;DPRED=0.0_8;COORDS=0.0_8;DROT=0.0_8;DFGRD0=0.0_8;DFGRD1=0.0_8
  PNEWDT=1.0_8;CELENT=1.0_8;CMNAME='MATERIAL_OTI'
  DO AXIS=1,3
    DROT(AXIS,AXIS)=1.0_8;DFGRD0(AXIS,AXIS)=1.0_8;DFGRD1(AXIS,AXIS)=1.0_8
  END DO
{seed_text}
  CALL umat_oti(STRESS_OTI,STATEV_OTI,DDSDDE_OTI,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
    STRAN_OTI,DSTRAN_OTI,TIME_OTI,DTIME_OTI,TEMP_OTI,DTEMP_OTI,PREDEF,DPRED,CMNAME, &
    3,3,NTENS,NSTATV,PROPS_OTI,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,1,1,1,1,1,INCREMENT)
  IF (PNEWDT%R < 1.0_8) ERROR STOP 'provider UMAT requested a time cutback'
  STRESS=STRESS_OTI%R;STATEV=STATEV_OTI%R
  DO PARAMETER_INDEX=1,NPARAM
    DO COMPONENT=1,NTENS
      DSIGMA_DP(COMPONENT,PARAMETER_INDEX)=GETIM(STRESS_OTI(COMPONENT),PARAMETER_INDEX)
    END DO
    DO COMPONENT=1,NSTATV
      DSTATEV_DP(COMPONENT,PARAMETER_INDEX)=GETIM(STATEV_OTI(COMPONENT),PARAMETER_INDEX)
    END DO
  END DO
  DO AXIS=1,NTENS
    DO COMPONENT=1,NTENS
      DDSDDE(COMPONENT,AXIS)=GETIM(STRESS_OTI(COMPONENT),NPARAM+AXIS)
    END DO
  END DO
END SUBROUTINE UMAT_OTI_INTERNAL

SUBROUTINE UMAT_OTI_EVAL({public_arguments})
  IMPLICIT NONE
{declarations}{public_carry}
{zero_carry}  CALL UMAT_OTI_INTERNAL({EVAL_ARGUMENTS}{CARRY_ARGUMENTS},1)
END SUBROUTINE UMAT_OTI_EVAL

SUBROUTINE UMAT_OTI_MARCH(PROPS,NPROPS,PATH,NPATH,DTARR,NTENS,NSTATV,NPARAM,DSIG,STROUT,DDOUT)
  IMPLICIT NONE
  INTEGER, INTENT(IN) :: NPROPS,NPATH,NTENS,NSTATV,NPARAM
  REAL(8), INTENT(IN) :: PROPS(NPROPS),PATH(NTENS,NPATH),DTARR(NPATH)
  REAL(8), INTENT(OUT) :: DSIG(NTENS,NPARAM,NPATH),STROUT(NTENS),DDOUT(NTENS,NTENS,NPATH)
  REAL(8) :: STATEV(NSTATV),STRAN(NTENS),TIME(2),DSTATE(NSTATV,NPARAM)
  REAL(8) :: DSIG_IN(NTENS,NPARAM),DSTATE_IN(NSTATV,NPARAM)
  INTEGER :: INCREMENT
{guard}
  IF (NPATH < 1) ERROR STOP 'provider path must contain at least one increment'
  IF (ANY(DTARR <= 0.0_8)) ERROR STOP 'provider DTARR must be positive'
  STROUT=0.0_8;STATEV=0.0_8;STRAN=0.0_8;TIME=0.0_8;DSIG_IN=0.0_8;DSTATE_IN=0.0_8
  DO INCREMENT=1,NPATH
    CALL UMAT_OTI_INTERNAL(STROUT,STATEV,DDOUT(:,:,INCREMENT),STRAN,PATH(:,INCREMENT), &
      TIME,DTARR(INCREMENT),293.15_8,0.0_8,PROPS,NPROPS,NTENS,NSTATV,NPARAM, &
      DSIG(:,:,INCREMENT),DSTATE,DSIG_IN,DSTATE_IN,INCREMENT)
    DSIG_IN=DSIG(:,:,INCREMENT);DSTATE_IN=DSTATE
    STRAN=STRAN+PATH(:,INCREMENT);TIME=TIME+DTARR(INCREMENT)
  END DO
END SUBROUTINE UMAT_OTI_MARCH
""" + total


def _emit_total(layout: GenericPSLayout, *, parameters: tuple[tuple[str, int], ...],
                ntens: int, guard: str, declarations: str, carry_declarations: str) -> str:
    """UMAT_OTI_EVAL_TOTAL: one first-order OTI call, every history seed.

    Parameter direction j carries d/dp_j of every input that depends on the
    parameters through the history (STRESS, STATEV, STRAN, DSTRAN) plus the
    unit PROPS seed, so the imaginary parts of the outputs are total
    derivatives. Directions NPARAM+1..NPARAM+NTENS are unit DSTRAN seeds, as
    in UMAT_OTI_INTERNAL: they give DDSDDE and DSTATEV_DDSTRAN.
    """
    nparam = len(parameters)
    seeds = []
    for direction, (_, slot) in enumerate(parameters, 1):
        member = member_name([direction])
        seeds.extend([
            f"  PROPS_OTI({slot})%{member}=1.0_8",
            f"  STRESS_OTI%{member}=DSIGMA_DP_IN(:,{direction})",
            f"  STATEV_OTI%{member}=DSTATEV_DP_IN(:,{direction})",
            f"  STRAN_OTI%{member}=STRAN_DP_IN(:,{direction})",
            f"  DSTRAN_OTI%{member}=DSTRAN_DP_IN(:,{direction})",
        ])
    for component in range(1, ntens + 1):
        seeds.append(f"  DSTRAN_OTI({component})%{member_name([nparam + component])}=1.0_8")
    seed_text = "\n".join(seeds)
    return f"""
SUBROUTINE UMAT_OTI_EVAL_TOTAL({TOTAL_ARGUMENTS})
  USE {layout.module_name}, ONLY: {layout.type_name}, ASSIGNMENT(=), GETIM
  USE umat_oti_lifted_mod, ONLY: umat_oti
  IMPLICIT NONE
{declarations}{carry_declarations}
  REAL(8), INTENT(IN) :: STRAN_DP_IN(NTENS,NPARAM),DSTRAN_DP_IN(NTENS,NPARAM),COORDS(3),CELENT
  REAL(8), INTENT(OUT) :: DSTATEV_DDSTRAN(NSTATV,NTENS),PNEWDT
  INTEGER, INTENT(IN) :: NOEL,NPT,KSTEP,KINC
  INTEGER :: COMPONENT,PARAMETER_INDEX,AXIS
  TYPE({layout.type_name}) :: STRESS_OTI(NTENS),STATEV_OTI(NSTATV),PROPS_OTI(NPROPS)
  TYPE({layout.type_name}) :: STRAN_OTI(NTENS),DSTRAN_OTI(NTENS),DDSDDE_OTI(NTENS,NTENS)
  TYPE({layout.type_name}) :: SSE,SPD,SCD,RPL,DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT
  TYPE({layout.type_name}) :: TIME_OTI(2),DTIME_OTI,TEMP_OTI,DTEMP_OTI,PREDEF(1),DPRED(1)
  TYPE({layout.type_name}) :: COORDS_OTI(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3),PNEWDT_OTI,CELENT_OTI
  CHARACTER(80) :: CMNAME
{guard}
  STRESS_OTI=STRESS;STATEV_OTI=STATEV;PROPS_OTI=PROPS
  STRAN_OTI=STRAN;DSTRAN_OTI=DSTRAN;DDSDDE_OTI=0.0_8
  TIME_OTI=TIME;DTIME_OTI=DTIME;TEMP_OTI=TEMP;DTEMP_OTI=DTEMP
  SSE=0.0_8;SPD=0.0_8;SCD=0.0_8;RPL=0.0_8;DDSDDT=0.0_8;DRPLDE=0.0_8;DRPLDT=0.0_8
  PREDEF=0.0_8;DPRED=0.0_8;COORDS_OTI=COORDS;DROT=0.0_8;DFGRD0=0.0_8;DFGRD1=0.0_8
  PNEWDT_OTI=1.0_8;CELENT_OTI=CELENT;CMNAME='MATERIAL_OTI'
  DO AXIS=1,3
    DROT(AXIS,AXIS)=1.0_8;DFGRD0(AXIS,AXIS)=1.0_8;DFGRD1(AXIS,AXIS)=1.0_8
  END DO
{seed_text}
  CALL umat_oti(STRESS_OTI,STATEV_OTI,DDSDDE_OTI,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
    STRAN_OTI,DSTRAN_OTI,TIME_OTI,DTIME_OTI,TEMP_OTI,DTEMP_OTI,PREDEF,DPRED,CMNAME, &
    3,3,NTENS,NSTATV,PROPS_OTI,NPROPS,COORDS_OTI,DROT,PNEWDT_OTI,CELENT_OTI,DFGRD0,DFGRD1, &
    NOEL,NPT,1,1,KSTEP,KINC)
  PNEWDT=PNEWDT_OTI%R
  STRESS=STRESS_OTI%R;STATEV=STATEV_OTI%R
  DO PARAMETER_INDEX=1,NPARAM
    DO COMPONENT=1,NTENS
      DSIGMA_DP(COMPONENT,PARAMETER_INDEX)=GETIM(STRESS_OTI(COMPONENT),PARAMETER_INDEX)
    END DO
    DO COMPONENT=1,NSTATV
      DSTATEV_DP(COMPONENT,PARAMETER_INDEX)=GETIM(STATEV_OTI(COMPONENT),PARAMETER_INDEX)
    END DO
  END DO
  DO AXIS=1,NTENS
    DO COMPONENT=1,NTENS
      DDSDDE(COMPONENT,AXIS)=GETIM(STRESS_OTI(COMPONENT),NPARAM+AXIS)
    END DO
    DO COMPONENT=1,NSTATV
      DSTATEV_DDSTRAN(COMPONENT,AXIS)=GETIM(STATEV_OTI(COMPONENT),NPARAM+AXIS)
    END DO
  END DO
END SUBROUTINE UMAT_OTI_EVAL_TOTAL
"""