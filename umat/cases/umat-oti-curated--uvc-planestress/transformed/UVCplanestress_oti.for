      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1RPL,DDSDDT,DRPLDE,DRPLDT,
     2STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,JSTEP,KINC)
      USE otim3n1, OTI_MODULE_DP => DP, OTI_E1 => E1, OTI_E2 => E2,
     1OTI_E3 => E3
      USE oti_intrinsics
      ! Note that IMPLICIT definition is active
      INCLUDE 'ABA_PARAM.INC'
C
      CHARACTER*80 CMNAME
C
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3),
     4JSTEP(4)
C
C
      ! Subroutine control
      INTEGER :: i, j, n_backstresses, it_num, converged
      ! Material properties
      REAL(8) :: elastic_modulus, Q_inf, b, D_inf, a,
     1shear_modulus, bulk_modulus, poisson_ratio, mu2
      ! Used for intermediate calculations
      REAL(8) :: yield_stress, ep_eq, ep_eq_init,
     1hard_iso_Q, hard_iso_D, hard_iso_total, isotropic_modulus,
     2yield_function, e_k, beta, gamma_denom, denom,
     3yield_condition, f_bar, f_bar_2, beta_prime, consist_param
      ! Tangent modulus
      REAL(8), DIMENSION(3) :: n_tilde, n_hat, H_prime, H_tilde
      REAL(8), DIMENSION(3,3) :: H_out_n, n_out_n, A_mat,
     1Xi_tilde, Xi_tilde_A, C_ep
      REAL(8) :: theta_1, theta_2
      ! Backstress arrays
      REAL(8), DIMENSION(:, :), ALLOCATABLE :: alpha_k, alpha_k_i
      REAL(8), DIMENSION(:), ALLOCATABLE :: C_k, gamma_k
      ! Tensors
      REAL(8), DIMENSION(3) :: strain_plastic, dstran_p,
     1alpha, gamma_diag, alpha_tilde,alpha_tilde_prime,
     2strain, eta, eta_tilde, eta_trial, stress_trial,
     3gamma_prime_diag, stress_rel
      REAL(8), DIMENSION(3, 3) :: Q_mat, Q_mat_t, Lambda_P, Lambda_C,
     1elastic_matrix, P_mat, compliance_matrix, ID3
      ! Parameters
      INTEGER :: N_BASIC_PROPS, TERM_PER_BACK, MAX_ITERATIONS,
     1I_ALPHA
      REAL(8) :: TOL, ONE, TWO, THREE, ZERO, SQRT23, SIX
      PARAMETER(TOL=1.0D-8,
     1N_BASIC_PROPS=7, TERM_PER_BACK=2, MAX_ITERATIONS=1000,
     2ONE=1.0D0, TWO=2.0D0, THREE=3.0D0, ZERO=0.D0, SIX=6.0D0,
     3SQRT23=SQRT(2.0D0/3.0D0), I_ALPHA=4)
C ----------------------------------------------------------------------C
C
      ! Initialize
