"""Source implementation of the DSPEVD interface for OTI helper lifting.

Uses cyclic Jacobi rotations, not LAPACK's divide-and-conquer algorithm.
Positive INFO signals nonconvergence (1).

**Repeated eigenvalues.** An individual eigenvalue of a repeated pair is not
differentiable, and no arithmetic can make it so: for a block

    [ a + p*e   q*e     ]
    [ q*e       a + r*e ]

the first-order eigenvalues are a + (p+r)/2 +- sqrt(((p-r)/2)**2 + q**2)*e,
and that square root is not linear in the perturbation. The eigenvectors are
worse: a repeated eigenvalue has an eigen*space*, and which basis of it the
perturbation selects depends on the direction of the perturbation, so with
several seeded directions there is no single basis to return.

What *is* differentiable is any symmetric function of the repeated block --
its trace and its determinant are linear in the perturbation -- and a yield
surface written as a sum over principal stresses is one. So this routine
averages a repeated cluster instead of refusing it: every eigenvalue in the
cluster gets the cluster mean, which leaves the sum exact and therefore gives
the exact derivative of any symmetric function of them, while making no claim
about an individual member that has no derivative to claim. The eigenvectors
are left as the primal Jacobi sweep produced them; a projector onto the whole
cluster is basis-independent, which is the form these expressions take.

A model that instead reads DIFFERENCES of principal stresses inside a repeated
cluster -- some yield surfaces are written that way -- is asking for
the part that does not exist, and gets zero for it.
"""

