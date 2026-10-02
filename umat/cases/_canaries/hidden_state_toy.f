C  Mutant canary for the hidden-state comparator of tools/corpus_cases.py.
C  Linear isotropic "material" STRESS = STRESS + E*DSTRAN, DDSDDE = E*I.
C  PROPS(2) > 0 switches on a SAVE'd call counter that scales the stress:
C  the output then depends on how often the routine was called before,
C  not only on its arguments (hidden state). PROPS(2) = 0 is the control:
C  identical code path, counter unused, so the comparator must accept it.
C  GPL-3.0-only (UMAT-OTI authors).
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
      INTEGER NCALL
      SAVE NCALL
      DATA NCALL /0/
      NCALL = NCALL + 1
      FAC = 1.D0
      IF (PROPS(2) .GT. 0.D0) FAC = 1.D0 + 1.D-3*DBLE(NCALL)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + FAC*PROPS(1)*DSTRAN(I)
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = FAC*PROPS(1)
      END DO
      STATEV(1) = STATEV(1) + DSTRAN(1)
      RETURN
      END
