! ===== master_parameters.f90 =====
!*******************************************************************************************************!
!> @brief This module contains the master parameters used in many Finite Element modules and other 
!! programs.
!!
!! @author Mauricio Aristizabal Cano, University of Texas at San Antonio
!*******************************************************************************************************!
MODULE master_parameters
   !----------------------------------------------------------------------------------------------------!
   IMPLICIT NONE
   !----------------------------------------------------------------------------------------------------!
   INTEGER,  PARAMETER :: dp     = SELECTED_REAL_KIND(15,306)
   INTEGER,  PARAMETER :: enum_t = SELECTED_INT_KIND(4)
   !----------------------------------------------------------------------------------------------------!
   INTEGER(enum_t), PARAMETER :: elNode        =  400, &
                                 elLine        =  401, &
                                 elTriangle    =  402, &
                                 elQuadrangle  =  403, &
                                 elTetrahedra  =  404, &
                                 elHexahedra   =  405, &  
                                 ! Definition of integration points.
                                 intLobatto    =  410, &
                                 intGauss      =  411
   !----------------------------------------------------------------------------------------------------!
   INTEGER, PARAMETER :: maxIntPts = 1024 
   !----------------------------------------------------------------------------------------------------!
   REAL(dp), PARAMETER :: ten    = 10.0_dp
   REAL(dp), PARAMETER :: eight  =  8.0_dp
   REAL(dp), PARAMETER :: six    =  6.0_dp
   REAL(dp), PARAMETER :: three  =  3.0_dp
   REAL(dp), PARAMETER :: two    =  2.0_dp
   REAL(dp), PARAMETER :: one    =  1.0_dp
   REAL(dp), PARAMETER :: half   =  0.5_dp
   REAL(dp), PARAMETER :: third  =  1.0_dp/3.0_dp
   REAL(dp), PARAMETER :: fourth =  0.25_dp
   REAL(dp), PARAMETER :: eighth =  0.125_dp
   REAL(dp), PARAMETER :: zero   =  0.0_dp
   REAL(dp), PARAMETER :: piOver4 = ATAN(one)
   REAL(dp), PARAMETER :: piOver2 = piOver4 * two
   REAL(dp), PARAMETER :: pi      = piOver4 * 4.0_dp !3.141592653589793_dp
   !----------------------------------------------------------------------------------------------------!
END MODULE master_parameters
!*******************************************************************************************************!
! ===== real_utils.f90 =====
!*******************************************************************************************************!
!> @brief This module contains types and subroutines to simplify handling of real matrix and vector 
!!        operations.
!! 
!! @author Mauricio Aristizabal Cano, University of Texas at San Antonio
!*******************************************************************************************************!
MODULE real_utils
   !---------------------------------------------------------------------------------------------------! 
   USE master_parameters
   IMPLICIT NONE
   !---------------------------------------------------------------------------------------------------! 
   INTERFACE PPRINT
     MODULE PROCEDURE RmatPrint, RvecPrint, Rprint,IPrint, ImatPrint, IvecPrint
   END INTERFACE
   
   !---------------------------------------------------------------------------------------------------! 
   ! Matrix Determinant overloads.
   !---------------------------------------------------------------------------------------------------! 

   INTERFACE det2x2
     MODULE PROCEDURE Rdet2x2
   END INTERFACE

   INTERFACE det3x3
     MODULE PROCEDURE Rdet3x3
   END INTERFACE

   INTERFACE det4x4
     MODULE PROCEDURE Rdet4x4
   END INTERFACE

   !---------------------------------------------------------------------------------------------------! 
   ! Matrix inverse overloads.
   !---------------------------------------------------------------------------------------------------! 

   INTERFACE inv2x2
     MODULE PROCEDURE Rmatinv2x2
   END INTERFACE

   INTERFACE inv3x3
     MODULE PROCEDURE Rmatinv3x3
   END INTERFACE

   INTERFACE inv4x4
     MODULE PROCEDURE Rmatinv4x4
   END INTERFACE

   !---------------------------------------------------------------------------------------------------! 
   ! Other Linalg Operations overloads.
   !---------------------------------------------------------------------------------------------------! 

   INTERFACE norm2_3
     MODULE PROCEDURE Rnorm2_3
   END INTERFACE

   INTERFACE cross3
     MODULE PROCEDURE Rcross3
   END INTERFACE

   INTERFACE interp1D
     MODULE PROCEDURE Rinterp1D
   END INTERFACE

   INTERFACE Inxn
     MODULE PROCEDURE RInxn
   END INTERFACE

   INTERFACE VectorToMatrix
     MODULE PROCEDURE RVectorToMatrix
   END INTERFACE

   INTERFACE MatrixToVector
     MODULE PROCEDURE RMatrixToVector
   END INTERFACE

   INTERFACE FrobeniusProduct
     MODULE PROCEDURE RFrobeniusProduct
   END INTERFACE


   !---------------------------------------------------------------------------------------------------! 

CONTAINS

   !***************************************************************************************************! 
   !> @brief 2 x 2  matrix inversion.
   !!
   !! Taken from https://fortranwiki.org/fortran/show/Matrix+inversion
   !!
   !! @param[in] A: Matrix to be printed.
   !! @param[out] B: inverse of A.
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rmatinv2x2(A,det) RESULT(B)

      IMPLICIT NONE

      REAL(dp), INTENT(IN) :: A(2,2)   !! Matrix
      REAL(dp), INTENT(IN), OPTIONAL :: det
      REAL(dp)             :: B(2,2)   !! Inverse matrix
      REAL(dp)             :: detinv

      IF ( PRESENT(det) ) THEN
         detinv = one/det
      ELSE
         ! Calculate the inverse determinant of the matrix
         detinv = one/(A(1,1)*A(2,2) - A(1,2)*A(2,1))
      END IF

      ! Calculate the inverse of the matrix
      B(1,1) =  detinv * A(2,2)
      B(2,1) = -detinv * A(2,1)
      B(1,2) = -detinv * A(1,2)
      B(2,2) =  detinv * A(1,1)
   END FUNCTION
   !===================================================================================================! 
   
   !***************************************************************************************************! 
   !> @brief 3 x 3  matrix inversion.
   !!
   !! Taken from https://fortranwiki.org/fortran/show/Matrix+inversion
   !!
   !! @param[in]  A: Matrix to be printed.
   !! @param[out] B: inverse of A.
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rmatinv3x3(A,det) RESULT(B)
      
      IMPLICIT NONE

      REAL(dp), INTENT(IN) :: A(3,3)   !! Matrix
      REAL(dp), INTENT(IN), OPTIONAL :: det
      REAL(dp)             :: B(3,3)   !! Inverse matrix
      REAL(dp)             :: detinv

      IF ( PRESENT(det) ) THEN
         detinv = one/det
      ELSE
         ! Calculate the inverse determinant of the matrix
         detinv = one/(A(1,1)*A(2,2)*A(3,3) - A(1,1)*A(2,3)*A(3,2)&
                       - A(1,2)*A(2,1)*A(3,3) + A(1,2)*A(2,3)*A(3,1)&
                       + A(1,3)*A(2,1)*A(3,2) - A(1,3)*A(2,2)*A(3,1))
      END IF 

      ! Calculate the inverse of the matrix
      B(1,1) = + detinv * (A(2,2)*A(3,3) - A(2,3)*A(3,2))
      B(2,1) = - detinv * (A(2,1)*A(3,3) - A(2,3)*A(3,1))
      B(3,1) = + detinv * (A(2,1)*A(3,2) - A(2,2)*A(3,1))
      B(1,2) = - detinv * (A(1,2)*A(3,3) - A(1,3)*A(3,2))
      B(2,2) = + detinv * (A(1,1)*A(3,3) - A(1,3)*A(3,1))
      B(3,2) = - detinv * (A(1,1)*A(3,2) - A(1,2)*A(3,1))
      B(1,3) = + detinv * (A(1,2)*A(2,3) - A(1,3)*A(2,2))
      B(2,3) = - detinv * (A(1,1)*A(2,3) - A(1,3)*A(2,1))
      B(3,3) = + detinv * (A(1,1)*A(2,2) - A(1,2)*A(2,1))

   END FUNCTION
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief 4 x 4  matrix inversion.
   !!
   !! Taken from https://fortranwiki.org/fortran/show/Matrix+inversion
   !!
   !! @param[in]  A: Matrix to be printed.
   !! @param[in]  det: (optional) Determinant of A.
   !! @param[out] B: inverse of A.
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rmatinv4x4(A,det) RESULT(B)
      
      IMPLICIT NONE

      REAL(dp), INTENT(IN) :: A(4,4)   !! Matrix
      REAL(dp), INTENT(IN), OPTIONAL :: det
      REAL(dp)             :: B(4,4)   !! Inverse matrix
      REAL(dp)             :: di  !! Determinant inverse

      ! Calculate the inverse determinant of the matrix
      IF ( PRESENT(det) ) THEN
         di = one/det
      ELSE
         di = &
    one/(A(1,1)*(A(2,2)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(2,4)*(A(3,2)*A(4,3)-A(3,3)*A(4,2)))&
         - A(1,2)*(A(2,1)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,3)-A(3,3)*A(4,1)))&
         + A(1,3)*(A(2,1)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(2,2)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))&
         - A(1,4)*(A(2,1)*(A(3,2)*A(4,3)-A(3,3)*A(4,2))+A(2,2)*(A(3,3)*A(4,1)-A(3,1)*A(4,3))+A(2,3)*(A(3,1)*A(4,2)-A(3,2)*A(4,1))))
      END IF 
      
      ! Calculate the inverse of the matrix
      B(1,1) = di*(A(2,2)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(2,4)*(A(3,2)*A(4,3)-A(3,3)*A(4,2)))
      B(2,1) = di*(A(2,1)*(A(3,4)*A(4,3)-A(3,3)*A(4,4))+A(2,3)*(A(3,1)*A(4,4)-A(3,4)*A(4,1))+A(2,4)*(A(3,3)*A(4,1)-A(3,1)*A(4,3)))
      B(3,1) = di*(A(2,1)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(2,2)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))
      B(4,1) = di*(A(2,1)*(A(3,3)*A(4,2)-A(3,2)*A(4,3))+A(2,2)*(A(3,1)*A(4,3)-A(3,3)*A(4,1))+A(2,3)*(A(3,2)*A(4,1)-A(3,1)*A(4,2)))
      B(1,2) = di*(A(1,2)*(A(3,4)*A(4,3)-A(3,3)*A(4,4))+A(1,3)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(1,4)*(A(3,3)*A(4,2)-A(3,2)*A(4,3)))
      B(2,2) = di*(A(1,1)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(1,3)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(1,4)*(A(3,1)*A(4,3)-A(3,3)*A(4,1)))
      B(3,2) = di*(A(1,1)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(1,2)*(A(3,1)*A(4,4)-A(3,4)*A(4,1))+A(1,4)*(A(3,2)*A(4,1)-A(3,1)*A(4,2)))
      B(4,2) = di*(A(1,1)*(A(3,2)*A(4,3)-A(3,3)*A(4,2))+A(1,2)*(A(3,3)*A(4,1)-A(3,1)*A(4,3))+A(1,3)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))
      B(1,3) = di*(A(1,2)*(A(2,3)*A(4,4)-A(2,4)*A(4,3))+A(1,3)*(A(2,4)*A(4,2)-A(2,2)*A(4,4))+A(1,4)*(A(2,2)*A(4,3)-A(2,3)*A(4,2)))
      B(2,3) = di*(A(1,1)*(A(2,4)*A(4,3)-A(2,3)*A(4,4))+A(1,3)*(A(2,1)*A(4,4)-A(2,4)*A(4,1))+A(1,4)*(A(2,3)*A(4,1)-A(2,1)*A(4,3)))
      B(3,3) = di*(A(1,1)*(A(2,2)*A(4,4)-A(2,4)*A(4,2))+A(1,2)*(A(2,4)*A(4,1)-A(2,1)*A(4,4))+A(1,4)*(A(2,1)*A(4,2)-A(2,2)*A(4,1)))
      B(4,3) = di*(A(1,1)*(A(2,3)*A(4,2)-A(2,2)*A(4,3))+A(1,2)*(A(2,1)*A(4,3)-A(2,3)*A(4,1))+A(1,3)*(A(2,2)*A(4,1)-A(2,1)*A(4,2)))
      B(1,4) = di*(A(1,2)*(A(2,4)*A(3,3)-A(2,3)*A(3,4))+A(1,3)*(A(2,2)*A(3,4)-A(2,4)*A(3,2))+A(1,4)*(A(2,3)*A(3,2)-A(2,2)*A(3,3)))
      B(2,4) = di*(A(1,1)*(A(2,3)*A(3,4)-A(2,4)*A(3,3))+A(1,3)*(A(2,4)*A(3,1)-A(2,1)*A(3,4))+A(1,4)*(A(2,1)*A(3,3)-A(2,3)*A(3,1)))
      B(3,4) = di*(A(1,1)*(A(2,4)*A(3,2)-A(2,2)*A(3,4))+A(1,2)*(A(2,1)*A(3,4)-A(2,4)*A(3,1))+A(1,4)*(A(2,2)*A(3,1)-A(2,1)*A(3,2)))
      B(4,4) = di*(A(1,1)*(A(2,2)*A(3,3)-A(2,3)*A(3,2))+A(1,2)*(A(2,3)*A(3,1)-A(2,1)*A(3,3))+A(1,3)*(A(2,1)*A(3,2)-A(2,2)*A(3,1)))
   END FUNCTION
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief 2 x 2  matrix determinant.
   !!
   !!
   !! @param[in] A: Matrix to be printed.
   !! @param[out] B: inverse of A.
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rdet2x2(A) RESULT(det)

      IMPLICIT NONE

      REAL(dp), INTENT(IN) :: A(2,2)   !! Matrix
      REAL(dp)             :: det

      ! Calculate the determinant of the matrix
      det = (A(1,1)*A(2,2) - A(1,2)*A(2,1))

   END FUNCTION
   !===================================================================================================! 
   
   !***************************************************************************************************! 
   !> @brief 3 x 3  matrix determinant.
   !!
   !!
   !! @param[in]  A: Matrix to be printed.
   !! @param[out] B: inverse of A.
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rdet3x3(A) RESULT(det)
      
      IMPLICIT NONE

      REAL(dp), INTENT(IN) :: A(3,3)   !! Matrix
      REAL(dp)             :: det

      ! Calculate the inverse determinant of the matrix
      det = (A(1,1)*A(2,2)*A(3,3) - A(1,1)*A(2,3)*A(3,2)&
           - A(1,2)*A(2,1)*A(3,3) + A(1,2)*A(2,3)*A(3,1)&
           + A(1,3)*A(2,1)*A(3,2) - A(1,3)*A(2,2)*A(3,1))

   END FUNCTION
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief 4 x 4  matrix determinant.
   !!
   !!
   !! @param[in]  A: Matrix to be printed.
   !! @param[out] B: inverse of A.
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rdet4x4(A) RESULT(det)
      
      IMPLICIT NONE

      REAL(dp), INTENT(IN) :: A(4,4)   !! Matrix
      REAL(dp)             :: det

      ! Calculate the determinant of the matrix
      det = &
      (A(1,1)*(A(2,2)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(2,4)*(A(3,2)*A(4,3)-A(3,3)*A(4,2)))&
     - A(1,2)*(A(2,1)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,3)-A(3,3)*A(4,1)))&
     + A(1,3)*(A(2,1)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(2,2)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))&
     - A(1,4)*(A(2,1)*(A(3,2)*A(4,3)-A(3,3)*A(4,2))+A(2,2)*(A(3,3)*A(4,1)-A(3,1)*A(4,3))+A(2,3)*(A(3,1)*A(4,2)-A(3,2)*A(4,1))))

   END FUNCTION
   !===================================================================================================! 
   
   !***************************************************************************************************! 
   !> @brief Cross product between two vectors.
   !!
   !! @param[in] a: Vector of 3 reals (rank 1).
   !! @param[in] b: Vector of 3 reals (rank 1).
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rcross3(a,b) RESULT(v)
      
      IMPLICIT NONE 

      REAL(dp), DIMENSION (3),INTENT(IN) :: a,b
      REAL(dp), DIMENSION (3) :: v
      
      v(1) = a(2) * b(3) - a(3) * b(2)
      v(2) = a(3) * b(1) - a(1) * b(3)
      v(3) = a(1) * b(2) - a(2) * b(1)

   END FUNCTION Rcross3
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief Norm of a 3 element vector. # There is an intrinsic function named norm2.
   !!
   !! @param[in] a: Vector of 3 reals (rank 1).
   !! @param[in] b: Vector of 3 reals (rank 1).
   !!
   !***************************************************************************************************!
   PURE FUNCTION Rnorm2_3(v) RESULT(n)
      
      IMPLICIT NONE 

      REAL(dp), INTENT(IN) :: v(3)
      REAL(dp) :: n
      
      n = SQRT( v(1)*v(1) + v(2)*v(2) + v(3)*v(3) )

   END FUNCTION Rnorm2_3
   !===================================================================================================! 


   !***************************************************************************************************! 
   !> @brief Pretty print a real scalar.
   !!
   !! @param[in] val: Value to be printed.
   !! @param[in] fmt: Format to print every element in the array.
   !!
   !***************************************************************************************************! 
   SUBROUTINE RPrint(val,fmt, unit)
      IMPLICIT NONE
      REAL(dp),   INTENT(IN) :: val
      CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
      INTEGER, INTENT(IN), OPTIONAL :: unit
      CHARACTER(len=:),ALLOCATABLE :: output_format
      INTEGER  i, j
      INTEGER :: unt
      !-------------------------------------------------------------------------------------------------!
      
      IF ( PRESENT(unit) ) THEN
         unt = unit
      ELSE
         unt = 6 ! Default print unit for most systems.
      END IF 

      IF (PRESENT(fmt)) THEN
         output_format = '('//trim(fmt)//')'
      ELSE
         output_format = '(F10.4)'
      END IF

      write(unt,output_format) val

   END SUBROUTINE
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief Pretty print a real matrix.
   !!
   !! @param[in] arr: Matrix to be printed.
   !! @param[in] fmt: Format to print every element in the array.
   !!
   !***************************************************************************************************! 
   SUBROUTINE RmatPrint(arr,fmt,unit)
      IMPLICIT NONE
      REAL(dp),   INTENT(IN) :: arr(:,:)
      CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
      INTEGER, INTENT(IN), OPTIONAL :: unit
      CHARACTER(len=:),ALLOCATABLE :: output_format
      INTEGER  i, j
      INTEGER :: unt
      !-------------------------------------------------------------------------------------------------!
      
      IF ( PRESENT(unit) ) THEN
         unt = unit
      ELSE
         unt = 6 ! Default print unit for most systems.
      END IF 

      IF (PRESENT(fmt)) THEN
         output_format = '('//trim(fmt)//')'
      ELSE
         output_format = '(F10.4)'
      END IF 

      write(unt,'(A)',advance="no") "["

      DO i=1,SIZE(arr,1)

         IF (I /= 1) THEN
            write(unt,'(A)',advance="no") " "   
         END IF 
         write(unt,'(A)',advance="no") "["

         DO j=1,SIZE(arr,2)
           
            write(unt,output_format,advance="no") &
              arr(i,j)

            write(unt,"(A)",advance="no") ", "

         END DO

         IF (I /= SIZE(arr,1)) THEN
            write(unt,'(A)') "]"
         ELSE
            write(unt,'(A)',advance="no") "]"   
         END IF 

      END DO
      
      write(unt,'(A)') "]"

   END SUBROUTINE
   !===================================================================================================! 
   
   !***************************************************************************************************! 
   !> @brief Pretty print a real vector.
   !!
   !! @param[in] arr: Vector to be printed.
   !! @param[in] fmt: Format to print every element in the array.
   !!
   !***************************************************************************************************! 
   SUBROUTINE RvecPrint(arr,fmt, unit)
      IMPLICIT NONE
      REAL(dp),   INTENT(IN) :: arr(:)
      CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
      INTEGER, INTENT(IN), OPTIONAL :: unit
      CHARACTER(len=:),ALLOCATABLE :: output_format
      INTEGER  i, j
      INTEGER :: unt
      !-------------------------------------------------------------------------------------------------!
      
      IF ( PRESENT(unit) ) THEN
         unt = unit
      ELSE
         unt = 6 ! Default print unit for most systems.
      END IF 

      IF (PRESENT(fmt)) THEN
         output_format = '('//trim(fmt)//')'
      ELSE
         output_format = '(F10.4)'
      END IF 

      write(unt,'(A)',advance="no") "["
      
      DO i=1,SIZE(arr,1)
         write(unt,output_format,advance="no") arr(i)
         write(unt,"(A)",advance="no") ", "
      END DO
      write(unt,'(A)') "]"

   END SUBROUTINE
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief Pretty print a integer scalar.
   !!
   !! @param[in] val: Value to be printed.
   !! @param[in] fmt: Format to print every element in the array.
   !!
   !***************************************************************************************************! 
   SUBROUTINE IPrint(val,fmt,unit)
      IMPLICIT NONE
      INTEGER,   INTENT(IN) :: val
      CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
      INTEGER, INTENT(IN), OPTIONAL :: unit
      CHARACTER(len=:),ALLOCATABLE :: output_format
      INTEGER :: unt
      !-------------------------------------------------------------------------------------------------!
      
      IF ( PRESENT(unit) ) THEN
         unt = unit
      ELSE
         unt = 6 ! Default print unit for most systems.
      END IF 

      IF (PRESENT(fmt)) THEN
         output_format = '('//trim(fmt)//')'
      ELSE
         output_format = '(I8)'
      END IF

      write(unt,output_format) val

   END SUBROUTINE
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief Pretty print a integer matrix.
   !!
   !! @param[in] arr: Matrix to be printed.
   !! @param[in] fmt: Format to print every element in the array.
   !!
   !***************************************************************************************************! 
   SUBROUTINE ImatPrint(arr,fmt,unit)
      IMPLICIT NONE
      INTEGER,   INTENT(IN) :: arr(:,:)
      CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
      INTEGER, INTENT(IN), OPTIONAL :: unit
      CHARACTER(len=:),ALLOCATABLE :: output_format
      INTEGER  i, j
      INTEGER :: unt
      !-------------------------------------------------------------------------------------------------!
      
      IF ( PRESENT(unit) ) THEN
         unt = unit
      ELSE
         unt = 6 ! Default print unit for most systems.
      END IF 

      IF (PRESENT(fmt)) THEN
         output_format = '('//trim(fmt)//')'
      ELSE
         output_format = '(I8)'
      END IF 

      write(unt,'(A)',advance="no") "["

      DO i=1,SIZE(arr,1)

         IF (I /= 1) THEN
            write(unt,'(A)',advance="no") " "   
         END IF 
         write(unt,'(A)',advance="no") "["

         DO j=1,SIZE(arr,2)
           
            write(unt,output_format,advance="no") &
              arr(i,j)

            write(unt,"(A)",advance="no") ", "

         END DO

         IF (I /= SIZE(arr,1)) THEN
            write(*,'(A)') "]"
         ELSE
            write(*,'(A)',advance="no") "]"   
         END IF 

      END DO
      
      write(unt,'(A)') "]"

   END SUBROUTINE
   !===================================================================================================! 
   
   !***************************************************************************************************! 
   !> @brief Pretty print a integer vector.
   !!
   !! @param[in] arr: Vector to be printed.
   !! @param[in] fmt: Format to print every element in the array.
   !!
   !***************************************************************************************************! 
   SUBROUTINE IvecPrint(arr,fmt,unit)
      IMPLICIT NONE
      INTEGER,   INTENT(IN) :: arr(:)
      CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
      INTEGER, INTENT(IN), OPTIONAL :: unit
      CHARACTER(len=:),ALLOCATABLE :: output_format
      INTEGER  i, j
      INTEGER :: unt
      !-------------------------------------------------------------------------------------------------!
      
      IF ( PRESENT(unit) ) THEN
         unt = unit
      ELSE
         unt = 6 ! Default print unit for most systems.
      END IF 

      IF (PRESENT(fmt)) THEN
         output_format = '('//trim(fmt)//')'
      ELSE
         output_format = '(I8)'
      END IF 

      WRITE(unt,'(A)',advance="no") "["
      
      DO i=1,SIZE(arr,1)
         WRITE(unt,output_format,advance='no') arr(i)
         WRITE(unt,'(A)',advance="no") ", "
      END DO
      WRITE(unt,'(A)') "]"

   END SUBROUTINE
   !===================================================================================================! 



   !***************************************************************************************************! 
   !> @brief Interpolation in 1D. xData MUST be in ascending order with no repeated entries.
   !!
   !! @param[in] xData: x-values of data in existance.
   !! @param[in] yData: y-values of data in existance.
   !! @param[in] x: Value to interpolate.
   !!
   !***************************************************************************************************! 
   FUNCTION Rinterp1D(xData,yData,x) RESULT(y)
      
      IMPLICIT NONE
      
      REAL(dp),   INTENT(IN) :: xData(:)
      REAL(dp),   INTENT(IN) :: yData( SIZE(xData) )
      REAL(dp),   INTENT(IN) :: x
      REAL(dp)               :: y ! Result.
      REAL(dp)               :: m
      INTEGER :: N, start, finish , range, mid 

      N = SIZE(xData)

      start = 1
      finish = N
      mid = (start + finish) / 2

      ! First check bounds
      IF ( x <= xData(start) ) THEN
         
         y =  yData(start)

      ELSEIF ( x >= xData(finish) ) THEN
         
         y =  yData(finish)

      ELSE
         
         range = finish - start

         ! Loop to find correct index.
         DO WHILE( range > 1 ) 
            
            IF (x > xData(mid)) THEN
              start = mid 
            ELSE 
              finish = mid
            END IF

            range = finish - start
            mid = (start + finish)/2

         END DO

         m = (yData(mid+1)-yData(mid)) / ( xData(mid+1)-xData(mid)) ! Line region slope.
         y = m * ( x - xData(mid) )  + yData(mid)

      END IF 


   END FUNCTION
   !===================================================================================================! 

   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief identity matrix rXr.
   !!
   !!
   !***************************************************************************************************!
   FUNCTION RInxn(r) RESULT(I)
      
      IMPLICIT NONE 

      INTEGER,   INTENT(IN)  :: r
      REAL(dp) :: I(r,r)
      INTEGER  :: j

      I = zero
      DO j = 1,r 
         I(j,j) = one
      END DO
      
   END FUNCTION
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief turn a tensor in vector notation to matrix notation.
   !!
   !!
   !***************************************************************************************************!
   PURE FUNCTION RVectorToMatrix(v) RESULT(T)
      
      IMPLICIT NONE 
      
      REAL(dp),   INTENT(IN)  :: v(6)
      REAL(dp) :: T(3,3)

      T(1,1) = v(1);  T(1,2) = v(4);  T(1,3) = v(6)
      T(2,1) = v(4);  T(2,2) = v(2);  T(2,3) = v(5)
      T(3,1) = v(6);  T(3,2) = v(5);  T(3,3) = v(3)
      
   END FUNCTION RVectorToMatrix
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief turn a tensor in matrix notation to vector notation.
   !!
   !!
   !***************************************************************************************************!
   PURE FUNCTION RMatrixToVector(T) RESULT(v)
      
      IMPLICIT NONE 
      
      REAL(dp),   INTENT(IN) :: T(3,3)
      REAL(dp) :: v(6)

      v(1) = T(1,1) 
      v(4) = T(2,1);  v(2) = T(2,2);
      v(6) = T(3,1);  v(5) = T(3,2);  v(3) = T(3,3)
      
   END FUNCTION RMatrixToVector
   !===================================================================================================! 

   !***************************************************************************************************! 
   !> @brief Compute the Frobenius product between two 3x3 tensors
   !!
   !!             res = A : B
   !!
   !! @param[in] A: 3x3 real tensor.
   !! @param[in] B: 3x3 real tensor.
   !!
   !***************************************************************************************************!
   PURE FUNCTION RFrobeniusProduct(A,B) RESULT(res)
      
      IMPLICIT NONE 
      
      REAL(dp), INTENT(IN) :: A(3,3), B(3,3)
      REAL(dp) :: res

      res = A(1,1)*B(1,1) + A(1,2)*B(1,2) + A(1,3)*B(1,3) + &
            A(2,1)*B(2,1) + A(2,2)*B(2,2) + A(2,3)*B(2,3) + &
            A(3,1)*B(3,1) + A(3,2)*B(3,2) + A(3,3)*B(3,3) 
      
   END FUNCTION RFrobeniusProduct
   !===================================================================================================! 

