"""OTI-liftable, unblocked implementations of the DGETRF/DGETRS interfaces.

Pivot selection uses primal magnitudes. Invalid arguments return negative INFO
without XERBLA. DGETRS additionally reports a zero diagonal with positive INFO.
"""

DGETRF_DEFINITION = """
      SUBROUTINE DGETRF(M,N,A,LDA,IPIV,INFO)
      IMPLICIT NONE
      INTEGER M,N,LDA,IPIV(*),INFO
      INTEGER COL,ROW,TARGET,PIVOT,INNER
      DOUBLE PRECISION A(LDA,*),BIGGEST,TEMP,DIVISOR
      INFO = 0
      IF (M.LT.0) THEN
        INFO = -1
      ELSE IF (N.LT.0) THEN
        INFO = -2
      ELSE IF (LDA.LT.MAX(1,M)) THEN
        INFO = -4
      END IF
      IF (INFO.NE.0) RETURN
      DO COL = 1,MIN(M,N)
        PIVOT = COL
        BIGGEST = ABS(A(COL,COL))
        DO ROW = COL+1,M
          IF (ABS(A(ROW,COL)).GT.BIGGEST) THEN
            PIVOT = ROW
            BIGGEST = ABS(A(ROW,COL))
          END IF
        END DO
        IPIV(COL) = PIVOT
        IF (A(PIVOT,COL).EQ.0.0D0) THEN
          IF (INFO.EQ.0) INFO = COL
        ELSE
          IF (PIVOT.NE.COL) THEN
            DO TARGET = 1,N
              TEMP = A(COL,TARGET)
              A(COL,TARGET) = A(PIVOT,TARGET)
              A(PIVOT,TARGET) = TEMP
            END DO
          END IF
          DIVISOR = A(COL,COL)
          DO INNER = 1,7
            IF (ABS(DIVISOR).GT.1.0D50) THEN
              DIVISOR = DIVISOR*1.0D-50
              DO ROW = COL+1,M
                A(ROW,COL) = A(ROW,COL)*1.0D-50
              END DO
            ELSE IF (ABS(DIVISOR).LT.1.0D-50) THEN
              DIVISOR = DIVISOR*1.0D50
              DO ROW = COL+1,M
                A(ROW,COL) = A(ROW,COL)*1.0D50
              END DO
            END IF
          END DO
          DO ROW = COL+1,M
            A(ROW,COL) = A(ROW,COL)/DIVISOR
          END DO
          DO TARGET = COL+1,N
            DO ROW = COL+1,M
              A(ROW,TARGET) = A(ROW,TARGET)
     &                        -A(ROW,COL)*A(COL,TARGET)
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
      INTEGER ROW,COL,RHS,PIVOT,INNER
      DOUBLE PRECISION A(LDA,*),B(LDB,*),TEMP,DIVISOR
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
      DO ROW = 1,N
        IF (A(ROW,ROW).EQ.0.0D0) THEN
          INFO = ROW
          RETURN
        END IF
      END DO
      IF (NORMAL) THEN
        DO ROW = 1,N
          PIVOT = IPIV(ROW)
          IF (PIVOT.NE.ROW) THEN
            DO RHS = 1,NRHS
              TEMP = B(ROW,RHS)
              B(ROW,RHS) = B(PIVOT,RHS)
              B(PIVOT,RHS) = TEMP
            END DO
          END IF
        END DO
        DO RHS = 1,NRHS
          DO ROW = 1,N
            DO COL = 1,ROW-1
              B(ROW,RHS) = B(ROW,RHS)-A(ROW,COL)*B(COL,RHS)
            END DO
          END DO
          DO ROW = N,1,-1
            TEMP = B(ROW,RHS)
            DO COL = ROW+1,N
              TEMP = TEMP-A(ROW,COL)*B(COL,RHS)
            END DO
            DIVISOR = A(ROW,ROW)
            DO INNER = 1,7
              IF (ABS(DIVISOR).GT.1.0D50) THEN
                DIVISOR = DIVISOR*1.0D-50
                TEMP = TEMP*1.0D-50
              ELSE IF (ABS(DIVISOR).LT.1.0D-50) THEN
                DIVISOR = DIVISOR*1.0D50
                TEMP = TEMP*1.0D50
              END IF
            END DO
            B(ROW,RHS) = TEMP/DIVISOR
          END DO
        END DO
      ELSE
        DO RHS = 1,NRHS
          DO ROW = 1,N
            TEMP = B(ROW,RHS)
            DO COL = 1,ROW-1
              TEMP = TEMP-A(COL,ROW)*B(COL,RHS)
            END DO
            DIVISOR = A(ROW,ROW)
            DO INNER = 1,7
              IF (ABS(DIVISOR).GT.1.0D50) THEN
                DIVISOR = DIVISOR*1.0D-50
                TEMP = TEMP*1.0D-50
              ELSE IF (ABS(DIVISOR).LT.1.0D-50) THEN
                DIVISOR = DIVISOR*1.0D50
                TEMP = TEMP*1.0D50
              END IF
            END DO
            B(ROW,RHS) = TEMP/DIVISOR
          END DO
          DO ROW = N,1,-1
            DO COL = ROW+1,N
              B(ROW,RHS) = B(ROW,RHS)-A(COL,ROW)*B(COL,RHS)
            END DO
          END DO
        END DO
        DO ROW = N,1,-1
          PIVOT = IPIV(ROW)
          IF (PIVOT.NE.ROW) THEN
            DO RHS = 1,NRHS
              TEMP = B(ROW,RHS)
              B(ROW,RHS) = B(PIVOT,RHS)
              B(PIVOT,RHS) = TEMP
            END DO
          END IF
        END DO
      END IF
      END
"""