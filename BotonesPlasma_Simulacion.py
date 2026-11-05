# -*- coding: utf-8 -*-
"""Simulacion de corte por plasma en la vista 3D de FreeCAD.

Recorre el programa ya calculado por Mecanizar plasma (objeto "G-code ... (cortes)",
en el orden real de corte): la antorcha se mueve, cada corte hecho se pinta en rojo
y los desplazamientos en vacio con linea discontinua. Es ligera, asi que sirve para
chapas enteras con cientos de piezas (el simulador de CAM se queda congelado).
"""
import math
import time
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

TITLE = "Simulacion de corte plasma"
CUT_SPEED = 2000.0 / 60.0      # mm/s (la real la pone QtPlasmaC segun el material)
RAPID_SPEED = 10000.0 / 60.0   # mm/s
SPEEDS = (("x1 (real)", 1), ("x5", 5), ("x20", 20), ("x100", 100), ("x500", 500))


def program_objects(doc):
    """[(gcode_object, pierces_object)] of every sheet machined in doc."""
    out = []
    for o in doc.Objects:
        if o.Name.startswith("Plasma_GCode_") and hasattr(o, "Shape"):
            n = o.Name[len("Plasma_GCode_"):]
            out.append((o, doc.getObject("Plasma_Perforaciones_" + n)))
    return sorted(out, key=lambda x: x[0].Name)


_path_cache = {}


def cached_path(gcode, z):
    """build_path of a G-code object, remembered while the object is unchanged
    (reopening the window or switching program is then immediate)."""
    shape = gcode.Shape
    b = shape.BoundBox
    key = (gcode.Document.Name, gcode.Name, len(shape.Edges), round(b.XMin, 3), round(b.YMin, 3),
           round(b.XMax, 3), round(b.YMax, 3), round(shape.Length, 3), round(z, 3))
    if key not in _path_cache:
        if len(_path_cache) > 40:
            _path_cache.clear()
        deflection = max(0.2, max(b.XLength, b.YLength) / 6000.0)   # ~ one screen pixel
        _path_cache[key] = build_path(shape.Wires, z, deflection)
    return _path_cache[key]


def build_path(wires, z, deflection=0.2):
    """Cut polylines in cut order and the rapid moves between them."""
    cuts = []
    for w in wires:
        pts = []
        for e in w.OrderedEdges if hasattr(w, "OrderedEdges") else w.Edges:
            seg = e.discretize(Deflection=deflection) if e.Curve.TypeId != "Part::GeomLine" else [e.Vertexes[0].Point, e.Vertexes[-1].Point]
            if pts and (pts[-1] - seg[0]).Length > 1e-3 and (pts[-1] - seg[-1]).Length < 1e-3:
                seg = list(reversed(seg))
            pts += seg if not pts else seg[1:]
        if len(pts) >= 2:
            cuts.append([(p.x, p.y, z) for p in pts])
    # timeline: rapid to start, then the cut
    steps = []  # (kind, points, length)
    pos = (0.0, 0.0, z)
    for c in cuts:
        steps.append(("rapid", [pos, c[0]], math.dist(pos, c[0])))
        length = sum(math.dist(c[i], c[i + 1]) for i in range(len(c) - 1))
        steps.append(("cut", c, length))
        pos = c[-1]
    steps.append(("rapid", [pos, (0.0, 0.0, z)], math.dist(pos, (0.0, 0.0, z))))
    t = 0.0
    for k, (kind, pts, length) in enumerate(steps):
        dur = length / (CUT_SPEED if kind == "cut" else RAPID_SPEED)
        steps[k] = dict(kind=kind, pts=pts, length=length, t0=t, t1=t + dur)
        t += dur
    return steps, t


