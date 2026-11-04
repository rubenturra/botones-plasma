# -*- coding: utf-8 -*-
# Mecanizar plasma  -  mecanizado automatico de corte por plasma en FreeCAD CAM
#  - Detecta chapas y piezas del anidado (o usa las piezas seleccionadas)
#  - Ventana: herramienta, postprocesador, QtPlasmaC, entradas/salidas y direccion
#    para exteriores e interiores, guardar retal para 1st Nesting, carpeta
#  - Por chapa: trabajo CAM, material, herramienta, Perfil, postprocesado, adaptacion
#    QtPlasmaC (agujeros primero), dibujo del G-code final, comprobacion y guardado
import FreeCAD as App, FreeCADGui as Gui, Part, os, re, math, importlib, time
from PySide import QtWidgets, QtCore

TITLE="Mecanizar plasma"
PREFS="User parameter:BaseApp/Preferences/Macros/MecanizarPlasma"
def log(m): App.Console.PrintMessage("[Plasma] %s\n"%m)

def retal_dir():
    """Carpeta de retales: la de la biblioteca de 1st Nesting, la propia o Documentos/Retales."""
    for path,key in (("User parameter:BaseApp/Preferences/Mod/IPNesting","OffcutLibraryFolder"),(PREFS,"RetalFolder")):
        d=App.ParamGet(path).GetString(key,"")
        if d: return d
    return os.path.join(os.path.expanduser("~"),"Documents","Retales")

# ------------------------------------------------------------------ documento
def detect(doc,use_selection=True):
    sel=[o for o in Gui.Selection.getSelection() if hasattr(o,"Shape") and o.Shape.Solids] if use_selection else []
    sheets=sorted([o for o in doc.Objects if o.Name.startswith("Sheet_") and o.TypeId=="Part::Feature"],key=lambda s:s.Shape.BoundBox.XMin)
    if sel: parts=sel; source="piezas seleccionadas"
    else:
        # Nesting results (Nesting_*) and bridge documents (Part_*, JoinedParts_*).
        parts=[o for o in doc.Objects if o.Name.startswith(("Nesting_","Part_","JoinedParts_")) and o.TypeId=="Part::Feature" and o.Shape.Solids]
        source="resultado del anidado"
    groups=[]
    if sheets:
        for s in sheets:
            b=s.Shape.BoundBox
            mine=[p for p in parts if p.Shape.BoundBox.XMin>=b.XMin-0.01 and p.Shape.BoundBox.XMax<=b.XMax+0.01 and p.Shape.BoundBox.YMin>=b.YMin-0.01 and p.Shape.BoundBox.YMax<=b.YMax+0.01]
            if mine: groups.append((s.Label,b,mine))
    elif parts:
        bb=App.BoundBox()
        for p in parts: bb.add(p.Shape.BoundBox)
        groups.append(("Piezas",App.BoundBox(bb.XMin-15,bb.YMin-15,bb.ZMin,bb.XMax+15,bb.YMax+15,bb.ZMax),parts))
    return groups,source

def find_offcut(doc,sb):
    for o in doc.Objects:
        if o.Name.startswith("Reusable_offcut") and o.TypeId=="Part::Feature":
            b=o.Shape.BoundBox
            if b.XMin>=sb.XMin-1 and b.XMax<=sb.XMax+1 and b.YMin>=sb.YMin-1 and b.YMax<=sb.YMax+1: return o
    return None

def export_offcut(doc,sb,name,thick,base):
    o=find_offcut(doc,sb)
    if not o: return None,"no hay retal reutilizable en esta chapa"
    import importDXF
    sh=o.Shape.copy(); sh.translate(App.Vector(-sb.XMin,-sb.YMin,-sh.BoundBox.ZMin))
    wires=[Part.Wire(e) for e in Part.sortEdges(sh.Edges)]
    closed=[w for w in wires if w.isClosed()]
    if not closed: return None,"el contorno del retal no es cerrado"
    folder=retal_dir(); os.makedirs(folder,exist_ok=True)
    area=max(Part.Face(w).Area for w in closed)
    fn=os.path.join(folder,"Retal_%s_%s_e%gmm_%s_%.2fm2.dxf"%(re.sub(r"[^\w\-]+","_",base),re.sub(r"[^\w\-]+","_",name),round(thick,1),time.strftime("%Y%m%d-%H%M"),area/1e6))
    tmp=App.newDocument("Retal_tmp_export",hidden=True) if "hidden" in App.newDocument.__doc__ else App.newDocument("Retal_tmp_export")
    try:
        f=tmp.addObject("Part::Feature","Retal"); f.Shape=Part.makeCompound(closed); tmp.recompute()
        importDXF.export([f],fn)
    finally:
        App.closeDocument(tmp.Name)
    note=""
    try:
        from Nesting1stOffcuts import extract_offcut_from_dxf
        outer,holes,bbox,info=extract_offcut_from_dxf(fn,debug=False,deflection=0.5)
        note="1st Nesting lo lee: %d puntos de contorno"%len(outer or [])
    except ImportError: note="1st Nesting no esta instalado; no se ha podido comprobar"
    except Exception as e: note="AVISO: 1st Nesting no ha podido leerlo (%s)"%e
    return fn,"%.2f m2 - %s"%(area/1e6,note)

# ------------------------------------------------------------------ geometria del G-code
def parse(path):
    conts=[]; cur=None; pos=[0.0,0.0]; z=1e9
    for l in open(path).read().splitlines():
        g=re.match(r"G0?([0-3])\b",l)
        if not g: continue
        g=int(g.group(1)); w=dict((k,float(v)) for k,v in re.findall(r"([XYZIJ])(-?[\d.]+)",l))
        nz=w.get("Z",z); end=[w.get("X",pos[0]), w.get("Y",pos[1])]
        if g==0:
            if cur and nz>1: conts.append(cur); cur=None
            pos=end; z=nz; continue
        if z>0.001 and nz<=0.001 and z<1e8: cur=[]; pos=end; z=nz; continue
        if cur is not None and math.dist(end,pos)>1e-6: cur.append((g,list(pos),end,w.get("I",0.0),w.get("J",0.0)))
        pos=end; z=nz
    if cur: conts.append(cur)
    return conts
def area(c):
    p=[x[1] for x in c]; return 0.5*sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p)))
def cbbox(c):
    xs=[];ys=[]
    for g,s,e,i,j in c:
        xs+=[s[0],e[0]]; ys+=[s[1],e[1]]
        if g in (2,3): cx,cy=s[0]+i,s[1]+j; r=math.hypot(i,j); xs+=[cx-r,cx+r]; ys+=[cy-r,cy+r]
    return min(xs),min(ys),max(xs),max(ys)
def reverse(cm):
    out=[]
    for g,s,e,i,j in reversed(cm):
        if g==1: out.append((1,list(e),list(s),0,0))
        else:
            c=(s[0]+i,s[1]+j); out.append((5-g,list(e),list(s),c[0]-e[0],c[1]-e[1]))
    return out
def tangent(cmd):
    g,s,e,i,j=cmd
    if g==1:
        L=math.dist(s,e); return [(e[0]-s[0])/L,(e[1]-s[1])/L]
    r=[-i,-j]; R=math.hypot(*r)
    return [-r[1]/R, r[0]/R] if g==3 else [r[1]/R, -r[0]/R]
def perp_left(v): return [-v[1],v[0]]
def arc_between(p,q,c,d_at_q,end_is_q=True):
    # arco de 90 grados con centro c entre p y q; devuelve G (2/3) tal que la tangente en q sea d_at_q
    a=[q[0]-c[0],q[1]-c[1]]; R=math.hypot(*a)
    t_ccw=[ -a[1]/R, a[0]/R]
    return 3 if (t_ccw[0]*d_at_q[0]+t_ccw[1]*d_at_q[1])>0 else 2