C
C ----------------------------------------------------------------------C
      ! Get the number of backstresses
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM3N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM3N1) :: ALPHA_OTI(3)
      TYPE(ONUMM3N1), ALLOCATABLE :: ALPHA_K_OTI(:, :)
      TYPE(ONUMM3N1) :: ALPHA_TILDE_OTI(3)
      TYPE(ONUMM3N1) :: ALPHA_TILDE_PRIME_OTI(3)
      TYPE(ONUMM3N1) :: BETA_OTI
      TYPE(ONUMM3N1) :: BETA_PRIME_OTI
      TYPE(ONUMM3N1) :: CONSIST_PARAM_OTI
      TYPE(ONUMM3N1), ALLOCATABLE :: C_K_OTI(:)
      TYPE(ONUMM3N1) :: DENOM_OTI
      TYPE(ONUMM3N1) :: DROT_OTI(3, 3)
      TYPE(ONUMM3N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM3N1) :: DSTRAN_P_OTI(3)
      TYPE(ONUMM3N1) :: ELASTIC_MATRIX_OTI(3, 3)
      TYPE(ONUMM3N1) :: EP_EQ_OTI
      TYPE(ONUMM3N1) :: EP_EQ_INIT_OTI
      TYPE(ONUMM3N1) :: ETA_OTI(3)
      TYPE(ONUMM3N1) :: ETA_TILDE_OTI(3)
      TYPE(ONUMM3N1) :: ETA_TRIAL_OTI(3)
      TYPE(ONUMM3N1) :: E_K_OTI
      TYPE(ONUMM3N1) :: F_BAR_OTI
      TYPE(ONUMM3N1) :: F_BAR_2_OTI
      TYPE(ONUMM3N1) :: GAMMA_DENOM_OTI
      TYPE(ONUMM3N1) :: GAMMA_DIAG_OTI(3)
      TYPE(ONUMM3N1), ALLOCATABLE :: GAMMA_K_OTI(:)
      TYPE(ONUMM3N1) :: GAMMA_PRIME_DIAG_OTI(3)
      TYPE(ONUMM3N1) :: HARD_ISO_D_OTI
      TYPE(ONUMM3N1) :: HARD_ISO_Q_OTI
      TYPE(ONUMM3N1) :: HARD_ISO_TOTAL_OTI
      TYPE(ONUMM3N1) :: ISOTROPIC_MODULUS_OTI
      TYPE(ONUMM3N1) :: P_MAT_OTI(3, 3)
      TYPE(ONUMM3N1) :: Q_MAT_OTI(3, 3)
      TYPE(ONUMM3N1) :: Q_MAT_T_OTI(3, 3)
      TYPE(ONUMM3N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM3N1) :: STRAIN_OTI(3)
      TYPE(ONUMM3N1) :: STRAIN_PLASTIC_OTI(3)
      TYPE(ONUMM3N1) :: STRESS_OTI(NTENS)
      TYPE(ONUMM3N1) :: STRESS_REL_OTI(3)
      TYPE(ONUMM3N1) :: STRESS_TRIAL_OTI(3)
      TYPE(ONUMM3N1) :: YIELD_CONDITION_OTI
C     OTIS seed initialization from GUI configuration
C     Read before assignment in the original: started at zero here (transform report)
      F_BAR_OTI = 0.0D0
      BETA_OTI = 0.0D0
      ISOTROPIC_MODULUS_OTI = 0.0D0
      DO OTI_HI = 1, 3
         ALPHA_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         ALPHA_TILDE_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         ALPHA_TILDE_PRIME_OTI(OTI_HI) = 0.0D0
      END DO
      BETA_OTI = 0.0D0
      BETA_PRIME_OTI = 0.0D0
      CONSIST_PARAM_OTI = 0.0D0
      DENOM_OTI = 0.0D0
      DO OTI_HI = 1, 3
         DO OTI_HJ = 1, 3
            DROT_OTI(OTI_HI,OTI_HJ) = 0.0D0
         END DO
      END DO
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         DSTRAN_P_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         DO OTI_HJ = 1, 3
            ELASTIC_MATRIX_OTI(OTI_HI,OTI_HJ) = 0.0D0
         END DO
      END DO
      EP_EQ_OTI = 0.0D0
      EP_EQ_INIT_OTI = 0.0D0
      DO OTI_HI = 1, 3
         ETA_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         ETA_TILDE_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         ETA_TRIAL_OTI(OTI_HI) = 0.0D0
      END DO
      E_K_OTI = 0.0D0
      F_BAR_OTI = 0.0D0
      F_BAR_2_OTI = 0.0D0
      GAMMA_DENOM_OTI = 0.0D0
      DO OTI_HI = 1, 3
         GAMMA_DIAG_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         GAMMA_PRIME_DIAG_OTI(OTI_HI) = 0.0D0
      END DO
      HARD_ISO_D_OTI = 0.0D0
      HARD_ISO_Q_OTI = 0.0D0
      HARD_ISO_TOTAL_OTI = 0.0D0
      ISOTROPIC_MODULUS_OTI = 0.0D0
      DO OTI_HI = 1, 3
         DO OTI_HJ = 1, 3
            P_MAT_OTI(OTI_HI,OTI_HJ) = 0.0D0
         END DO
      END DO
      DO OTI_HI = 1, 3
         DO OTI_HJ = 1, 3
            Q_MAT_OTI(OTI_HI,OTI_HJ) = 0.0D0
         END DO
      END DO
      DO OTI_HI = 1, 3
         DO OTI_HJ = 1, 3
            Q_MAT_T_OTI(OTI_HI,OTI_HJ) = 0.0D0
         END DO
      END DO
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         STRAIN_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         STRAIN_PLASTIC_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         STRESS_REL_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 3
         STRESS_TRIAL_OTI(OTI_HI) = 0.0D0
      END DO
      YIELD_CONDITION_OTI = 0.0D0
      DO OTI_I = 1, NTENS
         DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)
      END DO
      DO OTI_I = 1, NTENS
         STRESS_OTI(OTI_I) = STRESS(OTI_I)
      END DO
      DO OTI_I = 1, NSTATV
         STATEV_OTI(OTI_I) = STATEV(OTI_I)
      END DO
      DO OTI_HI = 1, 3
         DO OTI_HJ = 1, 3
            DROT_OTI(OTI_HI,OTI_HJ) = DROT(OTI_HI,OTI_HJ)
         END DO
      END DO
      DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1
      DSTRAN_OTI(2) = DSTRAN_OTI(2) + OTI_E2
      DSTRAN_OTI(3) = DSTRAN_OTI(3) + OTI_E3
      n_backstresses = (nprops - N_BASIC_PROPS) / TERM_PER_BACK
      IF (n_backstresses .EQ. 0) THEN
      PRINT *, "No backstresses defined, exiting!"
        CALL XIT  ! Exit from analysis command in Abaqus
      END IF
