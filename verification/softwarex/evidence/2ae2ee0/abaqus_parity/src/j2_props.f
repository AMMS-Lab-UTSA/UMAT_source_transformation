C ============================================================
C  Small-strain 3D J2 plasticity with linear isotropic hardening.
C  NTENS = 6 (Voigt engineering shear on off-diagonals).
C  Parameters (from PROPS):
C     PROPS(1) = E     Young's modulus
C     PROPS(2) = XNU   Poisson's ratio
C     PROPS(3) = SIGY0 Initial yield stress
C     PROPS(4) = H     Linear isotropic hardening modulus
C  State variables:
C     STATEV(1) = EQPLAS  accumulated equivalent plastic strain
C
C  Radial-return integration (Simo & Hughes ch. 3): computes the
C  elastic trial stress, tests f=q-sigma_y, and if positive updates
C  stress via s_new = s_trial * (1 - 3*mu*dgamma/q_trial), then
C  recovers dgamma = (q_trial - sigma_y)/(3*mu + H). The consistent
C  tangent is emitted for Abaqus.
C ============================================================
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
      PARAMETER (ZERO = 0.0D0, ONE = 1.0D0, TWO = 2.0D0,
     1           THREE = 3.0D0, ONE_HALF = 0.5D0,
     2           ONE_THIRD = 0.333333333333333333D0,
     3           TWO_THIRDS = 0.666666666666666667D0,
     4           THREE_HALVES = 1.5D0)
C
      DIMENSION STRESS_TRIAL(6), DEV_TRIAL(6)
      INTEGER I, J
C
C     Material parameters from PROPS.
      E     = PROPS(1)
      XNU   = PROPS(2)
      SIGY0 = PROPS(3)
      H     = PROPS(4)
      ELAM  = E * XNU / ((ONE + XNU) * (ONE - TWO * XNU))
      EMU   = E / (TWO * (ONE + XNU))
      TWOMU = TWO * EMU
C
C     Elastic trial stress (Voigt engineering shear).
      STRESS_TRIAL(1) = STRESS(1) + (ELAM + TWOMU) * DSTRAN(1) + ELAM * DSTRAN(2) + ELAM * DSTRAN(3)
      STRESS_TRIAL(2) = STRESS(2) + ELAM * DSTRAN(1) + (ELAM + TWOMU) * DSTRAN(2) + ELAM * DSTRAN(3)
      STRESS_TRIAL(3) = STRESS(3) + ELAM * DSTRAN(1) + ELAM * DSTRAN(2) + (ELAM + TWOMU) * DSTRAN(3)
      STRESS_TRIAL(4) = STRESS(4) + EMU * DSTRAN(4)
      STRESS_TRIAL(5) = STRESS(5) + EMU * DSTRAN(5)
      STRESS_TRIAL(6) = STRESS(6) + EMU * DSTRAN(6)
C
C     Trial pressure and deviator.
      PTRIAL = (STRESS_TRIAL(1) + STRESS_TRIAL(2) + STRESS_TRIAL(3)) * ONE_THIRD
      DEV_TRIAL(1) = STRESS_TRIAL(1) - PTRIAL
      DEV_TRIAL(2) = STRESS_TRIAL(2) - PTRIAL
      DEV_TRIAL(3) = STRESS_TRIAL(3) - PTRIAL
      DEV_TRIAL(4) = STRESS_TRIAL(4)
      DEV_TRIAL(5) = STRESS_TRIAL(5)
      DEV_TRIAL(6) = STRESS_TRIAL(6)
C
C     von Mises equivalent q = sqrt(3/2 sum s_ii^2 + 3 sum s_ij^2)
      Q_TRIAL = SQRT(THREE_HALVES * (DEV_TRIAL(1)*DEV_TRIAL(1)
     1                              + DEV_TRIAL(2)*DEV_TRIAL(2)
     2                              + DEV_TRIAL(3)*DEV_TRIAL(3))
     3          + THREE * (DEV_TRIAL(4)*DEV_TRIAL(4)
     4                   + DEV_TRIAL(5)*DEV_TRIAL(5)
     5                   + DEV_TRIAL(6)*DEV_TRIAL(6)))
C
      EQPLAS_N = STATEV(1)
      SIGMA_Y = SIGY0 + H * EQPLAS_N
      PHI = Q_TRIAL - SIGMA_Y
C
      IF (PHI .LE. ZERO) THEN
C        Elastic increment.
         DO I = 1, NTENS
            STRESS(I) = STRESS_TRIAL(I)
         END DO
      ELSE
C        Radial return.
         DGAMMA = PHI / (THREE * EMU + H)
         SCALE = THREE * EMU * DGAMMA / Q_TRIAL
         STRESS(1) = DEV_TRIAL(1) * (ONE - SCALE) + PTRIAL
         STRESS(2) = DEV_TRIAL(2) * (ONE - SCALE) + PTRIAL
         STRESS(3) = DEV_TRIAL(3) * (ONE - SCALE) + PTRIAL
         STRESS(4) = DEV_TRIAL(4) * (ONE - SCALE)
         STRESS(5) = DEV_TRIAL(5) * (ONE - SCALE)
         STRESS(6) = DEV_TRIAL(6) * (ONE - SCALE)
         STATEV(1) = EQPLAS_N + DGAMMA
      END IF
C
C     Consistent tangent — plain elastic form for now; the transformer
C     will not use this for parameter sensitivities.
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
