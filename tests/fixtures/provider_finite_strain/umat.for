C     Compressible neo-Hookean with a path-dependent stiffening term.
C
C     A DEFORMATION-GRADIENT-DRIVEN fixture: the Cauchy stress is built
C     from DFGRD1 alone and STRAN/DSTRAN are never read.  That is the whole
C     point of it -- every small-strain fixture in this repository returns a
C     stress from DSTRAN, so none of them can tell whether a provider entry
C     point actually forwards the caller's deformation gradient or quietly
C     substitutes the identity.  Driven through an entry point that passes
C     F = I this model returns exactly zero stress for every increment.
C
C       B     = F . F^T,  J = det F
C       sigma = scale * [ (mu/J)(B - I) + (lam/J) ln(J) I ]
C       scale = 1 + hard * kappa,   kappa = kappa_n + |ln J|
C
C     PROPS(1)=mu  PROPS(2)=lam  PROPS(3)=hard
C     STATEV(1)=kappa (the history; it feeds the stress back, so a total
C     derivative through a path differs from a one-shot one).
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IMPLICIT REAL*8(A-H,O-Z)
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION B(3,3)
      AMU  = PROPS(1)
      ALAM = PROPS(2)
      HARD = PROPS(3)
C     left Cauchy-Green B = F . F^T
      DO I = 1,3
        DO J = 1,3
          S = 0.0D0
          DO K = 1,3
            S = S + DFGRD1(I,K)*DFGRD1(J,K)
          END DO
          B(I,J) = S
        END DO
      END DO
      DETF = DFGRD1(1,1)*(DFGRD1(2,2)*DFGRD1(3,3)-DFGRD1(2,3)*DFGRD1(3,2))
     1     - DFGRD1(1,2)*(DFGRD1(2,1)*DFGRD1(3,3)-DFGRD1(2,3)*DFGRD1(3,1))
     2     + DFGRD1(1,3)*(DFGRD1(2,1)*DFGRD1(3,2)-DFGRD1(2,2)*DFGRD1(3,1))
      ALJ = LOG(DETF)
      AKAP = STATEV(1) + ABS(ALJ)
      SCALE = 1.0D0 + HARD*AKAP
      C1 = SCALE*AMU/DETF
      C2 = SCALE*ALAM*ALJ/DETF
      STRESS(1) = C1*(B(1,1)-1.0D0) + C2
      STRESS(2) = C1*(B(2,2)-1.0D0) + C2
      STRESS(3) = C1*(B(3,3)-1.0D0) + C2
      IF (NTENS .GE. 4) STRESS(4) = C1*B(1,2)
      IF (NTENS .GE. 5) STRESS(5) = C1*B(1,3)
      IF (NTENS .GE. 6) STRESS(6) = C1*B(2,3)
      STATEV(1) = AKAP
C     The consistent tangent is what the provider differentiates out; the
C     original only has to be a correct stress function for the reference.
      DO I = 1,NTENS
        DO J = 1,NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
      END DO
      PNEWDT = 1.0D0
      RETURN
      END