C
      ! Allocate the backstress related arrays
      ALLOCATE(C_k(n_backstresses))
C     OTIS shadow allocation mirroring the source's ALLOCATE of C_K
      IF (ALLOCATED(C_K_OTI)) DEALLOCATE(C_K_OTI)
      ALLOCATE(C_K_OTI(LBOUND(C_K,1):UBOUND(C_K,1)))
      DO OTI_HI = LBOUND(C_K_OTI,1), UBOUND(C_K_OTI,1)
         C_K_OTI(OTI_HI) = 0.0D0
      END DO
      ALLOCATE(gamma_k(n_backstresses))
C     OTIS shadow allocation mirroring the source's ALLOCATE of GAMMA_K
      IF (ALLOCATED(GAMMA_K_OTI)) DEALLOCATE(GAMMA_K_OTI)
      ALLOCATE(GAMMA_K_OTI(LBOUND(GAMMA_K,1):UBOUND(GAMMA_K,1)))
      DO OTI_HI = LBOUND(GAMMA_K_OTI,1), UBOUND(GAMMA_K_OTI,1)
         GAMMA_K_OTI(OTI_HI) = 0.0D0
      END DO
      ALLOCATE(alpha_k(n_backstresses, ntens))
C     OTIS shadow allocation mirroring the source's ALLOCATE of ALPHA_K
      IF (ALLOCATED(ALPHA_K_OTI)) DEALLOCATE(ALPHA_K_OTI)
      ALLOCATE(ALPHA_K_OTI(LBOUND(ALPHA_K,1):UBOUND(ALPHA_K,1),
     1LBOUND(ALPHA_K,2):UBOUND(ALPHA_K,2)))
      DO OTI_HI = LBOUND(ALPHA_K_OTI,1), UBOUND(ALPHA_K_OTI,1)
         DO OTI_HJ = LBOUND(ALPHA_K_OTI,2), UBOUND(ALPHA_K_OTI,2)
            ALPHA_K_OTI(OTI_HI,OTI_HJ) = 0.0D0
         END DO
      END DO
      ALLOCATE(alpha_k_i(n_backstresses, ntens))
C
      ! Material Properties
      elastic_modulus = props(1)
      poisson_ratio = props(2)
      yield_stress = props(3)
      q_inf = props(4)
      b = props(5)
      d_inf = props(6)
      a = props(7)
      DO i = 1, n_backstresses  ! First backstress starts at index = 8
        C_K_OTI(i) = props((N_BASIC_PROPS - 1) + 2 * i)
        GAMMA_K_OTI(i) = props(N_BASIC_PROPS + 2 * i)
      END DO
      shear_modulus = elastic_modulus / (TWO * (ONE + poisson_ratio))
      mu2 = TWO * shear_modulus
