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
      DIMENSION DEMECH(6), DS(6)
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0, THREE=3.D0)
      INTEGER K1, K2
C     Isotropic thermo-elasticity: E=PROPS(1), nu=PROPS(2), alpha=PROPS(3)
C     Mechanical strain increment = DSTRAN - alpha*DTEMP on the 3 normals.
C     STRESS += DDSDDE : (DSTRAN - alpha*DTEMP*e_normal). Self-contained.
      EMOD=PROPS(1)
      ENU=PROPS(2)
      ALPHA=PROPS(3)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      ELAM=(EBULK3-EG2)/THREE
C     zero the full elastic tangent
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=ZERO
        END DO
      END DO
      DO K1=1,3
        DO K2=1,3
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DDSDDE(4,4)=EG
      DDSDDE(5,5)=EG
      DDSDDE(6,6)=EG
C     mechanical strain increment: subtract thermal expansion on normals
      DO K1=1,NTENS
        DEMECH(K1)=DSTRAN(K1)
      END DO
      DO K1=1,3
        DEMECH(K1)=DSTRAN(K1)-ALPHA*DTEMP
      END DO
C     stress increment DS = DDSDDE . DEMECH, then STRESS += DS (inlined)
      DO K1=1,NTENS
        DS(K1)=ZERO
        DO K2=1,NTENS
          DS(K1)=DS(K1)+DDSDDE(K1,K2)*DEMECH(K2)
        END DO
      END DO
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+DS(K1)
      END DO
      RETURN
      END
