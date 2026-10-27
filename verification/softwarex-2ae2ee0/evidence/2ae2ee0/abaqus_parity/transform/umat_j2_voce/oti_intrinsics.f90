!===============================================================
! Mixed OTI/real intrinsic overloads. Generic interfaces are
! additive across modules, so these extend MIN/MAX/SIGN/MATMUL.
!===============================================================
MODULE oti_intrinsics
  USE master_parameters, ONLY: DP
  USE otim6n1
  IMPLICIT NONE
  PRIVATE
  PUBLIC :: MIN, MAX, SIGN, NINT, INT, LOG10, ASSIGNMENT(=), MATMUL
  PUBLIC :: OPERATOR(+), OPERATOR(-), OPERATOR(*), OPERATOR(/)
  PUBLIC :: OPERATOR(**), TINY, SUM, NORM2, OTI_VALUE, OTI_R4
  INTERFACE OPERATOR(**)
    MODULE PROCEDURE oti_pow_so
  END INTERFACE
  INTERFACE OTI_R4
    MODULE PROCEDURE oti_r4_o, oti_r4_d, oti_r4_s
  END INTERFACE
  INTERFACE TINY
    MODULE PROCEDURE oti_tiny
  END INTERFACE
  INTERFACE MATMUL
    MODULE PROCEDURE oti_matmul_oo_mv, oti_matmul_ro_mv, oti_matmul_or_mv
    MODULE PROCEDURE oti_matmul_oo_vm, oti_matmul_ro_vm, oti_matmul_or_vm
    MODULE PROCEDURE oti_matmul_oi_mm, oti_matmul_io_mm
  END INTERFACE MATMUL
  INTERFACE MIN
    MODULE PROCEDURE oti_min_or, oti_min_ro
  END INTERFACE MIN
  INTERFACE MAX
    MODULE PROCEDURE oti_max_or, oti_max_ro
  END INTERFACE MAX
  INTERFACE SIGN
    MODULE PROCEDURE oti_sign_oo, oti_sign_or, oti_sign_ro
  END INTERFACE SIGN
  INTERFACE NINT
    MODULE PROCEDURE oti_nint
  END INTERFACE NINT
  INTERFACE INT
    MODULE PROCEDURE oti_int
  END INTERFACE INT
  INTERFACE LOG10
    MODULE PROCEDURE oti_log10
  END INTERFACE LOG10
  INTERFACE SUM
    MODULE PROCEDURE oti_sum_r1, oti_sum_r2
  END INTERFACE SUM
  INTERFACE OTI_VALUE
    MODULE PROCEDURE oti_value_o, oti_value_d, oti_value_s, oti_value_i
  END INTERFACE OTI_VALUE
  INTERFACE NORM2
    MODULE PROCEDURE oti_norm2_r1, oti_norm2_r2
  END INTERFACE NORM2
  INTERFACE OPERATOR(+)
    MODULE PROCEDURE oti_add_io, oti_add_oi, oti_add_so, oti_add_os
  END INTERFACE
  INTERFACE OPERATOR(-)
    MODULE PROCEDURE oti_sub_io, oti_sub_oi, oti_sub_so, oti_sub_os
  END INTERFACE
  INTERFACE OPERATOR(*)
    MODULE PROCEDURE oti_mul_io, oti_mul_oi, oti_mul_so, oti_mul_os
  END INTERFACE
  INTERFACE OPERATOR(/)
    MODULE PROCEDURE oti_div_io, oti_div_oi, oti_div_so, oti_div_os
  END INTERFACE
  INTERFACE ASSIGNMENT(=)
    MODULE PROCEDURE oti_assign_s, oti_assign_i
  END INTERFACE
