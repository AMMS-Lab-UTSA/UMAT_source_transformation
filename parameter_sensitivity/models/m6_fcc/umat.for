C  ------------------------------------------------------------------------
C  FCC single-crystal plasticity (small strain, rate-dependent power-law slip).
C  12 {111}<110> slip systems, explicit sub-stepped integration.
C
C    PROPS(1)=C11  PROPS(2)=C12  PROPS(3)=C44   (cubic elastic, crystal frame)
C    PROPS(4)=g0   initial slip resistance
C    PROPS(5)=gsat saturation slip resistance
C    PROPS(6)=h0   initial hardening rate
C    PROPS(7)=a    hardening exponent
C    PROPS(8)=q    latent-hardening ratio
C    PROPS(9)=gd0  reference slip rate
C    PROPS(10)=m   rate sensitivity
C  STATEV(1..12) = slip resistances g^alpha.  NSTATV = 12.
C  Voigt (11,22,33,12,13,23), engineering shear. Crystal aligned with lab ([100]).
C  ------------------------------------------------------------------------
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION RMAT(12,6),CMAT(6,6),GRES(12),TAU(12),GDOT(12),DGAM(12),
     1 HALP(12),DEP(6),DSUB(6)
      INTEGER IA, IB, ISUB, I, J, K
      PARAMETER(NSUB=10, RNSUB=10.D0)
C     ---- Schmid vectors R^alpha = [P11,P22,P33,2P12,2P13,2P23] ----
      RMAT(1,1)=+0.0000000000D0
      RMAT(1,2)=+0.4082482905D0
      RMAT(1,3)=-0.4082482905D0
      RMAT(1,4)=+0.4082482905D0
      RMAT(1,5)=-0.4082482905D0
      RMAT(1,6)=+0.0000000000D0
      RMAT(2,1)=+0.4082482905D0
      RMAT(2,2)=+0.0000000000D0
      RMAT(2,3)=-0.4082482905D0
      RMAT(2,4)=+0.4082482905D0
      RMAT(2,5)=+0.0000000000D0
      RMAT(2,6)=-0.4082482905D0
      RMAT(3,1)=+0.4082482905D0
      RMAT(3,2)=-0.4082482905D0
      RMAT(3,3)=+0.0000000000D0
      RMAT(3,4)=+0.0000000000D0
      RMAT(3,5)=+0.4082482905D0
      RMAT(3,6)=-0.4082482905D0
      RMAT(4,1)=-0.0000000000D0
      RMAT(4,2)=+0.4082482905D0
      RMAT(4,3)=-0.4082482905D0
      RMAT(4,4)=-0.4082482905D0
      RMAT(4,5)=+0.4082482905D0
      RMAT(4,6)=+0.0000000000D0
      RMAT(5,1)=-0.4082482905D0
      RMAT(5,2)=+0.0000000000D0
      RMAT(5,3)=+0.4082482905D0
      RMAT(5,4)=+0.4082482905D0
      RMAT(5,5)=+0.0000000000D0
      RMAT(5,6)=+0.4082482905D0
      RMAT(6,1)=-0.4082482905D0
      RMAT(6,2)=+0.4082482905D0
      RMAT(6,3)=+0.0000000000D0
      RMAT(6,4)=+0.0000000000D0
      RMAT(6,5)=+0.4082482905D0
      RMAT(6,6)=+0.4082482905D0
      RMAT(7,1)=+0.0000000000D0
      RMAT(7,2)=-0.4082482905D0
      RMAT(7,3)=+0.4082482905D0
      RMAT(7,4)=+0.4082482905D0
      RMAT(7,5)=+0.4082482905D0
      RMAT(7,6)=+0.0000000000D0
      RMAT(8,1)=+0.4082482905D0
      RMAT(8,2)=-0.0000000000D0
      RMAT(8,3)=-0.4082482905D0
      RMAT(8,4)=-0.4082482905D0
      RMAT(8,5)=+0.0000000000D0
      RMAT(8,6)=+0.4082482905D0
      RMAT(9,1)=+0.4082482905D0
      RMAT(9,2)=-0.4082482905D0
      RMAT(9,3)=+0.0000000000D0
      RMAT(9,4)=+0.0000000000D0
      RMAT(9,5)=+0.4082482905D0
      RMAT(9,6)=+0.4082482905D0
      RMAT(10,1)=+0.0000000000D0
      RMAT(10,2)=+0.4082482905D0
      RMAT(10,3)=-0.4082482905D0
      RMAT(10,4)=+0.4082482905D0
      RMAT(10,5)=+0.4082482905D0
      RMAT(10,6)=+0.0000000000D0
      RMAT(11,1)=+0.4082482905D0
      RMAT(11,2)=+0.0000000000D0
      RMAT(11,3)=-0.4082482905D0
      RMAT(11,4)=+0.4082482905D0
      RMAT(11,5)=+0.0000000000D0
      RMAT(11,6)=+0.4082482905D0
      RMAT(12,1)=+0.4082482905D0
      RMAT(12,2)=-0.4082482905D0
      RMAT(12,3)=-0.0000000000D0
      RMAT(12,4)=+0.0000000000D0
      RMAT(12,5)=-0.4082482905D0
      RMAT(12,6)=+0.4082482905D0
