# Botones plasma: herramientas específicas del corte por plasma (FreeCAD CAM + QtPlasmaC).
# FreeCAD ejecuta este archivo con espacios de nombres separados: todo lo que
# usan los comandos se importa dentro de cada método.
import FreeCAD as App
import FreeCADGui as Gui


class _MecanizarPlasma:
    def GetResources(self):
        import BotonesPlasma_Gui
        return {"Pixmap": BotonesPlasma_Gui.icon("mecanizar_plasma.svg"),
                "MenuText": "Mecanizar plasma",
                "ToolTip": "Mecanizar para plasma las piezas seleccionadas o el resultado del anidado: "
                           "herramienta, postprocesador, QtPlasmaC, entradas/salidas, retal y simulación"}

    def Activated(self):
        import BotonesPlasma_Mecanizar
        BotonesPlasma_Mecanizar.main()

    def IsActive(self):
        import FreeCAD
        return FreeCAD.ActiveDocument is not None


class _DeshacerPlasma:
    def GetResources(self):
        import BotonesPlasma_Gui
        return {"Pixmap": BotonesPlasma_Gui.icon("deshacer_plasma.svg"),
                "MenuText": "Deshacer mecanizado plasma",
                "ToolTip": "Quitar del documento lo que hizo Mecanizar plasma (trabajos CAM, G-code, "
                           "perforaciones y simulación) y, si quieres, borrar los programas creados"}

    def Activated(self):
        import BotonesPlasma_Mecanizar
        BotonesPlasma_Mecanizar.undo()

    def IsActive(self):
        import FreeCAD
        return FreeCAD.ActiveDocument is not None


Gui.addCommand("BotonesPlasma_Mecanizar", _MecanizarPlasma())
Gui.addCommand("BotonesPlasma_Deshacer", _DeshacerPlasma())

try:
    from BotonesToolbar_Plasma import ensure_toolbar
    ensure_toolbar("CAMWorkbench", "Custom_BotonesPlasma", "Plasma",
                   ["BotonesPlasma_Mecanizar", "BotonesPlasma_Deshacer"])
except Exception as _e:
    App.Console.PrintWarning("Botones plasma: no se pudo crear la barra (%s)\n" % _e)

try:
    import BotonesPlasma_Gui
    BotonesPlasma_Gui.watch_workbenches()
except Exception as _e:
    App.Console.PrintWarning("Botones plasma: %s\n" % _e)
