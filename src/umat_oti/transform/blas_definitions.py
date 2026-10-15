"""OTI-liftable bodies of the BLAS routines and of DSYEV that UMATs call.

The loop orders are those of reference BLAS, so the real twins give the same
results as reference BLAS for finite arguments. Two shortcuts of reference BLAS
are left out because in the OTI copy a value can have a zero real part and
nonzero derivative parts: DAXPY does not return early when DA is zero, and
DGEMM does not skip a column when an entry of B is zero. The real results are
the same (an added 0*x is exact for finite x).

DSYEV is written on the supplied DSPEVD (cyclic Jacobi, see
spectral_definitions): the matrix is packed, DSPEVD gives the eigenvalues in
ascending order and, for JOBZ='V', orthonormal eigenvectors, which are copied
back into A. Eigenvalues agree with LAPACK's to rounding; eigenvectors agree up
to sign (and, inside a repeated cluster, up to a rotation within the cluster).

Licence: DCOPY, DSCAL, DAXPY, DGEMV and DGEMM are derived from Reference BLAS
(dcopy.f, dscal.f, daxpy.f, dgemv.f, dgemm.f) and DSYEV's interface and argument
checks from Reference LAPACK's dsyev.f (https://github.com/Reference-LAPACK/lapack),
BSD-3-Clause, Copyright (c) 1992-2023 The University of Tennessee and The
University of Tennessee Research Foundation, (c) 2000-2023 The University of
California Berkeley, (c) 2006-2023 The University of Colorado Denver. The full
notice is in THIRD_PARTY_NOTICES.md, section 5, and in
abaqus_utility_definitions.REFERENCE_LAPACK_LICENCE; generated files that hold
these bodies carry it.
"""

DCOPY_DEFINITION = """
      SUBROUTINE DCOPY(N,DX,INCX,DY,INCY)
      IMPLICIT NONE
      INTEGER N,INCX,INCY,I,IX,IY
      DOUBLE PRECISION DX(*),DY(*)
      IF (N.LE.0) RETURN
      IX = 1
      IY = 1
      IF (INCX.LT.0) IX = (-N+1)*INCX+1
      IF (INCY.LT.0) IY = (-N+1)*INCY+1
      DO I = 1,N
        DY(IY) = DX(IX)
        IX = IX+INCX
        IY = IY+INCY
      END DO
      END
"""

DSCAL_DEFINITION = """
      SUBROUTINE DSCAL(N,DA,DX,INCX)
      IMPLICIT NONE
      INTEGER N,INCX,I,IX
      DOUBLE PRECISION DA,DX(*)
      IF (N.LE.0 .OR. INCX.LE.0) RETURN
      IX = 1
      DO I = 1,N
        DX(IX) = DA*DX(IX)
        IX = IX+INCX
      END DO
      END
"""

DAXPY_DEFINITION = """
      SUBROUTINE DAXPY(N,DA,DX,INCX,DY,INCY)
      IMPLICIT NONE
      INTEGER N,INCX,INCY,I,IX,IY
      DOUBLE PRECISION DA,DX(*),DY(*)
      IF (N.LE.0) RETURN
      IX = 1
      IY = 1
      IF (INCX.LT.0) IX = (-N+1)*INCX+1
      IF (INCY.LT.0) IY = (-N+1)*INCY+1
      DO I = 1,N
        DY(IY) = DY(IY)+DA*DX(IX)
        IX = IX+INCX
        IY = IY+INCY
      END DO
      END
"""

DGEMV_DEFINITION = """
      SUBROUTINE DGEMV(TRANS,M,N,ALPHA,A,LDA,X,INCX,BETA,Y,INCY)
      IMPLICIT NONE
      CHARACTER TRANS
      INTEGER M,N,LDA,INCX,INCY,I,J,IX,IY,JX,JY,KX,KY,LENX,LENY
      DOUBLE PRECISION ALPHA,BETA,A(LDA,*),X(*),Y(*),TEMP
      LOGICAL NORMAL
      NORMAL = TRANS.EQ.'N' .OR. TRANS.EQ.'n'
      IF (M.EQ.0 .OR. N.EQ.0) RETURN
      IF (NORMAL) THEN
        LENX = N
        LENY = M
      ELSE
        LENX = M
        LENY = N
      END IF
      KX = 1
      KY = 1
      IF (INCX.LT.0) KX = 1-(LENX-1)*INCX
      IF (INCY.LT.0) KY = 1-(LENY-1)*INCY
      IF (BETA.NE.1.0D0) THEN
        IY = KY
        DO I = 1,LENY
          IF (BETA.EQ.0.0D0) THEN
            Y(IY) = 0.0D0
          ELSE
            Y(IY) = BETA*Y(IY)
          END IF
          IY = IY+INCY
        END DO
      END IF
      IF (NORMAL) THEN
        JX = KX
        DO J = 1,N
          TEMP = ALPHA*X(JX)
          IY = KY
          DO I = 1,M
            Y(IY) = Y(IY)+TEMP*A(I,J)
            IY = IY+INCY
          END DO
          JX = JX+INCX
        END DO
      ELSE
        JY = KY
        DO J = 1,N
          TEMP = 0.0D0
          IX = KX
          DO I = 1,M
            TEMP = TEMP+A(I,J)*X(IX)
            IX = IX+INCX
          END DO
          Y(JY) = Y(JY)+ALPHA*TEMP
          JY = JY+INCY
        END DO
      END IF
      END
"""

