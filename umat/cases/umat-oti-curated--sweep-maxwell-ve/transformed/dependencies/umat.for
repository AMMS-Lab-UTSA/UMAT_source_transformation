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
      DTR=ZERO
      DO K1=1,NDI
        DTR=DTR+DSTRAN(K1)
      END DO
      PHYD=ZERO
      DO K1=1,NDI
        PHYD=PHYD+STRESS(K1)
      END DO
      PHYD=PHYD/THREE
C     elastic volumetric update
      PNEW=PHYD+BULK*DTR
C     deviatoric stress update (implicit Maxwell), s_old from STATEV
      DO K1=1,NDI
        SDEV(K1)=(STATEV(K1)+EG2*(DSTRAN(K1)-DTR/THREE))*RFAC
      END DO
      DO K1=NDI+1,NTENS
        SDEV(K1)=(STATEV(K1)+EG*DSTRAN(K1))*RFAC
      END DO
C     assemble total stress (inline STRESS(K)=...)
      DO K1=1,NDI
        STRESS(K1)=SDEV(K1)+PNEW
      END DO
      DO K1=NDI+1,NTENS
        STRESS(K1)=SDEV(K1)
      END DO
C     store updated deviatoric stress state
      DO K1=1,NTENS
        STATEV(K1)=SDEV(K1)
      END DO
      RETURN
      END
