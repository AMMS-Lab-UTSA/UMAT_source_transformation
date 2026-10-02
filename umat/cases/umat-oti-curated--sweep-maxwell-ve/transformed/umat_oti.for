C  ------------------------------------------------------------------------
C  sweep_maxwell_ve  Linear Maxwell viscoelasticity (small strain, 3D).
C
C  PROPS(1)=E   PROPS(2)=nu   PROPS(3)=tau (deviatoric relaxation time)
C  STATEV(1..6) = deviatoric stress components carried from previous increment
C                 (Voigt 11,22,33,12,13,23, engineering shear).  NSTATV=6.
C
C  Volumetric response is elastic (bulk modulus K).  The deviatoric stress
C  relaxes with time constant tau.  Because tau is a PROPS-parameter we avoid
C  exp-of-a-parameter and use the backward-Euler (implicit) Maxwell update
C     s_new = (s_old + 2G*de_dev) / (1 + DTIME/tau)
C  which is a plain rational function of the parameters (transform-safe).
C  Self-contained: all helper math inlined; STRESS set by inline assignment.
C  ------------------------------------------------------------------------
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      USE otim6n1, OTI_MODULE_DP => DP, OTI_E1 => E1, OTI_E2 => E2,
     1OTI_E3 => E3, OTI_E4 => E4, OTI_E5 => E5, OTI_E6 => E6
      USE oti_intrinsics
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION SDEV(6)
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0)
      INTEGER K1,K2
C
      INTEGER :: OTI_I, OTI_J, OTI_HI, OTI_HJ, OTI_HK
      TYPE(ONUMM6N1) :: OTI_HX, OTI_HY, OTI_HTR
      TYPE(ONUMM6N1) :: DSTRAN_OTI(NTENS)
      TYPE(ONUMM6N1) :: DTR_OTI
      TYPE(ONUMM6N1) :: PHYD_OTI
      TYPE(ONUMM6N1) :: PNEW_OTI
      TYPE(ONUMM6N1) :: SDEV_OTI(6)
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      TAU=PROPS(3)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      BULK=EBULK3/THREE
C     implicit Maxwell relaxation factor 1/(1+DTIME/tau)  (denom>=1, no 0/0)
      RFAC=ONE/(ONE+DTIME/TAU)
      EG2E=EG2*RFAC
      EGE=EG*RFAC
      ELAME=(EBULK3-EG2E)/THREE
C     zero full tangent before setting entries
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=ZERO
        END DO
      END DO
C     consistent tangent: effective elastic operator (Geff=G*RFAC, bulk K)
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=ELAME
        END DO
        DDSDDE(K1,K1)=EG2E+ELAME
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1)=EGE
      END DO
C     volumetric strain increment and old hydrostatic pressure
C     OTIS seed initialization from GUI configuration
      DO OTI_HI = 1, NTENS
         DSTRAN_OTI(OTI_HI) = 0.0D0
      END DO
      DTR_OTI = 0.0D0
      PHYD_OTI = 0.0D0
      PNEW_OTI = 0.0D0
      DO OTI_HI = 1, 6
         SDEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_HI = 1, NTENS
         STRESS_OTI(OTI_HI) = 0.0D0
      END DO
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
      DTR_OTI=ZERO
      DO K1=1,NDI
        DTR_OTI=DTR_OTI+DSTRAN_OTI(K1)
      END DO
      PHYD_OTI=ZERO
      DO K1=1,NDI
        PHYD_OTI=PHYD_OTI+STRESS_OTI(K1)
      END DO
      PHYD_OTI=PHYD_OTI/THREE
C     elastic volumetric update
      PNEW_OTI=PHYD_OTI+BULK*DTR_OTI
C     deviatoric STRESS_OTI update (implicit Maxwell), s_old from STATEV_OTI
      DO K1=1,NDI
      SDEV_OTI(K1)=(STATEV_OTI(K1)+EG2*(DSTRAN_OTI(K1)-DTR_OTI/THREE))*
     1RFAC
      END DO
      DO K1=NDI+1,NTENS
        SDEV_OTI(K1)=(STATEV_OTI(K1)+EG*DSTRAN_OTI(K1))*RFAC
      END DO
C     assemble total STRESS_OTI (inline STRESS_OTI(K)=...)
      DO K1=1,NDI
        STRESS_OTI(K1)=SDEV_OTI(K1)+PNEW_OTI
      END DO
      DO K1=NDI+1,NTENS
        STRESS_OTI(K1)=SDEV_OTI(K1)
      END DO
C     store updated deviatoric STRESS_OTI state
      DO K1=1,NTENS
        STATEV_OTI(K1)=SDEV_OTI(K1)
      END DO
C     Copy real-valued OTIS outputs back to Abaqus arrays
      DO OTI_I = 1, NTENS
         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))
      END DO
      DO OTI_I = 1, NSTATV
         STATEV(OTI_I) = REAL(STATEV_OTI(OTI_I))
      END DO
C     OTIS DDSDDE extraction: DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)
      DO OTI_I = 1, NTENS
         DO OTI_J = 1, NTENS
            DDSDDE(OTI_I,OTI_J) =
     1      GETIM(STRESS_OTI(OTI_I),OTI_J)
         END DO
      END DO
      RETURN
      END
