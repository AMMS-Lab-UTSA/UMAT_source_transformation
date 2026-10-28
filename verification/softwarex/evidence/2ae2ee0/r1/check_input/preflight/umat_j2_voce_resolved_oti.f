C ======================================================================
C  umat_j2_voce.f  --  NEWLY WRITTEN replacement model. NOT TRANSFORMED.
C  NOT VERIFIED. Do not report any result from it until the verification
C  task in ../../../missing-evidence.md (task T4, R1) is done.
C
C  Provenance: written from scratch by Quill (Council builder agent,
C  AI-assisted; Claude) on 2026-10-27 for the UMAT-OTI manuscript, from
C  the standard small-strain von Mises radial-return formulation with
C  nonlinear isotropic hardening as presented in textbooks:
C    E.A. de Souza Neto, D. Peric, D.R.J. Owen, Computational Methods
C      for Plasticity, Wiley, 2008 (von Mises model, return mapping
C      with nonlinear isotropic hardening and its consistent tangent);
C    J.C. Simo, T.J.R. Hughes, Computational Inelasticity, Springer,
C      1998 (radial return, consistent elastoplastic tangent).
C  The governing equations implemented are written out in README.md
C  next to this file; they are the specification. No existing UMAT
C  source (bundled, imported, acquired or Abaqus-manual example) was
C  opened or copied while writing this file. Variable names were
C  chosen independently. Licence: none granted yet (Santiago decides;
C  if added to the UMAT-OTI repository it would fall under that
C  repository's licence).
C
C  Model: isotropic linear elasticity; von Mises yield; associative
C  flow; isotropic hardening
C     SY(EP) = SIGY0 + HLIN*EP + QSAT*(1 - EXP(-BSAT*EP))
C  Small strain only (NLGEOM=NO). NTENS = 6 (NDI = 3, NSHR = 3) only;
C  Voigt order 11,22,33,12,13,23 with engineering shear strains.
C  PROPS(1..6) = E, NU, SIGY0, HLIN, QSAT, BSAT.  NSTATV >= 1:
C  STATEV(1) = accumulated equivalent plastic strain EP.
C
C  The plastic multiplier DGAM is found by a scalar local Newton
C  iteration on  RES(DGAM) = QTR - 3*G*DGAM - SY(EP_n + DGAM) = 0,
C  update statement DGAM = DGAM - RES/DRES (scalar names, inside a DO
C  loop), so that UMAT-OTI's internal-Jacobian detector can apply.
C  At least one Newton step is always taken before the convergence
C  test (avoids the zero-iteration exit discussed by Noether, B3).
C ======================================================================
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
      DIMENSION STRIAL(6),SDEV(6),FLOWN(6)
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0, THREE=3.D0,
     1 HALF=0.5D0, THREEHALF=1.5D0, TOLR=1.D-12, MAXIT=50)
C
C     ---- material constants ------------------------------------------
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: DEVOL_OTI
      TYPE(ONUMM6N1) :: DGAM_OTI
      TYPE(ONUMM6N1) :: DRES_OTI
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: EPK_OTI
      TYPE(ONUMM6N1) :: EPN_OTI
      TYPE(ONUMM6N1) :: EPNEW_OTI
      TYPE(ONUMM6N1) :: FACT_OTI
      TYPE(ONUMM6N1) :: HPK_OTI
      TYPE(ONUMM6N1) :: PHI_OTI
      TYPE(ONUMM6N1) :: PTR_OTI
      TYPE(ONUMM6N1) :: QTR_OTI
      TYPE(ONUMM6N1) :: RES_OTI
      TYPE(ONUMM6N1) :: SDEV_OTI(6)
      TYPE(ONUMM6N1) :: SNORM_OTI
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      TYPE(ONUMM6N1) :: STRIAL_OTI(6)
      TYPE(ONUMM6N1) :: SYK_OTI
      TYPE(ONUMM6N1) :: SYN_OTI
      YMOD  = PROPS(1)
      PNU   = PROPS(2)
      SIGY0 = PROPS(3)
      HLIN  = PROPS(4)
      QSAT  = PROPS(5)
      BSAT  = PROPS(6)
      GMOD  = YMOD/(TWO*(ONE+PNU))
      BULK  = YMOD/(THREE*(ONE-TWO*PNU))
      ALAM  = BULK - TWO*GMOD/THREE
      G3    = THREE*GMOD
