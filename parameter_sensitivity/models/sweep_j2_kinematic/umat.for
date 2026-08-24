C  ------------------------------------------------------------------------
C  sweep_j2_kinematic : Small-strain von Mises (J2) plasticity with LINEAR
C  KINEMATIC (Prager) hardening.  Radial return on the RELATIVE stress
C  xi = dev(sigma) - alpha ; the yield surface has fixed size SIGY0 and
C  translates by the backstress alpha.
C
C  PROPS(1)=E  PROPS(2)=nu  PROPS(3)=SIGY0 (yield)  PROPS(4)=Hk (kin. mod.)
C  STATEV(1..6) = ALPHA (deviatoric backstress tensor, Voigt 11,22,33,12,13,23)
C
C  Return mapping (equivalent plastic strain increment DEQPL):
C     DEQPL = (SMISES - SIGY0)/(3G + Hk)          SMISES = q(sigma-alpha)
C     STRESS(K) = STRESS_trial(K) - 3G*DEQPL*FLOW(K)
C     ALPHA(K)  = ALPHA(K)        + Hk*DEQPL*FLOW(K)
C  Consistent (algorithmic) tangent is the isotropic-J2 form with HARD->Hk
C  and Mises/flow taken on the relative stress.  Self-contained; no external
C  CALLs; STRESS set by inline assignment.  INCLUDE ABA_PARAM.INC -> REAL*8.
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
      DIMENSION FLOW(6),ALPHA(6),RELS(6)
      INTEGER K1,K2,K
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HARD=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
C     read backstress history
      DO K=1,6
        ALPHA(K)=STATEV(K)
      END DO
C     elastic stiffness (also the predictor operator)
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=ZERO
        END DO
      END DO
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1)=EG
      END DO
C     elastic predictor stress
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)
        END DO
      END DO
C     relative stress xi = sigma - alpha (alpha deviatoric)
      DO K=1,NTENS
        RELS(K)=STRESS(K)-ALPHA(K)
      END DO
C     Mises equivalent of the relative stress (hydrostatic cancels)
      SMISES=(RELS(1)-RELS(2))**2+(RELS(2)-RELS(3))**2
     1      +(RELS(3)-RELS(1))**2
      DO K1=NDI+1,NTENS
        SMISES=SMISES+SIX*RELS(K1)**2
      END DO
      SMISES=SQRT(SMISES/TWO)
      SYIEL0=SIGY0
C
      IF (SMISES.GT.SYIEL0) THEN
C       flow direction from the RELATIVE deviatoric stress
        RHYDRO=(RELS(1)+RELS(2)+RELS(3))/THREE
        DO K1=1,NDI
          FLOW(K1)=(RELS(K1)-RHYDRO)/SMISES
        END DO
        DO K1=NDI+1,NTENS
          FLOW(K1)=RELS(K1)/SMISES
        END DO
C       closed-form return (linear kinematic hardening)
        DEQPL=(SMISES-SYIEL0)/(EG3+HARD)
        SYIELD=SYIEL0+HARD*DEQPL
C       stress update: sigma = sigma_trial - 3G*DEQPL*flow
        DO K1=1,NTENS
          STRESS(K1)=STRESS(K1)-EG3*DEQPL*FLOW(K1)
        END DO
C       backstress update: alpha += Hk*DEQPL*flow
        DO K1=1,NTENS
          ALPHA(K1)=ALPHA(K1)+HARD*DEQPL*FLOW(K1)
        END DO
C       consistent (algorithmic) tangent
        EFFG=EG*SYIELD/SMISES
        EFFG2=TWO*EFFG
        EFFG3=THREE/TWO*EFFG2
        EFFLAM=(EBULK3-EFFG2)/THREE
        EFFHRD=EG3*HARD/(EG3+HARD)-EFFG3
        DO K1=1,NTENS
          DO K2=1,NTENS
            DDSDDE(K2,K1)=ZERO
          END DO
        END DO
        DO K1=1,NDI
          DO K2=1,NDI
            DDSDDE(K2,K1)=EFFLAM
          END DO
          DDSDDE(K1,K1)=EFFG2+EFFLAM
        END DO
        DO K1=NDI+1,NTENS
          DDSDDE(K1,K1)=EFFG
        END DO
        DO K1=1,NTENS
          DO K2=1,NTENS
            DDSDDE(K2,K1)=DDSDDE(K2,K1)+EFFHRD*FLOW(K2)*FLOW(K1)
          END DO
        END DO
      END IF
C     store updated backstress
      DO K=1,6
        STATEV(K)=ALPHA(K)
      END DO
      RETURN
      END
