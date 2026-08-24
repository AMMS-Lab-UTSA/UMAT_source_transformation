C  ------------------------------------------------------------------------
C  SWEEP_DRUCKER_PRAGER  Linear (pressure-dependent) Drucker-Prager plasticity
C
C  Yield surface  f = q + BETA*p - k ,  with
C      p = -(S11+S22+S33)/3      (equivalent pressure, +ve in compression)
C      q = sqrt(3/2 s:s)         (von Mises equivalent, s = deviator)
C  PROPS(1)=E  PROPS(2)=nu  PROPS(3)=k (cohesion-like)  PROPS(4)=BETA (friction)
C  STATEV(1) = EQPLAS (accumulated plastic multiplier / eq. plastic strain)
C
C  Stress-driven predictor: incoming STRESS is previous-increment converged
C  stress; STRESS + Del:DSTRAN is the elastic predictor.  Associative flow on
C  the DP cone gives a CLOSED-FORM linear return (perfectly plastic, no
C  hardening):  f_new = f_trial - dlam*(3G + K*BETA^2) = 0, so
C      dlam = f_trial / (3G + K*BETA^2).
C  Deviator returns radially (scale = 1 - 3G*dlam/q_trial); the hydrostatic
C  part shifts by K*BETA*dlam.  Self-contained, no external CALLs; STRESS set
C  by inline assignments.  Voigt (11,22,33,12,13,23), engineering shear.
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
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
      INTEGER K1,K2
C
      EMOD=PROPS(1)
      ENU=PROPS(2)
      COHK=PROPS(3)
      BETA=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EBULK=EBULK3/THREE
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
      FLOOR=1.0D-8*1.0D-8
C     elastic stiffness (predictor operator + initialised tangent)
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
C     hydrostatic split:  SHYDRO = sigma_hydro = -p_trial
      SHYDRO=(STRESS(1)+STRESS(2)+STRESS(3))/THREE
      PTR=-SHYDRO
C     von Mises equivalent q of the predictor
      SMISES=(STRESS(1)-STRESS(2))**2+(STRESS(2)-STRESS(3))**2
     1      +(STRESS(3)-STRESS(1))**2
      DO K1=NDI+1,NTENS
        SMISES=SMISES+SIX*STRESS(K1)**2
      END DO
      SMISES=SQRT(SMISES/TWO+FLOOR)
C     Drucker-Prager yield residual of the predictor
      FTRIAL=SMISES+BETA*PTR-COHK
C
      IF (FTRIAL.GT.ZERO) THEN
C       closed-form associative linear-DP return
        DLAM=FTRIAL/(EG3+EBULK*BETA*BETA)
        SCALE=ONE-EG3*DLAM/SMISES
        SHYDNW=SHYDRO+EBULK*BETA*DLAM
        DO K1=1,NDI
          STRESS(K1)=(STRESS(K1)-SHYDRO)*SCALE+SHYDNW
        END DO
        DO K1=NDI+1,NTENS
          STRESS(K1)=STRESS(K1)*SCALE
        END DO
        EQPLAS=EQPLAS+DLAM
      END IF
      STATEV(1)=EQPLAS
      RETURN
      END
