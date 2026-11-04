      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION X(2), R(2), XJ(2,2)
      E = PROPS(1)
      B1 = E*(STRAN(1)+DSTRAN(1))
      B2 = E*(STRAN(2)+DSTRAN(2)) + 0.5D0*B1
      X(1) = STATEV(9)
      X(2) = STATEV(10)
      Q = 0.0D0
      DO IT = 1, 30
        R(1) = X(1) + 0.1D0*X(1)**3 + 0.2D0*X(1)*X(2) + Q - B1
        R(2) = X(2) + 0.1D0*X(2)**3 + 0.3D0*X(1)**2 - B2
        IF (IT .EQ. 2 .AND. KINC .EQ. 3) THEN
          STATEV(1) = XJ(1,1)
          STATEV(2) = XJ(2,1)
          STATEV(3) = XJ(1,2)
          STATEV(4) = XJ(2,2)
          STATEV(5) = X(1)
          STATEV(6) = X(2)
          STATEV(7) = Q
        END IF
        A11 = 1.0D0 + 0.3D0*X(1)**2 + 0.2D0*X(2)
        A12 = 0.2D0*X(1)
        A21 = 0.6D0*X(1)
        A22 = 1.0D0 + 0.3D0*X(2)**2
        DET = A11*A22 - A12*A21
        DX1 = (A22*R(1) - A12*R(2))/DET
        DX2 = (-A21*R(1) + A11*R(2))/DET
        X(1) = X(1) - DX1
        X(2) = X(2) - DX2
        Q = 0.05D0*X(1)
        IF (ABS(R(1))+ABS(R(2)) .LT. 1.0D-13) EXIT
      END DO
      STRESS(1) = X(1) + X(2)
      STRESS(2) = X(2)
      STRESS(3) = STRESS(3) + E*DSTRAN(3)
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
      END DO
      STATEV(9) = X(1)
      STATEV(10) = X(2)
      RETURN
      END