END MODULE real_utils
! ===== otim6n1.f90 =====
MODULE otim6n1

  USE master_parameters, ONLY: DP
  USE real_utils, ONLY: PPRINT, det2x2, det3x3, det4x4, inv2x2, inv3x3, inv4x4
  IMPLICIT NONE

  INTEGER, PARAMETER :: num_im_dir = 7
  INTEGER, PARAMETER :: torder     = 1
  INTEGER, PARAMETER :: n_imdir_order(2) = [1,6]

  TYPE ONUMM6N1
    ! Real
    REAL(DP) :: R
    ! Order 1
    REAL(DP) :: E1
    REAL(DP) :: E2
    REAL(DP) :: E3
    REAL(DP) :: E4
    REAL(DP) :: E5
    REAL(DP) :: E6
  END TYPE ONUMM6N1

  ! Constant imaginary directions.
  ! Order 1
  TYPE(ONUMM6N1), PARAMETER :: E1 = ONUMM6N1(0.0_dp,1.0_dp,0.0_dp,0.0_dp,0.0_dp,0.0_dp,0.0_dp)
  TYPE(ONUMM6N1), PARAMETER :: E2 = ONUMM6N1(0.0_dp,0.0_dp,1.0_dp,0.0_dp,0.0_dp,0.0_dp,0.0_dp)
  TYPE(ONUMM6N1), PARAMETER :: E3 = ONUMM6N1(0.0_dp,0.0_dp,0.0_dp,1.0_dp,0.0_dp,0.0_dp,0.0_dp)
  TYPE(ONUMM6N1), PARAMETER :: E4 = ONUMM6N1(0.0_dp,0.0_dp,0.0_dp,0.0_dp,1.0_dp,0.0_dp,0.0_dp)
  TYPE(ONUMM6N1), PARAMETER :: E5 = ONUMM6N1(0.0_dp,0.0_dp,0.0_dp,0.0_dp,0.0_dp,1.0_dp,0.0_dp)
  TYPE(ONUMM6N1), PARAMETER :: E6 = ONUMM6N1(0.0_dp,0.0_dp,0.0_dp,0.0_dp,0.0_dp,0.0_dp,1.0_dp)


  INTERFACE OPERATOR(*)
    MODULE PROCEDURE ONUMM6N1_MUL_OO_SS,ONUMM6N1_MUL_RO_SS,ONUMM6N1_MUL_OR_SS,ONUMM6N1_MUL_OO_VS,&
                     ONUMM6N1_MUL_RO_VS,ONUMM6N1_MUL_OR_VS,ONUMM6N1_MUL_OO_MS,ONUMM6N1_MUL_RO_MS,&
                     ONUMM6N1_MUL_OR_MS,ONUMM6N1_MUL_OO_SV,ONUMM6N1_MUL_RO_SV,ONUMM6N1_MUL_OR_SV,&
                     ONUMM6N1_MUL_OO_SM,ONUMM6N1_MUL_RO_SM,ONUMM6N1_MUL_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(+)
    MODULE PROCEDURE ONUMM6N1_ADD_OO_SS,ONUMM6N1_ADD_RO_SS,ONUMM6N1_ADD_OR_SS,ONUMM6N1_ADD_OO_VS,&
                     ONUMM6N1_ADD_RO_VS,ONUMM6N1_ADD_OR_VS,ONUMM6N1_ADD_OO_MS,ONUMM6N1_ADD_RO_MS,&
                     ONUMM6N1_ADD_OR_MS,ONUMM6N1_ADD_OO_SV,ONUMM6N1_ADD_RO_SV,ONUMM6N1_ADD_OR_SV,&
                     ONUMM6N1_ADD_OO_SM,ONUMM6N1_ADD_RO_SM,ONUMM6N1_ADD_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(-)
    MODULE PROCEDURE ONUMM6N1_NEG,ONUMM6N1_SUB_OO_SS,ONUMM6N1_SUB_RO_SS,ONUMM6N1_SUB_OR_SS,&
                     ONUMM6N1_SUB_OO_VS,ONUMM6N1_SUB_RO_VS,ONUMM6N1_SUB_OR_VS,ONUMM6N1_SUB_OO_MS,&
                     ONUMM6N1_SUB_RO_MS,ONUMM6N1_SUB_OR_MS,ONUMM6N1_SUB_OO_SV,ONUMM6N1_SUB_RO_SV,&
                     ONUMM6N1_SUB_OR_SV,ONUMM6N1_SUB_OO_SM,ONUMM6N1_SUB_RO_SM,ONUMM6N1_SUB_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(/)
    MODULE PROCEDURE ONUMM6N1_DIVISION_OO,ONUMM6N1_DIVISION_OR,ONUMM6N1_DIVISION_RO
  END INTERFACE

  INTERFACE ASSIGNMENT(=)
    MODULE PROCEDURE ONUMM6N1_ASSIGN_R
  END INTERFACE

  INTERFACE OPERATOR(**)
    MODULE PROCEDURE ONUMM6N1_POW_OR,ONUMM6N1_POW_RO,ONUMM6N1_POW_I8O,ONUMM6N1_POW_I4O,&
                     ONUMM6N1_POW_OI8,ONUMM6N1_POW_OI4,ONUMM6N1_POW_OO
  END INTERFACE

  INTERFACE OPERATOR(==)
    MODULE PROCEDURE ONUMM6N1_EQ_OO_SS,ONUMM6N1_EQ_RO_SS,ONUMM6N1_EQ_OR_SS,ONUMM6N1_EQ_OO_VS,&
                     ONUMM6N1_EQ_RO_VS,ONUMM6N1_EQ_OR_VS,ONUMM6N1_EQ_OO_MS,ONUMM6N1_EQ_RO_MS,&
                     ONUMM6N1_EQ_OR_MS,ONUMM6N1_EQ_OO_SV,ONUMM6N1_EQ_RO_SV,ONUMM6N1_EQ_OR_SV,&
                     ONUMM6N1_EQ_OO_SM,ONUMM6N1_EQ_RO_SM,ONUMM6N1_EQ_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(/=)
    MODULE PROCEDURE ONUMM6N1_NE_OO_SS,ONUMM6N1_NE_RO_SS,ONUMM6N1_NE_OR_SS,ONUMM6N1_NE_OO_VS,&
                     ONUMM6N1_NE_RO_VS,ONUMM6N1_NE_OR_VS,ONUMM6N1_NE_OO_MS,ONUMM6N1_NE_RO_MS,&
                     ONUMM6N1_NE_OR_MS,ONUMM6N1_NE_OO_SV,ONUMM6N1_NE_RO_SV,ONUMM6N1_NE_OR_SV,&
                     ONUMM6N1_NE_OO_SM,ONUMM6N1_NE_RO_SM,ONUMM6N1_NE_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(>=)
    MODULE PROCEDURE ONUMM6N1_GE_OO_SS,ONUMM6N1_GE_RO_SS,ONUMM6N1_GE_OR_SS,ONUMM6N1_GE_OO_VS,&
                     ONUMM6N1_GE_RO_VS,ONUMM6N1_GE_OR_VS,ONUMM6N1_GE_OO_MS,ONUMM6N1_GE_RO_MS,&
                     ONUMM6N1_GE_OR_MS,ONUMM6N1_GE_OO_SV,ONUMM6N1_GE_RO_SV,ONUMM6N1_GE_OR_SV,&
                     ONUMM6N1_GE_OO_SM,ONUMM6N1_GE_RO_SM,ONUMM6N1_GE_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(<=)
    MODULE PROCEDURE ONUMM6N1_LE_OO_SS,ONUMM6N1_LE_RO_SS,ONUMM6N1_LE_OR_SS,ONUMM6N1_LE_OO_VS,&
                     ONUMM6N1_LE_RO_VS,ONUMM6N1_LE_OR_VS,ONUMM6N1_LE_OO_MS,ONUMM6N1_LE_RO_MS,&
                     ONUMM6N1_LE_OR_MS,ONUMM6N1_LE_OO_SV,ONUMM6N1_LE_RO_SV,ONUMM6N1_LE_OR_SV,&
                     ONUMM6N1_LE_OO_SM,ONUMM6N1_LE_RO_SM,ONUMM6N1_LE_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(>)
    MODULE PROCEDURE ONUMM6N1_GT_OO_SS,ONUMM6N1_GT_RO_SS,ONUMM6N1_GT_OR_SS,ONUMM6N1_GT_OO_VS,&
                     ONUMM6N1_GT_RO_VS,ONUMM6N1_GT_OR_VS,ONUMM6N1_GT_OO_MS,ONUMM6N1_GT_RO_MS,&
                     ONUMM6N1_GT_OR_MS,ONUMM6N1_GT_OO_SV,ONUMM6N1_GT_RO_SV,ONUMM6N1_GT_OR_SV,&
                     ONUMM6N1_GT_OO_SM,ONUMM6N1_GT_RO_SM,ONUMM6N1_GT_OR_SM
  END INTERFACE

  INTERFACE OPERATOR(<)
    MODULE PROCEDURE ONUMM6N1_LT_OO_SS,ONUMM6N1_LT_RO_SS,ONUMM6N1_LT_OR_SS,ONUMM6N1_LT_OO_VS,&
                     ONUMM6N1_LT_RO_VS,ONUMM6N1_LT_OR_VS,ONUMM6N1_LT_OO_MS,ONUMM6N1_LT_RO_MS,&
                     ONUMM6N1_LT_OR_MS,ONUMM6N1_LT_OO_SV,ONUMM6N1_LT_RO_SV,ONUMM6N1_LT_OR_SV,&
                     ONUMM6N1_LT_OO_SM,ONUMM6N1_LT_RO_SM,ONUMM6N1_LT_OR_SM
  END INTERFACE

  INTERFACE PPRINT
    MODULE PROCEDURE ONUMM6N1_PPRINT_S,ONUMM6N1_PPRINT_V,ONUMM6N1_PPRINT_M
  END INTERFACE

  INTERFACE TRANSPOSE
    MODULE PROCEDURE ONUMM6N1_TRANSPOSE
  END INTERFACE

  INTERFACE MATMUL
    MODULE PROCEDURE ONUMM6N1_MATMUL_ONUMM6N1,R_MATMUL_ONUMM6N1,ONUMM6N1_MATMUL_R
  END INTERFACE

  INTERFACE DOT_PRODUCT
    MODULE PROCEDURE ONUMM6N1_DOT_PRODUCT_ONUMM6N1,R_DOT_PRODUCT_ONUMM6N1,ONUMM6N1_DOT_PRODUCT_R
  END INTERFACE

  INTERFACE UNFOLD
    MODULE PROCEDURE ONUMM6N1_TO_CR_MAT_S,ONUMM6N1_TO_CR_MAT_V,ONUMM6N1_TO_CR_MAT_M
  END INTERFACE

  INTERFACE TO_CR
    MODULE PROCEDURE ONUMM6N1_TO_CR_MAT_S,ONUMM6N1_TO_CR_MAT_V,ONUMM6N1_TO_CR_MAT_M
  END INTERFACE

  INTERFACE SIN
    MODULE PROCEDURE ONUMM6N1_SIN
  END INTERFACE

  INTERFACE COS
    MODULE PROCEDURE ONUMM6N1_COS
  END INTERFACE

  INTERFACE TAN
    MODULE PROCEDURE ONUMM6N1_TAN
  END INTERFACE

  INTERFACE ASIN
    MODULE PROCEDURE ONUMM6N1_ASIN
  END INTERFACE

  INTERFACE ACOS
    MODULE PROCEDURE ONUMM6N1_ACOS
  END INTERFACE

  INTERFACE ATAN
    MODULE PROCEDURE ONUMM6N1_ATAN
  END INTERFACE

  INTERFACE SINH
    MODULE PROCEDURE ONUMM6N1_SINH
  END INTERFACE

  INTERFACE COSH
    MODULE PROCEDURE ONUMM6N1_COSH
  END INTERFACE

  INTERFACE TANH
    MODULE PROCEDURE ONUMM6N1_TANH
  END INTERFACE

  INTERFACE SQRT
    MODULE PROCEDURE ONUMM6N1_SQRT
  END INTERFACE

  INTERFACE LOG
    MODULE PROCEDURE ONUMM6N1_LOG
  END INTERFACE

  INTERFACE EXP
    MODULE PROCEDURE ONUMM6N1_EXP
  END INTERFACE

  INTERFACE GEM
    MODULE PROCEDURE ONUMM6N1_GEM_OOO,ONUMM6N1_GEM_ROO,ONUMM6N1_GEM_ORO
  END INTERFACE

  INTERFACE FEVAL
    MODULE PROCEDURE ONUMM6N1_FEVAL
  END INTERFACE

  INTERFACE F2EVAL
    MODULE PROCEDURE ONUMM6N1_F2EVAL
  END INTERFACE

  INTERFACE REAL
    MODULE PROCEDURE ONUMM6N1_REAL
  END INTERFACE

  INTERFACE DET2X2
    MODULE PROCEDURE ONUMM6N1_det2x2
  END INTERFACE

  INTERFACE DET3X3
    MODULE PROCEDURE ONUMM6N1_det3x3
  END INTERFACE

  INTERFACE DET4X4
    MODULE PROCEDURE ONUMM6N1_det4x4
  END INTERFACE

  INTERFACE INV2X2
    MODULE PROCEDURE ONUMM6N1_INV2X2
  END INTERFACE

  INTERFACE INV3X3
    MODULE PROCEDURE ONUMM6N1_INV3X3
  END INTERFACE

  INTERFACE INV4X4
    MODULE PROCEDURE ONUMM6N1_INV4X4
  END INTERFACE

  INTERFACE GETIM
    MODULE PROCEDURE ONUMM6N1_GETIM_S,ONUMM6N1_GETIM_V,ONUMM6N1_GETIM_M
  END INTERFACE

  INTERFACE SETIM
    MODULE PROCEDURE ONUMM6N1_SETIM_S,ONUMM6N1_SETIM_V,ONUMM6N1_SETIM_M
  END INTERFACE

  INTERFACE MAX
    MODULE PROCEDURE ONUMM6N1_MAX
  END INTERFACE

  INTERFACE MIN
    MODULE PROCEDURE ONUMM6N1_MIN
  END INTERFACE

  INTERFACE MAXLOC
    MODULE PROCEDURE ONUMM6N1_MAXLOC_R1,ONUMM6N1_MAXLOC_R2,ONUMM6N1_MAXLOC_R3,ONUMM6N1_MAXLOC_R4
  END INTERFACE

  INTERFACE MAXVAL
    MODULE PROCEDURE ONUMM6N1_MAXVAL_R1,ONUMM6N1_MAXVAL_R2,ONUMM6N1_MAXVAL_R3,ONUMM6N1_MAXVAL_R4
  END INTERFACE

  INTERFACE MINLOC
    MODULE PROCEDURE ONUMM6N1_MINLOC_R1,ONUMM6N1_MINLOC_R2,ONUMM6N1_MINLOC_R3,ONUMM6N1_MINLOC_R4
  END INTERFACE

  INTERFACE MINVAL
    MODULE PROCEDURE ONUMM6N1_MINVAL_R1,ONUMM6N1_MINVAL_R2,ONUMM6N1_MINVAL_R3,ONUMM6N1_MINVAL_R4
  END INTERFACE

  INTERFACE ABS
    MODULE PROCEDURE ONUMM6N1_ABS
  END INTERFACE ABS
  INTERFACE KOTI_NORM
    MODULE PROCEDURE KOTI_NORM_ONUMM6N1
  END INTERFACE KOTI_NORM
  CONTAINS

  ELEMENTAL SUBROUTINE ONUMM6N1_ASSIGN_R(RES,LHS)
    
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS 
    TYPE(ONUMM6N1), INTENT(OUT) :: RES 

    ! Assign like function 'LHS'
    ! Real
    RES%R = LHS

    ! Order 1
    RES%E1 = 0.0_dp
    RES%E2 = 0.0_dp
    RES%E3 = 0.0_dp
    RES%E4 = 0.0_dp
    RES%E5 = 0.0_dp
    RES%E6 = 0.0_dp

  END SUBROUTINE ONUMM6N1_ASSIGN_R

  ELEMENTAL FUNCTION ONUMM6N1_NEG(LHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS 
    TYPE(ONUMM6N1) :: RES 

    ! Negation like function '-LHS'
    ! Real
    RES%R = -LHS%R
    ! Order 1
    RES%E1 = -LHS%E1
    RES%E2 = -LHS%E2
    RES%E3 = -LHS%E3
    RES%E4 = -LHS%E4
    RES%E5 = -LHS%E5
    RES%E6 = -LHS%E6

  END FUNCTION ONUMM6N1_NEG

  ELEMENTAL FUNCTION ONUMM6N1_ADD_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Addition like function 'LHS + RHS'
    !  Real
    RES%R = LHS%R + RHS%R

    ! Order 1
    RES%E1 = LHS%E1 + RHS%E1
    RES%E2 = LHS%E2 + RHS%E2
    RES%E3 = LHS%E3 + RHS%E3
    RES%E4 = LHS%E4 + RHS%E4
    RES%E5 = LHS%E5 + RHS%E5
    RES%E6 = LHS%E6 + RHS%E6

  END FUNCTION ONUMM6N1_ADD_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_ADD_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS + RHS%R

    ! Order 1
    RES%E1 =  + RHS%E1
    RES%E2 =  + RHS%E2
    RES%E3 =  + RHS%E3
    RES%E4 =  + RHS%E4
    RES%E5 =  + RHS%E5
    RES%E6 =  + RHS%E6

  END FUNCTION ONUMM6N1_ADD_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_ADD_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS%R + RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_ADD_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_SUB_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Addition like function 'LHS - RHS'
    !  Real
    RES%R = LHS%R - RHS%R

    ! Order 1
    RES%E1 = LHS%E1 - RHS%E1
    RES%E2 = LHS%E2 - RHS%E2
    RES%E3 = LHS%E3 - RHS%E3
    RES%E4 = LHS%E4 - RHS%E4
    RES%E5 = LHS%E5 - RHS%E5
    RES%E6 = LHS%E6 - RHS%E6

  END FUNCTION ONUMM6N1_SUB_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_SUB_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS - RHS%R

    ! Order 1
    RES%E1 =  - RHS%E1
    RES%E2 =  - RHS%E2
    RES%E3 =  - RHS%E3
    RES%E4 =  - RHS%E4
    RES%E5 =  - RHS%E5
    RES%E6 =  - RHS%E6

  END FUNCTION ONUMM6N1_SUB_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_SUB_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS%R - RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_SUB_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_MUL_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    !  Multiplication like function 'LHS*RHS'
    ! Order 1
    RES%E1 = LHS%R*RHS%E1 + LHS%E1*RHS%R
    RES%E2 = LHS%R*RHS%E2 + LHS%E2*RHS%R
    RES%E3 = LHS%R*RHS%E3 + LHS%E3*RHS%R
    RES%E4 = LHS%R*RHS%E4 + LHS%E4*RHS%R
    RES%E5 = LHS%R*RHS%E5 + LHS%E5*RHS%R
    RES%E6 = LHS%R*RHS%E6 + LHS%E6*RHS%R
    ! Order 0
    RES%R = LHS%R*RHS%R

  END FUNCTION ONUMM6N1_MUL_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_MUL_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS*RHS%R

    ! Order 1
    RES%E1 = LHS*RHS%E1
    RES%E2 = LHS*RHS%E2
    RES%E3 = LHS*RHS%E3
    RES%E4 = LHS*RHS%E4
    RES%E5 = LHS*RHS%E5
    RES%E6 = LHS*RHS%E6

  END FUNCTION ONUMM6N1_MUL_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_MUL_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS%R*RHS

    ! Order 1
    RES%E1 = LHS%E1*RHS
    RES%E2 = LHS%E2*RHS
    RES%E3 = LHS%E3*RHS
    RES%E4 = LHS%E4*RHS
    RES%E5 = LHS%E5*RHS
    RES%E6 = LHS%E6*RHS

  END FUNCTION ONUMM6N1_MUL_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_EQ_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS%R

  END FUNCTION ONUMM6N1_EQ_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_EQ_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS == RHS%R

  END FUNCTION ONUMM6N1_EQ_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_EQ_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS

  END FUNCTION ONUMM6N1_EQ_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_NE_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS%R

  END FUNCTION ONUMM6N1_NE_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_NE_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS /= RHS%R

  END FUNCTION ONUMM6N1_NE_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_NE_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS

  END FUNCTION ONUMM6N1_NE_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_LT_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS%R

  END FUNCTION ONUMM6N1_LT_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_LT_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS < RHS%R

  END FUNCTION ONUMM6N1_LT_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_LT_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS

  END FUNCTION ONUMM6N1_LT_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_GT_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS%R

  END FUNCTION ONUMM6N1_GT_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_GT_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS > RHS%R

  END FUNCTION ONUMM6N1_GT_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_GT_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS

  END FUNCTION ONUMM6N1_GT_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_LE_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS%R

  END FUNCTION ONUMM6N1_LE_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_LE_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS <= RHS%R

  END FUNCTION ONUMM6N1_LE_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_LE_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS

  END FUNCTION ONUMM6N1_LE_OR_SS

  ELEMENTAL FUNCTION ONUMM6N1_GE_OO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS%R

  END FUNCTION ONUMM6N1_GE_OO_SS

  ELEMENTAL FUNCTION ONUMM6N1_GE_RO_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS >= RHS%R

  END FUNCTION ONUMM6N1_GE_RO_SS

  ELEMENTAL FUNCTION ONUMM6N1_GE_OR_SS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS

  END FUNCTION ONUMM6N1_GE_OR_SS

  FUNCTION ONUMM6N1_ADD_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Addition like function 'LHS + RHS'
    !  Real
    RES%R = LHS%R + RHS%R

    ! Order 1
    RES%E1 = LHS%E1 + RHS%E1
    RES%E2 = LHS%E2 + RHS%E2
    RES%E3 = LHS%E3 + RHS%E3
    RES%E4 = LHS%E4 + RHS%E4
    RES%E5 = LHS%E5 + RHS%E5
    RES%E6 = LHS%E6 + RHS%E6

  END FUNCTION ONUMM6N1_ADD_OO_VS

  FUNCTION ONUMM6N1_ADD_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS + RHS%R

    ! Order 1
    RES%E1 =  + RHS%E1
    RES%E2 =  + RHS%E2
    RES%E3 =  + RHS%E3
    RES%E4 =  + RHS%E4
    RES%E5 =  + RHS%E5
    RES%E6 =  + RHS%E6

  END FUNCTION ONUMM6N1_ADD_RO_VS

  FUNCTION ONUMM6N1_ADD_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS%R + RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_ADD_OR_VS

  FUNCTION ONUMM6N1_SUB_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Addition like function 'LHS - RHS'
    !  Real
    RES%R = LHS%R - RHS%R

    ! Order 1
    RES%E1 = LHS%E1 - RHS%E1
    RES%E2 = LHS%E2 - RHS%E2
    RES%E3 = LHS%E3 - RHS%E3
    RES%E4 = LHS%E4 - RHS%E4
    RES%E5 = LHS%E5 - RHS%E5
    RES%E6 = LHS%E6 - RHS%E6

  END FUNCTION ONUMM6N1_SUB_OO_VS

  FUNCTION ONUMM6N1_SUB_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS - RHS%R

    ! Order 1
    RES%E1 =  - RHS%E1
    RES%E2 =  - RHS%E2
    RES%E3 =  - RHS%E3
    RES%E4 =  - RHS%E4
    RES%E5 =  - RHS%E5
    RES%E6 =  - RHS%E6

  END FUNCTION ONUMM6N1_SUB_RO_VS

  FUNCTION ONUMM6N1_SUB_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS%R - RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_SUB_OR_VS

  FUNCTION ONUMM6N1_MUL_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    !  Multiplication like function 'LHS*RHS'
    ! Order 1
    RES%E1 = LHS%R*RHS%E1 + LHS%E1*RHS%R
    RES%E2 = LHS%R*RHS%E2 + LHS%E2*RHS%R
    RES%E3 = LHS%R*RHS%E3 + LHS%E3*RHS%R
    RES%E4 = LHS%R*RHS%E4 + LHS%E4*RHS%R
    RES%E5 = LHS%R*RHS%E5 + LHS%E5*RHS%R
    RES%E6 = LHS%R*RHS%E6 + LHS%E6*RHS%R
    ! Order 0
    RES%R = LHS%R*RHS%R

  END FUNCTION ONUMM6N1_MUL_OO_VS

  FUNCTION ONUMM6N1_MUL_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS*RHS%R

    ! Order 1
    RES%E1 = LHS*RHS%E1
    RES%E2 = LHS*RHS%E2
    RES%E3 = LHS*RHS%E3
    RES%E4 = LHS*RHS%E4
    RES%E5 = LHS*RHS%E5
    RES%E6 = LHS*RHS%E6

  END FUNCTION ONUMM6N1_MUL_RO_VS

  FUNCTION ONUMM6N1_MUL_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS%R*RHS

    ! Order 1
    RES%E1 = LHS%E1*RHS
    RES%E2 = LHS%E2*RHS
    RES%E3 = LHS%E3*RHS
    RES%E4 = LHS%E4*RHS
    RES%E5 = LHS%E5*RHS
    RES%E6 = LHS%E6*RHS

  END FUNCTION ONUMM6N1_MUL_OR_VS

  FUNCTION ONUMM6N1_EQ_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS%R

  END FUNCTION ONUMM6N1_EQ_OO_VS

  FUNCTION ONUMM6N1_EQ_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS == RHS%R

  END FUNCTION ONUMM6N1_EQ_RO_VS

  FUNCTION ONUMM6N1_EQ_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS

  END FUNCTION ONUMM6N1_EQ_OR_VS

  FUNCTION ONUMM6N1_NE_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS%R

  END FUNCTION ONUMM6N1_NE_OO_VS

  FUNCTION ONUMM6N1_NE_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS /= RHS%R

  END FUNCTION ONUMM6N1_NE_RO_VS

  FUNCTION ONUMM6N1_NE_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS

  END FUNCTION ONUMM6N1_NE_OR_VS

  FUNCTION ONUMM6N1_LT_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS%R

  END FUNCTION ONUMM6N1_LT_OO_VS

  FUNCTION ONUMM6N1_LT_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS < RHS%R

  END FUNCTION ONUMM6N1_LT_RO_VS

  FUNCTION ONUMM6N1_LT_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS

  END FUNCTION ONUMM6N1_LT_OR_VS

  FUNCTION ONUMM6N1_GT_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS%R

  END FUNCTION ONUMM6N1_GT_OO_VS

  FUNCTION ONUMM6N1_GT_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS > RHS%R

  END FUNCTION ONUMM6N1_GT_RO_VS

  FUNCTION ONUMM6N1_GT_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS

  END FUNCTION ONUMM6N1_GT_OR_VS

  FUNCTION ONUMM6N1_LE_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS%R

  END FUNCTION ONUMM6N1_LE_OO_VS

  FUNCTION ONUMM6N1_LE_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS <= RHS%R

  END FUNCTION ONUMM6N1_LE_RO_VS

  FUNCTION ONUMM6N1_LE_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS

  END FUNCTION ONUMM6N1_LE_OR_VS

  FUNCTION ONUMM6N1_GE_OO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS%R

  END FUNCTION ONUMM6N1_GE_OO_VS

  FUNCTION ONUMM6N1_GE_RO_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS >= RHS%R

  END FUNCTION ONUMM6N1_GE_RO_VS

  FUNCTION ONUMM6N1_GE_OR_VS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS

  END FUNCTION ONUMM6N1_GE_OR_VS

  FUNCTION ONUMM6N1_ADD_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Addition like function 'LHS + RHS'
    !  Real
    RES%R = LHS%R + RHS%R

    ! Order 1
    RES%E1 = LHS%E1 + RHS%E1
    RES%E2 = LHS%E2 + RHS%E2
    RES%E3 = LHS%E3 + RHS%E3
    RES%E4 = LHS%E4 + RHS%E4
    RES%E5 = LHS%E5 + RHS%E5
    RES%E6 = LHS%E6 + RHS%E6

  END FUNCTION ONUMM6N1_ADD_OO_MS

  FUNCTION ONUMM6N1_ADD_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS + RHS%R

    ! Order 1
    RES%E1 =  + RHS%E1
    RES%E2 =  + RHS%E2
    RES%E3 =  + RHS%E3
    RES%E4 =  + RHS%E4
    RES%E5 =  + RHS%E5
    RES%E6 =  + RHS%E6

  END FUNCTION ONUMM6N1_ADD_RO_MS

  FUNCTION ONUMM6N1_ADD_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS%R + RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_ADD_OR_MS

  FUNCTION ONUMM6N1_SUB_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Addition like function 'LHS - RHS'
    !  Real
    RES%R = LHS%R - RHS%R

    ! Order 1
    RES%E1 = LHS%E1 - RHS%E1
    RES%E2 = LHS%E2 - RHS%E2
    RES%E3 = LHS%E3 - RHS%E3
    RES%E4 = LHS%E4 - RHS%E4
    RES%E5 = LHS%E5 - RHS%E5
    RES%E6 = LHS%E6 - RHS%E6

  END FUNCTION ONUMM6N1_SUB_OO_MS

  FUNCTION ONUMM6N1_SUB_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS - RHS%R

    ! Order 1
    RES%E1 =  - RHS%E1
    RES%E2 =  - RHS%E2
    RES%E3 =  - RHS%E3
    RES%E4 =  - RHS%E4
    RES%E5 =  - RHS%E5
    RES%E6 =  - RHS%E6

  END FUNCTION ONUMM6N1_SUB_RO_MS

  FUNCTION ONUMM6N1_SUB_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS%R - RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_SUB_OR_MS

  FUNCTION ONUMM6N1_MUL_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    !  Multiplication like function 'LHS*RHS'
    ! Order 1
    RES%E1 = LHS%R*RHS%E1 + LHS%E1*RHS%R
    RES%E2 = LHS%R*RHS%E2 + LHS%E2*RHS%R
    RES%E3 = LHS%R*RHS%E3 + LHS%E3*RHS%R
    RES%E4 = LHS%R*RHS%E4 + LHS%E4*RHS%R
    RES%E5 = LHS%R*RHS%E5 + LHS%E5*RHS%R
    RES%E6 = LHS%R*RHS%E6 + LHS%E6*RHS%R
    ! Order 0
    RES%R = LHS%R*RHS%R

  END FUNCTION ONUMM6N1_MUL_OO_MS

  FUNCTION ONUMM6N1_MUL_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS*RHS%R

    ! Order 1
    RES%E1 = LHS*RHS%E1
    RES%E2 = LHS*RHS%E2
    RES%E3 = LHS*RHS%E3
    RES%E4 = LHS*RHS%E4
    RES%E5 = LHS*RHS%E5
    RES%E6 = LHS*RHS%E6

  END FUNCTION ONUMM6N1_MUL_RO_MS

  FUNCTION ONUMM6N1_MUL_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS%R*RHS

    ! Order 1
    RES%E1 = LHS%E1*RHS
    RES%E2 = LHS%E2*RHS
    RES%E3 = LHS%E3*RHS
    RES%E4 = LHS%E4*RHS
    RES%E5 = LHS%E5*RHS
    RES%E6 = LHS%E6*RHS

  END FUNCTION ONUMM6N1_MUL_OR_MS

  FUNCTION ONUMM6N1_EQ_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS%R

  END FUNCTION ONUMM6N1_EQ_OO_MS

  FUNCTION ONUMM6N1_EQ_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS == RHS%R

  END FUNCTION ONUMM6N1_EQ_RO_MS

  FUNCTION ONUMM6N1_EQ_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS

  END FUNCTION ONUMM6N1_EQ_OR_MS

  FUNCTION ONUMM6N1_NE_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS%R

  END FUNCTION ONUMM6N1_NE_OO_MS

  FUNCTION ONUMM6N1_NE_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS /= RHS%R

  END FUNCTION ONUMM6N1_NE_RO_MS

  FUNCTION ONUMM6N1_NE_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS

  END FUNCTION ONUMM6N1_NE_OR_MS

  FUNCTION ONUMM6N1_LT_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS%R

  END FUNCTION ONUMM6N1_LT_OO_MS

  FUNCTION ONUMM6N1_LT_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS < RHS%R

  END FUNCTION ONUMM6N1_LT_RO_MS

  FUNCTION ONUMM6N1_LT_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS

  END FUNCTION ONUMM6N1_LT_OR_MS

  FUNCTION ONUMM6N1_GT_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS%R

  END FUNCTION ONUMM6N1_GT_OO_MS

  FUNCTION ONUMM6N1_GT_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS > RHS%R

  END FUNCTION ONUMM6N1_GT_RO_MS

  FUNCTION ONUMM6N1_GT_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS

  END FUNCTION ONUMM6N1_GT_OR_MS

  FUNCTION ONUMM6N1_LE_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS%R

  END FUNCTION ONUMM6N1_LE_OO_MS

  FUNCTION ONUMM6N1_LE_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS <= RHS%R

  END FUNCTION ONUMM6N1_LE_RO_MS

  FUNCTION ONUMM6N1_LE_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS

  END FUNCTION ONUMM6N1_LE_OR_MS

  FUNCTION ONUMM6N1_GE_OO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS%R

  END FUNCTION ONUMM6N1_GE_OO_MS

  FUNCTION ONUMM6N1_GE_RO_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS >= RHS%R

  END FUNCTION ONUMM6N1_GE_RO_MS

  FUNCTION ONUMM6N1_GE_OR_MS(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS
    LOGICAL :: RES(SIZE(LHS,1),SIZE(LHS,2)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS

  END FUNCTION ONUMM6N1_GE_OR_MS

  FUNCTION ONUMM6N1_ADD_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Addition like function 'LHS + RHS'
    !  Real
    RES%R = LHS%R + RHS%R

    ! Order 1
    RES%E1 = LHS%E1 + RHS%E1
    RES%E2 = LHS%E2 + RHS%E2
    RES%E3 = LHS%E3 + RHS%E3
    RES%E4 = LHS%E4 + RHS%E4
    RES%E5 = LHS%E5 + RHS%E5
    RES%E6 = LHS%E6 + RHS%E6

  END FUNCTION ONUMM6N1_ADD_OO_SV

  FUNCTION ONUMM6N1_ADD_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS + RHS%R

    ! Order 1
    RES%E1 =  + RHS%E1
    RES%E2 =  + RHS%E2
    RES%E3 =  + RHS%E3
    RES%E4 =  + RHS%E4
    RES%E5 =  + RHS%E5
    RES%E6 =  + RHS%E6

  END FUNCTION ONUMM6N1_ADD_RO_SV

  FUNCTION ONUMM6N1_ADD_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS%R + RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_ADD_OR_SV

  FUNCTION ONUMM6N1_SUB_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Addition like function 'LHS - RHS'
    !  Real
    RES%R = LHS%R - RHS%R

    ! Order 1
    RES%E1 = LHS%E1 - RHS%E1
    RES%E2 = LHS%E2 - RHS%E2
    RES%E3 = LHS%E3 - RHS%E3
    RES%E4 = LHS%E4 - RHS%E4
    RES%E5 = LHS%E5 - RHS%E5
    RES%E6 = LHS%E6 - RHS%E6

  END FUNCTION ONUMM6N1_SUB_OO_SV

  FUNCTION ONUMM6N1_SUB_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS - RHS%R

    ! Order 1
    RES%E1 =  - RHS%E1
    RES%E2 =  - RHS%E2
    RES%E3 =  - RHS%E3
    RES%E4 =  - RHS%E4
    RES%E5 =  - RHS%E5
    RES%E6 =  - RHS%E6

  END FUNCTION ONUMM6N1_SUB_RO_SV

  FUNCTION ONUMM6N1_SUB_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS%R - RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_SUB_OR_SV

  FUNCTION ONUMM6N1_MUL_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    !  Multiplication like function 'LHS*RHS'
    ! Order 1
    RES%E1 = LHS%R*RHS%E1 + LHS%E1*RHS%R
    RES%E2 = LHS%R*RHS%E2 + LHS%E2*RHS%R
    RES%E3 = LHS%R*RHS%E3 + LHS%E3*RHS%R
    RES%E4 = LHS%R*RHS%E4 + LHS%E4*RHS%R
    RES%E5 = LHS%R*RHS%E5 + LHS%E5*RHS%R
    RES%E6 = LHS%R*RHS%E6 + LHS%E6*RHS%R
    ! Order 0
    RES%R = LHS%R*RHS%R

  END FUNCTION ONUMM6N1_MUL_OO_SV

  FUNCTION ONUMM6N1_MUL_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS*RHS%R

    ! Order 1
    RES%E1 = LHS*RHS%E1
    RES%E2 = LHS*RHS%E2
    RES%E3 = LHS*RHS%E3
    RES%E4 = LHS*RHS%E4
    RES%E5 = LHS*RHS%E5
    RES%E6 = LHS*RHS%E6

  END FUNCTION ONUMM6N1_MUL_RO_SV

  FUNCTION ONUMM6N1_MUL_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS%R*RHS

    ! Order 1
    RES%E1 = LHS%E1*RHS
    RES%E2 = LHS%E2*RHS
    RES%E3 = LHS%E3*RHS
    RES%E4 = LHS%E4*RHS
    RES%E5 = LHS%E5*RHS
    RES%E6 = LHS%E6*RHS

  END FUNCTION ONUMM6N1_MUL_OR_SV

  FUNCTION ONUMM6N1_EQ_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS%R

  END FUNCTION ONUMM6N1_EQ_OO_SV

  FUNCTION ONUMM6N1_EQ_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS == RHS%R

  END FUNCTION ONUMM6N1_EQ_RO_SV

  FUNCTION ONUMM6N1_EQ_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS

  END FUNCTION ONUMM6N1_EQ_OR_SV

  FUNCTION ONUMM6N1_NE_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS%R

  END FUNCTION ONUMM6N1_NE_OO_SV

  FUNCTION ONUMM6N1_NE_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS /= RHS%R

  END FUNCTION ONUMM6N1_NE_RO_SV

  FUNCTION ONUMM6N1_NE_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS

  END FUNCTION ONUMM6N1_NE_OR_SV

  FUNCTION ONUMM6N1_LT_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS%R

  END FUNCTION ONUMM6N1_LT_OO_SV

  FUNCTION ONUMM6N1_LT_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS < RHS%R

  END FUNCTION ONUMM6N1_LT_RO_SV

  FUNCTION ONUMM6N1_LT_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS

  END FUNCTION ONUMM6N1_LT_OR_SV

  FUNCTION ONUMM6N1_GT_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS%R

  END FUNCTION ONUMM6N1_GT_OO_SV

  FUNCTION ONUMM6N1_GT_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS > RHS%R

  END FUNCTION ONUMM6N1_GT_RO_SV

  FUNCTION ONUMM6N1_GT_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS

  END FUNCTION ONUMM6N1_GT_OR_SV

  FUNCTION ONUMM6N1_LE_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS%R

  END FUNCTION ONUMM6N1_LE_OO_SV

  FUNCTION ONUMM6N1_LE_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS <= RHS%R

  END FUNCTION ONUMM6N1_LE_RO_SV

  FUNCTION ONUMM6N1_LE_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS

  END FUNCTION ONUMM6N1_LE_OR_SV

  FUNCTION ONUMM6N1_GE_OO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS%R

  END FUNCTION ONUMM6N1_GE_OO_SV

  FUNCTION ONUMM6N1_GE_RO_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS >= RHS%R

  END FUNCTION ONUMM6N1_GE_RO_SV

  FUNCTION ONUMM6N1_GE_OR_SV(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:)
    LOGICAL :: RES(SIZE(RHS,1)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS

  END FUNCTION ONUMM6N1_GE_OR_SV

  FUNCTION ONUMM6N1_ADD_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Addition like function 'LHS + RHS'
    !  Real
    RES%R = LHS%R + RHS%R

    ! Order 1
    RES%E1 = LHS%E1 + RHS%E1
    RES%E2 = LHS%E2 + RHS%E2
    RES%E3 = LHS%E3 + RHS%E3
    RES%E4 = LHS%E4 + RHS%E4
    RES%E5 = LHS%E5 + RHS%E5
    RES%E6 = LHS%E6 + RHS%E6

  END FUNCTION ONUMM6N1_ADD_OO_SM

  FUNCTION ONUMM6N1_ADD_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS + RHS%R

    ! Order 1
    RES%E1 =  + RHS%E1
    RES%E2 =  + RHS%E2
    RES%E3 =  + RHS%E3
    RES%E4 =  + RHS%E4
    RES%E5 =  + RHS%E5
    RES%E6 =  + RHS%E6

  END FUNCTION ONUMM6N1_ADD_RO_SM

  FUNCTION ONUMM6N1_ADD_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Addition like function 'LHS + RHS'
    ! Real
    RES%R = LHS%R + RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_ADD_OR_SM

  FUNCTION ONUMM6N1_SUB_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Addition like function 'LHS - RHS'
    !  Real
    RES%R = LHS%R - RHS%R

    ! Order 1
    RES%E1 = LHS%E1 - RHS%E1
    RES%E2 = LHS%E2 - RHS%E2
    RES%E3 = LHS%E3 - RHS%E3
    RES%E4 = LHS%E4 - RHS%E4
    RES%E5 = LHS%E5 - RHS%E5
    RES%E6 = LHS%E6 - RHS%E6

  END FUNCTION ONUMM6N1_SUB_OO_SM

  FUNCTION ONUMM6N1_SUB_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS - RHS%R

    ! Order 1
    RES%E1 =  - RHS%E1
    RES%E2 =  - RHS%E2
    RES%E3 =  - RHS%E3
    RES%E4 =  - RHS%E4
    RES%E5 =  - RHS%E5
    RES%E6 =  - RHS%E6

  END FUNCTION ONUMM6N1_SUB_RO_SM

  FUNCTION ONUMM6N1_SUB_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Addition like function 'LHS - RHS'
    ! Real
    RES%R = LHS%R - RHS

    ! Order 1
    RES%E1 = LHS%E1
    RES%E2 = LHS%E2
    RES%E3 = LHS%E3
    RES%E4 = LHS%E4
    RES%E5 = LHS%E5
    RES%E6 = LHS%E6

  END FUNCTION ONUMM6N1_SUB_OR_SM

  FUNCTION ONUMM6N1_MUL_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    !  Multiplication like function 'LHS*RHS'
    ! Order 1
    RES%E1 = LHS%R*RHS%E1 + LHS%E1*RHS%R
    RES%E2 = LHS%R*RHS%E2 + LHS%E2*RHS%R
    RES%E3 = LHS%R*RHS%E3 + LHS%E3*RHS%R
    RES%E4 = LHS%R*RHS%E4 + LHS%E4*RHS%R
    RES%E5 = LHS%R*RHS%E5 + LHS%E5*RHS%R
    RES%E6 = LHS%R*RHS%E6 + LHS%E6*RHS%R
    ! Order 0
    RES%R = LHS%R*RHS%R

  END FUNCTION ONUMM6N1_MUL_OO_SM

  FUNCTION ONUMM6N1_MUL_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS*RHS%R

    ! Order 1
    RES%E1 = LHS*RHS%E1
    RES%E2 = LHS*RHS%E2
    RES%E3 = LHS*RHS%E3
    RES%E4 = LHS*RHS%E4
    RES%E5 = LHS*RHS%E5
    RES%E6 = LHS*RHS%E6

  END FUNCTION ONUMM6N1_MUL_RO_SM

  FUNCTION ONUMM6N1_MUL_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Multiplication like function 'LHS*RHS'
    !  Real
    RES%R = LHS%R*RHS

    ! Order 1
    RES%E1 = LHS%E1*RHS
    RES%E2 = LHS%E2*RHS
    RES%E3 = LHS%E3*RHS
    RES%E4 = LHS%E4*RHS
    RES%E5 = LHS%E5*RHS
    RES%E6 = LHS%E6*RHS

  END FUNCTION ONUMM6N1_MUL_OR_SM

  FUNCTION ONUMM6N1_EQ_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS%R

  END FUNCTION ONUMM6N1_EQ_OO_SM

  FUNCTION ONUMM6N1_EQ_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS == RHS%R

  END FUNCTION ONUMM6N1_EQ_RO_SM

  FUNCTION ONUMM6N1_EQ_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS == RHS'
    ! Compare real-only 
    RES = LHS%R == RHS

  END FUNCTION ONUMM6N1_EQ_OR_SM

  FUNCTION ONUMM6N1_NE_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS%R

  END FUNCTION ONUMM6N1_NE_OO_SM

  FUNCTION ONUMM6N1_NE_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS /= RHS%R

  END FUNCTION ONUMM6N1_NE_RO_SM

  FUNCTION ONUMM6N1_NE_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS /= RHS'
    ! Compare real-only 
    RES = LHS%R /= RHS

  END FUNCTION ONUMM6N1_NE_OR_SM

  FUNCTION ONUMM6N1_LT_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS%R

  END FUNCTION ONUMM6N1_LT_OO_SM

  FUNCTION ONUMM6N1_LT_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS < RHS%R

  END FUNCTION ONUMM6N1_LT_RO_SM

  FUNCTION ONUMM6N1_LT_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS < RHS'
    ! Compare real-only 
    RES = LHS%R < RHS

  END FUNCTION ONUMM6N1_LT_OR_SM

  FUNCTION ONUMM6N1_GT_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS%R

  END FUNCTION ONUMM6N1_GT_OO_SM

  FUNCTION ONUMM6N1_GT_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS > RHS%R

  END FUNCTION ONUMM6N1_GT_RO_SM

  FUNCTION ONUMM6N1_GT_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS > RHS'
    ! Compare real-only 
    RES = LHS%R > RHS

  END FUNCTION ONUMM6N1_GT_OR_SM

  FUNCTION ONUMM6N1_LE_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS%R

  END FUNCTION ONUMM6N1_LE_OO_SM

  FUNCTION ONUMM6N1_LE_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS <= RHS%R

  END FUNCTION ONUMM6N1_LE_RO_SM

  FUNCTION ONUMM6N1_LE_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS <= RHS'
    ! Compare real-only 
    RES = LHS%R <= RHS

  END FUNCTION ONUMM6N1_LE_OR_SM

  FUNCTION ONUMM6N1_GE_OO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS%R

  END FUNCTION ONUMM6N1_GE_OO_SM

  FUNCTION ONUMM6N1_GE_RO_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS >= RHS%R

  END FUNCTION ONUMM6N1_GE_RO_SM

  FUNCTION ONUMM6N1_GE_OR_SM(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS
    REAL(DP), INTENT(IN) :: RHS(:,:)
    LOGICAL :: RES(SIZE(RHS,1),SIZE(RHS,2)) 

    ! Relation like function 'LHS >= RHS'
    ! Compare real-only 
    RES = LHS%R >= RHS

  END FUNCTION ONUMM6N1_GE_OR_SM

ELEMENTAL   FUNCTION ONUMM6N1_GEM_OOO(A,B,C)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A 
    TYPE(ONUMM6N1), INTENT(IN) :: B 
    TYPE(ONUMM6N1), INTENT(IN) :: C 
    TYPE(ONUMM6N1) :: RES 

    !  General multiplication like function 'A*B + C'

    ! Order 0
    RES%R = C%R + A%R*B%R

    ! Order 1
    RES%E1 = C%E1 + A%R*B%E1 + A%E1*B%R
    RES%E2 = C%E2 + A%R*B%E2 + A%E2*B%R
    RES%E3 = C%E3 + A%R*B%E3 + A%E3*B%R
    RES%E4 = C%E4 + A%R*B%E4 + A%E4*B%R
    RES%E5 = C%E5 + A%R*B%E5 + A%E5*B%R
    RES%E6 = C%E6 + A%R*B%E6 + A%E6*B%R

  END FUNCTION ONUMM6N1_GEM_OOO

ELEMENTAL   FUNCTION ONUMM6N1_GEM_ROO(A,B,C)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: A 
    TYPE(ONUMM6N1), INTENT(IN) :: B 
    TYPE(ONUMM6N1), INTENT(IN) :: C 
    TYPE(ONUMM6N1) :: RES 

    !  General multiplication like function 'A*B + C'
    ! Order 1
    RES%E1 = C%E1 + A*B%E1
    RES%E2 = C%E2 + A*B%E2
    RES%E3 = C%E3 + A*B%E3
    RES%E4 = C%E4 + A*B%E4
    RES%E5 = C%E5 + A*B%E5
    RES%E6 = C%E6 + A*B%E6
    ! Order 0
    RES%R = C%R + A*B%R

  END FUNCTION ONUMM6N1_GEM_ROO

ELEMENTAL   FUNCTION ONUMM6N1_GEM_ORO(A,B,C)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: A 
    REAL(DP), INTENT(IN) :: B 
    TYPE(ONUMM6N1), INTENT(IN) :: C 
    TYPE(ONUMM6N1) :: RES 

    !  General multiplication like function 'A*B + C'

    ! Order 0
    RES%R = C%R + A%R*B

    ! Order 1
    RES%E1 = C%E1 + A%E1*B
    RES%E2 = C%E2 + A%E2*B
    RES%E3 = C%E3 + A%E3*B
    RES%E4 = C%E4 + A%E4*B
    RES%E5 = C%E5 + A%E5*B
    RES%E6 = C%E6 + A%E6*B

  END FUNCTION ONUMM6N1_GEM_ORO

  FUNCTION ONUMM6N1_MATMUL_ONUMM6N1(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(RHS,2))

    !  Multiplication like function 'MATMUL(lhs,rhs)'
    ! Order 1
    res%E1 = MATMUL(lhs%R,rhs%E1) + MATMUL(lhs%E1,rhs%R)
    res%E2 = MATMUL(lhs%R,rhs%E2) + MATMUL(lhs%E2,rhs%R)
    res%E3 = MATMUL(lhs%R,rhs%E3) + MATMUL(lhs%E3,rhs%R)
    res%E4 = MATMUL(lhs%R,rhs%E4) + MATMUL(lhs%E4,rhs%R)
    res%E5 = MATMUL(lhs%R,rhs%E5) + MATMUL(lhs%E5,rhs%R)
    res%E6 = MATMUL(lhs%R,rhs%E6) + MATMUL(lhs%E6,rhs%R)
    ! Order 0
    res%R = MATMUL(lhs%R,rhs%R)

  END FUNCTION ONUMM6N1_MATMUL_ONUMM6N1

  FUNCTION R_MATMUL_ONUMM6N1(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(RHS,2))

    ! Multiplication like function 'MATMUL(lhs,rhs)'
    !  Real
    res%R = MATMUL(lhs,rhs%R)

    ! Order 1
    res%E1 = MATMUL(lhs,rhs%E1)
    res%E2 = MATMUL(lhs,rhs%E2)
    res%E3 = MATMUL(lhs,rhs%E3)
    res%E4 = MATMUL(lhs,rhs%E4)
    res%E5 = MATMUL(lhs,rhs%E5)
    res%E6 = MATMUL(lhs,rhs%E6)

  END FUNCTION R_MATMUL_ONUMM6N1

  FUNCTION ONUMM6N1_MATMUL_R(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    REAL(DP), INTENT(IN) :: RHS(:,:)
    TYPE(ONUMM6N1) :: RES(SIZE(LHS,1),SIZE(RHS,2))

    ! Multiplication like function 'MATMUL(lhs,rhs)'
    !  Real
    res%R = MATMUL(lhs%R,rhs)

    ! Order 1
    res%E1 = MATMUL(lhs%E1,rhs)
    res%E2 = MATMUL(lhs%E2,rhs)
    res%E3 = MATMUL(lhs%E3,rhs)
    res%E4 = MATMUL(lhs%E4,rhs)
    res%E5 = MATMUL(lhs%E5,rhs)
    res%E6 = MATMUL(lhs%E6,rhs)

  END FUNCTION ONUMM6N1_MATMUL_R

  FUNCTION ONUMM6N1_DOT_PRODUCT_ONUMM6N1(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(SIZE(LHS))
    TYPE(ONUMM6N1) :: RES

    !  Multiplication like function 'DOT_PRODUCT(lhs,rhs)'
    ! Order 1
    res%E1 = DOT_PRODUCT(lhs%R,rhs%E1) + DOT_PRODUCT(lhs%E1,rhs%R)
    res%E2 = DOT_PRODUCT(lhs%R,rhs%E2) + DOT_PRODUCT(lhs%E2,rhs%R)
    res%E3 = DOT_PRODUCT(lhs%R,rhs%E3) + DOT_PRODUCT(lhs%E3,rhs%R)
    res%E4 = DOT_PRODUCT(lhs%R,rhs%E4) + DOT_PRODUCT(lhs%E4,rhs%R)
    res%E5 = DOT_PRODUCT(lhs%R,rhs%E5) + DOT_PRODUCT(lhs%E5,rhs%R)
    res%E6 = DOT_PRODUCT(lhs%R,rhs%E6) + DOT_PRODUCT(lhs%E6,rhs%R)
    ! Order 0
    res%R = DOT_PRODUCT(lhs%R,rhs%R)

  END FUNCTION ONUMM6N1_DOT_PRODUCT_ONUMM6N1

  FUNCTION R_DOT_PRODUCT_ONUMM6N1(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    REAL(DP), INTENT(IN) :: LHS(:)
    TYPE(ONUMM6N1), INTENT(IN) :: RHS(SIZE(LHS))
    TYPE(ONUMM6N1) :: RES

    ! Multiplication like function 'DOT_PRODUCT(lhs,rhs)'
    !  Real
    res%R = DOT_PRODUCT(lhs,rhs%R)

    ! Order 1
    res%E1 = DOT_PRODUCT(lhs,rhs%E1)
    res%E2 = DOT_PRODUCT(lhs,rhs%E2)
    res%E3 = DOT_PRODUCT(lhs,rhs%E3)
    res%E4 = DOT_PRODUCT(lhs,rhs%E4)
    res%E5 = DOT_PRODUCT(lhs,rhs%E5)
    res%E6 = DOT_PRODUCT(lhs,rhs%E6)

  END FUNCTION R_DOT_PRODUCT_ONUMM6N1

  FUNCTION ONUMM6N1_DOT_PRODUCT_R(LHS,RHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:)
    REAL(DP), INTENT(IN) :: RHS(SIZE(LHS))
    TYPE(ONUMM6N1) :: RES

    ! Multiplication like function 'DOT_PRODUCT(lhs,rhs)'
    !  Real
    res%R = DOT_PRODUCT(lhs%R,rhs)

    ! Order 1
    res%E1 = DOT_PRODUCT(lhs%E1,rhs)
    res%E2 = DOT_PRODUCT(lhs%E2,rhs)
    res%E3 = DOT_PRODUCT(lhs%E3,rhs)
    res%E4 = DOT_PRODUCT(lhs%E4,rhs)
    res%E5 = DOT_PRODUCT(lhs%E5,rhs)
    res%E6 = DOT_PRODUCT(lhs%E6,rhs)

  END FUNCTION ONUMM6N1_DOT_PRODUCT_R

  FUNCTION ONUMM6N1_TRANSPOSE(LHS)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: LHS(:,:)
    TYPE(ONUMM6N1) :: RES (SIZE(LHS,2),SIZE(LHS,1))

    ! Negation like function 'TRANSPOSE(LHS)'
    ! Real
    RES%R = TRANSPOSE(LHS%R)
    ! Order 1
    RES%E1 = TRANSPOSE(LHS%E1)
    RES%E2 = TRANSPOSE(LHS%E2)
    RES%E3 = TRANSPOSE(LHS%E3)
    RES%E4 = TRANSPOSE(LHS%E4)
    RES%E5 = TRANSPOSE(LHS%E5)
    RES%E6 = TRANSPOSE(LHS%E6)

  END FUNCTION ONUMM6N1_TRANSPOSE

FUNCTION ONUMM6N1_TO_CR_MAT_S(VAL) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAL
    REAL(DP) :: RES(NUM_IM_DIR,NUM_IM_DIR) 
    INTEGER :: NCOLS=1, NROWS=1


    ! R x R -> R (1, 1)
    RES(1+NROWS*0:NROWS*1,1+NCOLS*0:NCOLS*1) = VAL%R
    ! R x E1 -> E1 (2, 2)
    RES(1+NROWS*1:NROWS*2,1+NCOLS*1:NCOLS*2) = VAL%R
    ! E1 x R -> E1 (2, 1)
    RES(1+NROWS*1:NROWS*2,1+NCOLS*0:NCOLS*1) = VAL%E1
    ! R x E2 -> E2 (3, 3)
    RES(1+NROWS*2:NROWS*3,1+NCOLS*2:NCOLS*3) = VAL%R
    ! E2 x R -> E2 (3, 1)
    RES(1+NROWS*2:NROWS*3,1+NCOLS*0:NCOLS*1) = VAL%E2
    ! R x E3 -> E3 (4, 4)
    RES(1+NROWS*3:NROWS*4,1+NCOLS*3:NCOLS*4) = VAL%R
    ! E3 x R -> E3 (4, 1)
    RES(1+NROWS*3:NROWS*4,1+NCOLS*0:NCOLS*1) = VAL%E3
    ! R x E4 -> E4 (5, 5)
    RES(1+NROWS*4:NROWS*5,1+NCOLS*4:NCOLS*5) = VAL%R
    ! E4 x R -> E4 (5, 1)
    RES(1+NROWS*4:NROWS*5,1+NCOLS*0:NCOLS*1) = VAL%E4
    ! R x E5 -> E5 (6, 6)
    RES(1+NROWS*5:NROWS*6,1+NCOLS*5:NCOLS*6) = VAL%R
    ! E5 x R -> E5 (6, 1)
    RES(1+NROWS*5:NROWS*6,1+NCOLS*0:NCOLS*1) = VAL%E5
    ! R x E6 -> E6 (7, 7)
    RES(1+NROWS*6:NROWS*7,1+NCOLS*6:NCOLS*7) = VAL%R
    ! E6 x R -> E6 (7, 1)
    RES(1+NROWS*6:NROWS*7,1+NCOLS*0:NCOLS*1) = VAL%E6
  END FUNCTION ONUMM6N1_TO_CR_MAT_S

FUNCTION ONUMM6N1_TO_CR_MAT_V(VAL) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAL(:)
    REAL(DP) :: RES(NUM_IM_DIR*SIZE(VAL,1),NUM_IM_DIR) 
    INTEGER :: NCOLS=1, NROWS=1

    NROWS = SIZE(VAL,1)

    ! R x R -> R (1, 1)
    RES(1+NROWS*0:NROWS*1,1) = VAL%R
    ! R x E1 -> E1 (2, 2)
    RES(1+NROWS*1:NROWS*2,2) = VAL%R
    ! E1 x R -> E1 (2, 1)
    RES(1+NROWS*1:NROWS*2,1) = VAL%E1
    ! R x E2 -> E2 (3, 3)
    RES(1+NROWS*2:NROWS*3,3) = VAL%R
    ! E2 x R -> E2 (3, 1)
    RES(1+NROWS*2:NROWS*3,1) = VAL%E2
    ! R x E3 -> E3 (4, 4)
    RES(1+NROWS*3:NROWS*4,4) = VAL%R
    ! E3 x R -> E3 (4, 1)
    RES(1+NROWS*3:NROWS*4,1) = VAL%E3
    ! R x E4 -> E4 (5, 5)
    RES(1+NROWS*4:NROWS*5,5) = VAL%R
    ! E4 x R -> E4 (5, 1)
    RES(1+NROWS*4:NROWS*5,1) = VAL%E4
    ! R x E5 -> E5 (6, 6)
    RES(1+NROWS*5:NROWS*6,6) = VAL%R
    ! E5 x R -> E5 (6, 1)
    RES(1+NROWS*5:NROWS*6,1) = VAL%E5
    ! R x E6 -> E6 (7, 7)
    RES(1+NROWS*6:NROWS*7,7) = VAL%R
    ! E6 x R -> E6 (7, 1)
    RES(1+NROWS*6:NROWS*7,1) = VAL%E6
  END FUNCTION ONUMM6N1_TO_CR_MAT_V

FUNCTION ONUMM6N1_TO_CR_MAT_M(VAL) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAL(:,:)
    REAL(DP) :: RES(NUM_IM_DIR*SIZE(VAL,1),NUM_IM_DIR*SIZE(VAL,2)) 
    INTEGER :: NCOLS=1, NROWS=1

    NCOLS = SIZE(VAL,1)
    NROWS = SIZE(VAL,2)

    ! R x R -> R (1, 1)
    RES(1+NROWS*0:NROWS*1,1+NCOLS*0:NCOLS*1) = VAL%R
    ! R x E1 -> E1 (2, 2)
    RES(1+NROWS*1:NROWS*2,1+NCOLS*1:NCOLS*2) = VAL%R
    ! E1 x R -> E1 (2, 1)
    RES(1+NROWS*1:NROWS*2,1+NCOLS*0:NCOLS*1) = VAL%E1
    ! R x E2 -> E2 (3, 3)
    RES(1+NROWS*2:NROWS*3,1+NCOLS*2:NCOLS*3) = VAL%R
    ! E2 x R -> E2 (3, 1)
    RES(1+NROWS*2:NROWS*3,1+NCOLS*0:NCOLS*1) = VAL%E2
    ! R x E3 -> E3 (4, 4)
    RES(1+NROWS*3:NROWS*4,1+NCOLS*3:NCOLS*4) = VAL%R
    ! E3 x R -> E3 (4, 1)
    RES(1+NROWS*3:NROWS*4,1+NCOLS*0:NCOLS*1) = VAL%E3
    ! R x E4 -> E4 (5, 5)
    RES(1+NROWS*4:NROWS*5,1+NCOLS*4:NCOLS*5) = VAL%R
    ! E4 x R -> E4 (5, 1)
    RES(1+NROWS*4:NROWS*5,1+NCOLS*0:NCOLS*1) = VAL%E4
    ! R x E5 -> E5 (6, 6)
    RES(1+NROWS*5:NROWS*6,1+NCOLS*5:NCOLS*6) = VAL%R
    ! E5 x R -> E5 (6, 1)
    RES(1+NROWS*5:NROWS*6,1+NCOLS*0:NCOLS*1) = VAL%E5
    ! R x E6 -> E6 (7, 7)
    RES(1+NROWS*6:NROWS*7,1+NCOLS*6:NCOLS*7) = VAL%R
    ! E6 x R -> E6 (7, 1)
    RES(1+NROWS*6:NROWS*7,1+NCOLS*0:NCOLS*1) = VAL%E6
  END FUNCTION ONUMM6N1_TO_CR_MAT_M

    SUBROUTINE ONUMM6N1_SETIM_S(VAL,IDX,RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(INOUT) :: VAL
    REAL(DP),INTENT(IN) :: RES 
    INTEGER, INTENT(IN) :: IDX

    SELECT CASE(IDX)
    ! Order 0
    CASE(0)
      VAL%R=RES

    ! Order 1
    CASE(1)
      VAL%E1=RES
    CASE(2)
      VAL%E2=RES
    CASE(3)
      VAL%E3=RES
    CASE(4)
      VAL%E4=RES
    CASE(5)
      VAL%E5=RES
    CASE(6)
      VAL%E6=RES

    END SELECT
  END SUBROUTINE ONUMM6N1_SETIM_S

    SUBROUTINE ONUMM6N1_SETIM_V(VAL,IDX,RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(INOUT) :: VAL(:)
    REAL(DP),INTENT(IN) :: RES(SIZE(VAL)) 
    INTEGER, INTENT(IN) :: IDX

    SELECT CASE(IDX)
    ! Order 0
    CASE(0)
      VAL%R=RES

    ! Order 1
    CASE(1)
      VAL%E1=RES
    CASE(2)
      VAL%E2=RES
    CASE(3)
      VAL%E3=RES
    CASE(4)
      VAL%E4=RES
    CASE(5)
      VAL%E5=RES
    CASE(6)
      VAL%E6=RES

    END SELECT
  END SUBROUTINE ONUMM6N1_SETIM_V

    SUBROUTINE ONUMM6N1_SETIM_M(VAL,IDX,RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(INOUT) :: VAL(:,:)
    REAL(DP),INTENT(IN) :: RES(SIZE(VAL,1),SIZE(VAL,2)) 
    INTEGER, INTENT(IN) :: IDX

    SELECT CASE(IDX)
    ! Order 0
    CASE(0)
      VAL%R=RES

    ! Order 1
    CASE(1)
      VAL%E1=RES
    CASE(2)
      VAL%E2=RES
    CASE(3)
      VAL%E3=RES
    CASE(4)
      VAL%E4=RES
    CASE(5)
      VAL%E5=RES
    CASE(6)
      VAL%E6=RES

    END SELECT
  END SUBROUTINE ONUMM6N1_SETIM_M

FUNCTION ONUMM6N1_GETIM_S(VAL,IDX) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAL
    REAL(DP) :: RES 
    INTEGER, INTENT(IN) :: IDX

    RES = 0.0_dp

    SELECT CASE(IDX)
    ! Order 0
    CASE(0)
      RES=VAL%R

    ! Order 1
    CASE(1)
      RES=VAL%E1
    CASE(2)
      RES=VAL%E2
    CASE(3)
      RES=VAL%E3
    CASE(4)
      RES=VAL%E4
    CASE(5)
      RES=VAL%E5
    CASE(6)
      RES=VAL%E6

    END SELECT
  END FUNCTION ONUMM6N1_GETIM_S

FUNCTION ONUMM6N1_GETIM_V(VAL,IDX) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAL(:)
    REAL(DP) :: RES(SIZE(VAL)) 
    INTEGER, INTENT(IN) :: IDX

    RES = 0.0_dp

    SELECT CASE(IDX)
    ! Order 0
    CASE(0)
      RES=VAL%R

    ! Order 1
    CASE(1)
      RES=VAL%E1
    CASE(2)
      RES=VAL%E2
    CASE(3)
      RES=VAL%E3
    CASE(4)
      RES=VAL%E4
    CASE(5)
      RES=VAL%E5
    CASE(6)
      RES=VAL%E6

    END SELECT
  END FUNCTION ONUMM6N1_GETIM_V

FUNCTION ONUMM6N1_GETIM_M(VAL,IDX) RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAL(:,:)
    REAL(DP) :: RES(SIZE(VAL,1),SIZE(VAL,2)) 
    INTEGER, INTENT(IN) :: IDX

    RES = 0.0_dp

    SELECT CASE(IDX)
    ! Order 0
    CASE(0)
      RES=VAL%R

    ! Order 1
    CASE(1)
      RES=VAL%E1
    CASE(2)
      RES=VAL%E2
    CASE(3)
      RES=VAL%E3
    CASE(4)
      RES=VAL%E4
    CASE(5)
      RES=VAL%E5
    CASE(6)
      RES=VAL%E6

    END SELECT
  END FUNCTION ONUMM6N1_GETIM_M

  SUBROUTINE ONUMM6N1_PPRINT_S(VAR,FMT,UNIT)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAR
    CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
    INTEGER, INTENT(IN), OPTIONAL :: unit
    CHARACTER(len=:),ALLOCATABLE :: output_format
    INTEGER :: unt

    IF ( PRESENT(unit) ) THEN
      unt = unit
    ELSE
      unt = 6
    END IF

    IF ( PRESENT(fmt) ) THEN
      output_format = '('//trim(fmt)//')'
    ELSE
      output_format = '(F10.4)'
    END IF

    ! Pretty print function.
    !  Real
    CALL PPRINT(VAR%R,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='NO') ' '

    !  Order 1
    WRITE(unt,'(A)',advance='NO') '+ '
    WRITE(unt,'(A)',advance='NO') 'E1 * '
    CALL PPRINT(VAR%E1,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='NO') '+ '
    WRITE(unt,'(A)',advance='NO') 'E2 * '
    CALL PPRINT(VAR%E2,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='NO') '+ '
    WRITE(unt,'(A)',advance='NO') 'E3 * '
    CALL PPRINT(VAR%E3,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='NO') '+ '
    WRITE(unt,'(A)',advance='NO') 'E4 * '
    CALL PPRINT(VAR%E4,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='NO') '+ '
    WRITE(unt,'(A)',advance='NO') 'E5 * '
    CALL PPRINT(VAR%E5,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='NO') '+ '
    WRITE(unt,'(A)',advance='NO') 'E6 * '
    CALL PPRINT(VAR%E6,unit=unt,fmt=output_format)


  END SUBROUTINE ONUMM6N1_PPRINT_S

  SUBROUTINE ONUMM6N1_PPRINT_V(VAR,FMT,UNIT)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAR(:)
    CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
    INTEGER, INTENT(IN), OPTIONAL :: unit
    CHARACTER(len=:),ALLOCATABLE :: output_format
    INTEGER :: unt

    IF ( PRESENT(unit) ) THEN
      unt = unit
    ELSE
      unt = 6
    END IF

    IF ( PRESENT(fmt) ) THEN
      output_format = '('//trim(fmt)//')'
    ELSE
      output_format = '(F10.4)'
    END IF

    ! Pretty print function.
    !  Real
    CALL PPRINT(VAR%R,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') ' '

    !  Order 1
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E1 * '
    CALL PPRINT(VAR%E1,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E2 * '
    CALL PPRINT(VAR%E2,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E3 * '
    CALL PPRINT(VAR%E3,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E4 * '
    CALL PPRINT(VAR%E4,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E5 * '
    CALL PPRINT(VAR%E5,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E6 * '
    CALL PPRINT(VAR%E6,unit=unt,fmt=output_format)


  END SUBROUTINE ONUMM6N1_PPRINT_V

  SUBROUTINE ONUMM6N1_PPRINT_M(VAR,FMT,UNIT)
    IMPLICIT NONE
    TYPE(ONUMM6N1), INTENT(IN) :: VAR(:,:)
    CHARACTER(len=*), INTENT(IN), OPTIONAL :: fmt
    INTEGER, INTENT(IN), OPTIONAL :: unit
    CHARACTER(len=:),ALLOCATABLE :: output_format
    INTEGER :: unt

    IF ( PRESENT(unit) ) THEN
      unt = unit
    ELSE
      unt = 6
    END IF

    IF ( PRESENT(fmt) ) THEN
      output_format = '('//trim(fmt)//')'
    ELSE
      output_format = '(F10.4)'
    END IF

    ! Pretty print function.
    !  Real
    CALL PPRINT(VAR%R,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') ' '

    !  Order 1
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E1 * '
    CALL PPRINT(VAR%E1,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E2 * '
    CALL PPRINT(VAR%E2,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E3 * '
    CALL PPRINT(VAR%E3,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E4 * '
    CALL PPRINT(VAR%E4,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E5 * '
    CALL PPRINT(VAR%E5,unit=unt,fmt=output_format)
    WRITE(unt,'(A)',advance='YES') '+ '
    WRITE(unt,'(A)',advance='YES') 'E6 * '
    CALL PPRINT(VAR%E6,unit=unt,fmt=output_format)


  END SUBROUTINE ONUMM6N1_PPRINT_M

  ELEMENTAL FUNCTION ONUMM6N1_FEVAL(X,DER0,DER1)&
    RESULT(RES)
    IMPLICIT NONE
    !  Definitions
    REAL(DP) :: FACTOR, COEF
    TYPE(ONUMM6N1), INTENT(IN)  :: X
    REAL(DP), INTENT(IN)  :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    TYPE(ONUMM6N1) :: DX, DX_P

    FACTOR = 1.0_DP
    COEF   = 0.0_DP
    DX     = X
    DX_P   = X

    !  Set real part of deltas zero.
    DX%R = 0.0_dp
    DX_P%R = 0.0_dp

    ! Sets real part
    RES = DER0

    ! Sets order 1
    FACTOR = FACTOR * 1
    COEF = DER1 / FACTOR
    ! RES = RES COEF * DX_P
    ! Order 1
    RES%E1 = RES%E1+COEF*DX_P%E1
    RES%E2 = RES%E2+COEF*DX_P%E2
    RES%E3 = RES%E3+COEF*DX_P%E3
    RES%E4 = RES%E4+COEF*DX_P%E4
    RES%E5 = RES%E5+COEF*DX_P%E5
    RES%E6 = RES%E6+COEF*DX_P%E6
    
  END FUNCTION ONUMM6N1_FEVAL


  ! SUBROUTINE ONUMM6N1_PPRINT_M_R(X, FMT)
  !     IMPLICIT NONE
  !     REAL(DP),INTENT(IN) :: X(:,:)
  !     INTEGER :: I, J
  !     CHARACTER(*),INTENT(IN),OPTIONAL :: FMT
  !     CHARACTER(:),ALLOCATABLE :: out_fmt
      
  !     IF (PRESENT(fmt)) THEN
  !       out_fmt = fmt
  !     ELSE
  !       out_fmt = 'F10.4'
  !     END IF
      
  !     write(*,'(A)',advance='no') "["
      
  !     DO I=1,SIZE(X,1)
        
  !       IF (I == 1) THEN
  !         write(*,'(A)',advance='no') "["
  !       ELSE
  !         write(*,'(A)',advance='no') " ["
  !       END IF 

  !       DO J=1,SIZE(X,2)
          
  !         write(*,'('//trim(out_fmt)//')',advance='no') X(I,J)

  !       END DO
        
  !       write(*,'(A)') "]"
      
  !     END DO

  !     write(*,'(A)') "]"

  ! END SUBROUTINE ONUMM6N1_PPRINT_M_R

  ! SUBROUTINE ONUMM6N1_PPRINT_V_R(X, FMT)
  !     IMPLICIT NONE
  !     REAL(DP),INTENT(IN) :: X(:)
  !     INTEGER :: I
  !     CHARACTER(*),INTENT(IN),OPTIONAL :: FMT
  !     CHARACTER(:),ALLOCATABLE :: out_fmt
      
  !     IF (PRESENT(fmt)) THEN
  !       out_fmt = fmt
  !     ELSE
  !       out_fmt = 'F10.4'
  !     END IF
      
  !     write(*,'(A)',advance='no') "["
      
  !     DO I=1,SIZE(X,1)

  !       write(*,'('//trim(out_fmt)//')',advance='no') X(I)

  !     END DO

  !     write(*,'(A)') "]"

  ! END SUBROUTINE ONUMM6N1_PPRINT_V_R

  ! !***************************************************************************************************! 
  ! !> @brief 2 x 2  matrix inversion.
  ! !!
  ! !! Taken from https://fortranwiki.org/fortran/show/Matrix+inversion
  ! !!
  ! !! @param[in] A: Matrix to be printed.
  ! !! @param[out] B: inverse of A.
  ! !!
  ! !***************************************************************************************************!
  ! PURE FUNCTION Rmatinv2x2(A,det) RESULT(B)

  !   IMPLICIT NONE

  !   REAL(dp), INTENT(IN) :: A(2,2)   !! Matrix
  !   REAL(dp), INTENT(IN), OPTIONAL :: det
  !   REAL(dp)             :: B(2,2)   !! Inverse matrix
  !   REAL(dp)             :: detinv

  !   IF ( PRESENT(det) ) THEN
  !     detinv = 1.0d0 / det
  !   ELSE
  !     ! Calculate the inverse determinant of the matrix
  !     detinv = 1.0d0 / det2x2(A)
  !   END IF

  !   ! Calculate the inverse of the matrix
  !   B(1,1) =  detinv * A(2,2)
  !   B(2,1) = -detinv * A(2,1)
  !   B(1,2) = -detinv * A(1,2)
  !   B(2,2) =  detinv * A(1,1)
  ! END FUNCTION
  ! !===================================================================================================! 
  
  ! !***************************************************************************************************! 
  ! !> @brief 3 x 3  matrix inversion.
  ! !!
  ! !! Taken from https://fortranwiki.org/fortran/show/Matrix+inversion
  ! !!
  ! !! @param[in]  A: Matrix to be printed.
  ! !! @param[out] B: inverse of A.
  ! !!
  ! !***************************************************************************************************!
  ! PURE FUNCTION Rmatinv3x3(A,det) RESULT(B)
      
  !     IMPLICIT NONE

  !     REAL(dp), INTENT(IN) :: A(3,3)   !! Matrix
  !     REAL(dp), INTENT(IN), OPTIONAL :: det
  !     REAL(dp)             :: B(3,3)   !! Inverse matrix
  !     REAL(dp)             :: detinv

  !     IF ( PRESENT(det) ) THEN
  !        detinv = 1.0d0/det
  !     ELSE
  !        ! Calculate the inverse determinant of the matrix
  !        detinv = 1.0d0/det3x3(A)
  !     END IF 

  !     ! Calculate the inverse of the matrix
  !     B(1,1) = + detinv * (A(2,2)*A(3,3) - A(2,3)*A(3,2))
  !     B(2,1) = - detinv * (A(2,1)*A(3,3) - A(2,3)*A(3,1))
  !     B(3,1) = + detinv * (A(2,1)*A(3,2) - A(2,2)*A(3,1))
  !     B(1,2) = - detinv * (A(1,2)*A(3,3) - A(1,3)*A(3,2))
  !     B(2,2) = + detinv * (A(1,1)*A(3,3) - A(1,3)*A(3,1))
  !     B(3,2) = - detinv * (A(1,1)*A(3,2) - A(1,2)*A(3,1))
  !     B(1,3) = + detinv * (A(1,2)*A(2,3) - A(1,3)*A(2,2))
  !     B(2,3) = - detinv * (A(1,1)*A(2,3) - A(1,3)*A(2,1))
  !     B(3,3) = + detinv * (A(1,1)*A(2,2) - A(1,2)*A(2,1))

  !  END FUNCTION
  !  !===================================================================================================! 

  !  !***************************************************************************************************! 
  !  !> @brief 4 x 4  matrix inversion.
  !  !!
  !  !! Taken from https://fortranwiki.org/fortran/show/Matrix+inversion
  !  !!
  !  !! @param[in]  A: Matrix to be printed.
  !  !! @param[in]  det: (optional) Determinant of A.
  !  !! @param[out] B: inverse of A.
  !  !!
  !  !***************************************************************************************************!
  !  PURE FUNCTION Rmatinv4x4(A,det) RESULT(B)
      
  !     IMPLICIT NONE

  !     REAL(dp), INTENT(IN) :: A(4,4)   !! Matrix
  !     REAL(dp), INTENT(IN), OPTIONAL :: det
  !     REAL(dp)             :: B(4,4)   !! Inverse matrix
  !     REAL(dp)             :: di  !! Determinant inverse

  !     ! Calculate the inverse determinant of the matrix
  !     IF ( PRESENT(det) ) THEN
  !        di = 1.0d0/det
  !     ELSE
  !        di = 1.0d0/det4x4(A)
  !     END IF 
      
  !     ! Calculate the inverse of the matrix
  !     B(1,1) = di*(A(2,2)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(2,4)*(A(3,2)*A(4,3)-A(3,3)*A(4,2)))
  !     B(2,1) = di*(A(2,1)*(A(3,4)*A(4,3)-A(3,3)*A(4,4))+A(2,3)*(A(3,1)*A(4,4)-A(3,4)*A(4,1))+A(2,4)*(A(3,3)*A(4,1)-A(3,1)*A(4,3)))
  !     B(3,1) = di*(A(2,1)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(2,2)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))
  !     B(4,1) = di*(A(2,1)*(A(3,3)*A(4,2)-A(3,2)*A(4,3))+A(2,2)*(A(3,1)*A(4,3)-A(3,3)*A(4,1))+A(2,3)*(A(3,2)*A(4,1)-A(3,1)*A(4,2)))
  !     B(1,2) = di*(A(1,2)*(A(3,4)*A(4,3)-A(3,3)*A(4,4))+A(1,3)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(1,4)*(A(3,3)*A(4,2)-A(3,2)*A(4,3)))
  !     B(2,2) = di*(A(1,1)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(1,3)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(1,4)*(A(3,1)*A(4,3)-A(3,3)*A(4,1)))
  !     B(3,2) = di*(A(1,1)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(1,2)*(A(3,1)*A(4,4)-A(3,4)*A(4,1))+A(1,4)*(A(3,2)*A(4,1)-A(3,1)*A(4,2)))
  !     B(4,2) = di*(A(1,1)*(A(3,2)*A(4,3)-A(3,3)*A(4,2))+A(1,2)*(A(3,3)*A(4,1)-A(3,1)*A(4,3))+A(1,3)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))
  !     B(1,3) = di*(A(1,2)*(A(2,3)*A(4,4)-A(2,4)*A(4,3))+A(1,3)*(A(2,4)*A(4,2)-A(2,2)*A(4,4))+A(1,4)*(A(2,2)*A(4,3)-A(2,3)*A(4,2)))
  !     B(2,3) = di*(A(1,1)*(A(2,4)*A(4,3)-A(2,3)*A(4,4))+A(1,3)*(A(2,1)*A(4,4)-A(2,4)*A(4,1))+A(1,4)*(A(2,3)*A(4,1)-A(2,1)*A(4,3)))
  !     B(3,3) = di*(A(1,1)*(A(2,2)*A(4,4)-A(2,4)*A(4,2))+A(1,2)*(A(2,4)*A(4,1)-A(2,1)*A(4,4))+A(1,4)*(A(2,1)*A(4,2)-A(2,2)*A(4,1)))
  !     B(4,3) = di*(A(1,1)*(A(2,3)*A(4,2)-A(2,2)*A(4,3))+A(1,2)*(A(2,1)*A(4,3)-A(2,3)*A(4,1))+A(1,3)*(A(2,2)*A(4,1)-A(2,1)*A(4,2)))
  !     B(1,4) = di*(A(1,2)*(A(2,4)*A(3,3)-A(2,3)*A(3,4))+A(1,3)*(A(2,2)*A(3,4)-A(2,4)*A(3,2))+A(1,4)*(A(2,3)*A(3,2)-A(2,2)*A(3,3)))
  !     B(2,4) = di*(A(1,1)*(A(2,3)*A(3,4)-A(2,4)*A(3,3))+A(1,3)*(A(2,4)*A(3,1)-A(2,1)*A(3,4))+A(1,4)*(A(2,1)*A(3,3)-A(2,3)*A(3,1)))
  !     B(3,4) = di*(A(1,1)*(A(2,4)*A(3,2)-A(2,2)*A(3,4))+A(1,2)*(A(2,1)*A(3,4)-A(2,4)*A(3,1))+A(1,4)*(A(2,2)*A(3,1)-A(2,1)*A(3,2)))
  !     B(4,4) = di*(A(1,1)*(A(2,2)*A(3,3)-A(2,3)*A(3,2))+A(1,2)*(A(2,3)*A(3,1)-A(2,1)*A(3,3))+A(1,3)*(A(2,1)*A(3,2)-A(2,2)*A(3,1)))
  !  END FUNCTION
  !  !===================================================================================================! 

  !***************************************************************************************************! 
  !> @brief 2 x 2  matrix determinant.
  !!
  !!
  !! @param[in] A: Matrix to be printed.
  !! @param[out] B: inverse of A.
  !!
  !***************************************************************************************************!
  PURE FUNCTION ONUMM6N1_det2x2(A) RESULT(det)

    IMPLICIT NONE

    TYPE(ONUMM6N1), INTENT(IN) :: A(2,2)   !! Matrix
    TYPE(ONUMM6N1)             :: det

    ! Calculate the determinant of the matrix
    det = (A(1,1)*A(2,2) - A(1,2)*A(2,1))

  END FUNCTION
  !===================================================================================================! 
  
  !***************************************************************************************************! 
  !> @brief 3 x 3  matrix determinant.
  !!
  !!
  !! @param[in]  A: Matrix to be printed.
  !! @param[out] B: inverse of A.
  !!
  !***************************************************************************************************!
  PURE FUNCTION ONUMM6N1_det3x3(A) RESULT(det)
      
    IMPLICIT NONE

    TYPE(ONUMM6N1), INTENT(IN) :: A(3,3)   !! Matrix
    TYPE(ONUMM6N1)             :: det

    ! Calculate the inverse determinant of the matrix
    det = (A(1,1)*A(2,2)*A(3,3) - A(1,1)*A(2,3)*A(3,2)&
         - A(1,2)*A(2,1)*A(3,3) + A(1,2)*A(2,3)*A(3,1)&
         + A(1,3)*A(2,1)*A(3,2) - A(1,3)*A(2,2)*A(3,1))

  END FUNCTION
  !===================================================================================================! 

  !***************************************************************************************************! 
  !> @brief 4 x 4  matrix determinant.
  !!
  !!
  !! @param[in]  A: Matrix to be printed.
  !! @param[out] B: inverse of A.
  !!
  !***************************************************************************************************!
  PURE FUNCTION ONUMM6N1_det4x4(A) RESULT(det)
      
    IMPLICIT NONE

    TYPE(ONUMM6N1), INTENT(IN) :: A(4,4)   !! Matrix
    TYPE(ONUMM6N1)             :: det

    ! Calculate the determinant of the matrix
    det = &
    (A(1,1)*(A(2,2)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,2)-A(3,2)*A(4,4))+A(2,4)*(A(3,2)*A(4,3)-A(3,3)*A(4,2)))&
   - A(1,2)*(A(2,1)*(A(3,3)*A(4,4)-A(3,4)*A(4,3))+A(2,3)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,3)-A(3,3)*A(4,1)))&
   + A(1,3)*(A(2,1)*(A(3,2)*A(4,4)-A(3,4)*A(4,2))+A(2,2)*(A(3,4)*A(4,1)-A(3,1)*A(4,4))+A(2,4)*(A(3,1)*A(4,2)-A(3,2)*A(4,1)))&
   - A(1,4)*(A(2,1)*(A(3,2)*A(4,3)-A(3,3)*A(4,2))+A(2,2)*(A(3,3)*A(4,1)-A(3,1)*A(4,3))+A(2,3)*(A(3,1)*A(4,2)-A(3,2)*A(4,1))))

  END FUNCTION
  !===================================================================================================! 
   
  !***************************************************************************************************! 
  !> @brief Cross product between two vectors.
  !!
  !! @param[in] a: Vector of 3 reals (rank 1).
  !! @param[in] b: Vector of 3 reals (rank 1).
  !!
  !***************************************************************************************************!
  PURE FUNCTION ONUMM6N1_cross3(a,b) RESULT(v)
      
    IMPLICIT NONE 

    TYPE(ONUMM6N1), DIMENSION (3),INTENT(IN) :: a,b
    TYPE(ONUMM6N1), DIMENSION (3) :: v
    
    v(1) = a(2) * b(3) - a(3) * b(2)
    v(2) = a(3) * b(1) - a(1) * b(3)
    v(3) = a(1) * b(2) - a(2) * b(1)

  END FUNCTION ONUMM6N1_cross3
  !===================================================================================================! 

  !***************************************************************************************************! 
  !> @brief Norm of a 3 element vector. # There is an intrinsic function named norm2.
  !!
  !! @param[in] a: Vector of 3 reals (rank 1).
  !! @param[in] b: Vector of 3 reals (rank 1).
  !!
  !***************************************************************************************************!
  FUNCTION ONUMM6N1_norm2_3(v) RESULT(n)
     
    IMPLICIT NONE 

    TYPE(ONUMM6N1), INTENT(IN) :: v(3)
    TYPE(ONUMM6N1) :: n
     
    n = SQRT( v(1)*v(1) + v(2)*v(2) + v(3)*v(3) )

  END FUNCTION ONUMM6N1_norm2_3
  !===================================================================================================! 

  ELEMENTAL FUNCTION ONUMM6N1_DIVISION_OO(X,Y) RESULT(RES)
      IMPLICIT NONE
      ! REAL(DP) :: DERIVS(TORDER + 1) 
      TYPE(ONUMM6N1), INTENT(IN) :: X
      TYPE(ONUMM6N1), INTENT(IN) :: Y
      TYPE(ONUMM6N1) :: RES

      RES = X*(Y**(-1.d0))

  END FUNCTION ONUMM6N1_DIVISION_OO

  ELEMENTAL FUNCTION ONUMM6N1_DIVISION_OR(X,Y) RESULT(RES)
      IMPLICIT NONE
      ! REAL(DP) :: DERIVS(TORDER + 1) 
      TYPE(ONUMM6N1), INTENT(IN) :: X
      REAL(DP), INTENT(IN) :: Y
      TYPE(ONUMM6N1) :: RES

      RES = X*(Y**(-1.d0))

  END FUNCTION ONUMM6N1_DIVISION_OR

  ELEMENTAL FUNCTION ONUMM6N1_DIVISION_RO(X,Y) RESULT(RES)
      IMPLICIT NONE
      ! REAL(DP) :: DERIVS(TORDER + 1) 
      REAL(DP), INTENT(IN) :: X
      TYPE(ONUMM6N1), INTENT(IN) :: Y
      TYPE(ONUMM6N1) :: RES

      RES = X*(Y**(-1.d0))

  END FUNCTION ONUMM6N1_DIVISION_RO

  ELEMENTAL FUNCTION ONUMM6N1_REAL(X) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: X
      REAL(DP) :: RES

      RES = X%R

  END FUNCTION ONUMM6N1_REAL

  FUNCTION ONUMM6N1_SQRT(X) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: X
      TYPE(ONUMM6N1) :: RES

      RES = X**0.5_DP

  END FUNCTION ONUMM6N1_SQRT

  FUNCTION ONUMM6N1_MAX(X1,X2) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: X1, X2
                                                
      TYPE(ONUMM6N1) :: RES
      RES = X1
      IF (X2>RES) RES = X2  

  END FUNCTION ONUMM6N1_MAX

  FUNCTION ONUMM6N1_MIN(X1,X2) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: X1, X2
                                                
      TYPE(ONUMM6N1) :: RES
      RES = X1
      IF (X2<RES) RES = X2

  END FUNCTION ONUMM6N1_MIN

  FUNCTION ONUMM6N1_MAXLOC_R1(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 1)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1))
      LOGICAL :: BACK_DEF
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK

      RES = MAXLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MAXLOC_R1

  FUNCTION ONUMM6N1_MAXLOC_R2(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 2)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2))
      LOGICAL :: BACK_DEF
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK
      
      RES = MAXLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MAXLOC_R2
  
  FUNCTION ONUMM6N1_MAXLOC_R3(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 3)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3))
      LOGICAL :: BACK_DEF
      
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK
      
      RES = MAXLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MAXLOC_R3

  FUNCTION ONUMM6N1_MAXLOC_R4(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:,:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3),SIZE(ARRAY,4))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 4)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3),SIZE(ARRAY,4))
      LOGICAL :: BACK_DEF
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK
      

      RES = MAXLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MAXLOC_R4

  
  FUNCTION ONUMM6N1_MAXVAL_R1(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
      INTEGER :: IDX( 1)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MAXLOC(ARRAY)
      RES = ARRAY(IDX(1))

  END FUNCTION ONUMM6N1_MAXVAL_R1

  FUNCTION ONUMM6N1_MAXVAL_R2(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
      INTEGER :: IDX( 2)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MAXLOC(ARRAY)
      RES = ARRAY(IDX(1),IDX(2))

  END FUNCTION ONUMM6N1_MAXVAL_R2

  FUNCTION ONUMM6N1_MAXVAL_R3(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:)
      INTEGER :: IDX( 3)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MAXLOC(ARRAY)
      RES = ARRAY(IDX(1),IDX(2),IDX(3))

  END FUNCTION ONUMM6N1_MAXVAL_R3

  FUNCTION ONUMM6N1_MAXVAL_R4(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:,:)
      INTEGER :: IDX( 4)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MAXLOC(ARRAY)
      RES = ARRAY(IDX(1),IDX(2),IDX(3),IDX(4))

  END FUNCTION ONUMM6N1_MAXVAL_R4


    FUNCTION ONUMM6N1_MINLOC_R1(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 1)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1))
      LOGICAL :: BACK_DEF
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK

      RES = MINLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MINLOC_R1

  FUNCTION ONUMM6N1_MINLOC_R2(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 2)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2))
      LOGICAL :: BACK_DEF
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK
      
      RES = MINLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MINLOC_R2
  
  FUNCTION ONUMM6N1_MINLOC_R3(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 3)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3))
      LOGICAL :: BACK_DEF
      
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK
      
      RES = MINLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MINLOC_R3

  FUNCTION ONUMM6N1_MINLOC_R4(ARRAY, MASK, BACK) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:,:)
      LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3),SIZE(ARRAY,4))
      LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
      INTEGER :: RES( 4)
      
      LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3),SIZE(ARRAY,4))
      LOGICAL :: BACK_DEF
      
      ! Assign defaults.
      MASK_DEF = .true.
      BACK_DEF = .false.
      
      
      IF (PRESENT(MASK)) MASK_DEF = MASK
      IF (PRESENT(BACK)) BACK_DEF = BACK
      

      RES = MINLOC(ARRAY%R, MASK = MASK_DEF)

  END FUNCTION ONUMM6N1_MINLOC_R4



  FUNCTION ONUMM6N1_MINVAL_R1(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
      INTEGER :: IDX( 1)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MINLOC(ARRAY)
      RES = ARRAY(IDX(1))

  END FUNCTION ONUMM6N1_MINVAL_R1

  FUNCTION ONUMM6N1_MINVAL_R2(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
      INTEGER :: IDX( 2)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MINLOC(ARRAY)
      RES = ARRAY(IDX(1),IDX(2))

  END FUNCTION ONUMM6N1_MINVAL_R2

  FUNCTION ONUMM6N1_MINVAL_R3(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:)
      INTEGER :: IDX( 3)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MINLOC(ARRAY)
      RES = ARRAY(IDX(1),IDX(2),IDX(3))

  END FUNCTION ONUMM6N1_MINVAL_R3

  FUNCTION ONUMM6N1_MINVAL_R4(ARRAY) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:,:)
      INTEGER :: IDX( 4)
      TYPE(ONUMM6N1) :: RES
      

      IDX = MINLOC(ARRAY)
      RES = ARRAY(IDX(1),IDX(2),IDX(3),IDX(4))

  END FUNCTION ONUMM6N1_MINVAL_R4

  ! FUNCTION ONUMM6N1_MAXLOC_DIM_R1(ARRAY, DIM, MASK, KIND, BACK) RESULT(RES)
  !     IMPLICIT NONE
  !     TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:)
  !     INTEGER, INTENT(IN) :: DIM  
  !     LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1))
  !     INTEGER, INTENT(IN), OPTIONAL :: KIND  ! Not used in this case.
  !     LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
  !     INTEGER :: RES( 1)
      
  !     LOGICAL :: MASK_DEF(SIZE(ARRAY,1))
  !     LOGICAL :: BACK_DEF
      
  !     ! Assign defaults.
  !     MASK_DEF = .true.
  !     BACK_DEF = .false.
      
  !     IF (PRESENT(MASK)) MASK_DEF = MASK
  !     IF (PRESENT(BACK)) BACK_DEF = BACK

  !     RES = MAXLOC(ARRAY%R, MASK = MASK_DEF)

  ! END FUNCTION ONUMM6N1_MAXLOC_DIM_R1

  ! FUNCTION ONUMM6N1_MAXLOC_DIM_R2(ARRAY, DIM, MASK, KIND, BACK) RESULT(RES)
  !     IMPLICIT NONE
  !     TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:)
  !     INTEGER, INTENT(IN) :: DIM  
  !     LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2))
  !     INTEGER, INTENT(IN), OPTIONAL :: KIND  ! Not used in this case.
  !     LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
  !     INTEGER :: RES( 2)
      
  !     LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2))
  !     LOGICAL :: BACK_DEF
      
  !     ! Assign defaults.
  !     MASK_DEF = .true.
  !     BACK_DEF = .false.
      
  !     IF (PRESENT(MASK)) MASK_DEF = MASK
  !     IF (PRESENT(BACK)) BACK_DEF = BACK
      
  !     RES = MAXLOC(ARRAY%R, DIM, MASK = MASK_DEF)

  ! END FUNCTION ONUMM6N1_MAXLOC_DIM_R2
  
  ! FUNCTION ONUMM6N1_MAXLOC_DIM_R3(ARRAY, DIM, MASK, KIND, BACK) RESULT(RES)
  !     IMPLICIT NONE
  !     TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:)
  !     INTEGER, INTENT(IN) :: DIM  
  !     LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3))
  !     INTEGER, INTENT(IN), OPTIONAL :: KIND  ! Not used in this case.
  !     LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
  !     INTEGER :: RES( 3)
      
  !     LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3))
  !     LOGICAL :: BACK_DEF
      
      
  !     ! Assign defaults.
  !     MASK_DEF = .true.
  !     BACK_DEF = .false.
      
  !     IF (PRESENT(MASK)) MASK_DEF = MASK
  !     IF (PRESENT(BACK)) BACK_DEF = BACK
      
  !     RES = MAXLOC(ARRAY%R, DIM, MASK = MASK_DEF)

  ! END FUNCTION ONUMM6N1_MAXLOC_DIM_R3

  ! FUNCTION ONUMM6N1_MAXLOC_DIM_R4(ARRAY, DIM, MASK, KIND, BACK) RESULT(RES)
  !     IMPLICIT NONE
  !     TYPE(ONUMM6N1), INTENT(IN) :: ARRAY(:,:,:,:)
  !     INTEGER, INTENT(IN) :: DIM  
  !     LOGICAL, INTENT(IN), OPTIONAL :: MASK(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3),SIZE(ARRAY,4))
  !     INTEGER, INTENT(IN), OPTIONAL :: KIND  ! Not used in this case, just for compatibility.
  !     LOGICAL, INTENT(IN), OPTIONAL :: BACK  ! Search from the back
      
  !     INTEGER :: RES( 4)
      
  !     LOGICAL :: MASK_DEF(SIZE(ARRAY,1),SIZE(ARRAY,2),SIZE(ARRAY,3),SIZE(ARRAY,4))
  !     LOGICAL :: BACK_DEF
      
  !     ! Assign defaults.
  !     MASK_DEF = .true.
  !     BACK_DEF = .false.
      
      
  !     IF (PRESENT(MASK)) MASK_DEF = MASK
  !     IF (PRESENT(BACK)) BACK_DEF = BACK
      

  !     RES = MAXLOC(ARRAY%R, DIM, MASK = MASK_DEF)

  ! END FUNCTION ONUMM6N1_MAXLOC_DIM_R4

  ELEMENTAL FUNCTION ONUMM6N1_TAN(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = TAN(X%R)
    DER1 = TAN(X%R)**2 + 1

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_TAN

  ELEMENTAL FUNCTION ONUMM6N1_COS(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = COS(X%R)
    DER1 = -SIN(X%R)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_COS

  ELEMENTAL FUNCTION ONUMM6N1_SIN(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = SIN(X%R)
    DER1 = COS(X%R)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_SIN

  ELEMENTAL FUNCTION ONUMM6N1_ATAN(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = ATAN(X%R)
    DER1 = 1D0/(X%R**2 + 1)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_ATAN

  ELEMENTAL FUNCTION ONUMM6N1_ACOS(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = ACOS(X%R)
    DER1 = -1/SQRT(1 - X%R**2)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_ACOS

  ELEMENTAL FUNCTION ONUMM6N1_ASIN(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = ASIN(X%R)
    DER1 = 1/SQRT(1 - X%R**2)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_ASIN

  ELEMENTAL FUNCTION ONUMM6N1_TANH(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = TANH(X%R)
    DER1 = 1 - TANH(X%R)**2

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_TANH

  ELEMENTAL FUNCTION ONUMM6N1_COSH(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = COSH(X%R)
    DER1 = SINH(X%R)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_COSH

  ELEMENTAL FUNCTION ONUMM6N1_SINH(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = SINH(X%R)
    DER1 = COSH(X%R)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_SINH

  ELEMENTAL FUNCTION ONUMM6N1_EXP(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = EXP(X%R)
    DER1 = EXP(X%R)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_EXP

  ELEMENTAL FUNCTION ONUMM6N1_LOG(X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0 = LOG(X%R)
    DER1 = 1D0/X%R

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_LOG

  ELEMENTAL FUNCTION ONUMM6N1_POW_OR(X,E) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP), INTENT(IN) :: E
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    DER0=0.0d0
    DER1=0.0d0
    
    DER0 = X%R**E
    IF ((E-0)/=0.0d0) THEN
      DER1 = E*X%R**(E - 1)
    END IF

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_POW_OR

  ELEMENTAL FUNCTION ONUMM6N1_POW_RO(E,X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    REAL(DP), INTENT(IN) :: E
    REAL(DP) :: DER0,DER1
    TYPE(ONUMM6N1) :: RES
    
    
    DER0 = E**X%R
    DER1 = E**X%R*LOG(E)

    RES = FEVAL(X,DER0,DER1)

  END FUNCTION ONUMM6N1_POW_RO

  ELEMENTAL FUNCTION ONUMM6N1_POW_I8O(E,X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    INTEGER(8), INTENT(IN) :: E
    TYPE(ONUMM6N1) :: RES
    
    RES = ONUMM6N1_POW_RO(REAL(E,8),X)
    
  END FUNCTION 

  ELEMENTAL FUNCTION ONUMM6N1_POW_I4O(E,X) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    INTEGER(4), INTENT(IN) :: E
    TYPE(ONUMM6N1) :: RES
    
    RES = ONUMM6N1_POW_RO(REAL(E,8),X)
    
  END FUNCTION 

  ELEMENTAL FUNCTION ONUMM6N1_POW_OI8(X,E) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    INTEGER(8), INTENT(IN) :: E
    TYPE(ONUMM6N1) :: RES
    
    RES = ONUMM6N1_POW_OR(X,REAL(E,8))
    
  END FUNCTION 

  ELEMENTAL FUNCTION ONUMM6N1_POW_OI4(X,E) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X
    INTEGER(4), INTENT(IN) :: E
    TYPE(ONUMM6N1) :: RES
    
    RES = ONUMM6N1_POW_OR(X,REAL(E,8))
    
  END FUNCTION 

  ELEMENTAL FUNCTION ONUMM6N1_F2EVAL(X,Y,DER0_0,DER1_0,DER1_1)&
    RESULT(RES)
    IMPLICIT NONE
    !  Definitions
    REAL(DP) :: COEF
    TYPE(ONUMM6N1), INTENT(IN)  :: X,Y
    REAL(DP), INTENT(IN)  :: DER0_0,DER1_0,DER1_1
    TYPE(ONUMM6N1) :: RES
    TYPE(ONUMM6N1) :: DX, DY

    COEF   = 0.0_DP
    DX     = X
    DY     = Y

    !  Set real part of deltas zero.
    DX%R = 0.0_dp
    DY%R = 0.0_dp

    ! Set real part
    RES = DER0_0

    ! Set order 1
    COEF = DER1_0 / 1.0_DP
    RES = RES + COEF*DX

    COEF = DER1_1 / 1.0_DP
    RES = RES + COEF*DY

    

  END FUNCTION ONUMM6N1_F2EVAL


  ELEMENTAL FUNCTION ONUMM6N1_POW_OO(X,Y) RESULT(RES)

    TYPE(ONUMM6N1), INTENT(IN) :: X, Y
    REAL(DP) :: DER0_0,DER1_0,DER1_1
    TYPE(ONUMM6N1) :: RES
    
    DER0_0 = X%R**Y%R
    DER1_0 = X%R**Y%R*Y%R/X%R
    DER1_1 = X%R**Y%R*LOG(X%R)

    RES = F2EVAL(X,Y,DER0_0,DER1_0,DER1_1)

  END FUNCTION ONUMM6N1_POW_OO


  FUNCTION ONUMM6N1_INV2X2(A,det)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1) , INTENT(IN) :: A(2,2) 
    TYPE(ONUMM6N1) , INTENT(IN), OPTIONAL :: det
    REAL(DP) :: detCalc
    TYPE(ONUMM6N1) :: RES(SIZE(A,1),SIZE(A,2)) 

    IF (PRESENT(det)) THEN
      detCalc=det%R
    ELSE
      detCalc=det2x2(A%R)
    END IF

    ! Get real part 
    RES%R=INV2X2(A%R,detCalc)

    ! Order 1
    RES%E1=-MATMUL(RES%R,(MATMUL(A%E1,RES%R)))
    RES%E2=-MATMUL(RES%R,(MATMUL(A%E2,RES%R)))
    RES%E3=-MATMUL(RES%R,(MATMUL(A%E3,RES%R)))
    RES%E4=-MATMUL(RES%R,(MATMUL(A%E4,RES%R)))
    RES%E5=-MATMUL(RES%R,(MATMUL(A%E5,RES%R)))
    RES%E6=-MATMUL(RES%R,(MATMUL(A%E6,RES%R)))

  END FUNCTION ONUMM6N1_INV2X2

  FUNCTION ONUMM6N1_INV3X3(A,det)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1) , INTENT(IN) :: A(3,3) 
    TYPE(ONUMM6N1) , INTENT(IN), OPTIONAL :: det
    REAL(DP) :: detCalc
    TYPE(ONUMM6N1) :: RES(SIZE(A,1),SIZE(A,2)) 

    IF (PRESENT(det)) THEN
      detCalc=det%R
    ELSE
      detCalc=det3x3(A%R)
    END IF

    ! Get real part 
    RES%R=INV3X3(A%R,detCalc)

    ! Order 1
    RES%E1=-MATMUL(RES%R,(MATMUL(A%E1,RES%R)))
    RES%E2=-MATMUL(RES%R,(MATMUL(A%E2,RES%R)))
    RES%E3=-MATMUL(RES%R,(MATMUL(A%E3,RES%R)))
    RES%E4=-MATMUL(RES%R,(MATMUL(A%E4,RES%R)))
    RES%E5=-MATMUL(RES%R,(MATMUL(A%E5,RES%R)))
    RES%E6=-MATMUL(RES%R,(MATMUL(A%E6,RES%R)))

  END FUNCTION ONUMM6N1_INV3X3

  FUNCTION ONUMM6N1_INV4X4(A,det)&
    RESULT(RES)
    IMPLICIT NONE
    TYPE(ONUMM6N1) , INTENT(IN) :: A(4,4) 
    TYPE(ONUMM6N1) , INTENT(IN), OPTIONAL :: det
    REAL(DP) :: detCalc
    TYPE(ONUMM6N1) :: RES(SIZE(A,1),SIZE(A,2)) 

    IF (PRESENT(det)) THEN
      detCalc=det%R
    ELSE
      detCalc=det4x4(A%R)
    END IF

    ! Get real part 
    RES%R=INV4X4(A%R,detCalc)

    ! Order 1
    RES%E1=-MATMUL(RES%R,(MATMUL(A%E1,RES%R)))
    RES%E2=-MATMUL(RES%R,(MATMUL(A%E2,RES%R)))
    RES%E3=-MATMUL(RES%R,(MATMUL(A%E3,RES%R)))
    RES%E4=-MATMUL(RES%R,(MATMUL(A%E4,RES%R)))
    RES%E5=-MATMUL(RES%R,(MATMUL(A%E5,RES%R)))
    RES%E6=-MATMUL(RES%R,(MATMUL(A%E6,RES%R)))

  END FUNCTION ONUMM6N1_INV4X4


  FUNCTION ONUMM6N1_ABS(A) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: A
      TYPE(ONUMM6N1) :: RES
      REAL(DP) :: SGN
      RES%R = ABS(A%R)
      IF (A%R > 0.0_dp) THEN
        SGN = 1.0_dp
      ELSE IF (A%R < 0.0_dp) THEN
        SGN = -1.0_dp
      ELSE
        SGN = 0.0_dp
      END IF
      RES%E1 = SGN * A%E1
      RES%E2 = SGN * A%E2
      RES%E3 = SGN * A%E3
      RES%E4 = SGN * A%E4
      RES%E5 = SGN * A%E5
      RES%E6 = SGN * A%E6
  END FUNCTION ONUMM6N1_ABS

  FUNCTION KOTI_NORM_ONUMM6N1(A) RESULT(RES)
      IMPLICIT NONE
      TYPE(ONUMM6N1), INTENT(IN) :: A
      REAL(DP) :: RES
      RES = SQRT(A%R*A%R + A%E1*A%E1 + A%E2*A%E2 + A%E3*A%E3 + A%E4*A%E4 + A%E5*A%E5 + A%E6*A%E6)
  END FUNCTION KOTI_NORM_ONUMM6N1
END MODULE otim6n1

! ===== umat_oti.for =====
!  ------------------------------------------------------------------------
!  M3  Small-strain von Mises (J2) plasticity, linear isotropic hardening.
!
!  PROPS(1)=E   PROPS(2)=nu   PROPS(3)=SIGY0 (initial yield)  PROPS(4)=H (hard.)
!  STATEV(1) = EQPLAS (accumulated equivalent plastic strain)
!
!  Stress-driven radial return.  The incoming STRESS is the converged stress of
!  the previous increment; STRESS + Del*DSTRAN is the elastic predictor.  Only
!  EQPLAS is required as history for the update, so NSTATV = 1.  Consistent
!  (algorithmic) tangent for linear hardening.  Voigt (11,22,33,12,13,23),
!  engineering shear.  Self-contained: no ROTSIG / UHARD.
!  ------------------------------------------------------------------------
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD, &
     & RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP, &
     & PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS, &
     & DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      USE otim6n1, OTI_MODULE_DP => DP, OTI_E1 => E1, OTI_E2 => E2, &
     & OTI_E3 => E3, OTI_E4 => E4, OTI_E5 => E5, OTI_E6 => E6
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS), &
     & DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS), &
     & TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3), &
     & DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION FLOW(6)
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
!
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: DEQPL_OTI
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: EQPLAS_OTI
      TYPE(ONUMM6N1) :: FLOW_OTI(6)
      TYPE(ONUMM6N1) :: SHYDRO_OTI
      TYPE(ONUMM6N1) :: SMISES_OTI
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      TYPE(ONUMM6N1) :: SYIEL0_OTI
      TYPE(ONUMM6N1) :: SYIELD_OTI
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HARD=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
!     elastic stiffness (also the predictor operator)
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
!     elastic predictor stress
!     OTIS seed initialization from GUI configuration
      DEQPL_OTI = 0.0D0
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      EQPLAS_OTI = 0.0D0
      DO OTI_HI = 1, 6
         FLOW_OTI(OTI_HI) = 0.0D0
      END DO
      SHYDRO_OTI = 0.0D0
      SMISES_OTI = 0.0D0
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
      SYIEL0_OTI = 0.0D0
      SYIELD_OTI = 0.0D0
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
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE(K2,K1)*DSTRAN_OTI(K1)
        END DO
      END DO
      EQPLAS_OTI=STATEV_OTI(1)
!     Mises equivalent STRESS_OTI of the predictor
      SMISES_OTI=(STRESS_OTI(1)-STRESS_OTI(2))**2.0D0+(STRESS_OTI(2)- &
     & STRESS_OTI(3))**2.0D0 +(STRESS_OTI(3)-STRESS_OTI(1))**2.0D0
!     OTIS-SKIP: 1      +(STRESS(3)-STRESS(1))**2
      DO K1=NDI+1,NTENS
        SMISES_OTI=SMISES_OTI+SIX*STRESS_OTI(K1)**2.0D0
      END DO
      SMISES_OTI=SQRT((((MAX(REAL(SMISES_OTI/TWO), 1.0D-30)) - &
     & REAL(SMISES_OTI/TWO)) + (SMISES_OTI/TWO)))
      SYIEL0_OTI=SIGY0+HARD*EQPLAS_OTI
!
      IF (REAL(SMISES_OTI).GT.REAL(SYIEL0_OTI)) THEN
!       actively yielding: hydrostatic / deviatoric split + flow direction
        SHYDRO_OTI=(STRESS_OTI(1)+STRESS_OTI(2)+STRESS_OTI(3))/THREE
        DO K1=1,NDI
          FLOW_OTI(K1)=(STRESS_OTI(K1)-SHYDRO_OTI)/SMISES_OTI
        END DO
        DO K1=NDI+1,NTENS
          FLOW_OTI(K1)=STRESS_OTI(K1)/SMISES_OTI
        END DO
!       closed-form return for linear hardening
        DEQPL_OTI=(SMISES_OTI-SYIEL0_OTI)/(EG3+HARD)
        SYIELD_OTI=SYIEL0_OTI+HARD*DEQPL_OTI
        DO K1=1,NDI
          STRESS_OTI(K1)=FLOW_OTI(K1)*SYIELD_OTI+SHYDRO_OTI
        END DO
        DO K1=NDI+1,NTENS
          STRESS_OTI(K1)=FLOW_OTI(K1)*SYIELD_OTI
        END DO
        EQPLAS_OTI=EQPLAS_OTI+DEQPL_OTI
!       consistent (algorithmic) tangent
!     OTIS-SKIP: EFFG=EG*SYIELD/SMISES
!     OTIS-SKIP: EFFG2=TWO*EFFG
!     OTIS-SKIP: EFFG3=THREE/TWO*EFFG2
!     OTIS-SKIP: EFFLAM=(EBULK3-EFFG2)/THREE
!     OTIS-SKIP: EFFHRD=EG3*HARD/(EG3+HARD)-EFFG3
!     OTIS-SKIP: DO K1=1,NTENS
!     OTIS-SKIP: DO K2=1,NTENS
!     OTIS-SKIP: DDSDDE(K2,K1)=ZERO
!     OTIS-SKIP: END DO
!     OTIS-SKIP: END DO
!     OTIS-SKIP: DO K1=1,NDI
!     OTIS-SKIP: DO K2=1,NDI
!     OTIS-SKIP: DDSDDE(K2,K1)=EFFLAM
!     OTIS-SKIP: END DO
!     OTIS-SKIP: DDSDDE(K1,K1)=EFFG2+EFFLAM
!     OTIS-SKIP: END DO
!     OTIS-SKIP: DO K1=NDI+1,NTENS
!     OTIS-SKIP: DDSDDE(K1,K1)=EFFG
!     OTIS-SKIP: END DO
!     OTIS-SKIP: DO K1=1,NTENS
!     OTIS-SKIP: DO K2=1,NTENS
!     OTIS-SKIP: DDSDDE(K2,K1)=DDSDDE(K2,K1)+EFFHRD*FLOW(K2)*FLOW(K1)
!     OTIS-SKIP: END DO
!     OTIS-SKIP: END DO
      END IF
      STATEV_OTI(1)=EQPLAS_OTI
!     Copy real-valued OTIS outputs back to Abaqus arrays
      DO OTI_I = 1, NTENS
         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))
      END DO
      DO OTI_I = 1, NSTATV
         STATEV(OTI_I) = REAL(STATEV_OTI(OTI_I))
      END DO
!     OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)
      DO OTI_I = 1, NTENS
         DO OTI_J = 1, NTENS
            DDSDDE(OTI_I,OTI_J) = &
     & GETIM(STRESS_OTI(OTI_I),OTI_J)
         END DO
      END DO
      RETURN
      END

