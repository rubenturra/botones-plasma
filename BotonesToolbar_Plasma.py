"""Crea (una sola vez) barras de herramientas propias en otros bancos de trabajo.

Usa las barras personalizadas de FreeCAD (Herramientas > Personalizar), así
el usuario puede moverlas, ocultarlas o quitarlas como cualquier otra.
"""
import FreeCAD as App

FLAGS = "User parameter:BaseApp/Preferences/Mod/BotonesPlasma"


def ensure_toolbar(workbench, group, title, commands):
    flags = App.ParamGet(FLAGS)
    key = "Toolbar_%s_%s" % (workbench, group)
    toolbars = App.ParamGet("User parameter:BaseApp/Workbench/%s/Toolbar" % workbench)
    if flags.GetBool(key, False) and not toolbars.HasGroup(group):
        return  # El usuario la quitó: no volver a crearla.
    bar = toolbars.GetGroup(group)
    bar.SetString("Name", title)
    bar.SetBool("Active", True)
    if any(not bar.GetString(c, "") for c in commands):
        # A new button: rewrite the bar so the buttons keep their order.
        for c in commands:
            bar.RemString(c)
        for c in commands:
            bar.SetString(c, "FreeCAD")
    flags.SetBool(key, True)
