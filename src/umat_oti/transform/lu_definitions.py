"""OTI-liftable implementations of the DGETRF/DGETRS interfaces, with reference-LAPACK semantics.

The arithmetic is that of reference LAPACK for the small matrices a UMAT factors
(below the block size, where reference DGETRF runs the recursive DGETRF2, whose
operations for these sizes are those of the right-looking unblocked DGETF2):

* pivot: the first row of largest magnitude in the column (IDAMAX);
* a pivot of exactly zero sets INFO to the first such column and the
  factorization still runs to the end, as reference LAPACK does;
* the column below the pivot is scaled by the reciprocal of the pivot when the
  pivot is at least the safe minimum, and divided by it otherwise (DSCAL /
  DGETRF2); the trailing update is A(i,k) + A(i,j)*(-A(j,k)) (DGER / DGEMM);
* DGETRS solves with DLASWP and DTRSM's loop orders and returns no INFO for a
  zero diagonal (a singular factor gives Inf/NaN, as in reference LAPACK).

Every division first brings the divisor (and its numerator) into [2**-166,
2**166] by powers of two. In real arithmetic that is exact -- the quotient,
and the reciprocal times the column, are the same bits as unscaled -- and it
keeps the OTI copy finite: the OTI algebra divides as x*y**(-1), whose
derivative part carries y**(-2), which overflows for |y| near 1e155 and above.
(An earlier version scaled by 1e50, which is not a power of two and moved the
real results.)

Reference DTRSM skips a column update when the right-hand-side entry is exactly
zero; here it is not skipped, because in the OTI copy a value can have a zero
real part and nonzero derivative parts, and skipping it would drop them. The
real results are the same except where a zero entry meets a zero diagonal
(reference LAPACK keeps the 0, this gives 0/0). Invalid arguments return a
negative INFO without calling XERBLA.
"""

DGETRF_DEFINITION = """
      SUBROUTINE DGETRF(M,N,A,LDA,IPIV,INFO)
      IMPLICIT NONE
      INTEGER M,N,LDA,IPIV(*),INFO
      INTEGER J,I,K,JP,INNER
      DOUBLE PRECISION A(LDA,*),BIGGEST,TEMP,RECIP,SFMIN,DIVISOR
      DOUBLE PRECISION BIG,SMALL
      PARAMETER (SFMIN = 2.2250738585072014D-308)
      PARAMETER (BIG = 2.0D0**166, SMALL = 2.0D0**(-166))
      INFO = 0
      IF (M.LT.0) THEN
        INFO = -1
      ELSE IF (N.LT.0) THEN
        INFO = -2
      ELSE IF (LDA.LT.MAX(1,M)) THEN
        INFO = -4
      END IF
      IF (INFO.NE.0) RETURN
      IF (M.EQ.0 .OR. N.EQ.0) RETURN
      DO J = 1,MIN(M,N)
        JP = J
        BIGGEST = ABS(A(J,J))
        DO I = J+1,M
          IF (ABS(A(I,J)).GT.BIGGEST) THEN
            JP = I
            BIGGEST = ABS(A(I,J))
          END IF
        END DO
        IPIV(J) = JP
        IF (A(JP,J).NE.0.0D0) THEN
          IF (JP.NE.J) THEN
            DO K = 1,N
              TEMP = A(J,K)
              A(J,K) = A(JP,K)
              A(JP,K) = TEMP
            END DO
          END IF
          IF (J.LT.M) THEN
            DIVISOR = A(J,J)
            DO INNER = 1,7
              IF (ABS(DIVISOR).GT.BIG) THEN
                DIVISOR = DIVISOR*SMALL
                DO I = J+1,M
                  A(I,J) = A(I,J)*SMALL
                END DO
              ELSE IF (ABS(DIVISOR).LT.SMALL) THEN
                DIVISOR = DIVISOR*BIG
                DO I = J+1,M
                  A(I,J) = A(I,J)*BIG
                END DO
              END IF
            END DO
            IF (ABS(A(J,J)).GE.SFMIN) THEN
              RECIP = 1.0D0/DIVISOR
              DO I = J+1,M
                A(I,J) = RECIP*A(I,J)
              END DO
            ELSE
              DO I = J+1,M
                A(I,J) = A(I,J)/DIVISOR
              END DO
            END IF
          END IF
        ELSE IF (INFO.EQ.0) THEN
          INFO = J
        END IF
        IF (J.LT.MIN(M,N)) THEN
          DO K = J+1,N
            TEMP = -A(J,K)
            DO I = J+1,M
              A(I,K) = A(I,K)+A(I,J)*TEMP
            END DO
          END DO
        END IF
      END DO
      END
"""

