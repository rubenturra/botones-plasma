# -*- coding: utf-8 -*-
"""Informe PDF de cada programa de plasma.

Al terminar Mecanizar plasma se guardan los datos de cada chapa (contornos de las
piezas, chapa, retal, perforaciones y datos del programa) y un FreeCAD sin ventana
dibuja en segundo plano un PDF al lado del programa (mismo nombre, .pdf):
datos de la chapa, espesor, material, piezas, longitudes, tiempo estimado y un
dibujo de la chapa. Asi el mecanizado no tarda mas.
"""
import json
import os
import re
import time

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# Density in kg/mm3 by material name (default: steel).
DENSITIES = (("alumin", 2.70e-6), ("inox", 7.95e-6), ("304", 7.95e-6), ("316", 7.98e-6),
             ("cobre", 8.96e-6), ("lat", 8.5e-6))
STEEL = 7.85e-6


def density(material):
    m = (material or "").lower()
    for key, value in DENSITIES:
        if key in m:
            return value
    return STEEL


# ---------------------------------------------------------------- en FreeCAD
_names_cache = {}


def source_names(doc):
    """{source part index: original part name} from the nesting result data."""
    meta = doc.getObject("NestingResultData")
    if meta is None or "ResultJson" not in meta.PropertiesList:
        return {}
    key = (doc.Name, len(meta.ResultJson))
    if key not in _names_cache:
        out = {}
        try:
            for s in json.loads(meta.ResultJson).get("sourceParts", []):
                if s.get("label") and s.get("source_part_index") is not None:
                    out[int(s["source_part_index"])] = str(s["label"])
        except Exception:
            pass
        _names_cache.clear()
        _names_cache[key] = out
    return _names_cache[key]


def collect(job_dir, res, settings):
    """Save what the report needs (runs in FreeCAD, takes well under a second).
    Returns the job file or None."""
    import Part
    rep = res["_report"]
    doc, index, name, sb, parts = rep["doc"], rep["index"], rep["name"], rep["sb"], rep["parts"]
    os.makedirs(job_dir, exist_ok=True)
    tag = "%s_hoja_%d" % (re.sub(r"\W+", "_", doc.Name), index)
    sheet = next((o for o in doc.Objects if o.Name.startswith("Sheet_") and o.Label == name), None)
    thickness = 0.0
    material = ""
    if sheet is not None:
        try:
            thickness = float(getattr(sheet, "Thickness", 0) or 0)
        except Exception:
            thickness = 0.0
        material = str(getattr(sheet, "Material", "") or "")
    zmin = min(p.Shape.BoundBox.ZMin for p in parts)
    zmax = max(p.Shape.BoundBox.ZMax for p in parts)
    if not thickness:
        thickness = zmax - zmin
    names = source_names(doc)
    groups = {}
    for p in parts:
        # Same source part = same type (FreeCAD renumbers the labels of copies:
        # Placa_20x200_10, Placa_20x200_11...). The first copy keeps the name.
        if "SourcePartIndex" in p.PropertiesList:
            key = "src_%s" % p.SourcePartIndex
        else:
            key = re.sub(r"\d{3}$", "", p.Label) or p.Label
        label = groups[key]["label"] if key in groups else names.get(
            getattr(p, "SourcePartIndex", None), p.Label)
        face = None
        for f in p.Shape.Faces:
            b = f.BoundBox
            if b.ZLength < 0.01 and abs(b.ZMax - p.Shape.BoundBox.ZMax) < 0.01:
                if face is None or f.Area > face.Area:
                    face = f
        g = groups.setdefault(key, dict(label=label, faces=[], count=0, area=0.0, holes=0,
                                          size=(p.Shape.BoundBox.XLength, p.Shape.BoundBox.YLength)))
        g["count"] += 1
        if face is not None:
            g["faces"].append(face)
            if g["count"] == 1:
                g["area"] = face.Area
                g["holes"] = len(face.Wires) - 1
    types = []
    for k, g in enumerate(sorted(groups.values(), key=lambda g: -g["count"])):
        brep = os.path.join(job_dir, "%s_tipo_%d.brep" % (tag, k))
        if g["faces"]:
            Part.makeCompound(g["faces"]).exportBrep(brep)
        types.append(dict(label=g["label"], count=g["count"], area=g["area"], holes=g["holes"],
                          size=list(g["size"]), brep=brep if g["faces"] else ""))
    sheet_brep = ""
    if sheet is not None:
        sheet_brep = os.path.join(job_dir, "%s_chapa.brep" % tag)
        sheet.Shape.exportBrep(sheet_brep)
    offcut_brep = ""
    offcut = rep.get("offcut")
    if offcut is not None:
        offcut_brep = os.path.join(job_dir, "%s_retal.brep" % tag)
        offcut.Shape.exportBrep(offcut_brep)
    cut_len = rep.get("cut_length", 0.0)
    data = dict(
        document=doc.Label, sheet=name, index=index,
        sheet_box=[sb.XMin, sb.YMin, sb.XMax, sb.YMax],
        thickness=thickness, material=material, density=density(material),
        types=types, sheet_brep=sheet_brep, offcut_brep=offcut_brep,
        pierces=[list(p) for p in rep.get("piers", [])],
        cut_length=cut_len, parts=len(parts),
        holes=res.get("holes", 0), outer=res.get("outer", 0), worst=res.get("worst", 0),
        program=res.get("final", ""), raw=res.get("raw", ""), retal=res.get("retal") or "",
        retal_info=res.get("retal_info", ""), date=time.strftime("%d/%m/%Y %H:%M"),
        kerf=settings.get("kerf", 0), tool=settings.get("tool", ""), post=settings.get("post", ""),
        feed=settings.get("feed", 2000.0), leads=settings.get("leads", {}),
        pdf=os.path.splitext(res.get("final") or res.get("raw"))[0] + ".pdf")
    fn = os.path.join(job_dir, "%s.json" % tag)
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return fn