C
C     OTIS seed initialization from GUI configuration
      DEVOL_OTI = 0.0D0
      DGAM_OTI = 0.0D0
      DRES_OTI = 0.0D0
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      EPK_OTI = 0.0D0
      EPN_OTI = 0.0D0
      EPNEW_OTI = 0.0D0
      FACT_OTI = 0.0D0
      HPK_OTI = 0.0D0
      PHI_OTI = 0.0D0
      PTR_OTI = 0.0D0
      QTR_OTI = 0.0D0
      RES_OTI = 0.0D0
      DO OTI_HI = 1, 6
         SDEV_OTI(OTI_HI) = 0.0D0
      END DO
      SNORM_OTI = 0.0D0
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, 6
         STRIAL_OTI(OTI_HI) = 0.0D0
      END DO
      SYK_OTI = 0.0D0
      SYN_OTI = 0.0D0
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
      EPN_OTI = STATEV_OTI(1)
C
C     ---- elastic predictor -------------------------------------------
      DEVOL_OTI = DSTRAN_OTI(1) + DSTRAN_OTI(2) + DSTRAN_OTI(3)
      DO I = 1, 3
      STRIAL_OTI(I) = STRESS_OTI(I) + ALAM*DEVOL_OTI + TWO*GMOD*
     1DSTRAN_OTI(I)
      END DO
      DO I = 4, 6
         STRIAL_OTI(I) = STRESS_OTI(I) + GMOD*DSTRAN_OTI(I)
      END DO
      PTR_OTI = (STRIAL_OTI(1) + STRIAL_OTI(2) + STRIAL_OTI(3))/THREE
      DO I = 1, 3
         SDEV_OTI(I) = STRIAL_OTI(I) - PTR_OTI
      END DO
      DO I = 4, 6
         SDEV_OTI(I) = STRIAL_OTI(I)
      END DO
C     norm of the deviator (tensor components; shear counted twice)
      SNORM_OTI = SQRT((((MAX(REAL(SDEV_OTI(1)**2 + SDEV_OTI(2)**2 +
     1SDEV_OTI(3)**2+ TWO*(SDEV_OTI(4)**2 + SDEV_OTI(5)**2 +
     1SDEV_OTI(6)**2)), 1.0D-30)) - REAL(SDEV_OTI(1)**2 + SDEV_OTI(2)**
     12 + SDEV_OTI(3)**2+ TWO*(SDEV_OTI(4)**2 + SDEV_OTI(5)**2 +
     1SDEV_OTI(6)**2))) + (SDEV_OTI(1)**2 + SDEV_OTI(2)**2 +
     1SDEV_OTI(3)**2+ TWO*(SDEV_OTI(4)**2 + SDEV_OTI(5)**2 +
     1SDEV_OTI(6)**2))))
C     OTIS-SKIP: 1      + TWO*(SDEV(4)**2 + SDEV(5)**2 + SDEV(6)**2))
      QTR_OTI = SQRT(THREEHALF)*SNORM_OTI
      SYN_OTI = SIGY0 + HLIN*EPN_OTI + QSAT*(ONE - EXP(-BSAT*EPN_OTI))
      PHI_OTI = QTR_OTI - SYN_OTI
C
C     ---- elastic tangent (also the elastic-branch result) ------------
      DO J = 1, 6
         DO I = 1, 6
C     OTIS-SKIP: DDSDDE(I,J) = ZERO
         END DO
      END DO
      DO J = 1, 3
         DO I = 1, 3
C     OTIS-SKIP: DDSDDE(I,J) = ALAM
         END DO
