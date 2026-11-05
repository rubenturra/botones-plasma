# -*- coding: utf-8 -*-
"""Visor de informes PDF de plasma dentro de FreeCAD (una pestaña más).

FreeCAD no trae visor de PDF, así que al crear cada informe se guarda también
una imagen de la página (mismo dibujo) y esta pestaña la enseña. A la izquierda,
todos los informes: los de los anidados abiertos y los de la carpeta de
programas, del más nuevo al más antiguo. Botones para abrir el PDF de verdad
con el visor del sistema (para imprimir) y para abrir su carpeta.
"""
import glob
import os
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

TITLE = "Informes PDF de plasma"
PREFS = "User parameter:BaseApp/Preferences/Macros/MecanizarPlasma"   # Mecanizar plasma (LastFolder)


def program_pdf(doc, gcode):
    """PDF of the program shown by a G-code object (Plasma_GCode_N)."""
    n = gcode.Name[len("Plasma_GCode_"):]
    job = doc.getObject("Plasma_Job_%s" % n)
    for f in getattr(job, "PlasmaFiles", []) or []:
        if f.endswith("_QtPlasmaC.ngc"):
            return os.path.splitext(f)[0] + ".pdf"
    return None


def all_pdfs():
    """Reports of the open nesting documents and of the program folder."""
    found = {}
    for d in App.listDocuments().values():
        for o in d.Objects:
            for f in getattr(o, "PlasmaFiles", []) or []:
                if f.endswith("_QtPlasmaC.ngc"):
                    pdf = os.path.splitext(f)[0] + ".pdf"
                    if os.path.isfile(pdf):
                        found[os.path.normcase(os.path.abspath(pdf))] = pdf
    folder = App.ParamGet(PREFS).GetString("LastFolder", "")
    if folder and os.path.isdir(folder):
        for pdf in glob.glob(os.path.join(folder, "*_QtPlasmaC.pdf")):
            found.setdefault(os.path.normcase(os.path.abspath(pdf)), pdf)
    return sorted(found.values(), key=lambda f: os.path.getmtime(f), reverse=True)


class Viewer(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.zoom = 0.0          # 0 = fit the page in the window
        self.image = None
        L = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("<b>Informes</b> (el más nuevo arriba)"))
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumWidth(330)
        self.list.currentRowChanged.connect(self._show)
        left.addWidget(self.list, 1)
        refresh = QtWidgets.QPushButton("Actualizar la lista")
        refresh.clicked.connect(lambda: self.fill(self.current()))
        left.addWidget(refresh)
        L.addLayout(left)
        right = QtWidgets.QVBoxLayout()
        bar = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel()
        self.title.setWordWrap(True)
        bar.addWidget(self.title, 1)
        for text, z in (("Ajustar", 0.0), ("50 %", 0.5), ("100 %", 1.0)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, z=z: self._set_zoom(z))
            bar.addWidget(b)
        self.open_btn = QtWidgets.QPushButton("Abrir el PDF (imprimir)")
        self.open_btn.clicked.connect(self._open_pdf)
        bar.addWidget(self.open_btn)
        self.folder_btn = QtWidgets.QPushButton("Abrir la carpeta")
        self.folder_btn.clicked.connect(self._open_folder)
        bar.addWidget(self.folder_btn)
        right.addLayout(bar)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.scroll.setBackgroundRole(QtGui.QPalette.Dark)
        self.page = QtWidgets.QLabel()
        self.page.setAlignment(QtCore.Qt.AlignCenter)
        self.scroll.setWidget(self.page)
        self.scroll.setWidgetResizable(False)
        right.addWidget(self.scroll, 1)
        L.addLayout(right, 1)
        self.pdfs = []

    def current(self):
        k = self.list.currentRow()
        return self.pdfs[k] if 0 <= k < len(self.pdfs) else None

    def fill(self, select=None):
        self.pdfs = all_pdfs()
        if select and os.path.isfile(select) and select not in self.pdfs:
            self.pdfs.insert(0, select)
        self.list.blockSignals(True)
        self.list.clear()
        for f in self.pdfs:
            name = os.path.basename(f)[:-len("_QtPlasmaC.pdf")] if f.endswith("_QtPlasmaC.pdf") else os.path.basename(f)
            item = QtWidgets.QListWidgetItem("%s\n%s" % (name, time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(f)))))
            item.setToolTip(f)
            self.list.addItem(item)
        self.list.blockSignals(False)
        index = 0
        if select:
            key = os.path.normcase(os.path.abspath(select))
            index = next((k for k, f in enumerate(self.pdfs) if os.path.normcase(os.path.abspath(f)) == key), 0)
        if self.pdfs:
            self.list.setCurrentRow(index)
            self._show(index)
        else:
            self.title.setText("No hay informes PDF todavía: se crean al pulsar «Mecanizar plasma».")
            self.page.clear()

    def _show(self, k):
        if not (0 <= k < len(self.pdfs)):
            return
        pdf = self.pdfs[k]
        import BotonesPlasma_Informe as I
        png = I.preview_file(pdf)
        self.title.setText("<b>%s</b><br><span style='color:gray'>%s</span>" % (os.path.basename(pdf), os.path.dirname(pdf)))
        if os.path.isfile(png):
            self.image = QtGui.QPixmap(png)
            self._render()
        else:
            self.image = None
            self.page.setText("Este informe se creó antes de que existiera el visor de FreeCAD.\n\n"
                              "Pulsa «Abrir el PDF (imprimir)» para verlo con el visor del sistema.\n"
                              "(Los informes nuevos se ven aquí directamente.)")
            self.page.adjustSize()

    def _set_zoom(self, z):
        self.zoom = z
        self._render()

    def _render(self):
        if self.image is None or self.image.isNull():
            return
        if self.zoom <= 0:
            area = self.scroll.viewport().size()
            pm = self.image.scaled(max(50, area.width() - 8), max(50, area.height() - 8),
                                   QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        else:
            pm = self.image.scaledToWidth(int(self.image.width() * self.zoom), QtCore.Qt.SmoothTransformation)
        self.page.setPixmap(pm)
        self.page.resize(pm.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom <= 0:
            QtCore.QTimer.singleShot(0, self._render)

    def _open_pdf(self):
        f = self.current()
        if f:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(f))

    def _open_folder(self):
        f = self.current()
        if f:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(f)))


_viewer = {}


def show(pdf=None):
    """Open (or bring to the front) the viewer tab and select pdf."""
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub = _viewer.get("sub")
    try:
        alive = sub is not None and sub.widget() is not None and sub in mdi.subWindowList()
    except RuntimeError:
        alive = False
    if not alive:
        viewer = Viewer()
        sub = mdi.addSubWindow(viewer)
        sub.setWindowTitle(TITLE)
        sub.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        _viewer["sub"] = sub
    viewer = sub.widget()
    sub.showMaximized()
    mdi.setActiveSubWindow(sub)
    viewer.fill(pdf)
    return viewer
