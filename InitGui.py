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

try:
    from BotonesToolbar_Plasma import ensure_toolbar
    ensure_toolbar("CAMWorkbench", "Custom_BotonesPlasma", "Plasma", ["BotonesPlasma_Mecanizar"])
except Exception as _e:
    App.Console.PrintWarning("Botones plasma: no se pudo crear la barra (%s)\n" % _e)
