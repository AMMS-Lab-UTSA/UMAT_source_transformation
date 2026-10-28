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
      USE otim6n1, OTI_MODULE_DP => DP, OTI_E1 => E1, OTI_E2 => E2,
     1OTI_E3 => E3, OTI_E4 => E4, OTI_E5 => E5, OTI_E6 => E6
      USE oti_intrinsics
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
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: DEV_TRIAL_OTI(6)
      TYPE(ONUMM6N1) :: DGAMMA_OTI
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: EQPLAS_N_OTI
      TYPE(ONUMM6N1) :: PHI_OTI
      TYPE(ONUMM6N1) :: PTRIAL_OTI
      TYPE(ONUMM6N1) :: Q_TRIAL_OTI
      TYPE(ONUMM6N1) :: SCALE_OTI
      TYPE(ONUMM6N1) :: SIGMA_Y_OTI
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      TYPE(ONUMM6N1) :: STRESS_TRIAL_OTI(6)
      E     = PROPS(1)
      XNU   = PROPS(2)
      SIGY0 = PROPS(3)
      H     = PROPS(4)
      ELAM  = E * XNU / ((ONE + XNU) * (ONE - TWO * XNU))
      EMU   = E / (TWO * (ONE + XNU))
      TWOMU = TWO * EMU
C
C     Elastic trial stress (Voigt engineering shear).
C     OTIS seed initialization from GUI configuration
      DO OTI_HI = 1, 6
         DEV_TRIAL_OTI(OTI_HI) = 0.0D0
      END DO
      DGAMMA_OTI = 0.0D0
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      EQPLAS_N_OTI = 0.0D0
      PHI_OTI = 0.0D0
      PTRIAL_OTI = 0.0D0
      Q_TRIAL_OTI = 0.0D0
      SCALE_OTI = 0.0D0
      SIGMA_Y_OTI = 0.0D0
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 6
         STRESS_TRIAL_OTI(OTI_HI) = 0.0D0
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
      STRESS_TRIAL_OTI(1) = STRESS_OTI(1) + (ELAM + TWOMU) *
     1DSTRAN_OTI(1) + ELAM * DSTRAN_OTI(2) + ELAM * DSTRAN_OTI(3)
      STRESS_TRIAL_OTI(2) = STRESS_OTI(2) + ELAM * DSTRAN_OTI(1) +
     1(ELAM + TWOMU) * DSTRAN_OTI(2) + ELAM * DSTRAN_OTI(3)
      STRESS_TRIAL_OTI(3) = STRESS_OTI(3) + ELAM * DSTRAN_OTI(1) + ELAM
     1* DSTRAN_OTI(2) + (ELAM + TWOMU) * DSTRAN_OTI(3)
      STRESS_TRIAL_OTI(4) = STRESS_OTI(4) + EMU * DSTRAN_OTI(4)
      STRESS_TRIAL_OTI(5) = STRESS_OTI(5) + EMU * DSTRAN_OTI(5)
      STRESS_TRIAL_OTI(6) = STRESS_OTI(6) + EMU * DSTRAN_OTI(6)
C
C     Trial pressure and deviator.
      PTRIAL_OTI = (STRESS_TRIAL_OTI(1) + STRESS_TRIAL_OTI(2) +
     1STRESS_TRIAL_OTI(3)) * ONE_THIRD
      DEV_TRIAL_OTI(1) = STRESS_TRIAL_OTI(1) - PTRIAL_OTI
      DEV_TRIAL_OTI(2) = STRESS_TRIAL_OTI(2) - PTRIAL_OTI
      DEV_TRIAL_OTI(3) = STRESS_TRIAL_OTI(3) - PTRIAL_OTI
      DEV_TRIAL_OTI(4) = STRESS_TRIAL_OTI(4)
      DEV_TRIAL_OTI(5) = STRESS_TRIAL_OTI(5)
      DEV_TRIAL_OTI(6) = STRESS_TRIAL_OTI(6)