def lead_in(q,d,n,kind,size):
    # devuelve (punto de perforacion, comandos hasta q)
    if kind=="Ninguna" or size<=0: return list(q),[]
    if kind=="Recta":
        p=[q[0]+size*n[0], q[1]+size*n[1]]; return p,[(1,p,list(q),0,0)]
    c=[q[0]+size*n[0], q[1]+size*n[1]]
    g=arc_between(None,q,c,d)
    # punto inicial: girar q-c 90 grados en sentido contrario al movimiento
    a=[q[0]-c[0],q[1]-c[1]]
    st=[c[0]+a[1],c[1]-a[0]] if g==3 else [c[0]-a[1],c[1]+a[0]]
    return st,[(g,st,list(q),c[0]-st[0],c[1]-st[1])]
def lead_out(q,d,n,kind,size):
    if kind=="Ninguna" or size<=0: return []
    if kind=="Recta":
        e=[q[0]+size*n[0], q[1]+size*n[1]]; return [(1,list(q),e,0,0)]
    c=[q[0]+size*n[0], q[1]+size*n[1]]
    a=[q[0]-c[0],q[1]-c[1]]
    g=3 if (-a[1]*d[0]+a[0]*d[1])>0 else 2
    e=[c[0]-a[1],c[1]+a[0]] if g==3 else [c[0]+a[1],c[1]-a[0]]
    return [(g,list(q),e,c[0]-q[0],c[1]-q[1])]
def fmt(v):
    t=("%.3f"%v).rstrip("0").rstrip("."); return "0" if t in ("-0","") else t
def arc_edge(s,e,c,cw):
    a0=math.atan2(s[1]-c[1],s[0]-c[0]); a1=math.atan2(e[1]-c[1],e[0]-c[0]); r=math.dist(s,c)
    if cw:
        if a1>=a0: a1-=2*math.pi
    else:
        if a1<=a0: a1+=2*math.pi
    am=(a0+a1)/2; m=(c[0]+r*math.cos(am),c[1]+r*math.sin(am))
    return Part.Arc(App.Vector(s[0],s[1],0),App.Vector(m[0],m[1],0),App.Vector(e[0],e[1],0)).toShape()
def edge(cmd):
    g,s,e,i,j=cmd
    return Part.LineSegment(App.Vector(s[0],s[1],0),App.Vector(e[0],e[1],0)).toShape() if g==1 else arc_edge(s,e,(s[0]+i,s[1]+j),g==2)

def outline(c):
    """Polygon of a contour (arcs sampled every ~10 degrees)."""
    pts=[]
    for g,s,e,i,j in c:
        pts.append(tuple(s))
        if g in (2,3):
            cx,cy=s[0]+i,s[1]+j; r=math.hypot(i,j)
            a0=math.atan2(s[1]-cy,s[0]-cx); a1=math.atan2(e[1]-cy,e[0]-cx)
            if g==2 and a1>=a0: a1-=2*math.pi
            if g==3 and a1<=a0: a1+=2*math.pi
            n=max(1,int(abs(a1-a0)/math.radians(10)))
            pts+=[(cx+r*math.cos(a0+(a1-a0)*t/n),cy+r*math.sin(a0+(a1-a0)*t/n)) for t in range(1,n)]
    return pts
def inside_poly(pt,poly):
    x,y=pt; res=False
    for (x1,y1),(x2,y2) in zip(poly,poly[1:]+poly[:1]):
        if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1: res=not res
    return res
def nesting_depth(conts,bbs):
    """How many contours really surround each one. Even = part outline, odd = hole;
    a part nested inside another part's hole has depth 2."""
    polys=[outline(c) for c in conts]; depth=[]
    for k in range(len(conts)):
        pt=polys[k][0]; n=0
        for j in range(len(conts)):
            if j!=k and bbs[j][0]<=bbs[k][0] and bbs[j][1]<=bbs[k][1] and bbs[j][2]>=bbs[k][2] and bbs[j][3]>=bbs[k][3] \
               and (bbs[j][2]-bbs[j][0])*(bbs[j][3]-bbs[j][1])>(bbs[k][2]-bbs[k][0])*(bbs[k][3]-bbs[k][1]) and inside_poly(pt,polys[j]):
                n+=1
        depth.append(n)
    return depth