class Simulation(QtWidgets.QDialog):
    def __init__(self, doc, gcode, offset=App.Vector()):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(TITLE)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.doc = self.gcode = self.root = None
        self.t = 0.0
        self.total = 0.0
        self.speed = 20
        self.playing = False
        self._last = None
        self._kind = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self._build_ui()
        self.load(doc, gcode)

    def load(self, doc, gcode):
        """Show another machined program in this same window."""
        if self.playing:
            self.toggle()
        self._remove_scene()
        if self.gcode is not None:
            try:
                self.gcode.ViewObject.Visibility = True
            except Exception:
                pass
        self.doc, self.gcode = doc, gcode
        bb = gcode.Shape.BoundBox
        self.z = bb.ZMax + 0.5
        self.steps, self.total = cached_path(gcode, self.z)
        self.ncuts = sum(1 for s in self.steps if s["kind"] == "cut")
        self._cut_full = [len(s["pts"]) for s in self.steps if s["kind"] == "cut"]
        self._rap_full = [len(s["pts"]) for s in self.steps if s["kind"] != "cut"]
        self._kind = None
        _bring_to_front(doc)
        self._build_scene()
        try:
            gcode.ViewObject.Visibility = False
        except Exception:
            pass
        try:
            v = Gui.getDocument(doc.Name).activeView(); v.viewTop(); v.fitAll()
        except Exception:
            pass
        self._refresh_programs()
        self._show(0.0)

    # ---------------------------------------------------------------- scene
    def _build_scene(self):
        from pivy import coin
        self.coin = coin
        self.root = coin.SoSeparator()
        self.root.setName("SimulacionPlasma")
        # cuts done (red, thick)
        self.cut_sep = coin.SoSeparator()
        mat = coin.SoMaterial(); mat.diffuseColor.setValue(0.9, 0.05, 0.05); mat.emissiveColor.setValue(0.6, 0.0, 0.0)
        style = coin.SoDrawStyle(); style.lineWidth = 2.5
        self.cut_coords = coin.SoCoordinate3(); self.cut_lines = coin.SoLineSet()
        for n in (mat, style, self.cut_coords, self.cut_lines):
            self.cut_sep.addChild(n)
        # rapids done (green, dashed)
        self.rap_sep = coin.SoSeparator()
        mat2 = coin.SoMaterial(); mat2.diffuseColor.setValue(0.1, 0.75, 0.2); mat2.emissiveColor.setValue(0.0, 0.45, 0.1)
        style2 = coin.SoDrawStyle(); style2.lineWidth = 1.0; style2.linePattern = 0xF0F0
        self.rap_coords = coin.SoCoordinate3(); self.rap_lines = coin.SoLineSet()
        for n in (mat2, style2, self.rap_coords, self.rap_lines):
            self.rap_sep.addChild(n)
        # torch
        self.torch_sep = coin.SoSeparator()
        self.torch_pos = coin.SoTranslation()
        mat3 = coin.SoMaterial(); self.torch_mat = mat3  # colour set per frame: blue cutting, green rapid
        # Torch size follows the sheet so it is easy to see on a whole sheet.
        bb = self.gcode.Shape.BoundBox
        r = max(15.0, 0.018 * max(bb.XLength, bb.YLength))
        cone = coin.SoCone(); cone.bottomRadius = r; cone.height = 3.0 * r
        rot = coin.SoRotationXYZ(); rot.axis = coin.SoRotationXYZ.X; rot.angle = -math.pi / 2
        lift = coin.SoTranslation(); lift.translation.setValue(0, 0, 1.5 * r)
        for n in (self.torch_pos, mat3, lift, rot, cone):
            self.torch_sep.addChild(n)
        for n in (self.cut_sep, self.rap_sep, self.torch_sep):
            self.root.addChild(n)
        # static coordinates; only the number of drawn vertices changes per frame
        cut_pts, rap_pts = [], []
        for s in self.steps:
            (cut_pts if s["kind"] == "cut" else rap_pts).extend(s["pts"])
        if cut_pts:
            self.cut_coords.point.setValues(0, len(cut_pts), cut_pts)
        if rap_pts:
            self.rap_coords.point.setValues(0, len(rap_pts), rap_pts)
        self.view = Gui.getDocument(self.doc.Name).activeView()
        self.view.getSceneGraph().addChild(self.root)

    def _remove_scene(self):
        if self.root is None:
            return
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception:
            pass
        self.root = None

    # ---------------------------------------------------------------- ui
    def _build_ui(self):
        L = QtWidgets.QVBoxLayout(self)
        h0 = QtWidgets.QHBoxLayout()
        h0.addWidget(QtWidgets.QLabel("Programa:"))
        self.prog_combo = _ProgramCombo(self)
        self.prog_combo.setToolTip("Todos los programas mecanizados de los documentos abiertos")
        self.prog_combo.activated.connect(self._pick_program)
        h0.addWidget(self.prog_combo, 1)
        L.addLayout(h0)
        self.info = QtWidgets.QLabel()
        L.addWidget(self.info)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(lambda v: self._seek(v / 1000.0 * self.total))
        L.addWidget(self.slider)
        h = QtWidgets.QHBoxLayout()
        self.play_btn = QtWidgets.QPushButton("▶ Reproducir")
        self.play_btn.clicked.connect(self.toggle)
        h.addWidget(self.play_btn)
        restart = QtWidgets.QPushButton("⏮ Inicio")
        restart.clicked.connect(lambda: self._seek(0.0))
        h.addWidget(restart)
        end = QtWidgets.QPushButton("⏭ Final")
        end.clicked.connect(lambda: self._seek(self.total))
        h.addWidget(end)
        h.addWidget(QtWidgets.QLabel("Velocidad:"))
        self.speed_combo = QtWidgets.QComboBox()
        for text, value in SPEEDS:
            self.speed_combo.addItem(text, value)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(lambda i: setattr(self, "speed", self.speed_combo.itemData(i)))
        h.addWidget(self.speed_combo)
        close = QtWidgets.QPushButton("Cerrar")
        close.clicked.connect(self.close)
        h.addWidget(close)
        L.addLayout(h)
        note = QtWidgets.QLabel("Antorcha azul: cortando · antorcha verde: en vacío · rojo: cortes hechos · "
                                "verde discontinuo: movimientos en vacío · "
                                "tiempo calculado con 2000 mm/min de corte (en la máquina manda QtPlasmaC).")
        note.setWordWrap(True); note.setStyleSheet("color: gray;")
        L.addWidget(note)
        self.setMinimumWidth(560)

    def _refresh_programs(self):
        self.progs = all_programs()
        self.prog_combo.blockSignals(True)
        self.prog_combo.clear()
        current = 0
        for k, (d, g) in enumerate(self.progs):
            self.prog_combo.addItem("%s  ·  %s" % (d.Label, g.Label))
            if self.gcode is not None and d.Name == self.doc.Name and g.Name == self.gcode.Name:
                current = k
        self.prog_combo.setCurrentIndex(current)
        self.prog_combo.blockSignals(False)

    def _pick_program(self, index):
        if 0 <= index < len(self.progs):
            d, g = self.progs[index]
            if d.Name != self.doc.Name or g.Name != self.gcode.Name:
                try:
                    self.load(d, g)
                except Exception as e:
                    App.Console.PrintError("%s: %s\n" % (TITLE, e))

    def toggle(self):
        self.playing = not self.playing
        if self.playing and self.t >= self.total:
            self.t = 0.0
        self.play_btn.setText("⏸ Pausa" if self.playing else "▶ Reproducir")
        self._last = time.time()
        (self.timer.start if self.playing else self.timer.stop)()

    def _tick(self):
        now = time.time()
        dt = now - (self._last or now)
        self._last = now
        self._show(min(self.total, self.t + dt * self.speed))
        if self.t >= self.total:
            self.toggle()

    def _seek(self, t):
        self._show(max(0.0, min(self.total, t)))

    def _show(self, t):
        self.t = t
        cut_counts, rap_counts = [], []
        torch = (0.0, 0.0, self.z)
        done_cuts = 0
        kind = "rapid"
        for s in self.steps:
            if s["t0"] < t < s["t1"]:
                kind = s["kind"]
            pts = s["pts"]
            if t >= s["t1"]:
                n = len(pts)
                torch = pts[-1]
                if s["kind"] == "cut":
                    done_cuts += 1
            elif t <= s["t0"]:
                n = 0
            else:
                # partial step: walk along the polyline
                frac = (t - s["t0"]) / max(s["t1"] - s["t0"], 1e-9)
                target = frac * s["length"]
                acc = 0.0; n = 1; torch = pts[0]
                for i in range(len(pts) - 1):
                    d = math.dist(pts[i], pts[i + 1])
                    if acc + d >= target:
                        f = (target - acc) / d if d > 0 else 0
                        torch = tuple(pts[i][k] + f * (pts[i + 1][k] - pts[i][k]) for k in range(3))
                        n = i + 1
                        break
                    acc += d; n = i + 2
            (cut_counts if s["kind"] == "cut" else rap_counts).append(n)
        self._fix_partial(self.cut_lines, cut_counts, self._cut_full)
        self._fix_partial(self.rap_lines, rap_counts, self._rap_full)
        self.torch_pos.translation.setValue(*torch)
        if kind != self._kind:
            self._kind = kind
            if kind == "cut":
                self.torch_mat.diffuseColor.setValue(0.05, 0.35, 1.0); self.torch_mat.emissiveColor.setValue(0.0, 0.2, 0.9)
            else:
                self.torch_mat.diffuseColor.setValue(0.1, 0.9, 0.2); self.torch_mat.emissiveColor.setValue(0.0, 0.6, 0.1)
        self.slider.blockSignals(True); self.slider.setValue(int(1000 * t / max(self.total, 1e-9))); self.slider.blockSignals(False)
        self.info.setText("Corte %d de %d  ·  %s de %s" % (done_cuts, self.ncuts, _mmss(t), _mmss(self.total)))

    @staticmethod
    def _fix_partial(lineset, counts, full):
        # A SoLineSet consumes its coordinates in order: draw the finished
        # polylines whole, the current one up to the torch, and stop there.
        values = []
        for c, f in zip(counts, full):
            if c >= f:
                values.append(f)
                continue
            if c >= 2:
                values.append(c)
            break
        if values:
            lineset.numVertices.setValues(0, len(values), values)
        lineset.numVertices.setNum(len(values))

    def closeEvent(self, event):
        self.timer.stop()
        self._remove_scene()
        if self in _open:
            _open.remove(self)
        try:
            self.gcode.ViewObject.Visibility = True
        except Exception:
            pass
        super().closeEvent(event)


