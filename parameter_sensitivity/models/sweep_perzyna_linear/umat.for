C  ------------------------------------------------------------------------
C  sweep_perzyna_linear : small-strain Perzyna viscoplasticity, LINEAR
C  overstress (exponent 1). Perfectly viscoplastic (no isotropic hardening).
C
C  PROPS(1)=E   PROPS(2)=nu   PROPS(3)=SIGY0 (yield)   PROPS(4)=eta (visc.)
C  STATEV(1) = EQPLAS (accumulated equivalent plastic strain)
C
C  Perzyna rule: dgamma = <f>/eta * DTIME  with  f = q - SIGY0  (linear).
C  Radial return: q = q_trial - 3G*dgamma, so with linear overstress
C     dgamma = DTIME*(q_trial - SIGY0) / (eta + 3G*DTIME)   (closed form)
C  which is algebraically the J2 linear-hardening return with H_eff=eta/DTIME
C  and a NON-evolving yield surface. Voigt (11,22,33,12,13,23), engineering
C  shear. Self-contained: no ROTSIG / UHARD. Inline STRESS update.
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
      DIMENSION FLOW(6)
      INTEGER K1,K2
      PARAMETER(ZERO=0.D0,ONE=1.D0,TWO=2.D0,THREE=3.D0,SIX=6.D0)
C
      EMOD=PROPS(1)
      ENU=PROPS(2)
      SIGY0=PROPS(3)
      ETA=PROPS(4)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      EG3=THREE*EG
      ELAM=(EBULK3-EG2)/THREE
C     effective (viscous) hardening slope from linear overstress
      HARDV=ETA/DTIME
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
C     elastic predictor stress (inline STRESS update)
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)
        END DO
      END DO
      EQPLAS=STATEV(1)
C     Mises equivalent stress of the predictor (tiny floor before sqrt)
      SMISES=(STRESS(1)-STRESS(2))**2+(STRESS(2)-STRESS(3))**2
     1      +(STRESS(3)-STRESS(1))**2
      DO K1=NDI+1,NTENS
        SMISES=SMISES+SIX*STRESS(K1)**2
      END DO
      SMISES=SQRT(SMISES/TWO)
C     non-evolving yield surface (perfectly viscoplastic); keep EQPLAS in the
C     expression (x ZERO) so the state->stress dataflow matches the J2 template
      SYIEL0=SIGY0+ZERO*EQPLAS
C
      IF (SMISES.GT.SYIEL0) THEN
C       actively (visco)plastic: hydrostatic / deviatoric split + flow direction
        SHYDRO=(STRESS(1)+STRESS(2)+STRESS(3))/THREE
        DO K1=1,NDI
          FLOW(K1)=(STRESS(K1)-SHYDRO)/SMISES
        END DO
        DO K1=NDI+1,NTENS
          FLOW(K1)=STRESS(K1)/SMISES
        END DO
C       closed-form linear-overstress return
        DEQPL=(SMISES-SYIEL0)/(EG3+HARDV)
        SYIELD=SYIEL0+HARDV*DEQPL
        DO K1=1,NDI
          STRESS(K1)=FLOW(K1)*SYIELD+SHYDRO
        END DO
        DO K1=NDI+1,NTENS
          STRESS(K1)=FLOW(K1)*SYIELD
        END DO
        EQPLAS=EQPLAS+DEQPL
C       consistent (algorithmic) tangent
        EFFG=EG*SYIELD/SMISES
        EFFG2=TWO*EFFG
        EFFG3=THREE/TWO*EFFG2
        EFFLAM=(EBULK3-EFFG2)/THREE
        EFFHRD=EG3*HARDV/(EG3+HARDV)-EFFG3
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
      STATEV(1)=EQPLAS
      RETURN
      END
