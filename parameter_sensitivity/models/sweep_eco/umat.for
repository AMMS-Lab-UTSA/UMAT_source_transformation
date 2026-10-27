C  ---------------------------------------------------------------------
C  Adapted from UMATS/UMAT_ECO.for in ABAQUS-US by Juan Gomez,
C  Universidad EAFIT (https://github.com/jgomezc1/ABAQUS-US).
C  The original is distributed under the MIT License; its notice is
C  kept below as that licence requires. See THIRD_PARTY_NOTICES.md 2a.
C
C  Copyright (c) [2015] [Juan Gomez]
C
C  Permission is hereby granted, free of charge, to any person obtaining
C  a copy of this software and associated documentation files (the
C  "Software"), to deal in the Software without restriction, including
C  without limitation the rights to use, copy, modify, merge, publish,
C  distribute, sublicense, and/or sell copies of the Software, and to
C  permit persons to whom the Software is furnished to do so, subject to
C  the following conditions:
C
C  The above copyright notice and this permission notice shall be
C  included in all copies or substantial portions of the Software.
C
C  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
C  EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
C  MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
C  NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
C  BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
C  ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
C  CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
C  SOFTWARE.
C  ---------------------------------------------------------------------
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
C     UMAT_ECO (Cosserat elasticity), self-contained; E=PROPS(1), nu=PROPS(2)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      ELAM=(EBULK3-EG2)/THREE
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=ZERO
        END DO
      END DO
      DO K1=1, 3
        DO K2=1, 3
          DDSDDE(K2, K1)=ELAM
        END DO
        DDSDDE(K1, K1)=EG2+ELAM
      END DO
      DDSDDE(4,4)=EG
      DDSDDE(5,5)=EG2
      DDSDDE(6,6)=EG2
C     stress increment DS = DDSDDE . DSTRAN, then STRESS += DS  (KMAVEC/KUPDVEC inlined)
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