C
      ! Elastic matrix (defined in column major)
      ELASTIC_MATRIX_OTI = RESHAPE((/ ONE, poisson_ratio, ZERO,
     1poisson_ratio, ONE, ZERO,ZERO, ZERO, (ONE-poisson_ratio) / TWO /),
     1SHAPE(ELASTIC_MATRIX_OTI))
C     OTIS-SKIP: 1poisson_ratio, ONE, ZERO,
C     OTIS-SKIP: 2ZERO, ZERO, (ONE-poisson_ratio) / TWO /),
C     OTIS-SKIP: 3SHAPE(elastic_matrix))
      ELASTIC_MATRIX_OTI = elastic_modulus / (ONE - poisson_ratio ** 2)
     1*ELASTIC_MATRIX_OTI
C     OTIS-SKIP: 1elastic_matrix
      ! Compliance matrix
C     compliance_matrix = RESHAPE((/ ONE, -poisson_ratio, ZERO,
C     OTIS-SKIP: 1-poisson_ratio, ONE, ZERO,
C    2ZERO, ZERO, TWO*(ONE + poisson_ratio)/), SHAPE(compliance_matrix))
C     compliance_matrix = ONE/elastic_modulus * compliance_matrix
C
      GAMMA_DIAG_OTI(:) = ZERO
      Q_MAT_OTI = RESHAPE((/ ONE, ONE, ZERO, -ONE, ONE, ZERO,ZERO, ZERO,
     1SQRT(TWO) /), SHAPE(Q_MAT_OTI))
C     OTIS-SKIP: 1ZERO, ZERO, SQRT(TWO) /), SHAPE(Q_mat))
      Q_MAT_OTI = ONE / SQRT(TWO) * Q_MAT_OTI
      Q_MAT_T_OTI = TRANSPOSE(Q_MAT_OTI)
C
      P_MAT_OTI = RESHAPE((/ TWO, -ONE, ZERO, -ONE, TWO, ZERO,ZERO,
     1ZERO, SIX /), SHAPE(P_MAT_OTI))
C     OTIS-SKIP: 1ZERO, ZERO, SIX /), SHAPE(P_mat))
      P_MAT_OTI = ONE / THREE * P_MAT_OTI
C
      Lambda_P(:, :) = ZERO
      Lambda_P(1, 1) = ONE/THREE
      Lambda_P(2, 2) = ONE
      Lambda_P(3, 3) = TWO
C
      Lambda_C(:, :) = ZERO
      Lambda_C(1, 1) = elastic_modulus / (ONE - poisson_ratio)
      Lambda_C(2, 2) = mu2
      Lambda_C(3, 3) = shear_modulus
C
      ! Read state variables
      EP_EQ_OTI = STATEV_OTI(1)
      EP_EQ_INIT_OTI = STATEV_OTI(1)
      CALL ROTSIG_OTI(STATEV_OTI(2), DROT_OTI, STRAIN_PLASTIC_OTI, 2,
     1ndi, nshr)
      ALPHA_OTI(:) = ZERO
      DO i = 1, n_backstresses
        DO j = 1, ntens
      CALL ROTSIG_OTI(STATEV_OTI(I_ALPHA+1 + (i-1) * ntens), DROT_OTI,
     1ALPHA_K_OTI(i, :), 1, ndi, nshr)
C     OTIS-SKIP: 1  alpha_k(i, :), 1, ndi, nshr)
        END DO
        ALPHA_OTI = ALPHA_OTI + ALPHA_K_OTI(i, :)
      END DO
C     OTIS-SKIP: alpha_k_i = alpha_k
C
      ID3(:, :) = ZERO
      DO i = 1, NTENS
        ID3(i, i) = ONE
      END DO
C ----------------------------------------------------------------------C
C
      ! Elastic trial step
