"""Starting a child process without a console window of its own.

On Windows this program runs without a console. A console program it starts
is then given a new one by the system — a black window that stays for as
long as the child lives, and closing it ends the child. ``CREATE_NO_WINDOW``
starts the child without that window.

This is the one place that says so. Every start of a child process passes
``**no_window()``; the two that open a program for its own window — the
browser and the file manager — do not, because those windows are the point.

On macOS and Linux nothing is passed: a call there is what it was.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any


def no_window() -> dict[str, Any]:
    """The keyword arguments that keep a child's console window away, for
    ``subprocess.Popen``, ``subprocess.run`` and
    ``asyncio.create_subprocess_exec`` alike; empty off Windows."""
    if sys.platform != "win32":
        return {}
    # Read by its name: only the subprocess module of a Python on Windows
    # carries the constant.
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
