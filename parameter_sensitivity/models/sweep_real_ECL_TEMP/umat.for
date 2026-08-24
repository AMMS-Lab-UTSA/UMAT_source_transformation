      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL,
     1 DDSDDT, DRPLDE, DRPLDT, STRAN, DSTRAN, TIME, DTIME, TEMP, DTEMP,
     2 PREDEF, DPRED, CMNAME, NDI, NSHR, NTENS, NSTATV, PROPS, NPROPS,
     3 COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, NOEL, NPT, LAYER,
     4 KSPT, KSTEP, KINC)
C     UMAT_ECL_TEMP (real ICP): classical isotropic elasticity with
C     temperature-dependent moduli + thermal strain.  Self-contained:
C     KCLEAR / KMAVEC / KUPDVEC inlined.  Small strain, 3D (NTENS=6).
C       PROPS(1)=E1  PROPS(2)=E2  (EMOD=(E1+E2*T)*1000)
C       PROPS(3)=G1  PROPS(4)=G2  (GMOD=(G1+G2*T)*1000)
C       PROPS(5)=CTE (thermal expansion coefficient)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS), STATEV(NSTATV),DDSDDE(NTENS, NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),
     2 PREDEF(1), DPRED(1), PROPS(NPROPS),COORDS(3),DROT(3, 3),
     3 DFGRD0(3, 3), DFGRD1(3, 3)
      DIMENSION DS(NTENS), DSTRTHER(NTENS), DSTRANM(NTENS)
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0, THREE=3.D0)
      INTEGER K1, K2
C
C     Temperature at the end of the step
      THETA=TEMP
      DTHETA=DTEMP
C     Temperature-dependent elastic properties
      EMOD=(PROPS(1)+PROPS(2)*THETA)*1000.0D0
      GMOD=(PROPS(3)+PROPS(4)*THETA)*1000.0D0
      ENU=(EMOD/(TWO*GMOD))-ONE
      CTE=PROPS(5)
C     Lame-type constants
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=TWO*GMOD
      EG=GMOD
      ELAM=(EBULK3-EG2)/THREE
C     Zero the FULL material Jacobian
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=ZERO
        END DO
      END DO
C     Elastic stiffness (isotropic)
      DO K1=1,3
        DO K2=1,3
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DO K1=4,NTENS
        DDSDDE(K1,K1)=EG
      END DO
C     Thermal strain increment (normal components only)  -- KCLEAR inlined
      DO K1=1,NTENS
        DSTRTHER(K1)=ZERO
      END DO
      DO K1=1,NDI
        DSTRTHER(K1)=CTE*DTHETA
      END DO
C     Mechanical strain increment = total - thermal
      DO K1=1,NTENS
        DSTRANM(K1)=DSTRAN(K1)-DSTRTHER(K1)
      END DO
C     Stress increment DS = DDSDDE . DSTRANM  -- KMAVEC inlined
      DO K1=1,NTENS
        DS(K1)=ZERO
        DO K2=1,NTENS
          DS(K1)=DS(K1)+DDSDDE(K1,K2)*DSTRANM(K2)
        END DO
      END DO
C     Update stress  -- KUPDVEC inlined
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+DS(K1)
      END DO
      RETURN
      END
