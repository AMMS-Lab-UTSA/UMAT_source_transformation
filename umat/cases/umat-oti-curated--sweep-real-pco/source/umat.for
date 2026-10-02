C  ------------------------------------------------------------------------
C  sweep_real_PCO  Plasticity Couple-Stress (reduced Cosserat) solid.
C
C  Self-contained, inline reformulation of the production UMAT_PCO.for.
C  The production routine builds the return map through the external helper
C  chain KCLEAR / KMMULT / KMTRAN / KMAVEC / KUPDVEC / KPROYECTOR /
C  KSPECTRAL (a fixed spectral/eigenvector decomposition of the couple-stress
C  deviatoric projector) plus a local Newton loop and a XIT abort.  None of
C  those helpers are self-contained and several use constructs the OTI
C  transform forbids (external CALLs updating STRESS, ABS-based Newton exit,
C  XIT).  They are provably unnecessary: because the spectral operator scales
C  every deviatoric/shear eigen-direction by the SAME factor 1/(1+2G*gamma)
C  and preserves the hydrostatic axis, B=Q*DIAG*Q^T reduces the whole update
C  to a radial return in the couple-stress metric, with a CLOSED FORM for the
C  linear-hardening consistency parameter (no Newton, no ABS, no eigen-solve).
C
C  Couple-stress structure retained faithfully:
C    * elastic operator: shear-12 modulus = G,  shear-13/23 modulus = 2G
C    * deviatoric metric P: normal block std, comp 12 weight 2, comps 13/23
C      weight 1  ->  FBAR^2 = s^T P s
C    * yield:  FBAR > sqrt(2/3)*(SIGY0 + H*EQPLAS)   (KUHARD scaling)
C
C  PROPS(1)=E  PROPS(2)=nu  PROPS(3)=SIGY0  PROPS(4)=H (hardening slope)
C  STATEV(1)=EQPLAS (accumulated equivalent plastic strain).
C  Voigt (11,22,33,12,13,23), engineering shear.
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
      DIMENSION DS(6),FLOW(6)
      INTEGER K1,K2
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      HARD=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      ELAM=(EBULK3-EG2)/THREE
      SQ23=SQRT(TWO/THREE)
      TOLER=1.0D-6
C     couple-stress elastic predictor operator (also stored in DDSDDE)
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=ZERO
        END DO
      END DO
      DO K1=1,3
        DO K2=1,3
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DDSDDE(4,4)=EG
      DDSDDE(5,5)=EG2
      DDSDDE(6,6)=EG2
C     elastic predictor stress: DS = DDSDDE . DSTRAN, STRESS += DS (inline)
      DO K1=1,NTENS
        DS(K1)=ZERO
        DO K2=1,NTENS
          DS(K1)=DS(K1)+DDSDDE(K1,K2)*DSTRAN(K2)
        END DO
      END DO
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+DS(K1)
      END DO
      EQPLAS=STATEV(1)
C     couple-stress equivalent measure of the predictor:  SMISES^2 = s^T P s
C     (normal block std, shear-12 weight 2, shear-13/23 weight 1).  Built in
C     the same accumulation idiom as the m3 J2 reference.
      SHYDRO=(STRESS(1)+STRESS(2)+STRESS(3))/THREE
      SMISES=(STRESS(1)-STRESS(2))**2+(STRESS(2)-STRESS(3))**2
     1      +(STRESS(3)-STRESS(1))**2
      SMISES=SMISES/THREE
      SMISES=SMISES+TWO*STRESS(4)**2+STRESS(5)**2+STRESS(6)**2
      SMISES=SQRT(SMISES)
      SYIEL0=SQ23*(SIGY0+HARD*EQPLAS)
C
      IF (SMISES.GT.(ONE+TOLER)*SYIEL0) THEN
C       actively yielding.  Closed-form radial return in the couple-stress
C       metric:  with t = 1 + 2G*gamma the updated equivalent stress is
C       SMISES/t, required equal to sqrt 2/3 times SIGY0 + H*EQPLAS.
C       Linear hardening gives t = SMISES + CC over AA + CC.  FLOW holds the
C       trial deviatoric parts (normal deviatoric for K1<=NDI, full component
C       for the shears), so STRESS is written from FLOW only, never read RHS.
        DO K1=1,NDI
          FLOW(K1)=STRESS(K1)-SHYDRO
        END DO
        DO K1=NDI+1,NTENS
          FLOW(K1)=STRESS(K1)
        END DO
        AA=SQ23*(SIGY0+HARD*EQPLAS)
        CC=(TWO/THREE)*HARD*SMISES/EG2
        TFAC=(SMISES+CC)/(AA+CC)
        GAM=(TFAC-ONE)/EG2
        DSCAL=ONE/TFAC
C       updated stress: hydrostatic axis preserved, deviatoric + all shear
C       components scaled by 1/TFAC.
        DO K1=1,NDI
          STRESS(K1)=FLOW(K1)*DSCAL+SHYDRO
        END DO
        DO K1=NDI+1,NTENS
          STRESS(K1)=FLOW(K1)*DSCAL
        END DO
C       equivalent plastic strain increment (KUHARD sqrt(2/3) scaling)
        EQPLAS=EQPLAS+SQ23*GAM*SMISES*DSCAL
      END IF
      STATEV(1)=EQPLAS
      RETURN
      END