DGEMM_DEFINITION = """
      SUBROUTINE DGEMM(TRANSA,TRANSB,M,N,K,ALPHA,A,LDA,B,LDB,
     &                 BETA,C,LDC)
      IMPLICIT NONE
      CHARACTER TRANSA,TRANSB
      INTEGER M,N,K,LDA,LDB,LDC,I,J,L
      DOUBLE PRECISION ALPHA,BETA,A(LDA,*),B(LDB,*),C(LDC,*),TEMP
      LOGICAL NOTA,NOTB
      NOTA = TRANSA.EQ.'N' .OR. TRANSA.EQ.'n'
      NOTB = TRANSB.EQ.'N' .OR. TRANSB.EQ.'n'
      IF (M.EQ.0 .OR. N.EQ.0) RETURN
      IF (NOTB) THEN
        IF (NOTA) THEN
          DO J = 1,N
            IF (BETA.EQ.0.0D0) THEN
              DO I = 1,M
                C(I,J) = 0.0D0
              END DO
            ELSE IF (BETA.NE.1.0D0) THEN
              DO I = 1,M
                C(I,J) = BETA*C(I,J)
              END DO
            END IF
            DO L = 1,K
              TEMP = ALPHA*B(L,J)
              DO I = 1,M
                C(I,J) = C(I,J)+TEMP*A(I,L)
              END DO
            END DO
          END DO
        ELSE
          DO J = 1,N
            DO I = 1,M
              TEMP = 0.0D0
              DO L = 1,K
                TEMP = TEMP+A(L,I)*B(L,J)
              END DO
              IF (BETA.EQ.0.0D0) THEN
                C(I,J) = ALPHA*TEMP
              ELSE
                C(I,J) = ALPHA*TEMP+BETA*C(I,J)
              END IF
            END DO
          END DO
        END IF
      ELSE
        IF (NOTA) THEN
          DO J = 1,N
            IF (BETA.EQ.0.0D0) THEN
              DO I = 1,M
                C(I,J) = 0.0D0
              END DO
            ELSE IF (BETA.NE.1.0D0) THEN
              DO I = 1,M
                C(I,J) = BETA*C(I,J)
              END DO
            END IF
            DO L = 1,K
              TEMP = ALPHA*B(J,L)
              DO I = 1,M
                C(I,J) = C(I,J)+TEMP*A(I,L)
              END DO
            END DO
          END DO
        ELSE
          DO J = 1,N
            DO I = 1,M
              TEMP = 0.0D0
              DO L = 1,K
                TEMP = TEMP+A(L,I)*B(J,L)
              END DO
              IF (BETA.EQ.0.0D0) THEN
                C(I,J) = ALPHA*TEMP
              ELSE
                C(I,J) = ALPHA*TEMP+BETA*C(I,J)
              END IF
            END DO
          END DO
        END IF
      END IF
      END
"""

DSYEV_DEFINITION = """
      SUBROUTINE DSYEV(JOBZ,UPLO,N,A,LDA,W,WORK,LWORK,INFO)
      IMPLICIT NONE
      CHARACTER JOBZ,UPLO
      INTEGER N,LDA,LWORK,INFO,ROW,COL,K,LWMIN
      DOUBLE PRECISION A(LDA,*),W(*),WORK(*)
      DOUBLE PRECISION AP(MAX(1,(N*(N+1))/2))
      DOUBLE PRECISION Z(MAX(1,N),MAX(1,N))
      DOUBLE PRECISION SWORK(1+6*MAX(1,N)+MAX(1,N)*MAX(1,N))
      INTEGER SIWORK(3+5*MAX(1,N))
      LOGICAL WANTZ,UPPER
      WANTZ = JOBZ.EQ.'V' .OR. JOBZ.EQ.'v'
      UPPER = UPLO.EQ.'U' .OR. UPLO.EQ.'u'
      INFO = 0
      IF (.NOT.WANTZ .AND. JOBZ.NE.'N' .AND. JOBZ.NE.'n') THEN
        INFO = -1
      ELSE IF (.NOT.UPPER .AND. UPLO.NE.'L' .AND. UPLO.NE.'l') THEN
        INFO = -2
      ELSE IF (N.LT.0) THEN
        INFO = -3
      ELSE IF (LDA.LT.MAX(1,N)) THEN
        INFO = -5
      END IF
      LWMIN = MAX(1,3*N-1)
      IF (INFO.EQ.0 .AND. LWORK.LT.LWMIN .AND. LWORK.NE.-1) INFO = -8
      IF (INFO.NE.0) RETURN
      WORK(1) = 1.0D0*LWMIN
      IF (LWORK.EQ.-1 .OR. N.EQ.0) RETURN
      K = 0
      IF (UPPER) THEN
        DO COL = 1,N
          DO ROW = 1,COL
            K = K+1
            AP(K) = A(ROW,COL)
          END DO
        END DO
      ELSE
        DO COL = 1,N
          DO ROW = COL,N
            K = K+1
            AP(K) = A(ROW,COL)
          END DO
        END DO
      END IF
      CALL DSPEVD(JOBZ,UPLO,N,AP,W,Z,MAX(1,N),SWORK,
     &            1+6*MAX(1,N)+MAX(1,N)*MAX(1,N),SIWORK,
     &            3+5*MAX(1,N),INFO)
      IF (INFO.NE.0 .OR. .NOT.WANTZ) RETURN
      DO COL = 1,N
        DO ROW = 1,N
          A(ROW,COL) = Z(ROW,COL)
        END DO
      END DO
      END
"""
