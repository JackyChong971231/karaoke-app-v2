"""Open the TV page and the control page in their own Edge windows at boot.

With a second screen, the TV page fills it in kiosk mode and the control page opens maximized on the main
screen. With one screen, both open as ordinary app windows, control page on top, so the laptop is never
trapped behind a kiosk window. Each page has its own Edge profile under the data folder, so its flags apply
even if Edge is already open, and the control page remembers its singer name between parties.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
               r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")


@dataclass(frozen=True, slots=True)
class Screen:
    left: int
    top: int
    width: int
    height: int
    """Physical pixels."""
    scale: float
    """Windows display scaling, 1.0 for 100%."""
    primary: bool


def screens() -> list[Screen]:
    """Every connected screen, in physical pixels whatever this process's own DPI awareness is."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32, shcore = ctypes.windll.user32, ctypes.windll.shcore
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    found: list[Screen] = []

    def visit(monitor: int, _dc: int, _rect: object, _data: int) -> bool:
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        shcore.GetDpiForMonitor(ctypes.c_void_p(monitor), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        r = info.rcMonitor
        found.append(Screen(r.left, r.top, r.right - r.left, r.bottom - r.top,
                            (dpi_x.value or 96) / 96, bool(info.dwFlags & 1)))
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)(visit)
    per_monitor_aware_v2 = ctypes.c_void_p(-4)
    previous = user32.SetThreadDpiAwarenessContext(per_monitor_aware_v2)
    try:
        user32.EnumDisplayMonitors(None, None, callback, 0)
    finally:
        user32.SetThreadDpiAwarenessContext(previous)
    return found


def dip_center(s: Screen, main: Screen) -> tuple[int, int]:
    """The screen's center in the coordinates Edge's --window-position takes.

    Edge places windows in scaled pixels and lays each screen's scaled rectangle against the edge it shares with
    the main screen, so a screen beside the main one is measured from that shared edge, not from its physical
    offset. Only the center matters: the window is small and kiosk mode then fills whichever screen holds it.
    """
    w, h = s.width / s.scale, s.height / s.scale
    main_w, main_h = main.width / main.scale, main.height / main.scale
    if s.left >= main.left + main.width:
        x = main_w + w / 2
    elif s.left + s.width <= main.left:
        x = -w / 2
    else:
        x = (s.left - main.left) / main.scale + w / 2
    if s.top >= main.top + main.height:
        y = main_h + h / 2
    elif s.top + s.height <= main.top:
        y = -h / 2
    else:
        y = (s.top - main.top) / s.scale + h / 2
    return round(x), round(y)


def open_pages(port: int, data: Path) -> None:
    edge = shutil.which("msedge") or next((p for p in _EDGE_PATHS if Path(p).exists()), None)
    base = f"http://localhost:{port}"
    if edge is None:
        print(f"  Open {base}/tv on the TV screen and {base}/control on the laptop (Edge was not found).")
        return
    found = screens()
    main = next((s for s in found if s.primary), None)
    tv_screen = next((s for s in found if not s.primary), None)
    common = ["--no-first-run", "--no-default-browser-check"]
    tv = [edge, *common, "--autoplay-policy=no-user-gesture-required", f"--user-data-dir={data / 'edge-tv'}"]
    control = [edge, *common, f"--user-data-dir={data / 'edge-control'}", "--start-maximized"]
    if main is not None and tv_screen is not None:
        x, y = dip_center(tv_screen, main)
        tv += ["--kiosk", f"--window-position={x - 320},{y - 180}", "--window-size=640,360", f"{base}/tv"]
        mx, my = dip_center(main, main)
        control += [f"--window-position={mx - 320},{my - 180}"]
    else:
        tv += ["--start-maximized", f"--app={base}/tv"]
        print("  Only one screen found: the TV page opened as a window. Use its full-screen button.")
    subprocess.Popen(tv)
    subprocess.Popen([*control, f"--app={base}/control"])
