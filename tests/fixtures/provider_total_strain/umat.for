C  ------------------------------------------------------------------------
C  Test fixture: total-strain isotropic damage elasticity with history.
C  Written for the UMAT_OTI_EVAL_TOTAL tests because it READS STRAN: the
C  stress is computed from the total strain STRAN+DSTRAN, not incremented
C  from the incoming STRESS, and the damage driver is a history maximum.
C
C    PROPS(1)=E  PROPS(2)=nu  PROPS(3)=K0 (damage threshold strain)
C    PROPS(4)=A  (damage rate) PROPS(5)=EPSMAX (asks for a cut-back above)
C    STATEV(1)=KAPPA, the largest equivalent strain reached so far.
C  eq = sqrt(e11^2+e22^2+e33^2 + (g12^2+g13^2+g23^2)/2)
C  d  = 1 - (K0/KAPPA) exp(-A (KAPPA-K0)) once KAPPA > K0, else 0
C  STRESS = (1-d) C : (STRAN+DSTRAN);  DDSDDE = secant (1-d) C.
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
      DIMENSION EPS(6)
      INTEGER K1,K2
      EMOD=PROPS(1)
      ENU=PROPS(2)
      RK0=PROPS(3)
      AD=PROPS(4)
      EMAX=PROPS(5)
      EBULK3=EMOD/(1.D0-2.D0*ENU)
      EG2=EMOD/(1.D0+ENU)
      EG=EG2/2.D0
      ELAM=(EBULK3-EG2)/3.D0
      DO K1=1,NTENS
        EPS(K1)=STRAN(K1)+DSTRAN(K1)
      END DO
      EQ=EPS(1)**2+EPS(2)**2+EPS(3)**2
      EQ=EQ+0.5D0*(EPS(4)**2+EPS(5)**2+EPS(6)**2)
      EQ=SQRT(EQ)
      IF (EQ.GT.EMAX) PNEWDT=0.5D0
      RKAP=STATEV(1)
      IF (EQ.GT.RKAP) RKAP=EQ
      DAM=0.D0
      IF (RKAP.GT.RK0) DAM=1.D0-(RK0/RKAP)*EXP(-AD*(RKAP-RK0))
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=0.D0
        END DO
      END DO
      DO K1=1,3
        DO K2=1,3
          DDSDDE(K2,K1)=(1.D0-DAM)*ELAM
        END DO
        DDSDDE(K1,K1)=(1.D0-DAM)*(EG2+ELAM)
      END DO
      DO K1=4,6
        DDSDDE(K1,K1)=(1.D0-DAM)*EG
      END DO
      DO K1=1,NTENS
        STRESS(K1)=0.D0
        DO K2=1,NTENS
          STRESS(K1)=STRESS(K1)+DDSDDE(K1,K2)*EPS(K2)
        END DO
      END DO
      STATEV(1)=RKAP
      RETURN
      END
