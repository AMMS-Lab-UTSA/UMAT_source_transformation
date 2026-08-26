!===============================================================
! Mixed OTI/real intrinsic overloads. Generic interfaces are
! additive across modules, so these extend MIN/MAX/SIGN.
!===============================================================
MODULE oti_intrinsics
  USE master_parameters, ONLY: DP
  USE otim4n1
  IMPLICIT NONE
  PRIVATE
  PUBLIC :: MIN, MAX, SIGN, OPERATOR(+)
  INTERFACE MIN
    MODULE PROCEDURE oti_min_or, oti_min_ro
  END INTERFACE MIN
  INTERFACE MAX
    MODULE PROCEDURE oti_max_or, oti_max_ro
  END INTERFACE MAX
  INTERFACE SIGN
    MODULE PROCEDURE oti_sign_oo, oti_sign_or
  END INTERFACE SIGN
  INTERFACE OPERATOR(+)
    MODULE PROCEDURE oti_unary_plus
  END INTERFACE
CONTAINS
  FUNCTION oti_min_or(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM4N1), INTENT(IN) :: A
    REAL(DP), INTENT(IN) :: B
    TYPE(ONUMM4N1) :: RES
    IF (B < A%R) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_min_or
  FUNCTION oti_min_ro(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A
    TYPE(ONUMM4N1), INTENT(IN) :: B
    TYPE(ONUMM4N1) :: RES
    IF (B%R < A) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_min_ro
  FUNCTION oti_max_or(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM4N1), INTENT(IN) :: A
    REAL(DP), INTENT(IN) :: B
    TYPE(ONUMM4N1) :: RES
    IF (B > A%R) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_max_or
  FUNCTION oti_max_ro(A, B) RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A
    TYPE(ONUMM4N1), INTENT(IN) :: B
    TYPE(ONUMM4N1) :: RES
    IF (B%R > A) THEN
      RES = B
    ELSE
      RES = A
    END IF
  END FUNCTION oti_max_ro
  FUNCTION oti_sign_oo(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM4N1), INTENT(IN) :: A, B
    TYPE(ONUMM4N1) :: RES
    IF (B%R < 0.0_DP) THEN
      RES = -ABS(A)
    ELSE
      RES = ABS(A)
    END IF
  END FUNCTION oti_sign_oo
  FUNCTION oti_sign_or(A, B) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM4N1), INTENT(IN) :: A
    REAL(DP), INTENT(IN) :: B
    TYPE(ONUMM4N1) :: RES
    IF (B < 0.0_DP) THEN
      RES = -ABS(A)
    ELSE
      RES = ABS(A)
    END IF
  END FUNCTION oti_sign_or
  FUNCTION oti_unary_plus(A) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM4N1), INTENT(IN) :: A
    TYPE(ONUMM4N1) :: RES
    RES = A
  END FUNCTION oti_unary_plus
END MODULE oti_intrinsics
