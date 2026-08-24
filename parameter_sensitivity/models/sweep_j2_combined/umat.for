C  ------------------------------------------------------------------------
C  sweep_j2_combined  Small-strain von Mises (J2) plasticity with BOTH
C  linear ISOTROPIC and linear KINEMATIC (backstress) hardening.
C
C  PROPS(1)=E   PROPS(2)=nu   PROPS(3)=SIGY0 (initial yield)
C  PROPS(4)=HISO (isotropic hard. modulus)   PROPS(5)=HKIN (kinematic)
C  STATEV(1)   = EQPLAS (accumulated equivalent plastic strain)
C  STATEV(2:7) = ALPHA  (deviatoric backstress, tensor Voigt 11,22,33,12,13,23)
C
C  Stress-driven radial return on the RELATIVE stress eta = dev(S) - ALPHA.
C  Yield radius grows as SIGY0+HISO*EQPLAS (isotropic); the backstress moves as
C  ALPHA += HKIN*DGAMMA*FLOW (linear kinematic).  Closed-form plastic multiplier
C  DGAMMA=(ETMISES-SYIEL0)/(3G+HISO+HKIN).  Voigt (11,22,33,12,13,23),
C  engineering shear.  Self-contained: no ROTSIG / UHARD.  STATEV is fully
C  updated BEFORE the final STRESS assignment so the OTI extraction is clean.
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
      DIMENSION FLOW(6),ETA(6),ALPHA(6)
      INTEGER K1,K2
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0,
     1 OP5=1.5D0,TINY=1.0D-8*1.0D-8)
C
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HISO=PROPS(4)
      HKIN=PROPS(5)
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
      DO K1=1,6
        ALPHA(K1)=STATEV(K1+1)
      END DO
C     relative stress eta = dev(STRESS) - ALPHA and its Mises norm
      SHYDRO=(STRESS(1)+STRESS(2)+STRESS(3))/THREE
      DO K1=1,NDI
        ETA(K1)=STRESS(K1)-SHYDRO-ALPHA(K1)
      END DO
      DO K1=NDI+1,NTENS
        ETA(K1)=STRESS(K1)-ALPHA(K1)
      END DO
      ETMISES=OP5*(ETA(1)**2+ETA(2)**2+ETA(3)**2)
      DO K1=NDI+1,NTENS
        ETMISES=ETMISES+THREE*ETA(K1)**2
      END DO
      ETMISES=SQRT(ETMISES+TINY)
      SYIEL0=SIGY0+HISO*EQPLAS
C
      IF (ETMISES.GT.SYIEL0) THEN
C       actively yielding: mises-normalised flow direction from eta
        DO K1=1,NTENS
          FLOW(K1)=ETA(K1)/ETMISES
        END DO
C       closed-form return for combined linear hardening
        DEQPL=(ETMISES-SYIEL0)/(EG3+HISO+HKIN)
C       update history FIRST (clean OTI extraction before final STRESS line)
        STATEV(1)=EQPLAS+DEQPL
        DO K1=1,6
          STATEV(K1+1)=ALPHA(K1)+HKIN*DEQPL*FLOW(K1)
        END DO
C       consistent (algorithmic) tangent (informational; OTI re-derives via AD)
        SYIELD=SYIEL0+HISO*DEQPL
        EFFG=EG*SYIELD/ETMISES
        EFFG2=TWO*EFFG
        EFFG3=THREE/TWO*EFFG2
        EFFLAM=(EBULK3-EFFG2)/THREE
        EFFHRD=EG3*(HISO+HKIN)/(EG3+HISO+HKIN)-EFFG3
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
C       radial return: shrink the deviator along FLOW (final STRESS update)
        DO K1=1,NTENS
          STRESS(K1)=STRESS(K1)-EG3*DEQPL*FLOW(K1)
        END DO
      END IF
      RETURN
      END