C
C ----------------------------------------------------------------------C
      ! Don't include e33, and calculate it later
      STRAIN_OTI = stran + DSTRAN_OTI
      STRESS_TRIAL_OTI = STRESS_OTI + MATMUL(ELASTIC_MATRIX_OTI,
     1DSTRAN_OTI)
      !stress_trial = MATMUL(elastic_matrix, strain - strain_plastic)
C
      HARD_ISO_Q_OTI = q_inf * (ONE - EXP(-b * EP_EQ_OTI))
      HARD_ISO_D_OTI = d_inf * (ONE - EXP(-a * EP_EQ_OTI))
      HARD_ISO_TOTAL_OTI = yield_stress + HARD_ISO_Q_OTI -
     1HARD_ISO_D_OTI
C
      ETA_TRIAL_OTI = MATMUL(Q_MAT_T_OTI, STRESS_TRIAL_OTI - ALPHA_OTI)
      ETA_OTI = ETA_TRIAL_OTI
C
      F_BAR_2_OTI = ZERO
      DO i = 1, ntens
      F_BAR_2_OTI = F_BAR_2_OTI + ETA_TRIAL_OTI(i)**2.0D0 * Lambda_P(i,
     1i)
      END DO
      YIELD_CONDITION_OTI = ONE/TWO*F_BAR_2_OTI - ONE/THREE*
     1HARD_ISO_TOTAL_OTI**2
C
      IF (REAL(YIELD_CONDITION_OTI) .LT. TOL) THEN
        converged = 1
      ELSE
        converged = 0
      END IF
C ----------------------------------------------------------------------C
C
      ! Return mapping in plane-stress subspace if plastic loading
C
C ----------------------------------------------------------------------C
      ! Calculate the consitency parameter
      it_num = 0
      CONSIST_PARAM_OTI = ZERO
      DO WHILE ((converged .EQ. 0) .AND. (it_num .LT. MAX_ITERATIONS))
        it_num = it_num + 1
C
        ! Calculate the isotropic hardening parameters
        HARD_ISO_Q_OTI = q_inf * (ONE - EXP(-b * EP_EQ_OTI))
        HARD_ISO_D_OTI = d_inf * (ONE - EXP(-a * EP_EQ_OTI))
      HARD_ISO_TOTAL_OTI = yield_stress + HARD_ISO_Q_OTI -
     1HARD_ISO_D_OTI
      ISOTROPIC_MODULUS_OTI = b*(q_inf-HARD_ISO_Q_OTI) - a*(d_inf-
     1HARD_ISO_D_OTI)
C
        ! Calculate the kinematic hardening related parameters
        BETA_OTI = ZERO
        ALPHA_TILDE_OTI(:) = ZERO
        DO i = 1, n_backstresses
          E_K_OTI = EXP(-GAMMA_K_OTI(i) * (EP_EQ_OTI - EP_EQ_INIT_OTI))
      BETA_OTI = BETA_OTI + C_K_OTI(i) / GAMMA_K_OTI(i) * (ONE -
     1E_K_OTI)
          DO j = 1, ntens
      ALPHA_TILDE_OTI(j) = ALPHA_TILDE_OTI(j) + ALPHA_K_OTI(i, j) *
     1E_K_OTI
          END DO
        END DO
        ALPHA_TILDE_OTI = ALPHA_OTI - ALPHA_TILDE_OTI
        BETA_OTI = ONE + BETA_OTI / HARD_ISO_TOTAL_OTI
C        
        ! Update the relative stress and eta
        GAMMA_DENOM_OTI = BETA_OTI + mu2 * CONSIST_PARAM_OTI
      GAMMA_DIAG_OTI(1) = ONE / (BETA_OTI+ CONSIST_PARAM_OTI*
     1elastic_modulus / (THREE*(ONE - poisson_ratio)))
C    1  + consist_param*elastic_modulus / (THREE*(ONE - poisson_ratio)))
        GAMMA_DIAG_OTI(2) = ONE / GAMMA_DENOM_OTI
        GAMMA_DIAG_OTI(3) = ONE / GAMMA_DENOM_OTI
      ETA_TILDE_OTI = ETA_TRIAL_OTI + MATMUL(Q_MAT_T_OTI,
     1ALPHA_TILDE_OTI)
        ETA_OTI = GAMMA_DIAG_OTI * ETA_TILDE_OTI