C     ---- properties ----
      C11=PROPS(1)
      C12=PROPS(2)
      C44=PROPS(3)
      G0=PROPS(4)
      GSAT=PROPS(5)
      H0=PROPS(6)
      AEXP=PROPS(7)
      QLAT=PROPS(8)
      GD0=PROPS(9)
      RM=PROPS(10)
C     ---- cubic elastic stiffness ----
      DO I=1,6
        DO J=1,6
          CMAT(I,J)=0.D0
        END DO
      END DO
      DO I=1,3
        DO J=1,3
          CMAT(I,J)=C12
        END DO
        CMAT(I,I)=C11
      END DO
      CMAT(4,4)=C44
      CMAT(5,5)=C44
      CMAT(6,6)=C44
C     DDSDDE returned as the elastic stiffness (OTI transform replaces it).
      DO I=1,6
        DO J=1,6
          DDSDDE(I,J)=CMAT(I,J)
        END DO
      END DO
C     ---- read accumulated hardening, defined as g minus the initial slip
C          resistance; it starts at zero and the initial resistance re-enters
C          the response through the sum G0 + GRES so it stays differentiable
      DO IA=1,12
        GRES(IA)=STATEV(IA)
      END DO
C     ---- explicit sub-stepped integration ----
      DTS=DTIME/RNSUB
      DO K=1,6
        DSUB(K)=DSTRAN(K)/RNSUB
      END DO
      DO ISUB=1,NSUB
        DO IA=1,12
          TAU(IA)=0.D0
          DO K=1,6
            TAU(IA)=TAU(IA)+STRESS(K)*RMAT(IA,K)
          END DO
          RATIO=TAU(IA)/(G0+GRES(IA))
C         power-law slip rate written with pure arithmetic (OTI-differentiable,
C         smooth at zero for m<1): gd0 * RATIO * (RATIO^2)^((1/m-1)/2).
C         Tiny floor keeps the base strictly positive so the OTI power (exp/log)
C         is well defined at RATIO=0 (elastic); negligible vs plastic RATIO~1.
          R2=RATIO*RATIO+0.00000001D0*0.00000001D0
          GDOT(IA)=GD0*(R2**((1.D0/RM-1.D0)/2.D0))*RATIO
          DGAM(IA)=GDOT(IA)*DTS
        END DO
        DO K=1,6
          DEP(K)=0.D0
          DO IA=1,12
            DEP(K)=DEP(K)+DGAM(IA)*RMAT(IA,K)
          END DO
        END DO
        DO I=1,6
          DO J=1,6
            STRESS(I)=STRESS(I)+CMAT(I,J)*(DSUB(J)-DEP(J))
          END DO
        END DO
        DO IA=1,12
          BASE=1.D0-(G0+GRES(IA))/GSAT
          IF (BASE.LT.0.D0) BASE=0.D0
          HALP(IA)=H0*BASE**AEXP
        END DO
        DO IA=1,12
          DG=0.D0
          DO IB=1,12
            QAB=QLAT
            IF (IA.EQ.IB) QAB=1.D0
            DG=DG+QAB*HALP(IB)*ABS(DGAM(IB))
          END DO
          GRES(IA)=GRES(IA)+DG
        END DO
      END DO
      DO IA=1,12
        STATEV(IA)=GRES(IA)
      END DO
      RETURN
      END
