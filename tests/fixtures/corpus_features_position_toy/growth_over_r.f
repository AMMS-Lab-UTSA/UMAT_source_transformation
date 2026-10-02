      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
C     Toy position-dependent growth law (Gauss, pass18 COORDS fix):
C     isotropic growth strain rate G = PROPS(3)*(1+NPT/10)/r, r = |COORDS(1:2)|,
C     as in the Jeff97 circular-plate laws. Non-finite at COORDS = 0.
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      E=PROPS(1)
      ANU=PROPS(2)
      ALAM=E*ANU/((1.D0+ANU)*(1.D0-2.D0*ANU))
      AMU=E/(2.D0*(1.D0+ANU))
      R=SQRT(COORDS(1)**2+COORDS(2)**2)
      G=PROPS(3)*(1.D0+0.1D0*NPT)/R
      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
      END DO
      DO I=1,NDI
        DO J=1,NDI
          DDSDDE(I,J)=ALAM
        END DO
        DDSDDE(I,I)=ALAM+2.D0*AMU
      END DO
      DO I=NDI+1,NTENS
        DDSDDE(I,I)=AMU
      END DO
      DO I=1,NTENS
        DO J=1,NTENS
          DG=0.D0
          IF (J .LE. NDI) DG=G*DTIME
          STRESS(I)=STRESS(I)+DDSDDE(I,J)*(DSTRAN(J)-DG)
        END DO
      END DO
C     STATEV(1): accumulated growth strain
      STATEV(1)=STATEV(1)+G*DTIME
      RETURN
      END
