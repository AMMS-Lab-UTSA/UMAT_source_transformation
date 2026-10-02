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
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION FLOW(6)
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
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
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)
        END DO
      END DO
      EQPLAS=STATEV(1)
C     Mises equivalent stress of the predictor
      SMISES=(STRESS(1)-STRESS(2))**2+(STRESS(2)-STRESS(3))**2
     1      +(STRESS(3)-STRESS(1))**2
      DO K1=NDI+1,NTENS
        SMISES=SMISES+SIX*STRESS(K1)**2
      END DO
      SMISES=SQRT(SMISES/TWO)
      SYIEL0=SIGY0+HARD*EQPLAS
C
      IF (SMISES.GT.SYIEL0) THEN
C       actively yielding: hydrostatic / deviatoric split + flow direction
        SHYDRO=(STRESS(1)+STRESS(2)+STRESS(3))/THREE
        DO K1=1,NDI
          FLOW(K1)=(STRESS(K1)-SHYDRO)/SMISES
        END DO
        DO K1=NDI+1,NTENS
          FLOW(K1)=STRESS(K1)/SMISES
        END DO
C       closed-form return for linear hardening
        DEQPL=(SMISES-SYIEL0)/(EG3+HARD)
        SYIELD=SYIEL0+HARD*DEQPL
        DO K1=1,NDI
          STRESS(K1)=FLOW(K1)*SYIELD+SHYDRO
        END DO
        DO K1=NDI+1,NTENS
          STRESS(K1)=FLOW(K1)*SYIELD
        END DO
        EQPLAS=EQPLAS+DEQPL
C       consistent (algorithmic) tangent
        EFFG=EG*SYIELD/SMISES
        EFFG2=TWO*EFFG
        EFFG3=THREE/TWO*EFFG2
        EFFLAM=(EBULK3-EFFG2)/THREE
        EFFHRD=EG3*HARD/(EG3+HARD)-EFFG3
        DO K1=1,NTENS
          DO K2=1,NTENS
            DDSDDE(K2,K1)=ZERO
          END DO
        END DO
        DO K1=1,NDI
          DO K2=1,NDI
            DDSDDE(K2,K1)=EFFLAM
          END DO
          DDSDDE(K1,K1)=EFFG2+EFFLAM
        END DO
        DO K1=NDI+1,NTENS
          DDSDDE(K1,K1)=EFFG
        END DO
        DO K1=1,NTENS
          DO K2=1,NTENS
            DDSDDE(K2,K1)=DDSDDE(K2,K1)+EFFHRD*FLOW(K2)*FLOW(K1)
          END DO
        END DO
      END IF
      STATEV(1)=EQPLAS
      RETURN
      END
