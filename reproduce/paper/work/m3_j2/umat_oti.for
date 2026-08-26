C  ------------------------------------------------------------------------
C  M3  Small-strain von Mises (J2) plasticity, linear isotropic hardening.
C
C  PROPS(1)=E   PROPS(2)=nu   PROPS(3)=SIGY0 (initial yield)  PROPS(4)=H (hard.)
C  STATEV(1) = EQPLAS (accumulated equivalent plastic strain)
C
C  Stress-driven radial return.  The incoming STRESS is the converged stress of
C  the previous increment; STRESS + Del*DSTRAN is the elastic predictor.  Only
C  EQPLAS is required as history for the update, so NSTATV = 1.  Consistent
C  (algorithmic) tangent for linear hardening.  Voigt (11,22,33,12,13,23),
C  engineering shear.  Self-contained: no ROTSIG / UHARD.
C  ------------------------------------------------------------------------
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      USE otim6n1, OTI_MODULE_DP => DP, OTI_E1 => E1, OTI_E2 => E2,
     1OTI_E3 => E3, OTI_E4 => E4, OTI_E5 => E5, OTI_E6 => E6
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION FLOW(6)
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: DEQPL_OTI
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: EQPLAS_OTI
      TYPE(ONUMM6N1) :: FLOW_OTI(6)
      TYPE(ONUMM6N1) :: SHYDRO_OTI
      TYPE(ONUMM6N1) :: SMISES_OTI
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      TYPE(ONUMM6N1) :: SYIEL0_OTI
      TYPE(ONUMM6N1) :: SYIELD_OTI
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HARD=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
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
C     OTIS seed initialization from GUI configuration
      DEQPL_OTI = 0.0D0
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      EQPLAS_OTI = 0.0D0
      DO OTI_HI = 1, 6
         FLOW_OTI(OTI_HI) = 0.0D0
      END DO
      SHYDRO_OTI = 0.0D0
      SMISES_OTI = 0.0D0
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
      SYIEL0_OTI = 0.0D0
      SYIELD_OTI = 0.0D0
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
        DO K2=1,NTENS
          STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE(K2,K1)*DSTRAN_OTI(K1)
        END DO
      END DO
      EQPLAS_OTI=STATEV_OTI(1)
C     Mises equivalent STRESS_OTI of the predictor
      SMISES_OTI=(STRESS_OTI(1)-STRESS_OTI(2))**2.0D0+(STRESS_OTI(2)-
     1STRESS_OTI(3))**2.0D0 +(STRESS_OTI(3)-STRESS_OTI(1))**2.0D0
C     OTIS-SKIP: 1      +(STRESS(3)-STRESS(1))**2
      DO K1=NDI+1,NTENS
        SMISES_OTI=SMISES_OTI+SIX*STRESS_OTI(K1)**2.0D0
      END DO
      SMISES_OTI=SQRT((((MAX(REAL(SMISES_OTI/TWO), 1.0D-30)) -
     1REAL(SMISES_OTI/TWO)) + (SMISES_OTI/TWO)))
      SYIEL0_OTI=SIGY0+HARD*EQPLAS_OTI
C
      IF (REAL(SMISES_OTI).GT.REAL(SYIEL0_OTI)) THEN
C       actively yielding: hydrostatic / deviatoric split + flow direction
        SHYDRO_OTI=(STRESS_OTI(1)+STRESS_OTI(2)+STRESS_OTI(3))/THREE
        DO K1=1,NDI
          FLOW_OTI(K1)=(STRESS_OTI(K1)-SHYDRO_OTI)/SMISES_OTI
        END DO
        DO K1=NDI+1,NTENS
          FLOW_OTI(K1)=STRESS_OTI(K1)/SMISES_OTI
        END DO
C       closed-form return for linear hardening
        DEQPL_OTI=(SMISES_OTI-SYIEL0_OTI)/(EG3+HARD)
        SYIELD_OTI=SYIEL0_OTI+HARD*DEQPL_OTI
        DO K1=1,NDI
          STRESS_OTI(K1)=FLOW_OTI(K1)*SYIELD_OTI+SHYDRO_OTI
        END DO
        DO K1=NDI+1,NTENS
          STRESS_OTI(K1)=FLOW_OTI(K1)*SYIELD_OTI
        END DO
        EQPLAS_OTI=EQPLAS_OTI+DEQPL_OTI
C       consistent (algorithmic) tangent
C     OTIS-SKIP: EFFG=EG*SYIELD/SMISES
C     OTIS-SKIP: EFFG2=TWO*EFFG
C     OTIS-SKIP: EFFG3=THREE/TWO*EFFG2
C     OTIS-SKIP: EFFLAM=(EBULK3-EFFG2)/THREE
C     OTIS-SKIP: EFFHRD=EG3*HARD/(EG3+HARD)-EFFG3
C     OTIS-SKIP: DO K1=1,NTENS
C     OTIS-SKIP: DO K2=1,NTENS
C     OTIS-SKIP: DDSDDE(K2,K1)=ZERO
C     OTIS-SKIP: END DO
C     OTIS-SKIP: END DO
C     OTIS-SKIP: DO K1=1,NDI
C     OTIS-SKIP: DO K2=1,NDI
C     OTIS-SKIP: DDSDDE(K2,K1)=EFFLAM
C     OTIS-SKIP: END DO
C     OTIS-SKIP: DDSDDE(K1,K1)=EFFG2+EFFLAM
C     OTIS-SKIP: END DO
C     OTIS-SKIP: DO K1=NDI+1,NTENS
C     OTIS-SKIP: DDSDDE(K1,K1)=EFFG
C     OTIS-SKIP: END DO
C     OTIS-SKIP: DO K1=1,NTENS
C     OTIS-SKIP: DO K2=1,NTENS
C     OTIS-SKIP: DDSDDE(K2,K1)=DDSDDE(K2,K1)+EFFHRD*FLOW(K2)*FLOW(K1)
C     OTIS-SKIP: END DO
C     OTIS-SKIP: END DO
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
