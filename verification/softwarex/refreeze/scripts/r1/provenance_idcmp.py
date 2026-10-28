# Identifier comparison: R1 vs umatmst3.f (recovered read-only: git -C refreeze/src/ust show a4a64c3^:UMATs/UMATs/ICP/umatmst3.f > umatmst3.f).
# Usage: python provenance_idcmp.py <R1.f> <umatmst3.f>
import re,sys
STD={'STRESS','STATEV','DDSDDE','SSE','SPD','SCD','RPL','DDSDDT','DRPLDE','DRPLDT','STRAN','DSTRAN','TIME','DTIME','TEMP','DTEMP','PREDEF','DPRED','CMNAME','NDI','NSHR','NTENS','NSTATV','PROPS','NPROPS','COORDS','DROT','PNEWDT','CELENT','DFGRD0','DFGRD1','NOEL','NPT','LAYER','KSPT','KSTEP','KINC','UMAT','SUBROUTINE','INCLUDE','CHARACTER','DIMENSION','PARAMETER','DO','END','IF','THEN','ELSE','RETURN','CONTINUE','GO','TO','SQRT','EXP','ABS','ABA_PARAM','INC','D0','I','J','K','K1','K2','LE','GT','LT','GE','EQ','NE','AND','OR','REAL','DOUBLE','PRECISION','WRITE','FORMAT','ENDIF','MIN','MAX'}
def ids(p):
    out=set()
    for l in open(p,errors='replace'):
        if l[:1] in 'Cc*!': continue
        l=l.split('!')[0]
        l=re.sub(r"'[^']*'","",l)
        for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',l[6:] if len(l)>6 else ''):
            t=t.upper()
            if t not in STD and not re.fullmatch(r'D\d*',t): out.add(t)
    return out
a,b=ids(sys.argv[1]),ids(sys.argv[2])
print('R1 ids',sorted(a)); print('mst3 ids',sorted(b)); print('shared',sorted(a&b))