def _mmss(seconds):
    seconds = int(round(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60) if seconds < 3600 else "%d:%02d:%02d" % (
        seconds // 3600, seconds // 60 % 60, seconds % 60)


class _ProgramCombo(QtWidgets.QComboBox):
    """Re-reads the open documents each time the list is opened."""
    def showPopup(self):
        try:
            self.parent()._refresh_programs()
        except Exception:
            pass
        super().showPopup()


def all_programs(docs=None):
    docs = docs if docs is not None else list(App.listDocuments().values())
    return [(d, g) for d in docs for g, p in program_objects(d)]


def _bring_to_front(doc):
    App.setActiveDocument(doc.Name)
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sub in mdi.subWindowList():
            if sub.windowTitle().split(" : ")[0] == doc.Label:
                mdi.setActiveSubWindow(sub)
                break
    except Exception:
        pass
    QtWidgets.QApplication.processEvents()


_open = []


def run(doc=None):
    """Open the simulation window. Every machined program of every open document
    can be chosen in its "Programa" list; doc (after Mecanizar plasma) picks the
    first program of that document."""
    progs = all_programs()
    if not progs:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), TITLE,
            "No hay ningún programa de plasma en los documentos abiertos. Pulsa antes «Mecanizar plasma»."); return
    want = doc if doc is not None else App.ActiveDocument
    doc, gcode = next(((d, g) for d, g in progs if want is not None and d.Name == want.Name), progs[0])
    if _open:
        sim = _open[0]
        sim.load(doc, gcode)
        sim.show(); sim.raise_()
        return sim
    sim = Simulation(doc, gcode)
    _open.append(sim)
    sim.show()
    try:  # bottom of the main window, so it does not cover the sheet
        g = Gui.getMainWindow().geometry()
        sim.move(g.x() + 300, g.y() + g.height() - sim.height() - 60)
    except Exception:
        pass
    return sim