CONTAINS
  FUNCTION oti_matmul_oo_mv(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: B(:)
    TYPE(ONUMM6N1) :: RES(SIZE(A, 1))
    INTEGER :: OTI_MM_I, OTI_MM_K
    RES = 0.0_DP
    DO OTI_MM_I = 1, SIZE(A, 1)
      DO OTI_MM_K = 1, SIZE(A, 2)
        RES(OTI_MM_I) = RES(OTI_MM_I) + A(OTI_MM_I, OTI_MM_K) * B(OTI_MM_K)
      END DO
    END DO
  END FUNCTION oti_matmul_oo_mv
  FUNCTION oti_matmul_ro_mv(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: B(:)
    TYPE(ONUMM6N1) :: RES(SIZE(A, 1))
    INTEGER :: OTI_MM_I, OTI_MM_K
    RES = 0.0_DP
    DO OTI_MM_I = 1, SIZE(A, 1)
      DO OTI_MM_K = 1, SIZE(A, 2)
        RES(OTI_MM_I) = RES(OTI_MM_I) + A(OTI_MM_I, OTI_MM_K) * B(OTI_MM_K)
      END DO
    END DO
  END FUNCTION oti_matmul_ro_mv
  FUNCTION oti_matmul_or_mv(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A(:,:)
    REAL(DP), INTENT(IN) :: B(:)
    TYPE(ONUMM6N1) :: RES(SIZE(A, 1))
    INTEGER :: OTI_MM_I, OTI_MM_K
    RES = 0.0_DP
    DO OTI_MM_I = 1, SIZE(A, 1)
      DO OTI_MM_K = 1, SIZE(A, 2)
        RES(OTI_MM_I) = RES(OTI_MM_I) + A(OTI_MM_I, OTI_MM_K) * B(OTI_MM_K)
      END DO
    END DO
  END FUNCTION oti_matmul_or_mv
  FUNCTION oti_matmul_oo_vm(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A(:)
    TYPE(ONUMM6N1), INTENT(IN) :: B(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(B, 2))
    INTEGER :: OTI_MM_J, OTI_MM_K
    RES = 0.0_DP
    DO OTI_MM_J = 1, SIZE(B, 2)
      DO OTI_MM_K = 1, SIZE(B, 1)
        RES(OTI_MM_J) = RES(OTI_MM_J) + A(OTI_MM_K) * B(OTI_MM_K, OTI_MM_J)
      END DO
    END DO
  END FUNCTION oti_matmul_oo_vm
  FUNCTION oti_matmul_ro_vm(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A(:)
    TYPE(ONUMM6N1), INTENT(IN) :: B(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(B, 2))
    INTEGER :: OTI_MM_J, OTI_MM_K
    RES = 0.0_DP
    DO OTI_MM_J = 1, SIZE(B, 2)
      DO OTI_MM_K = 1, SIZE(B, 1)
        RES(OTI_MM_J) = RES(OTI_MM_J) + A(OTI_MM_K) * B(OTI_MM_K, OTI_MM_J)
      END DO
    END DO
  END FUNCTION oti_matmul_ro_vm
  FUNCTION oti_matmul_or_vm(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A(:)
    REAL(DP), INTENT(IN) :: B(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(B, 2))
    INTEGER :: OTI_MM_J, OTI_MM_K
    RES = 0.0_DP
    DO OTI_MM_J = 1, SIZE(B, 2)
      DO OTI_MM_K = 1, SIZE(B, 1)
        RES(OTI_MM_J) = RES(OTI_MM_J) + A(OTI_MM_K) * B(OTI_MM_K, OTI_MM_J)
      END DO
    END DO
  END FUNCTION oti_matmul_or_vm
  FUNCTION oti_min_or(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(DP), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    IF (B < A%R) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_min_or
  FUNCTION oti_min_ro(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    IF (B%R < A) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_min_ro
  FUNCTION oti_max_or(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(DP), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    IF (B > A%R) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_max_or
  FUNCTION oti_max_ro(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    IF (B%R > A) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_max_ro
  ELEMENTAL FUNCTION oti_add_io(A, B) RESULT(RES)
    IMPLICIT NONE
    INTEGER, INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) + B
  END FUNCTION oti_add_io
  ELEMENTAL FUNCTION oti_add_oi(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    INTEGER, INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A + DBLE(B)
  END FUNCTION oti_add_oi
  ELEMENTAL FUNCTION oti_add_so(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(KIND=4), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) + B
  END FUNCTION oti_add_so
  ELEMENTAL FUNCTION oti_add_os(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(KIND=4), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A + DBLE(B)
  END FUNCTION oti_add_os
  ELEMENTAL FUNCTION oti_sub_io(A, B) RESULT(RES)
    IMPLICIT NONE
    INTEGER, INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) - B
  END FUNCTION oti_sub_io
  ELEMENTAL FUNCTION oti_sub_oi(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    INTEGER, INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A - DBLE(B)
  END FUNCTION oti_sub_oi
  ELEMENTAL FUNCTION oti_sub_so(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(KIND=4), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) - B
  END FUNCTION oti_sub_so
  ELEMENTAL FUNCTION oti_sub_os(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(KIND=4), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A - DBLE(B)
  END FUNCTION oti_sub_os
  ELEMENTAL FUNCTION oti_mul_io(A, B) RESULT(RES)
    IMPLICIT NONE
    INTEGER, INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) * B
  END FUNCTION oti_mul_io
  ELEMENTAL FUNCTION oti_mul_oi(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    INTEGER, INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A * DBLE(B)
  END FUNCTION oti_mul_oi
  ELEMENTAL FUNCTION oti_mul_so(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(KIND=4), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) * B
  END FUNCTION oti_mul_so
  ELEMENTAL FUNCTION oti_mul_os(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(KIND=4), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A * DBLE(B)
  END FUNCTION oti_mul_os
  ELEMENTAL FUNCTION oti_div_io(A, B) RESULT(RES)
    IMPLICIT NONE
    INTEGER, INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) / B
  END FUNCTION oti_div_io
  ELEMENTAL FUNCTION oti_div_oi(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    INTEGER, INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A / DBLE(B)
  END FUNCTION oti_div_oi
  ELEMENTAL FUNCTION oti_div_so(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(KIND=4), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = DBLE(A) / B
  END FUNCTION oti_div_so
  ELEMENTAL FUNCTION oti_div_os(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(KIND=4), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    RES = A / DBLE(B)
  END FUNCTION oti_div_os
  ELEMENTAL SUBROUTINE oti_assign_s(RES, LHS)
    IMPLICIT NONE
    REAL(KIND=4), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(OUT) :: RES
    RES = DBLE(LHS)
  END SUBROUTINE oti_assign_s
  ELEMENTAL SUBROUTINE oti_assign_i(RES, LHS)
    IMPLICIT NONE
    INTEGER, INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(OUT) :: RES
    RES = DBLE(LHS)
  END SUBROUTINE oti_assign_i
  ELEMENTAL FUNCTION oti_sign_oo(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A, B
    TYPE(ONUMM6N1) :: RES
    IF (SIGN(1.0_DP, B%R) < 0.0_DP) THEN
      RES = -ABS(A)
    ELSE
      RES = ABS(A)
    END IF
    RES%R = SIGN(A%R, B%R)
  END FUNCTION oti_sign_oo
  ELEMENTAL FUNCTION oti_sign_or(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    REAL(DP), INTENT(IN) :: B
    TYPE(ONUMM6N1) :: RES
    IF (SIGN(1.0_DP, B) < 0.0_DP) THEN
      RES = -ABS(A)
    ELSE
      RES = ABS(A)
    END IF
    RES%R = SIGN(A%R, B)
  END FUNCTION oti_sign_or
  ELEMENTAL FUNCTION oti_sign_ro(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A
    TYPE(ONUMM6N1), INTENT(IN) :: B
    REAL(DP) :: RES
    RES = SIGN(A, B%R)
  END FUNCTION oti_sign_ro
  FUNCTION oti_log10(A) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    TYPE(ONUMM6N1) :: RES
    RES = LOG(A) * (1.0_DP / LOG(10.0_DP))
  END FUNCTION oti_log10
  FUNCTION oti_nint(A) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    INTEGER :: RES
    RES = NINT(A%R)
  END FUNCTION oti_nint
  FUNCTION oti_int(A) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A
    INTEGER :: RES
    RES = INT(A%R)
  END FUNCTION oti_int
  ELEMENTAL FUNCTION oti_pow_so(BASE, EXPONENT) RESULT(RES)
    REAL, INTENT(IN) :: BASE
    TYPE(ONUMM6N1), INTENT(IN) :: EXPONENT
    TYPE(ONUMM6N1) :: RES
    RES = REAL(BASE, DP)**EXPONENT
  END FUNCTION oti_pow_so
  ELEMENTAL FUNCTION oti_r4_o(X) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: X
    TYPE(ONUMM6N1) :: RES
    RES = X
    RES%R = REAL(REAL(X%R, KIND=4), DP)
  END FUNCTION oti_r4_o
  ELEMENTAL FUNCTION oti_r4_d(X) RESULT(RES)
    REAL(DP), INTENT(IN) :: X
    REAL(DP) :: RES
    RES = REAL(REAL(X, KIND=4), DP)
  END FUNCTION oti_r4_d
  ELEMENTAL FUNCTION oti_r4_s(X) RESULT(RES)
    REAL(KIND=4), INTENT(IN) :: X
    REAL(KIND=4) :: RES
    RES = X
  END FUNCTION oti_r4_s
  ELEMENTAL FUNCTION oti_value_o(X) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: X
    TYPE(ONUMM6N1) :: RES
    RES = X
  END FUNCTION oti_value_o
  ELEMENTAL FUNCTION oti_value_d(X) RESULT(RES)
    REAL(DP), INTENT(IN) :: X
    TYPE(ONUMM6N1) :: RES
    RES = X
  END FUNCTION oti_value_d
  ELEMENTAL FUNCTION oti_value_s(X) RESULT(RES)
    REAL(KIND=4), INTENT(IN) :: X
    TYPE(ONUMM6N1) :: RES
    RES = REAL(X, DP)
  END FUNCTION oti_value_s
  ELEMENTAL FUNCTION oti_value_i(X) RESULT(RES)
    INTEGER, INTENT(IN) :: X
    TYPE(ONUMM6N1) :: RES
    RES = REAL(X, DP)
  END FUNCTION oti_value_i
  FUNCTION oti_matmul_oi_mm(A, B) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: A(:,:)
    INTEGER, INTENT(IN) :: B(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(A, 1), SIZE(B, 2))
    INTEGER :: I, J, K
    RES = 0.0D0
    DO J = 1, SIZE(B, 2)
      DO K = 1, SIZE(A, 2)
        DO I = 1, SIZE(A, 1)
          RES(I, J) = RES(I, J) + A(I, K)*REAL(B(K, J), DP)
        END DO
      END DO
    END DO
  END FUNCTION oti_matmul_oi_mm
  FUNCTION oti_matmul_io_mm(A, B) RESULT(RES)
    INTEGER, INTENT(IN) :: A(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: B(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(A, 1), SIZE(B, 2))
    INTEGER :: I, J, K
    RES = 0.0D0
    DO J = 1, SIZE(B, 2)
      DO K = 1, SIZE(A, 2)
        DO I = 1, SIZE(A, 1)
          RES(I, J) = RES(I, J) + REAL(A(I, K), DP)*B(K, J)
        END DO
      END DO
    END DO
  END FUNCTION oti_matmul_io_mm
  FUNCTION oti_sum_r1(ARRAY) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
    TYPE(ONUMM6N1) :: RES
    INTEGER :: I
    RES = 0.0D0
    DO I = 1, SIZE(ARRAY)
      RES = RES + ARRAY(I)
    END DO
  END FUNCTION oti_sum_r1
  FUNCTION oti_sum_r2(ARRAY) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
    TYPE(ONUMM6N1) :: RES
    INTEGER :: I, J
    RES = 0.0D0
    DO J = 1, SIZE(ARRAY, 2)
      DO I = 1, SIZE(ARRAY, 1)
        RES = RES + ARRAY(I, J)
      END DO
    END DO
  END FUNCTION oti_sum_r2
  FUNCTION oti_norm2_r1(ARRAY) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
    TYPE(ONUMM6N1) :: RES, ACC
    INTEGER :: I
    ACC = 0.0D0
    DO I = 1, SIZE(ARRAY)
      ACC = ACC + ARRAY(I)*ARRAY(I)
    END DO
    RES = SQRT(ACC)
  END FUNCTION oti_norm2_r1
  FUNCTION oti_norm2_r2(ARRAY) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
    TYPE(ONUMM6N1) :: RES, ACC
    INTEGER :: I, J
    ACC = 0.0D0
    DO J = 1, SIZE(ARRAY, 2)
      DO I = 1, SIZE(ARRAY, 1)
        ACC = ACC + ARRAY(I, J)*ARRAY(I, J)
      END DO
    END DO
    RES = SQRT(ACC)
  END FUNCTION oti_norm2_r2
  ELEMENTAL FUNCTION oti_tiny(VALUE) RESULT(RES)
    TYPE(ONUMM6N1), INTENT(IN) :: VALUE
    REAL(DP) :: RES
    RES = TINY(VALUE%R)
  END FUNCTION oti_tiny
END MODULE oti_intrinsics