C
C     von Mises equivalent q = sqrt(3/2 sum s_ii^2 + 3 sum s_ij^2)
      Q_TRIAL_OTI = SQRT((((MAX(REAL(THREE_HALVES * (DEV_TRIAL_OTI(1)*
     1DEV_TRIAL_OTI(1)+ DEV_TRIAL_OTI(2)*DEV_TRIAL_OTI(2)+
     1DEV_TRIAL_OTI(3)*DEV_TRIAL_OTI(3))+ THREE * (DEV_TRIAL_OTI(4)*
     1DEV_TRIAL_OTI(4)+ DEV_TRIAL_OTI(5)*DEV_TRIAL_OTI(5)+
     1DEV_TRIAL_OTI(6)*DEV_TRIAL_OTI(6))), 1.0D-30)) -
     1REAL(THREE_HALVES * (DEV_TRIAL_OTI(1)*DEV_TRIAL_OTI(1)+
     1DEV_TRIAL_OTI(2)*DEV_TRIAL_OTI(2)+ DEV_TRIAL_OTI(3)*
     1DEV_TRIAL_OTI(3))+ THREE * (DEV_TRIAL_OTI(4)*DEV_TRIAL_OTI(4)+
     1DEV_TRIAL_OTI(5)*DEV_TRIAL_OTI(5)+ DEV_TRIAL_OTI(6)*
     1DEV_TRIAL_OTI(6)))) + (THREE_HALVES * (DEV_TRIAL_OTI(1)*
     1DEV_TRIAL_OTI(1)+ DEV_TRIAL_OTI(2)*DEV_TRIAL_OTI(2)+
     1DEV_TRIAL_OTI(3)*DEV_TRIAL_OTI(3))+ THREE * (DEV_TRIAL_OTI(4)*
     1DEV_TRIAL_OTI(4)+ DEV_TRIAL_OTI(5)*DEV_TRIAL_OTI(5)+
     1DEV_TRIAL_OTI(6)*DEV_TRIAL_OTI(6)))))
C    1                              + DEV_TRIAL(2)*DEV_TRIAL(2)
C    2                              + DEV_TRIAL(3)*DEV_TRIAL(3))
C     OTIS-SKIP: 3          + THREE * (DEV_TRIAL(4)*DEV_TRIAL(4)
C     OTIS-SKIP: 4                   + DEV_TRIAL(5)*DEV_TRIAL(5)
C     OTIS-SKIP: 5                   + DEV_TRIAL(6)*DEV_TRIAL(6)))
C
      EQPLAS_N_OTI = STATEV_OTI(1)
      SIGMA_Y_OTI = SIGY0 + H * EQPLAS_N_OTI
      PHI_OTI = Q_TRIAL_OTI - SIGMA_Y_OTI
C
      IF (REAL(PHI_OTI) .LE. ZERO) THEN
C        Elastic increment.
         DO I = 1, NTENS
            STRESS_OTI(I) = STRESS_TRIAL_OTI(I)
         END DO
      ELSE
C        Radial return.
         DGAMMA_OTI = PHI_OTI / (THREE * EMU + H)
         SCALE_OTI = THREE * EMU * DGAMMA_OTI / Q_TRIAL_OTI
      STRESS_OTI(1) = DEV_TRIAL_OTI(1) * (ONE - SCALE_OTI) + PTRIAL_OTI
      STRESS_OTI(2) = DEV_TRIAL_OTI(2) * (ONE - SCALE_OTI) + PTRIAL_OTI
      STRESS_OTI(3) = DEV_TRIAL_OTI(3) * (ONE - SCALE_OTI) + PTRIAL_OTI
         STRESS_OTI(4) = DEV_TRIAL_OTI(4) * (ONE - SCALE_OTI)
         STRESS_OTI(5) = DEV_TRIAL_OTI(5) * (ONE - SCALE_OTI)
         STRESS_OTI(6) = DEV_TRIAL_OTI(6) * (ONE - SCALE_OTI)
         STATEV_OTI(1) = EQPLAS_N_OTI + DGAMMA_OTI
      END IF
C
C     Consistent tangent — plain elastic form for now; the transformer
C     will not use this for parameter sensitivities.
      DO I = 1, NTENS
         DO J = 1, NTENS
C     OTIS-SKIP: DDSDDE(I, J) = ZERO
         END DO
      END DO
      DO I = 1, 3
         DO J = 1, 3
C     OTIS-SKIP: DDSDDE(I, J) = ELAM
         END DO
C     OTIS-SKIP: DDSDDE(I, I) = ELAM + TWOMU
      END DO
C     OTIS-SKIP: DDSDDE(4, 4) = EMU
C     OTIS-SKIP: DDSDDE(5, 5) = EMU
C     OTIS-SKIP: DDSDDE(6, 6) = EMU
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
C
      RETURN
      END