C
        ! Calculate the norm of the relative stress
      F_BAR_2_OTI = ONE/THREE * ETA_OTI(1)**2 + ETA_OTI(2)**2 + TWO *
     1ETA_OTI(3)**2
      F_BAR_OTI = SQRT((((MAX(REAL(F_BAR_2_OTI), 1.0D-30)) -
     1REAL(F_BAR_2_OTI)) + (F_BAR_2_OTI)))
C
        BETA_PRIME_OTI = ZERO
        ALPHA_TILDE_PRIME_OTI(:) = ZERO
        DO i = 1, n_backstresses
          E_K_OTI = EXP(-GAMMA_K_OTI(i) * (EP_EQ_OTI - EP_EQ_INIT_OTI))
      BETA_PRIME_OTI = BETA_PRIME_OTI- C_K_OTI(i) *
     1ISOTROPIC_MODULUS_OTI/ (GAMMA_K_OTI(i) * HARD_ISO_TOTAL_OTI**2) *
     1(ONE - E_K_OTI)+ C_K_OTI(i) * E_K_OTI / HARD_ISO_TOTAL_OTI
C     OTIS-SKIP: 1    - C_k(i) * isotropic_modulus
C     OTIS-SKIP: 2    / (gamma_k(i) * hard_iso_total**2) * (ONE - e_k)
C     OTIS-SKIP: 3    + C_k(i) * e_k / hard_iso_total
          DO j = 1, ntens
      ALPHA_TILDE_PRIME_OTI(j) = ALPHA_TILDE_PRIME_OTI(j)+
     1GAMMA_K_OTI(i) * E_K_OTI * ALPHA_K_OTI(i, j)
C     OTIS-SKIP: 1      + gamma_k(i) * e_k * alpha_k(i, j)
          END DO
        END DO
        BETA_PRIME_OTI = SQRT23 * F_BAR_OTI * BETA_PRIME_OTI
      ALPHA_TILDE_PRIME_OTI = SQRT23 * F_BAR_OTI * ALPHA_TILDE_PRIME_OTI
        DO i = 1, ntens
      GAMMA_PRIME_DIAG_OTI(i) = -GAMMA_DIAG_OTI(i) ** 2.0D0*
     1(BETA_PRIME_OTI + Lambda_P(i, i) * Lambda_C(i, i))
C     OTIS-SKIP: 1    * (beta_prime + Lambda_P(i, i) * Lambda_C(i, i))
        END DO

      YIELD_CONDITION_OTI = ONE/TWO*F_BAR_2_OTI - ONE/THREE*
     1HARD_ISO_TOTAL_OTI**2
      DENOM_OTI = DOT_PRODUCT( MATMUL(Lambda_P, ETA_OTI),
     1GAMMA_PRIME_DIAG_OTI * ETA_TILDE_OTI+ GAMMA_DIAG_OTI *
     1MATMUL(Q_MAT_T_OTI, ALPHA_TILDE_PRIME_OTI) )- SQRT23*TWO/THREE *
     1HARD_ISO_TOTAL_OTI * ISOTROPIC_MODULUS_OTI * F_BAR_OTI
C     OTIS-SKIP: 1  gamma_prime_diag * eta_tilde
C     OTIS-SKIP: 2  + gamma_diag * MATMUL(Q_mat_t, alpha_tilde_prime) )
C    3  - SQRT23*TWO/THREE * hard_iso_total * isotropic_modulus * f_bar
C
      CONSIST_PARAM_OTI = CONSIST_PARAM_OTI - YIELD_CONDITION_OTI /
     1DENOM_OTI
      EP_EQ_OTI = EP_EQ_INIT_OTI + SQRT23 * CONSIST_PARAM_OTI *
     1F_BAR_OTI
C
        IF (ABS(REAL(YIELD_CONDITION_OTI)) .LT. TOL) THEN
          converged = 1
        END IF
      END DO
C ----------------------------------------------------------------------C
C
      ! Update variables
C
C ----------------------------------------------------------------------C
      IF (it_num .EQ. 0) THEN  ! Elastic loading
        STRESS_OTI = STRESS_TRIAL_OTI
