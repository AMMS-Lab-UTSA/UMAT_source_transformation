C ============================================================
C  Small-strain isotropic linear-elastic UMAT (3D, NTENS=6).
C  Reads Young's modulus and Poisson's ratio from PROPS:
C     PROPS(1) = E    (Young's modulus)
C     PROPS(2) = XNU  (Poisson's ratio)
C  No STATEV. Written in classical fixed-form Fortran with the
C  standard Abaqus UMAT signature so the source transformer can
C  operate on it without any material-specific hint.
C ============================================================
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
C
      INCLUDE 'ABA_PARAM.INC'
C
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
C
      PARAMETER (ONE = 1.0D0, TWO = 2.0D0, THREE = 3.0D0, ZERO = 0.0D0)
C
      INTEGER I, J
      DIMENSION DSTRESS(6)
C
C     Material properties from PROPS.
      E    = PROPS(1)
      XNU  = PROPS(2)
      ELAM = E * XNU / ((ONE + XNU) * (ONE - TWO * XNU))
      EG2  = E / (ONE + XNU)
      EG   = EG2 / TWO
C
C     Stress increment: sigma_new = sigma_old + C : dstran (Voigt engineering shear).
      DSTRESS(1) = (ELAM + EG2) * DSTRAN(1) + ELAM * DSTRAN(2) + ELAM * DSTRAN(3)
      DSTRESS(2) = ELAM * DSTRAN(1) + (ELAM + EG2) * DSTRAN(2) + ELAM * DSTRAN(3)
      DSTRESS(3) = ELAM * DSTRAN(1) + ELAM * DSTRAN(2) + (ELAM + EG2) * DSTRAN(3)
      DSTRESS(4) = EG * DSTRAN(4)
      DSTRESS(5) = EG * DSTRAN(5)
      DSTRESS(6) = EG * DSTRAN(6)
C
      DO I = 1, NTENS
         STRESS(I) = STRESS(I) + DSTRESS(I)
      END DO
C
C     Consistent tangent (unchanged in linear elasticity).
      DO I = 1, NTENS
         DO J = 1, NTENS
            DDSDDE(I, J) = ZERO
         END DO
      END DO
      DO I = 1, 3
         DO J = 1, 3
            DDSDDE(I, J) = ELAM
         END DO
         DDSDDE(I, I) = ELAM + EG2
      END DO
      DDSDDE(4, 4) = EG
      DDSDDE(5, 5) = EG
      DDSDDE(6, 6) = EG
C
      RETURN
      END
