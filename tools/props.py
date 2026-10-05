import sys,struct; sys.path.insert(0,'/home/claude/smnc-recon/tools')
import ue3pkg as U
def tags(p,b,o):
    r=U.R(b,o); out=[]
    while True:
        name=p.nm(r)
        if name=='None': return out,r.o
        typ=p.nm(r); size=r.i32(); idx=r.i32(); extra=None
        if typ=='StructProperty': extra=p.nm(r)
        elif typ=='ByteProperty': extra=p.nm(r)
        elif typ=='BoolProperty': extra=b[r.o]; r.o+=1; out.append((name,typ,idx,extra,b'')); continue
        val=b[r.o:r.o+size]; r.o+=size
        out.append((name,typ,idx,extra,val))
