C  ------------------------------------------------------------------------
C  sweep_j2_kinematic : Small-strain von Mises (J2) plasticity with LINEAR
C  KINEMATIC (Prager) hardening.  Radial return on the RELATIVE stress
C  xi = dev(sigma) - alpha ; the yield surface has fixed size SIGY0 and
C  translates by the backstress alpha.
C
C  PROPS(1)=E  PROPS(2)=nu  PROPS(3)=SIGY0 (yield)  PROPS(4)=Hk (kin. mod.)
C  STATEV(1..6) = ALPHA (deviatoric backstress tensor, Voigt 11,22,33,12,13,23)
C
C  Return mapping (equivalent plastic strain increment DEQPL):
C     DEQPL = (SMISES - SIGY0)/(3G + Hk)          SMISES = q(sigma-alpha)
C     STRESS(K) = STRESS_trial(K) - 3G*DEQPL*FLOW(K)
C     ALPHA(K)  = ALPHA(K)        + Hk*DEQPL*FLOW(K)
C  Consistent (algorithmic) tangent is the isotropic-J2 form with HARD->Hk
C  and Mises/flow taken on the relative stress.  Self-contained; no external
C  CALLs; STRESS set by inline assignment.  INCLUDE ABA_PARAM.INC -> REAL*8.
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
      DIMENSION FLOW(6),ALPHA(6),RELS(6)
      INTEGER K1,K2,K
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: ALPHA_OTI(6)
      TYPE(ONUMM6N1) :: DEQPL_OTI
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: FLOW_OTI(6)
      TYPE(ONUMM6N1) :: RELS_OTI(6)
      TYPE(ONUMM6N1) :: RHYDRO_OTI
      TYPE(ONUMM6N1) :: SMISES_OTI
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HARD=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
C     read backstress history
C     OTIS seed initialization from GUI configuration
      DO OTI_HI = 1, 6
         ALPHA_OTI(OTI_HI) = 0.0D0
      END DO
      DEQPL_OTI = 0.0D0
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 6
         FLOW_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 6
         RELS_OTI(OTI_HI) = 0.0D0
      END DO
      RHYDRO_OTI = 0.0D0
      SMISES_OTI = 0.0D0
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
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
      DO K=1,6
        ALPHA_OTI(K)=STATEV_OTI(K)
      END DO
C     elastic stiffness (also the predictor operator)
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=ZERO
        END DO
      END DO
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1)=EG
      END DO
C     elastic predictor stress
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE(K2,K1)*DSTRAN_OTI(K1)
        END DO
      END DO
C     relative stress xi = sigma - alpha (alpha deviatoric)
      DO K=1,NTENS
        RELS_OTI(K)=STRESS_OTI(K)-ALPHA_OTI(K)
      END DO
C     Mises equivalent of the relative STRESS_OTI (hydrostatic cancels)
      SMISES_OTI=(RELS_OTI(1)-RELS_OTI(2))**2+(RELS_OTI(2)-RELS_OTI(3))*
     1*2+(RELS_OTI(3)-RELS_OTI(1))**2
C     OTIS-SKIP: 1      +(RELS(3)-RELS(1))**2
      DO K1=NDI+1,NTENS
        SMISES_OTI=SMISES_OTI+SIX*RELS_OTI(K1)**2
      END DO
      SMISES_OTI=SQRT((((MAX(REAL(SMISES_OTI/TWO), 1.0D-30)) -
     1REAL(SMISES_OTI/TWO)) + (SMISES_OTI/TWO)))
      SYIEL0=SIGY0
C
      IF (REAL(SMISES_OTI).GT.SYIEL0) THEN
C       flow direction from the RELATIVE deviatoric stress
        RHYDRO_OTI=(RELS_OTI(1)+RELS_OTI(2)+RELS_OTI(3))/THREE
        DO K1=1,NDI
          FLOW_OTI(K1)=(RELS_OTI(K1)-RHYDRO_OTI)/SMISES_OTI
        END DO
        DO K1=NDI+1,NTENS
          FLOW_OTI(K1)=RELS_OTI(K1)/SMISES_OTI
        END DO
C       closed-form return (linear kinematic hardening)
        DEQPL_OTI=(SMISES_OTI-SYIEL0)/(EG3+HARD)
C     OTIS-SKIP: SYIELD=SYIEL0+HARD*DEQPL
C       stress update: sigma = sigma_trial - 3G*DEQPL*flow
        DO K1=1,NTENS
          STRESS_OTI(K1)=STRESS_OTI(K1)-EG3*DEQPL_OTI*FLOW_OTI(K1)
        END DO
C       backstress update: ALPHA_OTI += Hk*DEQPL_OTI*FLOW_OTI
        DO K1=1,NTENS
          ALPHA_OTI(K1)=ALPHA_OTI(K1)+HARD*DEQPL_OTI*FLOW_OTI(K1)
        END DO
C       consistent (algorithmic) tangent
C     OTIS-SKIP: EFFG=EG*SYIELD/SMISES
C     OTIS-SKIP: EFFG2=TWO*EFFG
C     OTIS-SKIP: EFFG3=THREE/TWO*EFFG2
C     OTIS-SKIP: EFFLAM=(EBULK3-EFFG2)/THREE
C     OTIS-SKIP: EFFHRD=EG3*HARD/(EG3+HARD)-EFFG3
        DO K1=1,NTENS
          DO K2=1,NTENS
C     OTIS-SKIP: DDSDDE(K2,K1)=ZERO
          END DO
        END DO
        DO K1=1,NDI
          DO K2=1,NDI
C     OTIS-SKIP: DDSDDE(K2,K1)=EFFLAM
          END DO
C     OTIS-SKIP: DDSDDE(K1,K1)=EFFG2+EFFLAM
        END DO
        DO K1=NDI+1,NTENS
C     OTIS-SKIP: DDSDDE(K1,K1)=EFFG
        END DO
        DO K1=1,NTENS
          DO K2=1,NTENS
C     OTIS-SKIP: DDSDDE(K2,K1)=DDSDDE(K2,K1)+EFFHRD*FLOW(K2)*FLOW(K1)
          END DO
        END DO
      END IF
C     store updated backstress
      DO K=1,6
        STATEV_OTI(K)=ALPHA_OTI(K)
      END DO
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