DGETRS_DEFINITION = """
      SUBROUTINE DGETRS(TRANS,N,NRHS,A,LDA,IPIV,B,LDB,INFO)
      IMPLICIT NONE
      CHARACTER TRANS
      INTEGER N,NRHS,LDA,LDB,IPIV(*),INFO
      INTEGER I,J,K,IP,INNER
      DOUBLE PRECISION A(LDA,*),B(LDB,*),TEMP,DIVISOR
      DOUBLE PRECISION BIG,SMALL
      PARAMETER (BIG = 2.0D0**166, SMALL = 2.0D0**(-166))
      LOGICAL NORMAL
      NORMAL = TRANS.EQ.'N' .OR. TRANS.EQ.'n'
      INFO = 0
      IF (.NOT.NORMAL .AND. TRANS.NE.'T' .AND. TRANS.NE.'t'
     &    .AND. TRANS.NE.'C' .AND. TRANS.NE.'c') THEN
        INFO = -1
      ELSE IF (N.LT.0) THEN
        INFO = -2
      ELSE IF (NRHS.LT.0) THEN
        INFO = -3
      ELSE IF (LDA.LT.MAX(1,N)) THEN
        INFO = -5
      ELSE IF (LDB.LT.MAX(1,N)) THEN
        INFO = -8
      END IF
      IF (INFO.NE.0 .OR. N.EQ.0 .OR. NRHS.EQ.0) RETURN
      IF (NORMAL) THEN
        DO I = 1,N
          IP = IPIV(I)
          IF (IP.NE.I) THEN
            DO J = 1,NRHS
              TEMP = B(I,J)
              B(I,J) = B(IP,J)
              B(IP,J) = TEMP
            END DO
          END IF
        END DO
        DO J = 1,NRHS
          DO K = 1,N
            DO I = K+1,N
              B(I,J) = B(I,J)-B(K,J)*A(I,K)
            END DO
          END DO
          DO K = N,1,-1
            DIVISOR = A(K,K)
            TEMP = B(K,J)
            DO INNER = 1,7
              IF (ABS(DIVISOR).GT.BIG) THEN
                DIVISOR = DIVISOR*SMALL
                TEMP = TEMP*SMALL
              ELSE IF (ABS(DIVISOR).LT.SMALL) THEN
                DIVISOR = DIVISOR*BIG
                TEMP = TEMP*BIG
              END IF
            END DO
            B(K,J) = TEMP/DIVISOR
            DO I = 1,K-1
              B(I,J) = B(I,J)-B(K,J)*A(I,K)
            END DO
          END DO
        END DO
      ELSE
        DO J = 1,NRHS
          DO I = 1,N
            TEMP = B(I,J)
            DO K = 1,I-1
              TEMP = TEMP-A(K,I)*B(K,J)
            END DO
            DIVISOR = A(I,I)
            DO INNER = 1,7
              IF (ABS(DIVISOR).GT.BIG) THEN
                DIVISOR = DIVISOR*SMALL
                TEMP = TEMP*SMALL
              ELSE IF (ABS(DIVISOR).LT.SMALL) THEN
                DIVISOR = DIVISOR*BIG
                TEMP = TEMP*BIG
              END IF
            END DO
            B(I,J) = TEMP/DIVISOR
          END DO
          DO I = N,1,-1
            TEMP = B(I,J)
            DO K = I+1,N
              TEMP = TEMP-A(K,I)*B(K,J)
            END DO
            B(I,J) = TEMP
          END DO
        END DO
        DO I = N,1,-1
          IP = IPIV(I)
          IF (IP.NE.I) THEN
            DO J = 1,NRHS
              TEMP = B(I,J)
              B(I,J) = B(IP,J)
              B(IP,J) = TEMP
            END DO
          END IF
        END DO
      END IF
      END
"""