def adapt(raw,dst,faces,sheet,opt,title,tick):
    conts=parse(raw)
    bbs=[cbbox(c) for c in conts]
    depth=nesting_depth(conts,bbs)
    inner=[d%2==1 for d in depth]
    # Cut every contour before any contour that surrounds it: holes of parts
    # nested in another part's hole, those parts, that hole, outer outlines.
    order=sorted(range(len(conts)),key=lambda k:-depth[k])
    ox,oy=sheet.XMin,sheet.YMin
    # Spatial grid of part faces: each pierce test only looks at the parts
    # around it instead of every part on the sheet.
    CELL=100.0; grid={}; boxes=[f.BoundBox for f in faces]
    for idx,b in enumerate(boxes):
        for gx in range(int((b.XMin-12)//CELL),int((b.XMax+12)//CELL)+1):
            for gy in range(int((b.YMin-12)//CELL),int((b.YMax+12)//CELL)+1):
                grid.setdefault((gx,gy),[]).append(idx)
    cache={}
    def clearance(pt):
        key=(round(pt[0],3),round(pt[1],3))
        if key in cache: return cache[key]
        if min(pt[0]-sheet.XMin,pt[1]-sheet.YMin,sheet.XMax-pt[0],sheet.YMax-pt[1])<2:
            cache[key]=-1; return -1
        best=99.0; v=None; P3=App.Vector(pt[0],pt[1],0)
        for idx in grid.get((int(pt[0]//CELL),int(pt[1]//CELL)),()):
            b=boxes[idx]
            if b.XMin-12<pt[0]<b.XMax+12 and b.YMin-12<pt[1]<b.YMax+12:
                f=faces[idx]
                if b.XMin<=pt[0]<=b.XMax and b.YMin<=pt[1]<=b.YMax and f.isInside(P3,0.01,True):
                    cache[key]=-1; return -1
                if v is None: v=Part.Vertex(P3)
                best=min(best,f.distToShape(v)[0])
        cache[key]=best; return best
    E,I=opt["ext"],opt["int"]
    out=["(%s - %d agujeros + %d contornos - origen en la esquina de la chapa)"%(title,sum(inner),len(conts)-sum(inner)),
         "(FreeCAD CAM + postprocesador linuxcnc, adaptado a QtPlasmaC con Botones plasma / Mecanizar plasma)",
         "(Exteriores: entrada %s %g mm en %s, salida %s %g mm, %s)"%(E["in"],E["in_len"],E.get("pos","Lado").lower(),E["out"],E["out_len"],E["dir"].lower()),
         "(Interiores: entrada %s %g mm en %s, salida %s %g mm, %s)"%(I["in"],I["in_len"],I.get("pos","Lado").lower(),I["out"],I["out_len"],I["dir"].lower()),
         "(Primero agujeros, despues contornos. Velocidad y alturas: material seleccionado en QtPlasmaC)",
         "G21","G40 G49 G64 P0.1 G90 G91.1","F#<_hal[plasmac.cut-feed-rate]>"]
    worst=99; short=0; wires=[]; piers=[]
    for n_,k in enumerate(order):
        if tick(n_,len(order)): return None
        o=I if inner[k] else E
        cm=conts[k]; want_ccw=(o["dir"]=="Antihorario")
        if (area(cm)>0)!=want_ccw: cm=reverse(cm)
        ccw=want_ccw
        scrap_left=(ccw if inner[k] else not ccw)
        lines=[i for i,x in enumerate(cm) if x[0]==1 and math.dist(x[1],x[2])>=(10 if not inner[k] else 0.5)]
        span=min(bbs[k][2]-bbs[k][0],bbs[k][3]-bbs[k][1])
        circle=inner[k] and not [x for x in cm if x[0]==1]
        def scrap_n(dv):
            pl=perp_left(dv); return pl if scrap_left else [-pl[0],-pl[1]]
        cands=[]   # (q, seq, d, nvec)
        if o.get("pos")=="Esquina" and not circle:
            kerfr=opt.get("kerf",1.5)/2.0+0.05
            for idx,x in enumerate(cm):
                g,s,e,i,j=x
                if g in (2,3) and math.hypot(i,j)<=kerfr:          # esquina convexa redondeada por la compensacion
                    c=[s[0]+i,s[1]+j]; R=math.hypot(i,j)
                    a0=math.atan2(s[1]-c[1],s[0]-c[0]); a1=math.atan2(e[1]-c[1],e[0]-c[0])
                    if g==2:
                        if a1>=a0: a1-=2*math.pi
                    else:
                        if a1<=a0: a1+=2*math.pi
                    am=(a0+a1)/2; m=[c[0]+R*math.cos(am),c[1]+R*math.sin(am)]
                    nv=[(m[0]-c[0])/R,(m[1]-c[1])/R]
                    sn=scrap_n(tangent((g,m,e,c[0]-m[0],c[1]-m[1])))
                    if nv[0]*sn[0]+nv[1]*sn[1]<0: continue
                    seq=[(g,m,e,c[0]-m[0],c[1]-m[1])]+cm[idx+1:]+cm[:idx]+[(g,s,m,i,j)]
                    cands.append((m,seq,tangent(seq[0]),nv))
                elif g==1 and idx>0 or (g==1 and cm[-1][0]==1):
                    prev=cm[idx-1]
                    if prev[0]!=1: continue
                    d0=tangent(prev); d1=tangent(x)
                    if d0[0]*d1[0]+d0[1]*d1[1]>math.cos(math.radians(30)): continue
                    n0=scrap_n(d0); n1=scrap_n(d1); nb=[n0[0]+n1[0],n0[1]+n1[1]]; L=math.hypot(*nb)
                    if L<1e-6: continue
                    nb=[nb[0]/L,nb[1]/L]
                    # solo esquinas convexas vistas desde el desecho
                    turn=d0[0]*d1[1]-d0[1]*d1[0]
                    if inner[k] and (turn>0)!=ccw: continue
                    if (not inner[k]): continue
                    seq=cm[idx:]+cm[:idx]
                    cands.append((list(x[1]),seq,d1,nb))
        if not cands:
            if lines:
                ts=(0.15,0.3,0.5,0.7,0.85) if not inner[k] else (0.5,)
                for idx in (lines if not inner[k] else [max(lines,key=lambda i: math.dist(cm[i][1],cm[i][2]))]):
                    g,s,e,_,_=cm[idx]
                    for t in ts:
                        q=[s[0]+t*(e[0]-s[0]), s[1]+t*(e[1]-s[1])]
                        seq=[(1,q,e,0,0)]+cm[idx+1:]+cm[:idx]+[(1,s,q,0,0)]
                        cands.append((q,seq,tangent(seq[0]),None))
            else:
                g,s,e,i,j=cm[0]; q=list(s); d0=tangent(cm[0])
                if o["in"]=="Recta" and circle:
                    c=[s[0]+i,s[1]+j]; L=math.dist(c,q); nv=[(c[0]-q[0])/L,(c[1]-q[1])/L]
                else: nv=None
                cands.append((q,cm,d0,nv))
        cap_in=o["in_len"]; cap_out=o["out_len"]
        if inner[k]:
            rp=span/2.0
            cap_in=min(cap_in, rp if (o["in"]=="Recta" and circle) else 0.45*rp if circle else 0.4*span)
            cap_out=min(cap_out, 0.45*rp if circle else 0.4*span)
        sizes=[cap_in*f for f in ((1.0,0.85,0.7,0.6,0.55,0.5) if not inner[k] else (1.0,))]
        best=None; top=(cap_in+0.75,sizes[0])
        for q,seq,d,nv in cands:
            nperp=scrap_n(d)
            for sz in sizes:
                if o["in"]=="Recta" and nv is not None: p,lin=lead_in(q,d,nv,"Recta",sz)
                else: p,lin=lead_in(q,d,nperp,o["in"],sz)
                c=99 if inner[k] else clearance(p)
                score=(min(c,cap_in+0.75),sz)
                if best is None or score>best[0]: best=(score,q,seq,d,(nv if nv is not None else nperp),p,lin,c,sz)
                if score[0]>=cap_in+0.75: break     # smaller sizes cannot score better here
            if best[0]>=top: break                  # best possible entry already found
        score,q,seq,d,nvec,p,lin,c,sz=best
        # salida: tangente al final del contorno (llega a q)
        d_end=tangent(seq[-1]) if seq[-1][0]==1 else None
        if d_end is None:
            g,s,e,i,j=seq[-1]; cc=[s[0]+i,s[1]+j]; a=[e[0]-cc[0],e[1]-cc[1]]; R=math.hypot(*a)
            d_end=[-a[1]/R,a[0]/R] if g==3 else [a[1]/R,-a[0]/R]
        lout=[]
        if o["out"]!="Ninguna":
            for f in (1.0,0.7,0.5,0.3):
                lo=lead_out(q,d_end,(nvec if o["out"]=="Recta" else scrap_n(d_end)),o["out"],cap_out*f)
                if inner[k] or not lo or clearance(lo[-1][2])>=1.0: lout=lo; break
        if not inner[k]:
            worst=min(worst,c); short+= sz<cap_in-1e-6
        full=lin+seq+lout
        out+=["G0 X%s Y%s"%(fmt(p[0]-ox),fmt(p[1]-oy)),"M3 $0 S1"]
        if not lin: pass
        for g,s_,e_,i,j in full:
            out.append("G%d X%s Y%s"%(g,fmt(e_[0]-ox),fmt(e_[1]-oy))+("" if g==1 else " I%s J%s"%(fmt(i),fmt(j))))
        out.append("M5 $0")
        wires.append(Part.Wire([edge(x) for x in full])); piers.append(p)
    out+=["G0 X0 Y0","M2"]
    open(dst,"w",newline="\n").write("\n".join(out)+"\n")
    return dict(holes=sum(inner),outer=len(conts)-sum(inner),worst=worst,short=short,wires=wires,piers=piers,text="\n".join(out))

# ------------------------------------------------------------------ CAM
WORKERS=4  # FreeCAD processes used to compute the CAM profiles in parallel

WORKER_SCRIPT=r'''
import FreeCAD as App, Part, importlib, json, traceback
cfg=json.load(open(r"%(cfg)s"))
try:
    try:
        import Path; Path.Log.setLevel(Path.Log.Level.NOTICE,"Path.Tool.assets.manager")
    except Exception: pass
    doc=App.newDocument("w"); sh=Part.Shape(); sh.importBrep(cfg["brep"])
    comp=doc.addObject("Part::Feature","Caras"); comp.Shape=sh; doc.recompute()
    import Path.Main.Job as PathJob, Path.Op.Profile as PathProfile
    job=PathJob.Create("Job",[comp]); job.PostProcessor="linuxcnc"
    tc=job.Tools.Group[0]; tc.Tool.Diameter=cfg["kerf"]
    tc.HorizFeed="2000 mm/min"; tc.VertFeed="2000 mm/min"; tc.HorizRapid="10000 mm/min"; tc.VertRapid="5000 mm/min"; tc.SpindleSpeed=1
    model=job.Model.Group[0]; ops=[]
    for lv in sorted(set(cfg["levels"])):
        names=["Face%%d"%%(k+1) for k,l in enumerate(cfg["levels"]) if l==lv]
        op=PathProfile.Create("P%%d"%%lv,parentJob=job); op.Base=[(model,names)]
        op.Side="Outside"; op.Direction="CW"; op.UseComp=True
        op.processPerimeter=True; op.processHoles=True; op.processCircles=True; op.ToolController=tc
        for p in ("StartDepth","FinalDepth","StepDown"): op.setExpression(p,None)
        op.StartDepth=cfg["zmax"]; op.FinalDepth=cfg["zmin"]; op.StepDown=cfg["zmax"]-cfg["zmin"]
        ops.append(op)
    doc.recompute()
    m=importlib.import_module("Path.Post.scripts.linuxcnc_post")
    m.export([tc]+ops,cfg["out"],"--no-show-editor --no-comments")
    open(cfg["out"]+".ok","w").write("ok")
except Exception:
    open(cfg["out"]+".err","w").write(traceback.format_exc())
'''

def worker_exe():
    for n in ("FreeCADCmd.exe","freecadcmd.exe","FreeCADCmd","freecadcmd"):
        f=os.path.join(App.getHomePath(),"bin",n)
        if os.path.isfile(f): return f
    return None

def parallel_profiles(faces_by_level,kerf,zmin,zmax,raw,tick=None,workers=WORKERS):
    """Compute the Profile of the top faces in several FreeCAD processes at once
    and write one merged linuxcnc program. Returns False to fall back."""
    import subprocess, tempfile, json, shutil
    exe=worker_exe()
    items=[(lv,f) for lv,f in faces_by_level]
    if not exe or len(items)<2*workers: return False
    # Balance the bins by number of edges (the CAM cost grows with them).
    bins=[[] for _ in range(workers)]; load=[0]*workers
    for lv,f in sorted(items,key=lambda x:-len(x[1].Edges)):
        k=load.index(min(load)); bins[k].append((lv,f)); load[k]+=len(f.Edges)
    tmp=tempfile.mkdtemp(prefix="plasma_cam_")
    procs=[]
    try:
        for k,b in enumerate(bins):
            brep=os.path.join(tmp,"caras_%d.brep"%k); out=os.path.join(tmp,"perfil_%d.ngc"%k)
            Part.makeCompound([f for lv,f in b]).exportBrep(brep)
            cfg=os.path.join(tmp,"cfg_%d.json"%k)
            json.dump(dict(brep=brep,out=out,kerf=kerf,zmin=zmin,zmax=zmax,levels=[lv for lv,f in b]),open(cfg,"w"))
            script=os.path.join(tmp,"trabajo_%d.py"%k); open(script,"w").write(WORKER_SCRIPT%dict(cfg=cfg))
            procs.append((subprocess.Popen([exe,script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          creationflags=0x08000000 if os.name=="nt" else 0),out))
        t0=time.time()
        while True:
            done=sum(1 for pr,out in procs if pr.poll() is not None)
            if tick and tick(done,len(procs),time.time()-t0):
                return False
            if done==len(procs): break
            QtWidgets.QApplication.processEvents(); time.sleep(0.2)
        if not all(os.path.exists(out+".ok") and os.path.exists(out) for pr,out in procs):
            errs=[open(out+".err").read()[-300:] for pr,out in procs if os.path.exists(out+".err")]
            log("Calculo en paralelo fallido, se hace en este FreeCAD: %s"%(errs[0] if errs else "sin resultado"))
            return False
        with open(raw,"w",newline="\n") as dst:
            for pr,out in procs: dst.write(open(out).read()+"\n")
        log("Perfiles calculados en %d procesos en %.0f s"%(len(procs),time.time()-t0))
        return True
    finally:
        for pr,out in procs:
            if pr.poll() is None:
                try: pr.kill()
                except Exception: pass
        shutil.rmtree(tmp,ignore_errors=True)

def make_job(doc,i,name,sb,parts,kerf,tool_label,post,with_ops=True):
    import Path, Path.Main.Job as PathJob, Path.Main.Stock as PathStock, Path.Op.Profile as PathProfile
    try: Path.Log.setLevel(Path.Log.Level.NOTICE,"Path.Tool.assets.manager")
    except Exception: pass
    comp=doc.addObject("Part::Feature","Plasma_Piezas_%d"%i); comp.Label="Plasma %s - piezas"%name
    comp.Shape=Part.makeCompound([p.Shape.copy() for p in parts]); comp.ViewObject.Visibility=False
    doc.recompute()
    zmin=comp.Shape.BoundBox.ZMin; zmax=comp.Shape.BoundBox.ZMax; th=zmax-zmin
    job=PathJob.Create("Plasma_Job_%d"%i,[comp]); job.Label="Plasma %s"%name
    job.PostProcessor=post
    if job.Stock: doc.removeObject(job.Stock.Name)
    job.Stock=PathStock.CreateBox(job, App.Vector(sb.XLength,sb.YLength,th), App.Placement(App.Vector(sb.XMin,sb.YMin,zmin),App.Rotation()))
    tc=job.Tools.Group[0]; tc.Label="TC: %s"%tool_label; tc.Tool.Label=tool_label; tc.Tool.Diameter=kerf
    tc.HorizFeed="2000 mm/min"; tc.VertFeed="2000 mm/min"; tc.HorizRapid="10000 mm/min"; tc.VertRapid="5000 mm/min"; tc.SpindleSpeed=1
    model=job.Model.Group[0]
    top=["Face%d"%(k+1) for k,f in enumerate(model.Shape.Faces) if f.normalAt(0,0).z>0.99 and abs(f.CenterOfMass.z-zmax)<0.01]
    # CAM Profile ignores the outline of a face lying inside another face's
    # hole (part-in-part nesting), so every nesting level gets its own profile.
    levels=nesting_levels(model.Shape.Faces,top)
    ops=[]
    if not with_ops:
        doc.recompute()
        return job,tc,ops,model,len(top),th,[(levels[n],model.Shape.Faces[int(n[4:])-1]) for n in top]
    for lv in sorted(set(levels.values())):
        names=[n for n in top if levels[n]==lv]
        op=PathProfile.Create("Plasma_Perfil_%d_%d"%(i,lv), parentJob=job)
        op.Label="Corte plasma %s"%name+("" if lv==0 else " (piezas dentro de agujeros, nivel %d)"%lv)
        op.Base=[(model,names)]; op.Side="Outside"; op.Direction="CW"; op.UseComp=True
        op.processPerimeter=True; op.processHoles=True; op.processCircles=True; op.ToolController=tc
        for p in ("StartDepth","FinalDepth","StepDown"): op.setExpression(p,None)
        op.StartDepth=zmax; op.FinalDepth=zmin; op.StepDown=th
        ops.append(op)
    doc.recompute()
    return job,tc,ops,model,len(top),th,None

def nesting_levels(faces,names):
    """Level of each top face: how many other faces' holes contain it."""
    f={n:faces[int(n[4:])-1] for n in names}
    holes=[]
    for n,face in f.items():
        for w in face.Wires:
            if not w.isSame(face.OuterWire):
                try: holes.append((n,Part.Face(w)))
                except Exception: pass
    level={}
    for n,face in f.items():
        c=face.OuterWire.BoundBox.Center; pt=App.Vector(c.x,c.y,face.CenterOfMass.z)
        probe=face.Vertexes[0].Point if not face.isInside(pt,0.01,True) else pt
        lv=0
        for owner,hf in holes:
            if owner==n: continue
            hb=hf.BoundBox; fb=face.BoundBox
            if hb.XMin<=fb.XMin and hb.YMin<=fb.YMin and hb.XMax>=fb.XMax and hb.YMax>=fb.YMax and \
               hf.isInside(App.Vector(probe.x,probe.y,hf.CenterOfMass.z),0.01,True):
                lv+=1
        level[n]=lv
    return level

def remove_job(doc,job,comp_name):
    names={job.Name,comp_name}|{o.Name for o in job.OutListRecursive}
    names={n for n in names if not n.startswith(("Nesting_","Sheet","Reusable","Part_","JoinedParts_","Bridges_"))}
    for _ in range(10):
        left=[n for n in names if doc.getObject(n)]
        if not left: break
        for n in left:
            o=doc.getObject(n)
            if o and not [x for x in o.InList if x.Name in names and doc.getObject(x.Name)]: doc.removeObject(n)
    doc.recompute()

def show_program_in_job(doc,i,name,job,tc,raw):
    """Put the profiles computed in parallel into the CAM job as one operation."""
    try:
        import Path.Op.Custom as PathCustom
        lines=[l.strip() for l in open(raw).read().splitlines()
               if l.strip() and not l.startswith("(") and l.split()[0] in ("G0","G1","G2","G3","G00","G01","G02","G03")]
        op=PathCustom.Create("Plasma_Perfil_%d_paralelo"%i, parentJob=job)
        op.Label="Corte plasma %s (perfiles calculados en %d nucleos)"%(name,WORKERS)
        op.Source="Text"; op.Gcode=lines; op.ToolController=tc
        op.recompute()
    except Exception as e: log("No se pudo poner el programa en el trabajo CAM: %s"%e)

def run_post(post,objs,path):
    mod=importlib.import_module("Path.Post.scripts.%s_post"%post)
    try: mod.export(objs,path,"--no-show-editor --no-comments")
    except TypeError: mod.export(objs,path)
    return path


# ------------------------------------------------------------------ limpieza y simulacion
def remove_previous(doc):
    jobs=[o for o in doc.Objects if hasattr(o,"Operations") and (o.Name.startswith(("Plasma_Job","Plasma_SIM","Job_Plasma_SIM")))]
    victims=set()
    for j in jobs:
        victims.add(j.Name)
        for o in j.OutListRecursive: victims.add(o.Name)
    for o in doc.Objects:
        if o.Name.startswith(("Plasma_","Job_Plasma_SIM")): victims.add(o.Name)
    victims={n for n in victims if not n.startswith(("Nesting_","Sheet","Reusable","Part_","JoinedParts_","Bridges_"))}
    for _ in range(10):
        left=[n for n in victims if doc.getObject(n)]
        if not left: break
        for n in left:
            o=doc.getObject(n)
            if o and not [x for x in o.InList if x.Name in victims and doc.getObject(x.Name)]: doc.removeObject(n)
    for n in [n for n in victims if doc.getObject(n)]:
        try: doc.removeObject(n)
        except Exception: pass
    doc.recompute(); return len(victims)

def undo(doc=None):
    """Deshacer Mecanizar plasma: quita trabajos CAM, G-code, perforaciones y
    simulacion del documento y, si se quiere, borra los programas y retales creados."""
    doc=doc or App.ActiveDocument
    if not doc:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(),"Deshacer mecanizado plasma","No hay ningun documento abierto."); return
    objs=[o for o in doc.Objects if o.Name.startswith(("Plasma_","Job_Plasma_SIM"))]
    if not objs:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(),"Deshacer mecanizado plasma","Este documento no tiene mecanizado de plasma."); return
    files=sorted({f for o in objs for f in getattr(o,"PlasmaFiles",[]) if os.path.isfile(f)})
    box=QtWidgets.QMessageBox(Gui.getMainWindow()); box.setWindowTitle("Deshacer mecanizado plasma"); box.setIcon(QtWidgets.QMessageBox.Question)
    box.setText("Se quitara del documento %s el mecanizado de plasma: trabajos CAM, G-code, perforaciones y simulacion.\n\nLas piezas y las chapas no se tocan."%doc.Label)
    chk=None
    if files:
        chk=QtWidgets.QCheckBox("Borrar tambien los %d archivos creados (programas .ngc y retal)"%len(files)); box.setCheckBox(chk)
        box.setDetailedText("\n".join(files))
    yes=box.addButton("Deshacer",QtWidgets.QMessageBox.AcceptRole); box.addButton("Cancelar",QtWidgets.QMessageBox.RejectRole)
    box.exec_()
    if box.clickedButton() is not yes: return
    try:
        if Gui.Control.activeDialog(): Gui.Control.closeDialog()
    except Exception: pass
    doc.openTransaction("Deshacer mecanizado plasma")
    n=remove_previous(doc)
    for o in doc.Objects:
        if o.Name.startswith(("Nesting_","Part_","JoinedParts_")) and o.TypeId=="Part::Feature":
            try: o.ViewObject.Transparency=0
            except Exception: pass
    doc.commitTransaction()
    deleted=0
    if chk is not None and chk.isChecked():
        for f in files:
            try: os.remove(f); deleted+=1
            except OSError: pass
    log("Deshecho: %d objetos quitados, %d archivos borrados"%(n,deleted))
    QtWidgets.QMessageBox.information(Gui.getMainWindow(),"Deshacer mecanizado plasma",
        "Hecho: quitados %d objetos del mecanizado%s."%(n,(", borrados %d archivos"%deleted) if deleted else ""))

def make_sim(doc,i,name,comp,sb,kerf,text,zmin,zmax):
    import Path.Main.Job as PathJob, Path.Main.Stock as PathStock, Path.Op.Custom as PathCustom
    ox,oy=sb.XMin,sb.YMin
    def shift(l):
        l=re.sub(r"X(-?[\d.]+)",lambda m:"X%s"%fmt(float(m.group(1))+ox),l)
        return re.sub(r"Y(-?[\d.]+)",lambda m:"Y%s"%fmt(float(m.group(1))+oy),l)
    up=zmax+5; lines=["G21","G90","G0 Z%s"%fmt(up),"M3 S1000"]
    for l in text.splitlines():
        if not l or l.startswith("(") or l.startswith(("G21","G40","F#","M2")): continue
        if l.startswith("M3 $0"): lines.append("G1 Z%s F600"%fmt(zmin)); continue
        if l.startswith("M5 $0"): lines.append("G0 Z%s"%fmt(up)); continue
        l=shift(l)
        if l.startswith(("G1","G2","G3")): l+=" F2000"
        lines.append(l)
    lines.append("M5")
    job=PathJob.Create("Job_Plasma_SIM_%d"%i,[comp]); job.Label="SIMULACION programa final %s"%name
    if job.Stock: doc.removeObject(job.Stock.Name)
    job.Stock=PathStock.CreateBox(job, App.Vector(sb.XLength,sb.YLength,zmax-zmin), App.Placement(App.Vector(sb.XMin,sb.YMin,zmin),App.Rotation()))
    tc=job.Tools.Group[0]; tc.Label="TC: plasma (simulacion)"; tc.Tool.Diameter=kerf
    tc.HorizFeed="2000 mm/min"; tc.VertFeed="2000 mm/min"; tc.HorizRapid="10000 mm/min"; tc.VertRapid="5000 mm/min"; tc.SpindleSpeed=1
    op=PathCustom.Create("Plasma_SIM_Programa_%d"%i, parentJob=job); op.Label="Programa final %s"%name
    op.Source="Text"; op.Gcode=lines; op.ToolController=tc
    for m in job.Model.Group: m.ViewObject.Visibility=False
    doc.recompute(); return job

def restore_cursor():
    n=0
    while QtWidgets.QApplication.overrideCursor() is not None and n<50:
        QtWidgets.QApplication.restoreOverrideCursor(); n+=1

def sim_accuracy(job):
    """CAM simulator accuracy (1-10). High accuracy on a whole sheet builds a
    huge model and freezes the simulator, so large sheets use a low value."""
    try:
        b=job.Stock.Shape.BoundBox; area=b.XLength*b.YLength/1e6
    except Exception: return 3
    return 2 if area>2 else 3 if area>0.5 else 5 if area>0.1 else 8

def open_simulator(job):
    def _play():
        restore_cursor()
        try:
            mw=Gui.getMainWindow()
            for sl in mw.findChildren(QtWidgets.QSlider):
                if sl.objectName()=="sliderAccuracy" and sl.isVisible():
                    sl.setValue(max(sl.minimum(),min(sl.maximum(),sim_accuracy(job))))
            for dw in mw.findChildren(QtWidgets.QDockWidget):
                for cb in dw.findChildren(QtWidgets.QComboBox):
                    if cb.isVisible() and cb.findText(job.Label)>=0: cb.setCurrentIndex(cb.findText(job.Label))
                for b in dw.findChildren(QtWidgets.QAbstractButton):
                    if b.isVisible() and b.text() in ("Reproducir","Play","Launch"): b.click(); return
        except Exception as e: log("No se pudo lanzar el simulador: %s"%e)
    def _to_main_screen():
        # The simulator opens its own window; keep it on the main screen.
        try:
            from PySide import QtGui
            screen=QtGui.QGuiApplication.primaryScreen(); g=screen.availableGeometry()
            for w in QtGui.QGuiApplication.topLevelWindows():
                if w.isVisible() and "CAM Simulator" in w.title() and not g.contains(w.geometry().center()):
                    w.setScreen(screen); w.setGeometry(g.x()+80,g.y()+80,int(g.width()*0.8),int(g.height()*0.75))
        except Exception as e: log("No se pudo colocar el simulador: %s"%e)
    def _open():
        restore_cursor()
        try:
            if Gui.Control.activeDialog(): Gui.Control.closeDialog()
            Gui.Selection.clearSelection(); Gui.Selection.addSelection(job.Document.Name,job.Name)
            Gui.runCommand("CAM_SimulatorGL")
            QtCore.QTimer.singleShot(800,_play)
            QtCore.QTimer.singleShot(1500,_to_main_screen)
        except Exception as e: log("No se pudo abrir el simulador: %s"%e)
    QtCore.QTimer.singleShot(300,_open)

def clean_name(t):
    t=re.sub(r"[^\w\- ]+","_",(t or "").strip()) or "programa"
    return re.sub(r"-\d{8}-\d{4,6}$","",t)

# ------------------------------------------------------------------ ventana
class LeadBox(QtWidgets.QGroupBox):
    def __init__(self,title,d_in,d_in_len,d_out,d_out_len,d_dir):
        super().__init__(title); F=QtWidgets.QFormLayout(self)
        def row(kinds,kd,ln):
            h=QtWidgets.QHBoxLayout(); c=QtWidgets.QComboBox(); c.addItems(kinds); c.setCurrentText(kd)
            s=QtWidgets.QDoubleSpinBox(); s.setRange(0,30); s.setDecimals(1); s.setSuffix(" mm"); s.setValue(ln)
            c.currentTextChanged.connect(lambda t: s.setEnabled(t!="Ninguna")); s.setEnabled(kd!="Ninguna")
            h.addWidget(c,2); h.addWidget(s,1); return h,c,s
        h,self.cin,self.lin=row(["Recta","Arco","Ninguna"],d_in,d_in_len); F.addRow("Entrada:",h)
        h,self.cout,self.lout=row(["Ninguna","Recta","Arco"],d_out,d_out_len); F.addRow("Salida:",h)
        self.pos=QtWidgets.QComboBox(); self.pos.addItems(["Lado","Esquina"]); F.addRow("Posicion entrada:",self.pos)
        self.dir=QtWidgets.QComboBox(); self.dir.addItems(["Horario","Antihorario"]); self.dir.setCurrentText(d_dir); F.addRow("Direccion:",self.dir)
    def get(self): return {"in":self.cin.currentText(),"in_len":self.lin.value(),"out":self.cout.currentText(),"out_len":self.lout.value(),"dir":self.dir.currentText(),"pos":self.pos.currentText()}

class Dialog(QtWidgets.QDialog):
    def __init__(self,groups,source,doc):
        super().__init__(Gui.getMainWindow()); self.setWindowTitle(TITLE); self.setMinimumWidth(520)
        L=QtWidgets.QVBoxLayout(self)
        self.doc=doc; self.groups=groups; self.source=source
        hi=QtWidgets.QHBoxLayout(); self.info=QtWidgets.QLabel(); self.info.setWordWrap(True); hi.addWidget(self.info,1)
        self.allbtn=QtWidgets.QPushButton("Usar todas las piezas\ndel anidado"); self.allbtn.clicked.connect(self._use_all)
        hi.addWidget(self.allbtn); L.addLayout(hi); self._show_info()
        F=QtWidgets.QFormLayout(); L.addLayout(F)
        self.tool=QtWidgets.QComboBox(); self.tool.setEditable(True)
        for t in ("Plasma kerf 1.0 mm","Plasma kerf 1.5 mm","Plasma kerf 2.0 mm","Plasma kerf 2.5 mm","Plasma kerf 3.0 mm"): self.tool.addItem(t)
        self.tool.setCurrentIndex(1)
        self.kerf=QtWidgets.QDoubleSpinBox(); self.kerf.setRange(0.2,10); self.kerf.setDecimals(2); self.kerf.setSuffix(" mm"); self.kerf.setValue(1.5)
        self.tool.currentTextChanged.connect(self._kerf_from_name)
        F.addRow("Herramienta:",self.tool); F.addRow("Ancho de corte (kerf):",self.kerf)
        self.post=QtWidgets.QComboBox()
        try:
            import Path.Preferences as PP; posts=sorted(PP.allEnabledPostProcessors())
        except Exception: posts=["linuxcnc"]
        self.post.addItems(posts)
        if "linuxcnc" in posts: self.post.setCurrentText("linuxcnc")
        F.addRow("Postprocesador:",self.post)
        self.qt=QtWidgets.QCheckBox("Adaptar a QtPlasmaC (recomendado para tu plasma)"); self.qt.setChecked(True)
        F.addRow("",self.qt)
        h=QtWidgets.QHBoxLayout()
        self.ext=LeadBox("Exteriores (contornos)","Recta",4.0,"Ninguna",2.0,"Horario")
        self.int=LeadBox("Interiores (agujeros)","Recta",4.0,"Ninguna",1.5,"Antihorario")
        h.addWidget(self.ext); h.addWidget(self.int); L.addLayout(h)
        self.post.currentTextChanged.connect(self._post_changed)
        self.retal=QtWidgets.QCheckBox("Guardar el retal para usarlo en 1st Nesting (DXF en %s)"%retal_dir()); self.retal.setChecked(True)
        if not any(find_offcut(doc,g[1]) for g in groups):
            self.retal.setChecked(False); self.retal.setEnabled(False); self.retal.setText("Guardar el retal para 1st Nesting (no hay retal en este anidado)")
        L.addWidget(self.retal)
        self.sim=QtWidgets.QCheckBox("Crear la simulacion del programa final y abrir el simulador al terminar"); self.sim.setChecked(True); L.addWidget(self.sim)
        self.clean=QtWidgets.QCheckBox("Borrar el mecanizado anterior hecho con este boton"); self.clean.setChecked(True); L.addWidget(self.clean)
        others=nesting_documents()
        self.all_docs=QtWidgets.QCheckBox("Mecanizar todos los anidados abiertos (%d): %s"%(len(others),", ".join(d.Label for d in others)))
        self.all_docs.setEnabled(len(others)>1); self.all_docs.setChecked(False)
        self.all_docs.setToolTip("Hace el mecanizado de cada documento de anidado abierto con estas mismas opciones; "
                                 "cada uno guarda sus programas con su nombre (por ejemplo ..._Nesting_Result_10mm_QtPlasmaC.ngc)")
        L.addWidget(self.all_docs)
        F2=QtWidgets.QFormLayout(); L.addLayout(F2)
        last=App.ParamGet(PREFS).GetString("LastFolder","")
        h=QtWidgets.QHBoxLayout(); self.folder=QtWidgets.QLineEdit(last if last and os.path.isdir(last) else (os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")))
        b=QtWidgets.QPushButton("..."); b.setFixedWidth(30); b.clicked.connect(self._pick); h.addWidget(self.folder); h.addWidget(b)
        F2.addRow("Carpeta del programa:",h)
        lastname=App.ParamGet(PREFS).GetString("LastName","")
        self.name=QtWidgets.QLineEdit(lastname or re.sub(r"[^\w\-]+","_",doc.Label)); F2.addRow("Nombre del programa:",self.name)
        self.preview=QtWidgets.QLabel(); self.preview.setStyleSheet("color:gray"); F2.addRow("",self.preview)
        self.name.textChanged.connect(self._upd_preview); self._upd_preview()
        bb=QtWidgets.QDialogButtonBox(); bb.addButton("Mecanizar",QtWidgets.QDialogButtonBox.AcceptRole); bb.addButton("Cancelar",QtWidgets.QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); L.addWidget(bb)
    def _show_info(self):
        npz=sum(len(g[2]) for g in self.groups)
        self.info.setText("<b>%d chapa(s), %d piezas</b> (%s)<br>"%(len(self.groups),npz,self.source)+
            "<br>".join("&nbsp;&nbsp;%s: %d piezas, %.0f x %.0f mm"%(g[0],len(g[2]),g[1].XLength,g[1].YLength) for g in self.groups))
        self.allbtn.setEnabled(self.source=="piezas seleccionadas")
    def _use_all(self):
        groups,source=detect(self.doc,False)
        if not groups:
            QtWidgets.QMessageBox.warning(self,TITLE,"No hay resultado de anidado con piezas en este documento."); return
        self.groups=groups; self.source="todas las piezas del anidado"
        Gui.Selection.clearSelection()
        for g in groups:
            for p in g[2]: Gui.Selection.addSelection(self.doc.Name,p.Name)
        self._show_info()
        if hasattr(self,"retal"):
            has=any(find_offcut(self.doc,g[1]) for g in groups)
            self.retal.setEnabled(has); self.retal.setChecked(has)
    def _upd_preview(self,*a):
        self.preview.setText("Se guardara como: %s-%s_QtPlasmaC.ngc"%(clean_name(self.name.text()),time.strftime("%Y%m%d-%H%M")))
    def _post_changed(self,t):
        ok=(t=="linuxcnc"); self.qt.setEnabled(ok); self.qt.setChecked(ok); self.ext.setEnabled(ok); self.int.setEnabled(ok)
    def _kerf_from_name(self,t):
        m=re.search(r"(\d+(?:[.,]\d+)?)\s*mm",t)
        if m: self.kerf.setValue(float(m.group(1).replace(",",".")))
    def _pick(self):
        d=QtWidgets.QFileDialog.getExistingDirectory(self,"Carpeta de salida",self.folder.text())
        if d: self.folder.setText(d)

# ------------------------------------------------------------------ proceso
def mecanizar(doc,groups,kerf,tool_label,post,adapt_qt,opt,outdir,base,save_retal=False,progress=None,make_simulation=True):
    def step(txt,val=None):
        log(txt)
        if progress:
            progress.setLabelText(txt)
            if val is not None: progress.setValue(val)
            QtWidgets.QApplication.processEvents(); return progress.wasCanceled()
        return False
    results=[]; total=len(groups)
    for i,(name,sb,parts) in enumerate(groups,1):
        tag=("_chapa%d"%i) if total>1 else ""
        if step("%s: creando trabajo CAM, material y herramienta (%d piezas)..."%(name,len(parts)),int(100*(i-1)/total)): return results
        raw=os.path.join(outdir,"%s%s_%s.ngc"%(base,tag,post))
        parallel=False
        if post=="linuxcnc" and worker_exe():
            job,tc,ops,model,ntop,th,top_faces=make_job(doc,i,name,sb,parts,kerf,tool_label,post,with_ops=False)
            bb=model.Shape.BoundBox
            def ptick(done,n,secs):
                return step("%s: calculando los perfiles de corte en %d nucleos a la vez (%d de %d terminados, %.0f s)..."%(name,n,done,n,secs),
                            int(100*(i-1)/total+3*done/max(n,1)))
            parallel=parallel_profiles(top_faces,kerf,bb.ZMin,bb.ZMax,raw,ptick)
            if not parallel:
                if progress and progress.wasCanceled(): return results
                remove_job(doc,job,"Plasma_Piezas_%d"%i)   # fall back to the classic in-process profiles
            else:
                show_program_in_job(doc,i,name,job,tc,raw)
        if not parallel:
            job,tc,ops,model,ntop,th,_=make_job(doc,i,name,sb,parts,kerf,tool_label,post)
        Gui.ActiveDocument.ActiveView.viewTop(); Gui.SendMsgToActiveView("ViewFit"); QtWidgets.QApplication.processEvents()
        if step("%s: perfil calculado (%d caras). Postprocesando con %s..."%(name,ntop,post)): return results
        if not parallel:
            run_post(post,[tc]+ops,raw)
        # The profiles are computed; adding drawings later must not make
        # FreeCAD recompute them again (that doubled the time).
        for o in [job]+list(job.OutListRecursive): 
            try: o.purgeTouched()
            except Exception: pass
        res=dict(name=name,raw=raw,parts=len(parts),final=raw)
        res["expected_holes"]=sum(len([f for f in p.Shape.Faces if f.normalAt(0,0).z>0.99][0].Wires)-1 for p in parts)
        if adapt_qt:
            faces=[f for f in model.Shape.Faces if f.normalAt(0,0).z<-0.99]
            dst=os.path.join(outdir,"%s%s_QtPlasmaC.ngc"%(base,tag))
            def tick(n,N):
                if progress:
                    progress.setLabelText("%s: entradas/salidas y adaptacion a QtPlasmaC (%d/%d)..."%(name,n,N))
                    progress.setValue(int(100*(i-1)/total + 100/total*n/max(N,1)))
                    QtWidgets.QApplication.processEvents(); return progress.wasCanceled()
                return False
            r=adapt(raw,dst,faces,sb,opt,"%s %.0f x %.0f mm"%(name,sb.XLength,sb.YLength),tick)
            if r is None: return results
            g=doc.addObject("Part::Feature","Plasma_GCode_%d"%i); g.Label="G-code %s (cortes)"%name; g.Shape=Part.makeCompound(r["wires"])
            g.ViewObject.LineColor=(0.0,0.6,0.0); g.ViewObject.LineWidth=2
            pp=doc.addObject("Part::Feature","Plasma_Perforaciones_%d"%i); pp.Label="Perforaciones %s"%name
            pp.Shape=Part.makeCompound([Part.Vertex(App.Vector(x,y,0)) for x,y in r["piers"]]); pp.ViewObject.PointColor=(1.0,0.0,0.0); pp.ViewObject.PointSize=6
            txt=r["text"]
            res.update(final=dst,holes=r["holes"],outer=r["outer"],worst=r["worst"],short=r["short"],
                       m3=txt.count("M3 $0 S1"),m5=txt.count("M5 $0"),z=len(re.findall(r"\bZ-?\d",txt)))
            for o in (g,pp): o.recompute()
            QtWidgets.QApplication.processEvents()
            if make_simulation:
                step("%s: creando la simulacion del programa final..."%name)
                comp=model.Objects[0] if hasattr(model,"Objects") and model.Objects else doc.getObject("Plasma_Piezas_%d"%i)
                comp=doc.getObject("Plasma_Piezas_%d"%i) or comp
                res["sim"]=make_sim(doc,i,name,comp,sb,kerf,txt,comp.Shape.BoundBox.ZMin,comp.Shape.BoundBox.ZMax)
                job.ViewObject.Visibility=False
        if save_retal:
            step("%s: guardando el retal para 1st Nesting..."%name)
            fn,info=export_offcut(doc,sb,name,th,base); res["retal"]=fn; res["retal_info"]=info
        files=[f for f in (res.get("raw"),res.get("final"),res.get("retal")) if f]
        try:
            if "PlasmaFiles" not in job.PropertiesList:
                job.addProperty("App::PropertyStringList","PlasmaFiles","Plasma","Archivos creados por Mecanizar plasma")
            job.PlasmaFiles=sorted(set(files))
        except Exception: pass
        results.append(res)
    return results

def nesting_documents():
    """Open documents with a nesting result (sheets and parts) to machine."""
    out=[]
    for d in App.listDocuments().values():
        if d.Name.startswith("Nesting_Preview"): continue
        try:
            if detect(d,False)[0]: out.append(d)
        except Exception: pass
    return out

def activate_doc(doc):
    App.setActiveDocument(doc.Name)
    try:
        mdi=Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sub in mdi.subWindowList():
            if sub.windowTitle().split(" : ")[0]==doc.Label: mdi.setActiveSubWindow(sub); break
    except Exception: pass
    QtWidgets.QApplication.processEvents()

def main():
    doc=App.ActiveDocument
    if not doc: QtWidgets.QMessageBox.warning(None,TITLE,"Abre primero el proyecto con las piezas."); return
    groups,source=detect(doc)
    if not groups: QtWidgets.QMessageBox.warning(None,TITLE,"No encuentro piezas.\nSelecciona las piezas a cortar o abre un resultado de anidado."); return
    dlg=Dialog(groups,source,doc)
    if dlg.exec_()!=QtWidgets.QDialog.Accepted: return
    outdir=dlg.folder.text(); os.makedirs(outdir,exist_ok=True)
    App.ParamGet(PREFS).SetString("LastFolder",outdir)
    nm=clean_name(dlg.name.text())
    App.ParamGet(PREFS).SetString("LastName",nm)
    base="%s-%s"%(nm,time.strftime("%Y%m%d-%H%M"))
    opt={"ext":dlg.ext.get(),"int":dlg.int.get(),"kerf":dlg.kerf.value()}
    try: Gui.activateWorkbench("CAMWorkbench")
    except Exception: pass
    prog=QtWidgets.QProgressDialog("Preparando...","Cancelar",0,100,Gui.getMainWindow()); prog.setWindowTitle(TITLE)
    prog.setWindowModality(QtCore.Qt.WindowModal); prog.setMinimumDuration(0); prog.setMinimumWidth(480)
    t0=time.time()
    # One document, or every open nesting result with the same options.
    targets=[(doc,dlg.groups)]
    if dlg.all_docs.isChecked():
        targets=[(d,dlg.groups if d is doc else detect(d,False)[0]) for d in nesting_documents()]
    res=[]
    for n_doc,(d,groups) in enumerate(targets,1):
        if prog.wasCanceled(): break
        activate_doc(d)
        prog.setWindowTitle("%s - %s (%d de %d)"%(TITLE,d.Label,n_doc,len(targets)))
        if dlg.clean.isChecked():
            prog.setLabelText("%s: borrando el mecanizado anterior..."%d.Label); QtWidgets.QApplication.processEvents()
            n=remove_previous(d); log("%s: borrados %d objetos del mecanizado anterior"%(d.Label,n))
        dbase=base if len(targets)==1 else "%s_%s"%(base,clean_name(d.Label))
        part=mecanizar(d,groups,dlg.kerf.value(),dlg.tool.currentText(),dlg.post.currentText(),dlg.qt.isChecked() and dlg.qt.isEnabled(),opt,outdir,dbase,dlg.retal.isChecked() and dlg.retal.isEnabled(),prog,dlg.sim.isChecked() and dlg.qt.isChecked())
        for r in part:
            if len(targets)>1: r["name"]="%s · %s"%(d.Label,r["name"])
        res+=part
        for o in d.Objects:
            if o.Name.startswith(("Nesting_","Part_","JoinedParts_")) and o.TypeId=="Part::Feature": o.ViewObject.Transparency=50
        try: Gui.getDocument(d.Name).activeView().viewTop(); Gui.getDocument(d.Name).activeView().fitAll()
        except Exception: pass
        if d.FileName: d.save()
    prog.setValue(100); prog.close(); restore_cursor()
    activate_doc(doc)
    lines=[]; ok=True
    for r in res:
        if "holes" in r:
            good=(r["holes"]==r["expected_holes"] and r["outer"]==r["parts"] and r["m3"]==r["m5"]==r["holes"]+r["outer"] and r["z"]==0 and r["worst"]>=3)
            ok&=good
            t="%s %s\n   Piezas %d -> contornos %d | agujeros %d de %d\n   Perforacion mas cercana a una pieza: %.1f mm | entradas acortadas: %d\n   Programa: %s"%(
                "OK" if good else "REVISAR", r["name"], r["parts"], r["outer"], r["holes"], r["expected_holes"], r["worst"], r["short"], r["final"])
        else: t="%s\n   Programa (sin adaptar): %s"%(r["name"],r["final"])
        if "retal" in r: t+="\n   Retal: %s"%(("%s (%s)"%(r["retal"],r["retal_info"])) if r["retal"] else r["retal_info"])
        lines.append(t)
    msg="Terminado en %.0f s.\n\n"%(time.time()-t0)+"\n\n".join(lines)
    if any("worst" in r and r["worst"]<3 for r in res): msg+="\n\nATENCION: hay perforaciones a menos de 3 mm de una pieza. Aumenta la separacion del anidado."
    if not ok: msg+="\n\nAlgo no cuadra: revisa el programa antes de cortar."
    msg+="\n\nAntes de cortar: elige el material en QtPlasmaC y haz una pasada en vacio."
    sims=[r["sim"] for r in res if r.get("sim")]
    if sims: msg+="\n\nSe abre la simulacion de corte en la vista 3D: Reproducir, velocidad y barra para avanzar."
    log(msg); QtWidgets.QMessageBox.information(Gui.getMainWindow(),TITLE,msg)
    if sims:
        import BotonesPlasma_Simulacion
        QtCore.QTimer.singleShot(300, lambda: BotonesPlasma_Simulacion.run(doc if len(targets)==1 else None))
