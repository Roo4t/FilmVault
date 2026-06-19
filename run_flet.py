"""FilmVault — Flet GUI launcher (no console window).
Usage: pythonw run_flet.py  or  double-click run.bat
"""
from __future__ import annotations

import os
import sys

# pythonw.exe has no console — redirect stdout/stderr to avoid crashes on print()
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def _single_instance() -> None:
    """Ensure only one FilmVault instance runs. Bring existing window to front."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    mutex_name = "FilmVault_SingleInstance_Mutex"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        # Another instance is running — bring it to front
        hwnd = user32.FindWindowW(None, "FilmVault")
        if hwnd:
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        sys.exit(0)


def _ensure_venw() -> None:
    """Re-launch under venv pythonw.exe (no-console) if not already running from it."""
    scripts_dir = os.path.join(os.path.dirname(__file__), ".venv", "Scripts")
    venv_pythonw = os.path.join(scripts_dir, "pythonw.exe")
    if os.path.abspath(sys.executable) != os.path.abspath(venv_pythonw):
        if os.path.exists(venv_pythonw):
            os.execv(venv_pythonw, [venv_pythonw] + sys.argv)


_single_instance()
_ensure_venw()

import flet as ft
from app.flet_gui import main

# ── Explicit scraper plugin imports for PyInstaller bundling ──
# (Dynamic imports via importlib are invisible to PyInstaller's analyser)
import app.scraper.plugins.javbus   # noqa: F401
import app.scraper.plugins.javdb    # noqa: F401
import app.scraper.plugins.avsox    # noqa: F401
import app.scraper.plugins.javlib   # noqa: F401

if __name__ == "__main__":
    ft.run(main, name="FilmVault")
