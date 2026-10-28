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
     1 HALF=0.5D0, THREEHALF=1.5D0, TOLR=-1.D0, MAXIT=3)
C
C     ---- material constants ------------------------------------------
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
      EPN = STATEV(1)
C
C     ---- elastic predictor -------------------------------------------
      DEVOL = DSTRAN(1) + DSTRAN(2) + DSTRAN(3)
      DO I = 1, 3
         STRIAL(I) = STRESS(I) + ALAM*DEVOL + TWO*GMOD*DSTRAN(I)
      END DO
      DO I = 4, 6
         STRIAL(I) = STRESS(I) + GMOD*DSTRAN(I)
      END DO
      PTR = (STRIAL(1) + STRIAL(2) + STRIAL(3))/THREE
      DO I = 1, 3
         SDEV(I) = STRIAL(I) - PTR
      END DO
      DO I = 4, 6
         SDEV(I) = STRIAL(I)
      END DO
C     norm of the deviator (tensor components; shear counted twice)
      SNORM = SQRT(SDEV(1)**2 + SDEV(2)**2 + SDEV(3)**2
     1      + TWO*(SDEV(4)**2 + SDEV(5)**2 + SDEV(6)**2))
      QTR = SQRT(THREEHALF)*SNORM
      SYN = SIGY0 + HLIN*EPN + QSAT*(ONE - EXP(-BSAT*EPN))
      PHI = QTR - SYN
C
C     ---- elastic tangent (also the elastic-branch result) ------------
      DO J = 1, 6
         DO I = 1, 6
            DDSDDE(I,J) = ZERO
         END DO
      END DO
      DO J = 1, 3
         DO I = 1, 3
            DDSDDE(I,J) = ALAM
         END DO
         DDSDDE(J,J) = ALAM + TWO*GMOD
      END DO
      DO I = 4, 6
         DDSDDE(I,I) = GMOD
      END DO
C
      IF (PHI .LE. ZERO) THEN
C        ---- elastic step ---------------------------------------------
         DO I = 1, 6
            STRESS(I) = STRIAL(I)
         END DO
         RETURN
      END IF
C
C     ---- plastic step: scalar local Newton on DGAM -------------------
      DGAM = ZERO
      DO KNEWT = 1, MAXIT
         EPK  = EPN + DGAM
         SYK  = SIGY0 + HLIN*EPK + QSAT*(ONE - EXP(-BSAT*EPK))
         HPK  = HLIN + QSAT*BSAT*EXP(-BSAT*EPK)
         RES  = QTR - G3*DGAM - SYK
         DRES = -G3 - HPK
         DGAM = DGAM - RES/DRES
         IF (ABS(RES) .LE. TOLR*SIGY0) GO TO 20
      END DO
C     no convergence: ask Abaqus for a smaller increment
      PNEWDT = 0.25D0
   20 CONTINUE
C
      EPNEW = EPN + DGAM
      HPNEW = HLIN + QSAT*BSAT*EXP(-BSAT*EPNEW)
      FACT  = ONE - G3*DGAM/QTR
      DO I = 1, 6
         FLOWN(I) = SDEV(I)/SNORM
      END DO
      DO I = 1, 3
         STRESS(I) = FACT*SDEV(I) + PTR
      END DO
      DO I = 4, 6
         STRESS(I) = FACT*SDEV(I)
      END DO
      STATEV(1) = EPNEW
C
C     ---- hand-coded consistent tangent (README Eq. T) ----------------
C     D = K 1x1 + 2G*FACT*Idev + 6G^2*(DGAM/QTR - 1/(3G+H')) n x n
      C1 = TWO*GMOD*FACT
      C2 = 6.D0*GMOD*GMOD*(DGAM/QTR - ONE/(G3 + HPNEW))
      DO J = 1, 6
         DO I = 1, 6
            DDSDDE(I,J) = C2*FLOWN(I)*FLOWN(J)
         END DO
      END DO
      DO J = 1, 3
         DO I = 1, 3
            DDSDDE(I,J) = DDSDDE(I,J) + BULK - C1/THREE
         END DO
         DDSDDE(J,J) = DDSDDE(J,J) + C1
      END DO
      DO I = 4, 6
         DDSDDE(I,I) = DDSDDE(I,I) + HALF*C1
      END DO
C
      RETURN
      END
