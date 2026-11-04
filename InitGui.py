# Botones plasma: herramientas específicas del corte por plasma (FreeCAD CAM + QtPlasmaC).
import os
import FreeCAD as App
import FreeCADGui as Gui

_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.path.join(
    App.getUserAppDataDir(), "Mod", "botones-plasma")


class _MecanizarPlasma:
    def GetResources(self):
        return {"Pixmap": os.path.join(_DIR, "icons", "mecanizar_plasma.svg"),
                "MenuText": "Mecanizar plasma",
                "ToolTip": "Mecanizar para plasma las piezas seleccionadas o el resultado del anidado: "
                           "herramienta, postprocesador, QtPlasmaC, entradas/salidas, retal y simulación"}

    def Activated(self):
        import BotonesPlasma_Mecanizar
        BotonesPlasma_Mecanizar.main()

    def IsActive(self):
        return App.ActiveDocument is not None


Gui.addCommand("BotonesPlasma_Mecanizar", _MecanizarPlasma())


class _DeshacerPlasma:
    def GetResources(self):
        return {"Pixmap": os.path.join(_DIR, "icons", "deshacer_plasma.svg"),
                "MenuText": "Deshacer mecanizado plasma",
                "ToolTip": "Quitar del documento lo que hizo Mecanizar plasma (trabajos CAM, G-code, "
                           "perforaciones y simulación) y, si quieres, borrar los programas creados"}

    def Activated(self):
        import BotonesPlasma_Mecanizar
        BotonesPlasma_Mecanizar.undo()

    def IsActive(self):
        return App.ActiveDocument is not None


Gui.addCommand("BotonesPlasma_Deshacer", _DeshacerPlasma())

try:
    from BotonesToolbar_Plasma import ensure_toolbar
    ensure_toolbar("CAMWorkbench", "Custom_BotonesPlasma", "Plasma", ["BotonesPlasma_Mecanizar", "BotonesPlasma_Deshacer"])
except Exception as _e:
    App.Console.PrintWarning("Botones plasma: no se pudo crear la barra (%s)\n" % _e)


# CAM has many toolbars: the Plasma one ended squeezed at the right edge and
# hidden behind ». Put it at the start of its own toolbar row in CAM.
def _place_plasma_toolbar():
    try:
        from PySide import QtWidgets, QtCore
        mw = Gui.getMainWindow()
        bars = [t for t in mw.findChildren(QtWidgets.QToolBar) if t.windowTitle() == "Plasma" and t.isVisible()]
        if not bars:
            return
        bar = bars[0]
        if bar.width() >= bar.sizeHint().width() - 2:
            return  # Already fully visible.
        mw.removeToolBar(bar)
        mw.addToolBarBreak(QtCore.Qt.TopToolBarArea)
        mw.addToolBar(QtCore.Qt.TopToolBarArea, bar)
        bar.show()
    except Exception as _e:
        App.Console.PrintLog("Botones plasma: barra no recolocada (%s)\n" % _e)


def _on_workbench(name):
    if name == "CAMWorkbench":
        from PySide import QtCore
        QtCore.QTimer.singleShot(300, _place_plasma_toolbar)


try:
    Gui.getMainWindow().workbenchActivated.connect(_on_workbench)
except Exception as _e:
    App.Console.PrintWarning("Botones plasma: no se pudo vigilar el banco de trabajo (%s)\n" % _e)
