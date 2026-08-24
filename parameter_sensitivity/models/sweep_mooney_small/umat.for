      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL,
     1 DDSDDT, DRPLDE, DRPLDT, STRAN, DSTRAN, TIME, DTIME, TEMP, DTEMP,
     2 PREDEF, DPRED, CMNAME, NDI, NSHR, NTENS, NSTATV, PROPS, NPROPS,
     3 COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, NOEL, NPT, LAYER,
     4 KSPT, KSTEP, KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS), STATEV(NSTATV),DDSDDE(NTENS, NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),
     2 PREDEF(1), DPRED(1), PROPS(NPROPS),COORDS(3),DROT(3, 3),
     3 DFGRD0(3, 3), DFGRD1(3, 3)
      DIMENSION DS(NTENS)
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0, THREE=3.D0)
      INTEGER K1,K2
C     Small-strain compressible neo-Hookean reduction = isotropic elasticity
C     Parameters: mu (shear)=PROPS(1), kappa (bulk)=PROPS(2)
C     C = kappa*I(x)I + 2*mu*(I4 - 1/3 I(x)I)
C     Normal-normal diag = kappa + 4/3 mu ; off-diag = kappa - 2/3 mu ; shear = mu
      EMU=PROPS(1)
      EKAP=PROPS(2)
      ELAM=EKAP-(TWO/THREE)*EMU
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=ZERO
        END DO
      END DO
      DO K1=1, 3
        DO K2=1, 3
          DDSDDE(K2, K1)=ELAM
        END DO
        DDSDDE(K1, K1)=ELAM+TWO*EMU
      END DO
      DDSDDE(4,4)=EMU
      DDSDDE(5,5)=EMU
      DDSDDE(6,6)=EMU
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