C     OTIS-SKIP: DDSDDE(J,J) = ALAM + TWO*GMOD
      END DO
      DO I = 4, 6
C     OTIS-SKIP: DDSDDE(I,I) = GMOD
      END DO
C
      IF (REAL(PHI_OTI) .LE. ZERO) THEN
C        ---- elastic step ---------------------------------------------
         DO I = 1, 6
            STRESS_OTI(I) = STRIAL_OTI(I)
         END DO
      GO TO 99999
      END IF
C
C     ---- plastic step: scalar local Newton on DGAM -------------------
      DGAM_OTI = ZERO
      DO KNEWT = 1, MAXIT
         EPK_OTI  = EPN_OTI + DGAM_OTI
      SYK_OTI  = SIGY0 + HLIN*EPK_OTI + QSAT*(ONE - EXP(-BSAT*EPK_OTI))
         HPK_OTI  = HLIN + QSAT*BSAT*EXP(-BSAT*EPK_OTI)
         RES_OTI  = QTR_OTI - G3*DGAM_OTI - SYK_OTI
         DRES_OTI = -G3 - HPK_OTI
         DGAM_OTI = DGAM_OTI - RES_OTI/DRES_OTI
         IF (ABS(REAL(RES_OTI)) .LE. TOLR*SIGY0) GO TO 20
      END DO
C     no convergence: ask Abaqus for a smaller increment
      PNEWDT = 0.25D0
   20 CONTINUE
C
      EPNEW_OTI = EPN_OTI + DGAM_OTI
C     OTIS-SKIP: HPNEW = HLIN + QSAT*BSAT*EXP(-BSAT*EPNEW)
      FACT_OTI  = ONE - G3*DGAM_OTI/QTR_OTI
      DO I = 1, 6
C     OTIS-SKIP: FLOWN(I) = SDEV(I)/SNORM
      END DO
      DO I = 1, 3
         STRESS_OTI(I) = FACT_OTI*SDEV_OTI(I) + PTR_OTI
      END DO
      DO I = 4, 6
         STRESS_OTI(I) = FACT_OTI*SDEV_OTI(I)
      END DO
      STATEV_OTI(1) = EPNEW_OTI
C
C     ---- hand-coded consistent tangent (README Eq. T) ----------------
C     D = K 1x1 + 2G*FACT*Idev + 6G^2*(DGAM/QTR - 1/(3G+H')) n x n
C     OTIS-SKIP: C1 = TWO*GMOD*FACT
C     OTIS-SKIP: C2 = 6.D0*GMOD*GMOD*(DGAM/QTR - ONE/(G3 + HPNEW))
      DO J = 1, 6
         DO I = 1, 6
C     OTIS-SKIP: DDSDDE(I,J) = C2*FLOWN(I)*FLOWN(J)
         END DO
      END DO
      DO J = 1, 3
         DO I = 1, 3
C     OTIS-SKIP: DDSDDE(I,J) = DDSDDE(I,J) + BULK - C1/THREE
         END DO
C     OTIS-SKIP: DDSDDE(J,J) = DDSDDE(J,J) + C1
      END DO
      DO I = 4, 6
C     OTIS-SKIP: DDSDDE(I,I) = DDSDDE(I,I) + HALF*C1
      END DO
C
      GO TO 99999
99999 CONTINUE
C     OTIS real extraction inserted before RETURN
C     Copy real-valued OTIS outputs back to Abaqus arrays
      DO OTI_I = 1, NTENS
         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))
      END DO
      DO OTI_I = 1, NSTATV
         STATEV(OTI_I) = REAL(STATEV_OTI(OTI_I))
      END DO
C     OTIS derivative extraction inserted before RETURN
C     OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)
      DO OTI_I = 1, NTENS
         DO OTI_J = 1, NTENS
            DDSDDE(OTI_I,OTI_J) =
     1      GETIM(STRESS_OTI(OTI_I),OTI_J)
         END DO
      END DO
      END
