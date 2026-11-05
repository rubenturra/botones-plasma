"""CPU budget for background work (CAM worker processes, PDF reports).

* Automatic core count: every core the process may use, minus one for FreeCAD.
* LinuxCNC first: when LinuxCNC runs on the same PC (Linux), two cores are
  left free for it and our processes start at the lowest priority, whatever
  number of cores is selected.
Pure Python, no FreeCAD imports (unit testable).
"""
import os
import time

LINUXCNC_PROCESSES = ("linuxcnc", "linuxcncsvr", "milltask", "rtapi_app", "qtplasmac")
_cache = {"t": 0.0, "value": False}


def available_cores():
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except Exception:
        pass
    return max(1, os.cpu_count() or 1)


def linuxcnc_running(max_age=5.0):
    """True when a LinuxCNC process runs on this PC (checked at most every 5 s)."""
    now = time.time()
    if now - _cache["t"] < max_age:
        return _cache["value"]
    found = False
    if os.path.isdir("/proc"):
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    with open("/proc/%s/comm" % pid) as handle:
                        name = handle.read().strip().lower()
                except OSError:
                    continue
                if name in LINUXCNC_PROCESSES or name.startswith("qtplasmac"):
                    found = True
                    break
        except OSError:
            found = False
    _cache.update(t=now, value=found)
    return found


def core_budget():
    """Cores our background work may use in total."""
    cores = available_cores()
    reserve = 2 if linuxcnc_running() else 1
    return max(1, cores - reserve)


def threads_for(selected, engines=1):
    """Threads per engine. selected: an int, or 0/None/'auto' for automatic.
    A manual value is still capped when LinuxCNC is running."""
    budget = core_budget()
    try:
        value = int(selected)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        # Automatic: the budget is shared by the engines running together.
        return max(1, budget // max(1, int(engines)))
    if linuxcnc_running():
        value = min(value, budget)
    return max(1, value)


def low_priority(command):
    """(command, Popen keyword arguments) that start a process below FreeCAD
    (and far below LinuxCNC when it runs), so the machine control is never
    slowed down. On Linux/macOS the command is run through "nice"."""
    import shutil
    strong = linuxcnc_running()
    command = list(command)
    if os.name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        priority = 0x00000040 if strong else 0x00004000   # IDLE / BELOW_NORMAL
        return command, {"creationflags": CREATE_NO_WINDOW | priority}
    nice = shutil.which("nice")
    if nice:
        command = [nice, "-n", "19" if strong else "10"] + command
    return command, {}


def freecad_cmd():
    """FreeCAD without window (FreeCADCmd) on Windows, Linux (packages, AppImage,
    snap, flatpak) and macOS; None when not found."""
    import shutil
    import sys
    names = ("FreeCADCmd.exe", "freecadcmd.exe", "FreeCADCmd", "freecadcmd")
    folders = []
    try:
        import FreeCAD as App
        folders.append(os.path.join(App.getHomePath(), "bin"))
        folders.append(os.path.join(App.getHomePath(), "MacOS"))
    except Exception:
        pass
    folders.append(os.path.dirname(os.path.abspath(sys.executable)))
    for folder in folders:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path) and (os.name == "nt" or os.access(path, os.X_OK)):
                return path
    for name in ("FreeCADCmd", "freecadcmd", "freecad.cmd"):
        path = shutil.which(name)
        if path:
            return path
    return None
