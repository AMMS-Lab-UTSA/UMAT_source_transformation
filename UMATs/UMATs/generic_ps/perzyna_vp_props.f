C ============================================================
C  Small-strain 3D Perzyna-type viscoplastic UMAT with helper
C  subroutines (to exercise the transformer's helper-closure
C  lifting on a genuinely different code structure from j2_props.f).
C  NTENS = 6.
C  Parameters (from PROPS):
C     PROPS(1) = E     Young's modulus
C     PROPS(2) = XNU   Poisson's ratio
C     PROPS(3) = SIGY0 Initial yield stress
C     PROPS(4) = ETA   Viscosity coefficient (time-scale)
C     PROPS(5) = MEXP  Rate exponent (>= 1)
C  State variables:
C     STATEV(1) = EQPLAS  accumulated equivalent plastic strain
C  Update: explicit Perzyna rate law
C     dEQPLAS = (max(q - sigy0, 0) / (ETA * sigy0))**MEXP * DTIME
C ============================================================
      SUBROUTINE KELASTIC_TRIAL(STRESS_TRIAL, STRESS, DSTRAN, ELAM, TWOMU, EMU, NTENS)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS_TRIAL(NTENS), STRESS(NTENS), DSTRAN(NTENS)
      STRESS_TRIAL(1) = STRESS(1) + (ELAM + TWOMU) * DSTRAN(1) + ELAM * DSTRAN(2) + ELAM * DSTRAN(3)
      STRESS_TRIAL(2) = STRESS(2) + ELAM * DSTRAN(1) + (ELAM + TWOMU) * DSTRAN(2) + ELAM * DSTRAN(3)
      STRESS_TRIAL(3) = STRESS(3) + ELAM * DSTRAN(1) + ELAM * DSTRAN(2) + (ELAM + TWOMU) * DSTRAN(3)
      STRESS_TRIAL(4) = STRESS(4) + EMU * DSTRAN(4)
      STRESS_TRIAL(5) = STRESS(5) + EMU * DSTRAN(5)
      STRESS_TRIAL(6) = STRESS(6) + EMU * DSTRAN(6)
      RETURN
      END
C
      SUBROUTINE KDEVIATOR(DEV, STRESS_TRIAL, PTRIAL)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION DEV(6), STRESS_TRIAL(6)
      DEV(1) = STRESS_TRIAL(1) - PTRIAL
      DEV(2) = STRESS_TRIAL(2) - PTRIAL
      DEV(3) = STRESS_TRIAL(3) - PTRIAL
      DEV(4) = STRESS_TRIAL(4)
      DEV(5) = STRESS_TRIAL(5)
      DEV(6) = STRESS_TRIAL(6)
      RETURN
      END
C
      SUBROUTINE KMISES(Q, DEV)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION DEV(6)
      Q = SQRT(1.5D0 * (DEV(1)*DEV(1) + DEV(2)*DEV(2) + DEV(3)*DEV(3))
     1        + 3.0D0 * (DEV(4)*DEV(4) + DEV(5)*DEV(5) + DEV(6)*DEV(6)))
      RETURN
      END
C
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
C
      INCLUDE 'ABA_PARAM.INC'
C
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
C
      PARAMETER (ZERO = 0.0D0, ONE = 1.0D0, TWO = 2.0D0, THREE = 3.0D0,
     1           ONE_THIRD = 0.333333333333333333D0)
C
      DIMENSION STRESS_TRIAL(6), DEV(6)
      INTEGER I, J
      REAL*8  MEXP
C
      E     = PROPS(1)
      XNU   = PROPS(2)
      SIGY0 = PROPS(3)
      ETA   = PROPS(4)
      MEXP  = PROPS(5)
      ELAM  = E * XNU / ((ONE + XNU) * (ONE - TWO * XNU))
      EMU   = E / (TWO * (ONE + XNU))
      TWOMU = TWO * EMU
C
      CALL KELASTIC_TRIAL(STRESS_TRIAL, STRESS, DSTRAN, ELAM, TWOMU, EMU, NTENS)
      PTRIAL = (STRESS_TRIAL(1) + STRESS_TRIAL(2) + STRESS_TRIAL(3)) * ONE_THIRD
      CALL KDEVIATOR(DEV, STRESS_TRIAL, PTRIAL)
      CALL KMISES(Q, DEV)
C
      OVERSTRESS = Q - SIGY0
      IF (OVERSTRESS .LE. ZERO) THEN
         DO I = 1, NTENS
            STRESS(I) = STRESS_TRIAL(I)
         END DO
      ELSE
C        Perzyna: gamma_dot = (overstress / (ETA * SIGY0))**MEXP
         RATE = (OVERSTRESS / (ETA * SIGY0)) ** MEXP
         DGAMMA = RATE * DTIME
         SCALE = THREE * EMU * DGAMMA / Q
         STRESS(1) = DEV(1) * (ONE - SCALE) + PTRIAL
         STRESS(2) = DEV(2) * (ONE - SCALE) + PTRIAL
         STRESS(3) = DEV(3) * (ONE - SCALE) + PTRIAL
         STRESS(4) = DEV(4) * (ONE - SCALE)
         STRESS(5) = DEV(5) * (ONE - SCALE)
         STRESS(6) = DEV(6) * (ONE - SCALE)
         STATEV(1) = STATEV(1) + DGAMMA
      END IF
C
C     Elastic tangent (approximation).
      DO I = 1, NTENS
         DO J = 1, NTENS
            DDSDDE(I, J) = ZERO
         END DO
      END DO
      DO I = 1, 3
         DO J = 1, 3
            DDSDDE(I, J) = ELAM
         END DO
         DDSDDE(I, I) = ELAM + TWOMU
      END DO
      DDSDDE(4, 4) = EMU
      DDSDDE(5, 5) = EMU
      DDSDDE(6, 6) = EMU
C
      RETURN
      END