C     OTIS-SKIP: ddsdde = elastic_matrix
      ELSE  ! Plastic loading
      ETA_TILDE_OTI = ETA_TRIAL_OTI + MATMUL(Q_MAT_T_OTI,
     1ALPHA_TILDE_OTI)
        ETA_OTI = GAMMA_DIAG_OTI * ETA_TILDE_OTI
        STRESS_REL_OTI = MATMUL(Q_MAT_OTI, ETA_OTI)
C
        HARD_ISO_Q_OTI = q_inf * (ONE - EXP(-b * EP_EQ_OTI))
        HARD_ISO_D_OTI = d_inf * (ONE - EXP(-a * EP_EQ_OTI))
      HARD_ISO_TOTAL_OTI = yield_stress + HARD_ISO_Q_OTI -
     1HARD_ISO_D_OTI
        DO i = 1, n_backstresses
          E_K_OTI = EXP(-GAMMA_K_OTI(i) * (EP_EQ_OTI - EP_EQ_INIT_OTI))
          DO j = 1, ntens
      ALPHA_K_OTI(i, j) = ALPHA_K_OTI(i, j) * E_K_OTI +
     1STRESS_REL_OTI(j)/HARD_ISO_TOTAL_OTI * C_K_OTI(i)/GAMMA_K_OTI(i)*
     1(ONE-E_K_OTI)
C    1      stress_rel(j)/hard_iso_total * c_k(i)/gamma_k(i)*(ONE-e_k)
          END DO
        END DO
C        strain_plastic = strain_plastic
C     1  + consist_param * MATMUL(P_mat, stress_rel)
C        stress = MATMUL(elastic_matrix, strain - strain_plastic)
      DSTRAN_P_OTI = CONSIST_PARAM_OTI * MATMUL(P_MAT_OTI,
     1STRESS_REL_OTI)
        STRAIN_PLASTIC_OTI = STRAIN_PLASTIC_OTI + DSTRAN_P_OTI
      STRESS_OTI = STRESS_TRIAL_OTI - MATMUL(ELASTIC_MATRIX_OTI,
     1DSTRAN_P_OTI)
      END IF
C ----------------------------------------------------------------------C
C
      ! Compute consistent tangent moduli
C
C ----------------------------------------------------------------------C
      IF (it_num .GT. 0) THEN
C     OTIS-SKIP: n_hat = stress_rel / f_bar
C       H_prime =-(beta-ONE)*isotropic_modulus*stress_rel/hard_iso_total
        DO i = 1, n_backstresses
          E_K_OTI = EXP(-GAMMA_K_OTI(i) * (EP_EQ_OTI - EP_EQ_INIT_OTI))
      H_prime = REAL(H_prime + C_K_OTI(i) * E_K_OTI * STRESS_REL_OTI /
     1HARD_ISO_TOTAL_OTI- GAMMA_K_OTI(i) * E_K_OTI * alpha_k_i(i, :))
C     OTIS-SKIP: 1    - gamma_k(i) * e_k * alpha_k_i(i, :)
        END DO
        H_prime = SQRT23 * H_prime
        DO i = 1, NTENS
          DO j = 1, NTENS
            H_out_n(i, j) = H_prime(i) * n_hat(j)
          END DO
        END DO
      A_mat = REAL(BETA_OTI * ID3 + CONSIST_PARAM_OTI * MATMUL(H_out_n,
     1P_MAT_OTI))
        A_mat = matinv3(A_mat)
C
      n_tilde = REAL(n_hat - CONSIST_PARAM_OTI * MATMUL(A_mat, H_prime))
      Xi_tilde = REAL(compliance_matrix+CONSIST_PARAM_OTI*
     1MATMUL(P_MAT_OTI, A_mat))
        Xi_tilde = matinv3(Xi_tilde)
        Xi_tilde_A = MATMUL(A_mat, Xi_tilde)
C
      theta_2 = REAL(ONE - TWO/THREE * ISOTROPIC_MODULUS_OTI *
     1CONSIST_PARAM_OTI)
      H_tilde = REAL(H_prime + MATMUL(Xi_tilde, MATMUL(P_MAT_OTI,
     1n_tilde)))
      theta_1 = REAL(TWO/THREE * ISOTROPIC_MODULUS_OTI+ theta_2*
     1DOT_PRODUCT(n_hat,MATMUL(P_MAT_OTI,MATMUL(A_mat,H_tilde))))
