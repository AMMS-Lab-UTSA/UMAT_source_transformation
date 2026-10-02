C  ------------------------------------------------------------------------
C  sweep_real_PCO  Plasticity Couple-Stress (reduced Cosserat) solid.
C
C  Self-contained, inline reformulation of the production UMAT_PCO.for.
C  The production routine builds the return map through the external helper
C  chain KCLEAR / KMMULT / KMTRAN / KMAVEC / KUPDVEC / KPROYECTOR /
C  KSPECTRAL (a fixed spectral/eigenvector decomposition of the couple-stress
C  deviatoric projector) plus a local Newton loop and a XIT abort.  None of
C  those helpers are self-contained and several use constructs the OTI
C  transform forbids (external CALLs updating STRESS, ABS-based Newton exit,
C  XIT).  They are provably unnecessary: because the spectral operator scales
C  every deviatoric/shear eigen-direction by the SAME factor 1/(1+2G*gamma)
C  and preserves the hydrostatic axis, B=Q*DIAG*Q^T reduces the whole update
C  to a radial return in the couple-stress metric, with a CLOSED FORM for the
C  linear-hardening consistency parameter (no Newton, no ABS, no eigen-solve).
C
C  Couple-stress structure retained faithfully:
C    * elastic operator: shear-12 modulus = G,  shear-13/23 modulus = 2G
C    * deviatoric metric P: normal block std, comp 12 weight 2, comps 13/23
C      weight 1  ->  FBAR^2 = s^T P s
C    * yield:  FBAR > sqrt(2/3)*(SIGY0 + H*EQPLAS)   (KUHARD scaling)
C
C  PROPS(1)=E  PROPS(2)=nu  PROPS(3)=SIGY0  PROPS(4)=H (hardening slope)
C  STATEV(1)=EQPLAS (accumulated equivalent plastic strain).
C  Voigt (11,22,33,12,13,23), engineering shear.
C  ------------------------------------------------------------------------
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      USE otim6n1, OTI_MODULE_DP => DP, OTI_E1 => E1, OTI_E2 => E2,
     1OTI_E3 => E3, OTI_E4 => E4, OTI_E5 => E5, OTI_E6 => E6
      USE oti_intrinsics
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION DS(6),FLOW(6)
      INTEGER K1,K2
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: AA_OTI
      TYPE(ONUMM6N1) :: CC_OTI
      TYPE(ONUMM6N1) :: DS_OTI(6)
      TYPE(ONUMM6N1) :: DSCAL_OTI
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: EQPLAS_OTI
      TYPE(ONUMM6N1) :: FLOW_OTI(6)
      TYPE(ONUMM6N1) :: GAM_OTI
      TYPE(ONUMM6N1) :: SHYDRO_OTI
      TYPE(ONUMM6N1) :: SMISES_OTI
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      TYPE(ONUMM6N1) :: SYIEL0_OTI
      TYPE(ONUMM6N1) :: TFAC_OTI
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HARD=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      ELAM=(EBULK3-EG2)/THREE
      SQ23=SQRT(TWO/THREE)
      TOLER=1.0D-6
C     couple-stress elastic predictor operator (also stored in DDSDDE)
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=ZERO
        END DO
      END DO
      DO K1=1,3
        DO K2=1,3
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DDSDDE(4,4)=EG
      DDSDDE(5,5)=EG2
      DDSDDE(6,6)=EG2
C     elastic predictor stress: DS = DDSDDE . DSTRAN, STRESS += DS (inline)
C     OTIS seed initialization from GUI configuration
      AA_OTI = 0.0D0
      CC_OTI = 0.0D0
      DO OTI_HI = 1, 6
         DS_OTI(OTI_HI) = 0.0D0
      END DO
      DSCAL_OTI = 0.0D0
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      EQPLAS_OTI = 0.0D0
      DO OTI_HI = 1, 6
         FLOW_OTI(OTI_HI) = 0.0D0
      END DO
      GAM_OTI = 0.0D0
      SHYDRO_OTI = 0.0D0
      SMISES_OTI = 0.0D0
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
      SYIEL0_OTI = 0.0D0
      TFAC_OTI = 0.0D0
      DO OTI_I = 1, NTENS
         DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)
      END DO
      DO OTI_I = 1, NTENS
         STRESS_OTI(OTI_I) = STRESS(OTI_I)
      END DO
      DO OTI_I = 1, NSTATV
         STATEV_OTI(OTI_I) = STATEV(OTI_I)
      END DO
      DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1
      DSTRAN_OTI(2) = DSTRAN_OTI(2) + OTI_E2
      DSTRAN_OTI(3) = DSTRAN_OTI(3) + OTI_E3
      DSTRAN_OTI(4) = DSTRAN_OTI(4) + OTI_E4
      DSTRAN_OTI(5) = DSTRAN_OTI(5) + OTI_E5
      DSTRAN_OTI(6) = DSTRAN_OTI(6) + OTI_E6
      DO K1=1,NTENS
        DS_OTI(K1)=ZERO
        DO K2=1,NTENS
          DS_OTI(K1)=DS_OTI(K1)+DDSDDE(K1,K2)*DSTRAN_OTI(K2)
        END DO
      END DO
      DO K1=1,NTENS
        STRESS_OTI(K1)=STRESS_OTI(K1)+DS_OTI(K1)
      END DO
      EQPLAS_OTI=STATEV_OTI(1)