DSPEVD_DEFINITION = """
      SUBROUTINE DSPEVD(JOBZ,UPLO,N,AP,W,Z,LDZ,WORK,LWORK,
     &                  IWORK,LIWORK,INFO)
      IMPLICIT NONE
      CHARACTER JOBZ, UPLO
      INTEGER N,LDZ,LWORK,LIWORK,INFO,IWORK(*)
      DOUBLE PRECISION AP(*),W(*),Z(LDZ,*),WORK(*)
      DOUBLE PRECISION AMAT(MAX(1,N),MAX(1,N))
      DOUBLE PRECISION VECS(MAX(1,N),MAX(1,N))
      DOUBLE PRECISION SCALE,GAP,OFFVAL,ROOT,TANGENT,COSINE,SINE
      DOUBLE PRECISION LEFTVAL,RIGHTVAL,TEMP,RESIDUAL,BIGGEST
      INTEGER LWMIN,LIWMIN,ROW,COL,PACKED,SWEEP,LEFT,RIGHT
      INTEGER SELECTED,PIVOT,SCALEPOWER,RESCALE
      LOGICAL WANTZ,UPPER,LQUERY
      WANTZ = JOBZ.EQ.'V' .OR. JOBZ.EQ.'v'
      UPPER = UPLO.EQ.'U' .OR. UPLO.EQ.'u'
      LQUERY = LWORK.EQ.-1 .OR. LIWORK.EQ.-1
      INFO = 0
      IF (.NOT.WANTZ .AND. JOBZ.NE.'N' .AND. JOBZ.NE.'n') THEN
        INFO = -1
      ELSE IF (.NOT.UPPER .AND. UPLO.NE.'L'
     &         .AND. UPLO.NE.'l') THEN
        INFO = -2
      ELSE IF (N.LT.0) THEN
        INFO = -3
      ELSE IF (LDZ.LT.1 .OR. (WANTZ .AND. LDZ.LT.N)) THEN
        INFO = -7
      END IF
      IF (INFO.NE.0) RETURN
      LWMIN = 1
      LIWMIN = 1
      IF (N.GT.1) THEN
        LWMIN = 2*N
        IF (WANTZ) THEN
          LWMIN = 1+6*N+N*N
          LIWMIN = 3+5*N
        END IF
      END IF
      WORK(1) = DBLE(LWMIN)
      IWORK(1) = LIWMIN
      IF (LQUERY) RETURN
      IF (LWORK.LT.LWMIN) THEN
        INFO = -9
      ELSE IF (LIWORK.LT.LIWMIN) THEN
        INFO = -11
      END IF
      IF (INFO.NE.0 .OR. N.EQ.0) RETURN
      IF (N.EQ.1) THEN
        W(1) = AP(1)
        IF (WANTZ) Z(1,1) = 1.0D0
        RETURN
      END IF
      PACKED = 0
      SCALE = 0.0D0
      DO COL = 1,N
        IF (UPPER) THEN
          DO ROW = 1,COL
            PACKED = PACKED+1
            AMAT(ROW,COL) = AP(PACKED)
            AMAT(COL,ROW) = AP(PACKED)
            IF (ABS(AP(PACKED)).GT.SCALE) THEN
              SCALE = ABS(AP(PACKED))
            END IF
          END DO
        ELSE
          DO ROW = COL,N
            PACKED = PACKED+1
            AMAT(ROW,COL) = AP(PACKED)
            AMAT(COL,ROW) = AP(PACKED)
            IF (ABS(AP(PACKED)).GT.SCALE) THEN
              SCALE = ABS(AP(PACKED))
            END IF
          END DO
        END IF
      END DO
      IF (SCALE.EQ.0.0D0) THEN
        TEMP = AMAT(1,1)
        DO ROW = 2,N
          TEMP = TEMP+AMAT(ROW,ROW)
        END DO
        TEMP = TEMP/DBLE(N)
        DO COL = 1,N
          W(COL) = TEMP
          IF (WANTZ) THEN
            DO ROW = 1,N
              Z(ROW,COL) = 0.0D0
            END DO
            Z(COL,COL) = 1.0D0
          END IF
        END DO
        RETURN
      END IF
      SCALEPOWER = 0
      DO WHILE (SCALE.GT.1.0D50)
        IF (SCALEPOWER.GE.7) THEN
          INFO = 1
          RETURN
        END IF
        DO COL = 1,N
          DO ROW = 1,N
            AMAT(ROW,COL) = AMAT(ROW,COL)*1.0D-50
          END DO
        END DO
        SCALE = SCALE*1.0D-50
        SCALEPOWER = SCALEPOWER+1
      END DO
      DO WHILE (SCALE.LT.1.0D-50)
        DO COL = 1,N
          DO ROW = 1,N
            AMAT(ROW,COL) = AMAT(ROW,COL)*1.0D50
          END DO
        END DO
        SCALE = SCALE*1.0D50
        SCALEPOWER = SCALEPOWER-1
      END DO
      DO COL = 1,N
        DO ROW = 1,N
          AMAT(ROW,COL) = AMAT(ROW,COL)/SCALE
          VECS(ROW,COL) = 0.0D0
        END DO
        VECS(COL,COL) = 1.0D0
      END DO
!     ROOT is hypot(GAP, 2*OFFVAL), formed without squaring either term.
!     SQRT(GAP*GAP + 4*OFFVAL*OFFVAL) underflows: OFFVAL*OFFVAL is exactly
!     zero below about 1.5D-154, so ROOT came back as ABS(GAP) -- and as zero
!     when GAP had converged to zero as well, which is the ordinary end state
!     for a repeated eigenvalue. TANGENT then divided 2*OFFVAL by zero. The
!     guard below passes, because OFFVAL is not zero; it simply cannot survive
!     being squared. Measured: a 3x3 with two eigenvalues 4.5D-13 apart
!     reaches GAP = 0 with OFFVAL = -2.9D-184 and returns NaN.
!
!     Scaling by the larger term keeps the ratio inside range, so the small
!     one underflows harmlessly inside a sum that is already one. Note what
!     this must NOT do: skip the rotation when OFFVAL looks negligible. Under
!     a hypercomplex type an off-diagonal whose real part is zero can still
!     carry the whole derivative, and dropping it returns eigenvector
!     sensitivities of zero for every diagonal matrix.
      DO SWEEP = 1,50
        DO LEFT = 1,N-1
          DO RIGHT = LEFT+1,N
            GAP = AMAT(RIGHT,RIGHT)-AMAT(LEFT,LEFT)
            OFFVAL = AMAT(LEFT,RIGHT)
            IF (GAP.NE.0.0D0 .OR. OFFVAL.NE.0.0D0) THEN
              BIGGEST = ABS(GAP)
              TEMP = ABS(OFFVAL+OFFVAL)
              IF (BIGGEST.GE.TEMP) THEN
                ROOT = BIGGEST*SQRT(1.0D0+(TEMP/BIGGEST)*(TEMP/BIGGEST))
              ELSE
                ROOT = TEMP*SQRT(1.0D0+(BIGGEST/TEMP)*(BIGGEST/TEMP))
              END IF
              IF (GAP.LT.0.0D0) ROOT = -ROOT
              TANGENT = (2.0D0*OFFVAL)/(GAP+ROOT)
              COSINE = 1.0D0/SQRT(1.0D0+TANGENT*TANGENT)
              SINE = TANGENT*COSINE
              AMAT(LEFT,LEFT) = AMAT(LEFT,LEFT)-TANGENT*OFFVAL
              AMAT(RIGHT,RIGHT) = AMAT(RIGHT,RIGHT)+TANGENT*OFFVAL
              AMAT(LEFT,RIGHT) = 0.0D0
              AMAT(RIGHT,LEFT) = 0.0D0
              DO ROW = 1,N
                IF (ROW.NE.LEFT .AND. ROW.NE.RIGHT) THEN
                  LEFTVAL = AMAT(ROW,LEFT)
                  RIGHTVAL = AMAT(ROW,RIGHT)
                  AMAT(ROW,LEFT) = COSINE*LEFTVAL-SINE*RIGHTVAL
                  AMAT(LEFT,ROW) = AMAT(ROW,LEFT)
                  AMAT(ROW,RIGHT) = SINE*LEFTVAL+COSINE*RIGHTVAL
                  AMAT(RIGHT,ROW) = AMAT(ROW,RIGHT)
                END IF
                LEFTVAL = VECS(ROW,LEFT)
                RIGHTVAL = VECS(ROW,RIGHT)
                VECS(ROW,LEFT) = COSINE*LEFTVAL-SINE*RIGHTVAL
                VECS(ROW,RIGHT) = SINE*LEFTVAL+COSINE*RIGHTVAL
              END DO
            END IF
          END DO
        END DO
      END DO
!     Written as .NOT.(RESIDUAL.LE.tol) rather than RESIDUAL.GT.tol: every
!     comparison against NaN is false, so the .GT. form reported INFO = 0 --
!     success -- on a matrix whose eigenvalues had all become NaN.
      RESIDUAL = 0.0D0
      DO COL = 1,N
        W(COL) = AMAT(COL,COL)
        DO ROW = 1,COL-1
          IF (ABS(AMAT(ROW,COL)).GT.RESIDUAL) THEN
            RESIDUAL = ABS(AMAT(ROW,COL))
          END IF
        END DO
      END DO
      IF (.NOT.(RESIDUAL.LE.1.0D-13)) THEN
        INFO = 1
        RETURN
      END IF
      DO LEFT = 1,N-1
        SELECTED = LEFT
        DO RIGHT = LEFT+1,N
          IF (W(RIGHT).LT.W(SELECTED)) SELECTED = RIGHT
        END DO
        IF (SELECTED.NE.LEFT) THEN
          TEMP = W(LEFT)
          W(LEFT) = W(SELECTED)
          W(SELECTED) = TEMP
          DO ROW = 1,N
            TEMP = VECS(ROW,LEFT)
            VECS(ROW,LEFT) = VECS(ROW,SELECTED)
            VECS(ROW,SELECTED) = TEMP
          END DO
        END IF
      END DO
      LEFT = 1
      DO WHILE (LEFT.LE.N)
        RIGHT = LEFT
        DO WHILE (RIGHT.LT.N)
          IF (W(RIGHT+1)-W(RIGHT).GT.1.0D-12) EXIT
          RIGHT = RIGHT+1
        END DO
        IF (RIGHT.GT.LEFT) THEN
          TEMP = W(LEFT)
          DO COL = LEFT+1,RIGHT
            TEMP = TEMP+W(COL)
          END DO
          TEMP = TEMP/DBLE(RIGHT-LEFT+1)
          DO COL = LEFT,RIGHT
            W(COL) = TEMP
          END DO
        END IF
        LEFT = RIGHT+1
      END DO
      DO COL = 1,N
        W(COL) = W(COL)*SCALE
        DO RESCALE = 1,ABS(SCALEPOWER)
          IF (SCALEPOWER.GT.0) THEN
            W(COL) = W(COL)*1.0D50
          ELSE
            W(COL) = W(COL)*1.0D-50
          END IF
        END DO
        IF (WANTZ) THEN
          PIVOT = 1
          BIGGEST = ABS(VECS(1,COL))
          DO ROW = 2,N
            IF (ABS(VECS(ROW,COL)).GT.BIGGEST) THEN
              PIVOT = ROW
              BIGGEST = ABS(VECS(ROW,COL))
            END IF
          END DO
          IF (VECS(PIVOT,COL).LT.0.0D0) THEN
            DO ROW = 1,N
              VECS(ROW,COL) = -VECS(ROW,COL)
            END DO
          END IF
          DO ROW = 1,N
            Z(ROW,COL) = VECS(ROW,COL)
          END DO
        END IF
      END DO
      END
"""