C    1  + theta_2*DOT_PRODUCT(n_hat,MATMUL(P_mat,MATMUL(A_mat,H_tilde)))
        DO i = 1, NTENS
          DO j = 1, NTENS
            n_out_n(i, j) = n_tilde(i) * n_hat(j)
          END DO
        END DO

C     OTIS-SKIP: C_ep = Xi_tilde - theta_2 / theta_1 *
C     OTIS-SKIP: 1  MATMUL(Xi_tilde,
C     OTIS-SKIP: 2  MATMUL(P_mat,
C     OTIS-SKIP: 3  MATMUL(n_out_n,
C     OTIS-SKIP: 4  MATMUL(P_mat, Xi_tilde_A))))
C
C     OTIS-SKIP: ddsdde = ONE/TWO * (C_ep + TRANSPOSE(C_ep))
        END IF
C ----------------------------------------------------------------------C
C
      ! Update the state variables
C
C ----------------------------------------------------------------------C
      STATEV_OTI(1) = EP_EQ_OTI
      STATEV_OTI(2:(1+ntens)) = STRAIN_PLASTIC_OTI
      DO i = 1, n_backstresses
        DO j = 1, ntens
          STATEV_OTI(I_ALPHA + (i-1) * ntens + j) = ALPHA_K_OTI(i, j)
        END DO
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
C ----------------------------------------------------------------------C
C
      ! Reduce time increment if did not converge
C
C ----------------------------------------------------------------------C
      IF (it_num .EQ. MAX_ITERATIONS) THEN
        PRINT *, "WARNING: Return mapping in integration point ", npt,
     1  " of element ", noel, " did not converge."
        PRINT *, "Reducing time increment to 1/4 of current value."
        PNEWDT = 0.25
      END IF
      RETURN
        
      CONTAINS
C ----------------------------------------------------------------------C
C
      ! Define matrix inverse
C
C ----------------------------------------------------------------------C
      ! From: http://fortranwiki.org/fortran/show/Matrix+inversion
      pure function matinv3(A) result(B)
      !! Performs a direct calculation of the inverse of a 3×3 matrix.
      REAL(8), intent(in) :: A(3,3)   !! Matrix
      REAL(8)             :: B(3,3)   !! Inverse matrix
      REAL(8)             :: detinv

      ! Calculate the inverse determinant of the matrix
      detinv = 1.D0 / (A(1,1)*A(2,2)*A(3,3) - A(1,1)*A(2,3)*A(3,2)
     1- A(1,2)*A(2,1)*A(3,3) + A(1,2)*A(2,3)*A(3,1)
     2+ A(1,3)*A(2,1)*A(3,2) - A(1,3)*A(2,2)*A(3,1))

      ! Calculate the inverse of the matrix
      B(1,1) = +detinv * (A(2,2)*A(3,3) - A(2,3)*A(3,2))
      B(2,1) = -detinv * (A(2,1)*A(3,3) - A(2,3)*A(3,1))
      B(3,1) = +detinv * (A(2,1)*A(3,2) - A(2,2)*A(3,1))
      B(1,2) = -detinv * (A(1,2)*A(3,3) - A(1,3)*A(3,2))
      B(2,2) = +detinv * (A(1,1)*A(3,3) - A(1,3)*A(3,1))
      B(3,2) = -detinv * (A(1,1)*A(3,2) - A(1,2)*A(3,1))
      B(1,3) = +detinv * (A(1,2)*A(2,3) - A(1,3)*A(2,2))
      B(2,3) = -detinv * (A(1,1)*A(2,3) - A(1,3)*A(2,1))
      B(3,3) = +detinv * (A(1,1)*A(2,2) - A(1,2)*A(2,1))
      end function
      END

C     ROTSIG: supplied body removed from the emitted file; the host (Abaqus, its MKL for LAPACK/BLAS) provides the real routine, and the transform calls its OTI copy ROTSIG_OTI.