C     couple-stress equivalent measure of the predictor:  SMISES^2 = s^T P s
C     (normal block std, shear-12 weight 2, shear-13/23 weight 1).  Built in
C     the same accumulation idiom as the m3 J2 reference.
      SHYDRO_OTI=(STRESS_OTI(1)+STRESS_OTI(2)+STRESS_OTI(3))/THREE
      SMISES_OTI=(STRESS_OTI(1)-STRESS_OTI(2))**2+(STRESS_OTI(2)-
     1STRESS_OTI(3))**2+(STRESS_OTI(3)-STRESS_OTI(1))**2
C     OTIS-SKIP: 1      +(STRESS(3)-STRESS(1))**2
      SMISES_OTI=SMISES_OTI/THREE
      SMISES_OTI=SMISES_OTI+TWO*STRESS_OTI(4)**2+STRESS_OTI(5)**2+
     1STRESS_OTI(6)**2
      SMISES_OTI=SQRT((((MAX(REAL(SMISES_OTI), 1.0D-30)) -
     1REAL(SMISES_OTI)) + (SMISES_OTI)))
      SYIEL0_OTI=SQ23*(SIGY0+HARD*EQPLAS_OTI)
C
      IF (REAL(SMISES_OTI).GT.(ONE+TOLER)*REAL(SYIEL0_OTI)) THEN
C       actively yielding.  Closed-form radial return in the couple-stress
C       metric:  with t = 1 + 2G*gamma the updated equivalent stress is
C       SMISES/t, required equal to sqrt 2/3 times SIGY0 + H*EQPLAS.
C       Linear hardening gives t = SMISES + CC over AA + CC.  FLOW holds the
C       trial deviatoric parts (normal deviatoric for K1<=NDI, full component
C       for the shears), so STRESS is written from FLOW only, never read RHS.
        DO K1=1,NDI
          FLOW_OTI(K1)=STRESS_OTI(K1)-SHYDRO_OTI
        END DO
        DO K1=NDI+1,NTENS
          FLOW_OTI(K1)=STRESS_OTI(K1)
        END DO
        AA_OTI=SQ23*(SIGY0+HARD*EQPLAS_OTI)
        CC_OTI=(TWO/THREE)*HARD*SMISES_OTI/EG2
        TFAC_OTI=(SMISES_OTI+CC_OTI)/(AA_OTI+CC_OTI)
        GAM_OTI=(TFAC_OTI-ONE)/EG2
        DSCAL_OTI=ONE/TFAC_OTI
C       updated stress: hydrostatic axis preserved, deviatoric + all shear
C       components scaled by 1/TFAC.
        DO K1=1,NDI
          STRESS_OTI(K1)=FLOW_OTI(K1)*DSCAL_OTI+SHYDRO_OTI
        END DO
        DO K1=NDI+1,NTENS
          STRESS_OTI(K1)=FLOW_OTI(K1)*DSCAL_OTI
        END DO
C       equivalent plastic strain increment (KUHARD sqrt(2/3) scaling)
        EQPLAS_OTI=EQPLAS_OTI+SQ23*GAM_OTI*SMISES_OTI*DSCAL_OTI
      END IF
      STATEV_OTI(1)=EQPLAS_OTI
C     Copy real-valued OTIS outputs back to Abaqus arrays
      DO OTI_I = 1, NTENS
         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))
      END DO
      DO OTI_I = 1, NSTATV
         STATEV(OTI_I) = REAL(STATEV_OTI(OTI_I))
      END DO
C     OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)
      DO OTI_I = 1, NTENS
         DO OTI_J = 1, NTENS
            DDSDDE(OTI_I,OTI_J) =
     1      GETIM(STRESS_OTI(OTI_I),OTI_J)
         END DO
      END DO
      RETURN
      END
