"""Interface helpers of Botones plasma (a real module, so names resolve normally)."""
import os
import FreeCAD as App
import FreeCADGui as Gui

DIR = os.path.dirname(os.path.abspath(__file__))


def icon(name):
    return os.path.join(DIR, "icons", name)


def place_plasma_toolbar():
    """CAM has many toolbars: put Plasma at the start of its own row when it is
    squeezed behind the » overflow."""
    try:
        from PySide import QtWidgets, QtCore
        mw = Gui.getMainWindow()
        bars = [t for t in mw.findChildren(QtWidgets.QToolBar) if t.windowTitle() == "Plasma" and t.isVisible()]
        if not bars:
            return
        bar = bars[0]
        if bar.width() >= bar.sizeHint().width() - 2:
            return
        mw.removeToolBar(bar)
        mw.addToolBarBreak(QtCore.Qt.TopToolBarArea)
        mw.addToolBar(QtCore.Qt.TopToolBarArea, bar)
        bar.show()
    except Exception as e:
        App.Console.PrintLog("Botones plasma: barra no recolocada (%s)\n" % e)


def on_workbench(name):
    if name == "CAMWorkbench":
        from PySide import QtCore
        QtCore.QTimer.singleShot(300, place_plasma_toolbar)
        QtCore.QTimer.singleShot(1500, place_plasma_toolbar)


def watch_workbenches():
    try:
        Gui.getMainWindow().workbenchActivated.connect(on_workbench)
    except Exception as e:
        App.Console.PrintWarning("Botones plasma: no se pudo vigilar el banco de trabajo (%s)\n" % e)
