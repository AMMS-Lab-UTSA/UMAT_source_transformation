C  ------------------------------------------------------------------------
C  M5  Thermally-activated (Kocks-type) von Mises viscoplasticity.
C
C  A single-crystal-flavoured flow rule with the six parameters used in the
C  residual-method crystal-plasticity study:
C     PROPS(1)=E     PROPS(2)=nu
C     PROPS(3)=TAU0  friction / flow resistance
C     PROPS(4)=DG    activation energy group  (DeltaG/kT, dimensionless)
C     PROPS(5)=PEXP  glide exponent p
C     PROPS(6)=QEXP  glide exponent q
C     PROPS(7)=GAM0  reference slip rate
C     PROPS(8)=HARD  hardening modulus H
C  STATEV(1) = equivalent plastic strain (EQPLAS).  NSTATV = 1.
C
C  Overstress return: gdot = GAM0*exp(-DG*[1-(smises/s)^p]^q), s=TAU0+H*EQPLAS,
C  with radial return smises = smises_tr - 3G*deqpl and consistency
C  deqpl = DTIME*gdot.  Newton on deqpl.  Voigt (11,22,33,12,13,23), eng. shear.
C  DDSDDE here is the elastic predictor; the OTI transform replaces it with the
C  exact algorithmic tangent d(STRESS)/d(DSTRAN).
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
      TAU0=PROPS(3)
      DG=PROPS(4)
      PEXP=PROPS(5)
      QEXP=PROPS(6)
      GAM0=PROPS(7)
      HARD=PROPS(8)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
C     elastic stiffness / predictor operator (also returned as DDSDDE)
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
C
      IF (SMISES.GT.1.D-12) THEN
C       flow direction (deviatoric unit, Mises-normalized)
        SHYDRO=(STRESS(1)+STRESS(2)+STRESS(3))/THREE
        DO K1=1,NDI
          FLOW(K1)=(STRESS(K1)-SHYDRO)/SMISES
        END DO
        DO K1=NDI+1,NTENS
          FLOW(K1)=STRESS(K1)/SMISES
        END DO
C       Newton on the equivalent plastic strain increment DEQPL
        DEQPL=ZERO
        DO KNEWT=1,60
          SBAR=SMISES-EG3*DEQPL
          SRES=TAU0+HARD*(EQPLAS+DEQPL)
          X=SBAR/SRES
          IF (X.LE.ZERO) X=1.D-8
          IF (X.GE.ONE) THEN
            GDOT=GAM0
            DGDOT=ZERO
          ELSE
            BR=ONE-X**PEXP
            R=BR**QEXP
            GDOT=GAM0*EXP(-DG*R)
            DXDD=(-EG3*SRES-SBAR*HARD)/(SRES*SRES)
            DBRDD=-PEXP*X**(PEXP-ONE)*DXDD
            DRDD=QEXP*BR**(QEXP-ONE)*DBRDD
            DGDOT=GDOT*(-DG)*DRDD
          END IF
          F=DEQPL-DTIME*GDOT
          DF=ONE-DTIME*DGDOT
          DEQPL=DEQPL-F/DF
          IF (DEQPL.LT.ZERO) DEQPL=ZERO
          IF (DEQPL.GT.0.999D0*SMISES/EG3) DEQPL=0.999D0*SMISES/EG3
        END DO
        SYIELD=SMISES-EG3*DEQPL
C       update stress (radial return) and state
        DO K1=1,NDI
          STRESS(K1)=FLOW(K1)*SYIELD+SHYDRO
        END DO
        DO K1=NDI+1,NTENS
          STRESS(K1)=FLOW(K1)*SYIELD
        END DO
        EQPLAS=EQPLAS+DEQPL
      END IF
      STATEV(1)=EQPLAS
      RETURN
      END