def launch(job_files):
    """Draw every report in ONE background FreeCAD (no window)."""
    import subprocess
    import FreeCAD as App
    if not job_files:
        return None
    exe = None
    for n in ("FreeCADCmd.exe", "freecadcmd.exe", "FreeCADCmd", "freecadcmd"):
        f = os.path.join(App.getHomePath(), "bin", n)
        if os.path.isfile(f):
            exe = f
            break
    if exe is None:
        return None
    job_dir = os.path.dirname(job_files[0])
    script = os.path.join(job_dir, "informe.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\nimport sys\nsys.path.insert(0, %r)\n"
                "import BotonesPlasma_Informe as I\nI.build_all(%r, %r)\n"
                % (MODULE_DIR, list(job_files), job_dir))
    return subprocess.Popen([exe, script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000 if os.name == "nt" else 0)


# ---------------------------------------------------------------- en segundo plano
def build_all(job_files, job_dir):
    import shutil
    log = []
    try:
        for fn in job_files:
            try:
                data = json.load(open(fn, encoding="utf-8"))
                build(data)
                log.append("ok " + data["pdf"])
            except Exception:
                import traceback
                log.append(traceback.format_exc())
    finally:
        try:
            open(os.path.join(os.path.dirname(job_dir), "ultimo_informe.log"), "w",
                 encoding="utf-8").write("\n".join(log))
        except Exception:
            pass
        shutil.rmtree(job_dir, ignore_errors=True)


def _rings(brep, deflection=0.5):
    """[(outer, [holes])] of every face in a BREP, as point lists."""
    import Part
    if not brep or not os.path.exists(brep):
        return []
    shape = Part.Shape()
    shape.importBrep(brep)
    out = []
    for face in shape.Faces:
        wires = sorted(face.Wires, key=lambda w: -w.BoundBox.DiagonalLength)
        rings = []
        for w in wires:
            pts = []
            for e in w.OrderedEdges:
                seg = e.discretize(Deflection=deflection)
                if pts and (pts[-1] - seg[0]).Length > 1e-3 and (pts[-1] - seg[-1]).Length < 1e-3:
                    seg = list(reversed(seg))
                pts += seg
            rings.append([(p.x, p.y) for p in pts])
        if rings:
            out.append((rings[0], rings[1:]))
    return out


COLOURS = ((231, 76, 60), (52, 152, 219), (46, 204, 113), (155, 89, 182), (241, 196, 15),
           (230, 126, 34), (26, 188, 156), (236, 64, 122), (52, 73, 94), (149, 165, 166))


def _fmt(v, d=0):
    s = ("{:,.%df}" % d).format(v)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _elide(text, n):
    text = str(text or "")
    return text if len(text) <= n else "…" + text[-(n - 1):]


def _time(minutes):
    s = int(round(minutes * 60))
    return "%d h %02d min" % (s // 3600, s // 60 % 60) if s >= 3600 else "%d min %02d s" % (s // 60, s % 60)


def build(data, png_preview=None):
    try:
        from PySide6 import QtGui, QtCore
    except ImportError:
        from PySide2 import QtGui, QtCore
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(["informe"])
    dpi = 200
    dpm = dpi / 25.4                       # dots per mm
    p = QtGui.QPainter()
    images = []

    class Pages:
        """PDF pages, or PNG images of the same pages (png_preview) to check them."""
        def __init__(self):
            if png_preview:
                self.dev = None
                self.newPage(first=True)
            else:
                self.dev = QtGui.QPdfWriter(data["pdf"])
                self.dev.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
                self.dev.setPageMargins(QtCore.QMarginsF(12, 12, 12, 12), QtGui.QPageLayout.Millimeter)
                self.dev.setResolution(dpi)
                self.dev.setTitle("Programa plasma %s - %s" % (data["document"], data["sheet"]))
                self.dev.setCreator("Botones plasma")
                p.begin(self.dev)

        def newPage(self, first=False):
            if not png_preview:
                self.dev.newPage()
                return
            if not first:
                p.end()
            im = QtGui.QImage(int(186 * dpm), int(273 * dpm), QtGui.QImage.Format_RGB32)
            im.setDotsPerMeterX(int(dpi / 0.0254)); im.setDotsPerMeterY(int(dpi / 0.0254))
            im.fill(QtGui.QColor(255, 255, 255))
            images.append(im)
            self.dev = im
            p.begin(im)

        def width(self):
            return self.dev.width()

        def height(self):
            return self.dev.height()

    pdf = Pages()
    W = pdf.width()
    H = pdf.height()

    def font(size, bold=False):
        f = QtGui.QFont("Arial")
        f.setPointSizeF(size)
        f.setBold(bold)
        p.setFont(f)
        return QtGui.QFontMetricsF(f, pdf.dev)

    y = 0.0

    def line(text, size=9.5, bold=False, x=0.0, colour=(0, 0, 0), advance=True):
        nonlocal y
        fm = font(size, bold)
        p.setPen(QtGui.QColor(*colour))
        p.drawText(QtCore.QPointF(x, y + fm.ascent()), text)
        if advance:
            y += fm.height() * 1.15
        return fm

    # ---- header
    line("Programa de corte por plasma", 17, True, colour=(20, 40, 80))
    line("%s  ·  %s  ·  %s" % (data["document"], data["sheet"], data["date"]), 10.5, colour=(80, 80, 80))
    y += 1.5 * dpm
    p.setPen(QtGui.QPen(QtGui.QColor(20, 40, 80), 0.5 * dpm))
    p.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(W, y))
    y += 3 * dpm

    x0, y0, x1, y1 = data["sheet_box"]
    sw, sh = x1 - x0, y1 - y0
    thick = data["thickness"]
    dens = data["density"]
    types = data["types"]
    parts_area = sum(t["area"] * t["count"] for t in types)
    sheet_area = sw * sh
    weight_sheet = sheet_area * thick * dens
    weight_parts = parts_area * thick * dens
    cut_m = data["cut_length"] / 1000.0
    feed = float(data["feed"] or 2000.0)
    est = data["cut_length"] / feed if feed else 0
    material = data["material"] or "(no indicado)"
    leads = data.get("leads") or {}

    def lead_txt(l):
        if not l:
            return "-"
        return "entrada %s %s mm, salida %s %s mm, %s" % (
            l.get("in", ""), _fmt(l.get("in_len", 0), 1),
            l.get("out", ""), _fmt(l.get("out_len", 0), 1), l.get("dir", "").lower())

    info_left = [
        ("Chapa", "%s x %s mm" % (_fmt(sw), _fmt(sh))),
        ("Espesor", "%s mm" % _fmt(thick, 1)),
        ("Material", material),
        ("Superficie chapa", "%s m²" % _fmt(sheet_area / 1e6, 2)),
        ("Peso chapa (aprox.)", "%s kg" % _fmt(weight_sheet, 1)),
        ("Piezas", "%d (%d tipos)" % (data["parts"], len(types))),
        ("Peso piezas (aprox.)", "%s kg" % _fmt(weight_parts, 1)),
        ("Aprovechamiento", "%s %%" % _fmt(100.0 * parts_area / sheet_area if sheet_area else 0, 1)),
    ]
    info_right = [
        ("Contornos / agujeros", "%d / %d" % (data["outer"], data["holes"])),
        ("Perforaciones", "%d" % len(data["pierces"])),
        ("Longitud de corte", "%s m" % _fmt(cut_m, 2)),
        ("Tiempo de corte (est.)", "%s a %s mm/min" % (_time(est), _fmt(feed))),
        ("Sangría (kerf)", "%s mm" % _fmt(data["kerf"], 2)),
        ("Herramienta", data["tool"] or "-"),
        ("Postprocesador", data["post"] or "-"),
        ("Perforación más cercana", "%s mm de una pieza" % _fmt(data["worst"], 1)),
    ]
    col = W / 2
    top = y
    for k, (a, b) in enumerate(info_left):
        line(a, 9, True, 0, (70, 70, 70), advance=False)
        line(b, 9.5, False, 42 * dpm)
    yl = y
    y = top
    for k, (a, b) in enumerate(info_right):
        line(a, 9, True, col, (70, 70, 70), advance=False)
        line(b, 9.5, False, col + 46 * dpm)
    y = max(y, yl) + 1 * dpm
    line("Entradas/salidas exteriores: %s" % lead_txt(leads.get("ext")), 8, False, 0, (90, 90, 90))
    line("Entradas/salidas interiores: %s" % lead_txt(leads.get("int")), 8, False, 0, (90, 90, 90))
    line("Programa: %s" % _elide(data["program"], 110), 8, False, 0, (90, 90, 90))
    if data.get("retal"):
        line("Retal: %s (%s)" % (os.path.basename(data["retal"]), data.get("retal_info", "")), 8, False, 0, (90, 90, 90))
    y += 3 * dpm

    # ---- one page: the parts table goes under the drawing, so the drawing
    # gets the height the table leaves free (at least 60 mm).
    n_rows = max(1, len(types))
    row_pt = 8.5
    def rh_of(pt):
        f = QtGui.QFont("Arial")
        f.setPointSizeF(pt)
        return QtGui.QFontMetricsF(f, pdf.dev).height()
    def table_height(pt):
        return (rh_of(pt) * 1.4 + n_rows * rh_of(pt) * 1.35 + 1 * dpm + rh_of(9) * 2
                + 3 * rh_of(7.5) * 1.15 + 6 * dpm)
    min_draw = 60 * dpm
    while row_pt > 5.5 and H - y - table_height(row_pt) - 8 * dpm < min_draw:
        row_pt -= 0.5
    legend_h = 6 * dpm
    avail_h = max(min_draw, H - y - table_height(row_pt) - legend_h - 2 * dpm)
    scale = min(W / sw, avail_h / sh) if sw > 0 and sh > 0 else 1
    dw, dh = sw * scale, sh * scale
    ox = (W - dw) / 2
    oy = y

    def pt(x, yy):
        return QtCore.QPointF(ox + (x - x0) * scale, oy + (y1 - yy) * scale)

    def path(rings):
        pa = QtGui.QPainterPath()
        pa.setFillRule(QtCore.Qt.OddEvenFill)
        for ring in rings:
            if len(ring) < 2:
                continue
            pa.moveTo(pt(*ring[0]))
            for q in ring[1:]:
                pa.lineTo(pt(*q))
            pa.closeSubpath()
        return pa

    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    sheet_rings = _rings(data["sheet_brep"], 1.0)
    p.setPen(QtGui.QPen(QtGui.QColor(60, 60, 60), 0.35 * dpm))
    p.setBrush(QtGui.QColor(236, 238, 241))
    if sheet_rings:
        for outer, holes in sheet_rings:
            p.drawPath(path([outer] + holes))
    else:
        p.drawRect(QtCore.QRectF(ox, oy, dw, dh))
    for outer, holes in _rings(data["offcut_brep"], 1.0):
        p.setPen(QtGui.QPen(QtGui.QColor(39, 174, 96), 0.3 * dpm, QtCore.Qt.DashLine))
        p.setBrush(QtGui.QBrush(QtGui.QColor(39, 174, 96, 90), QtCore.Qt.BDiagPattern))
        p.drawPath(path([outer] + holes))
    for k, t in enumerate(types):
        c = COLOURS[k % len(COLOURS)]
        p.setPen(QtGui.QPen(QtGui.QColor(*c).darker(160), 0.15 * dpm))
        p.setBrush(QtGui.QColor(c[0], c[1], c[2], 170))
        for outer, holes in _rings(t["brep"], 0.5):
            p.drawPath(path([outer] + holes))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(200, 0, 0))
    r = max(0.35 * dpm, 1.2)
    for q in data["pierces"]:
        p.drawEllipse(pt(q[0], q[1]), r, r)
    y = oy + dh + 2 * dpm
    line("Dibujo a escala 1:%s · rojo: perforaciones · verde rayado: retal reutilizable" % _fmt(1 / (scale / dpm)),
         7.5, False, 0, (90, 90, 90))

    # ---- parts table (same page)
    y += 2 * dpm
    cols = [("", 7), ("Pieza", 58), ("Cant.", 15), ("Medidas (mm)", 32), ("Agujeros", 18),
            ("Área (cm²)", 22), ("Peso ud. (kg)", 22), ("Peso total (kg)", 24)]
    scale_c = W / (sum(c[1] for c in cols) * dpm)
    xs = []
    acc = 0.0
    for c in cols:
        xs.append(acc)
        acc += c[1] * dpm * scale_c
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(20, 40, 80))
    fm = font(row_pt, True)
    p.drawRect(QtCore.QRectF(0, y, W, fm.height() * 1.4))
    for (title, w), x in zip(cols, xs):
        p.setPen(QtGui.QColor(255, 255, 255))
        p.drawText(QtCore.QPointF(x + 1 * dpm, y + fm.ascent() + fm.height() * 0.2), title)
    y += fm.height() * 1.4
    total_w = 0.0
    for k, t in enumerate(types):
        fm = font(row_pt)
        rh = fm.height() * 1.35
        if k % 2:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(242, 244, 247))
            p.drawRect(QtCore.QRectF(0, y, W, rh))
        c = COLOURS[k % len(COLOURS)]
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(*c))
        p.drawRect(QtCore.QRectF(xs[0] + 1 * dpm, y + rh * 0.2, 4 * dpm, rh * 0.6))
        wu = t["area"] * thick * dens
        total_w += wu * t["count"]
        vals = ["", t["label"], "%d" % t["count"], "%s x %s" % (_fmt(t["size"][0], 0), _fmt(t["size"][1], 0)),
                "%d" % t["holes"], _fmt(t["area"] / 100.0, 1), _fmt(wu, 2), _fmt(wu * t["count"], 1)]
        p.setPen(QtGui.QColor(0, 0, 0))
        for v, x, (title, w) in zip(vals, xs, cols):
            text = fm.elidedText(v, QtCore.Qt.ElideRight, w * dpm * scale_c - 2 * dpm)
            p.drawText(QtCore.QPointF(x + 1 * dpm, y + fm.ascent() + rh * 0.13), text)
        y += rh
    p.setPen(QtGui.QPen(QtGui.QColor(20, 40, 80), 0.3 * dpm))
    p.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(W, y))
    y += 1 * dpm
    fm = font(9, True)
    p.setPen(QtGui.QColor(0, 0, 0))
    p.drawText(QtCore.QPointF(xs[1] + 1 * dpm, y + fm.ascent()), "TOTAL")
    p.drawText(QtCore.QPointF(xs[2] + 1 * dpm, y + fm.ascent()), "%d" % data["parts"])
    p.drawText(QtCore.QPointF(xs[7] + 1 * dpm, y + fm.ascent()), _fmt(total_w, 1))
    y += fm.height() * 2
    line("Pesos aproximados con densidad %s kg/dm³%s." % (
        _fmt(dens * 1e6, 2), (" (%s)" % data["material"]) if data["material"] else " (acero)"), 7.5, False, 0, (90, 90, 90))
    line("Tiempo de corte estimado con el avance indicado; en la máquina manda la tabla de corte de QtPlasmaC.",
         7.5, False, 0, (90, 90, 90))
    line("Antes de cortar: elige el material en QtPlasmaC y haz una pasada en vacío.", 7.5, False, 0, (90, 90, 90))
    p.end()
    if png_preview:
        for k, im in enumerate(images):
            im.save("%s_%d.png" % (png_preview, k + 1))
    del app
