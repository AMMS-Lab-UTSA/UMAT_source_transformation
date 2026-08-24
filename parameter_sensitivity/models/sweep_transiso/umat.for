      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
C     Transversely isotropic linear elasticity. Plane of isotropy = 1-2,
C     axis of symmetry = 3. Voigt order (11,22,33,12,13,23). Small strain.
C     Self-contained. Stiffness built by analytic inverse of the 3x3
C     normal-compliance block; shear diagonals set directly.
C     PROPS(1)=EP (in-plane Young), PROPS(2)=ET (axial Young),
C     PROPS(3)=XNUP (in-plane Poisson), PROPS(4)=XNUPT (plane-axis Poisson),
C     PROPS(5)=GT (transverse/axial shear modulus).
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0)
      DIMENSION DS(6)
      INTEGER K1,K2
      EP    = PROPS(1)
      ET    = PROPS(2)
      XNUP  = PROPS(3)
      XNUPT = PROPS(4)
      G13   = PROPS(5)
      G23   = PROPS(5)
C     Symmetric 3x3 normal compliance block:
C       [ A  B  C ]   A = 1/EP, B = -XNUP/EP,
C       [ B  A  C ]   C = -XNUPT/EP, D = 1/ET
C       [ C  C  D ]
      A = ONE/EP
      B = -XNUP/EP
      C = -XNUPT/EP
      D = ONE/ET
C     Closed-form determinant of the 3x3 (factored form):
      DET = (A-B)*(D*(A+B) - TWO*C*C)
C     Tiny positive floor to avoid exact 0/0 (~1.0D-24, negligible vs DET):
      DETS = DET + ONE/(1.0D8*1.0D8*1.0D8)
C     Analytic inverse (symmetric) -> normal stiffness block:
      Q11 = (A*D - C*C)/DETS
      Q12 = (C*C - B*D)/DETS
      Q13 = (C*(B-A))/DETS
      Q33 = (A*A - B*B)/DETS
C     In-plane shear modulus for the 12 component:
      GP = EP/(TWO*(ONE+XNUP))
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=ZERO
        END DO
      END DO
      DDSDDE(1,1)=Q11
      DDSDDE(2,2)=Q11
      DDSDDE(3,3)=Q33
      DDSDDE(1,2)=Q12
      DDSDDE(2,1)=Q12
      DDSDDE(1,3)=Q13
      DDSDDE(3,1)=Q13
      DDSDDE(2,3)=Q13
      DDSDDE(3,2)=Q13
      DDSDDE(4,4)=GP
      DDSDDE(5,5)=G13
      DDSDDE(6,6)=G23
      DO K1=1,NTENS
        DS(K1)=ZERO
        DO K2=1,NTENS
          DS(K1)=DS(K1)+DDSDDE(K1,K2)*DSTRAN(K2)
        END DO
      END DO
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+DS(K1)
      END DO
      RETURN
      END
