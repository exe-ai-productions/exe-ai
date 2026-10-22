"""How much memory this machine has, in round gigabytes.

On Apple Silicon the graphics card and the processor share one pool, so the
machine total IS the honest ceiling for a model plan — there is no separate
VRAM number that would say more. Reported once, as a fact about the machine,
next to the estimate of what a planned server start will take.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import threading
import time

from app.no_console import no_window


def gesamt_gb() -> float | None:
    """The machine's physical memory in GiB, or None where it cannot be read.

    Binary gigabytes on purpose: the number on the spec sheet of every
    machine is counted that way, and a readout that says 68.7 on a
    "64 GB" machine reads as a bug, not as precision."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            lage = _Status()
            lage.dwLength = ctypes.sizeof(_Status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(lage)):
                return None
            rohe = int(lage.ullTotalPhys)
        else:
            rohe = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return None
    return round(rohe / 1024**3, 1)


# The lines of a ``vm_stat`` report that count as memory in use.
_COUNTED_PAGES = ("active", "wired down", "occupied by compressor")


def belegt_gb() -> float | None:
    """How much of that pool is in use right now, in GiB, or None.

    On macOS the sum of active, wired and compressor pages from ``vm_stat``
    — the same figure Activity Monitor calls "Memory Used". Free plus
    inactive pages are NOT counted: the file cache empties itself under
    pressure, and a readout that calls a warm cache "full" would cry wolf
    on every healthy machine. On Windows the total minus what the kernel
    reports as available, which follows the same idea.
    """
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            lage = _Status()
            lage.dwLength = ctypes.sizeof(_Status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(lage)):
                return None
            rohe = int(lage.ullTotalPhys) - int(lage.ullAvailPhys)
        elif sys.platform == "darwin":
            pages = _vm_stat_pages()
            seiten = sum(pages.get(name, 0) for name in _COUNTED_PAGES) if pages else 0
            if not seiten:
                return None
            rohe = seiten * os.sysconf("SC_PAGE_SIZE")
        else:
            return None
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None
    return round(rohe / 1024**3, 1)


def _vm_stat_pages() -> dict[str, int] | None:
    """The page counts of one ``vm_stat`` report, by the name on each line.

    The lines read "Pages wired down:    123456." — the key is the text between
    "Pages " and the colon, the number is the last thing on the line. None
    where the tool cannot be run or says no."""
    run = subprocess.run(
        ["vm_stat"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        **no_window(),
    )
    if run.returncode != 0:
        return None
    pages: dict[str, int] = {}
    for line in run.stdout.splitlines():
        found = re.match(r"Pages ([a-z ]+):\s+(\d+)\.?$", line.strip())
        if found:
            pages[found.group(1)] = int(found.group(2))
    return pages


def used_and_wired_gb() -> tuple[float | None, float | None]:
    """The sum ``belegt_gb`` gives and the wired part alone, from ONE report.

    The wired part is the memory the system keeps resident and cannot take
    away, the part a model's weights live in once loaded — which is why the
    page of the local models shows it. macOS only: where the platform has no
    such figure the second value is None — a guess would be worse than a
    dash. Reading both from one report keeps them consistent (the wired part
    is part of the sum) and costs one subprocess, not two."""
    if sys.platform != "darwin":
        return belegt_gb(), None
    try:
        pages = _vm_stat_pages()
        if not pages:
            return None, None
        page_size = os.sysconf("SC_PAGE_SIZE")
        used = sum(pages.get(name, 0) for name in _COUNTED_PAGES)
        wired = pages.get("wired down", 0)
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None, None
    return (
        round(used * page_size / 1024**3, 1) if used else None,
        round(wired * page_size / 1024**3, 1) if wired else None,
    )


def _metal_working_set_bytes() -> int | None:
    """The working set the system recommends for the default Metal device, in bytes.

    Read through the system's own Metal framework, so no extra dependency is
    needed: the device is created with ``MTLCreateSystemDefaultDevice`` and
    asked for ``recommendedMaxWorkingSetSize``. None where the framework or
    the device is not there."""
    import ctypes
    import ctypes.util

    objc_path = ctypes.util.find_library("objc")
    if not objc_path:
        return None
    metal = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
    objc = ctypes.CDLL(objc_path)
    metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.objc_msgSend.restype = ctypes.c_uint64
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    device = metal.MTLCreateSystemDefaultDevice()
    if not device:
        return None
    try:
        size = objc.objc_msgSend(device, objc.sel_registerName(b"recommendedMaxWorkingSetSize"))
    finally:
        # The call above handed over a retained device; give it back.
        objc.objc_msgSend(device, objc.sel_registerName(b"release"))
    return int(size) or None


# The limit is read again after this many seconds: it changes only when the
# setting is changed, and the memory readout is asked for every few seconds.
_LIMIT_MAX_AGE = 30.0
# A read that gave nothing is tried again sooner: it may have been the start of
# the service, not the machine.
_LIMIT_FAILED_MAX_AGE = 5.0
_limit_cache: tuple[float, float | None] | None = None
_limit_lock = threading.Lock()


def wired_limit_gb() -> float | None:
    """The most memory macOS lets the graphics side keep wired, in GiB, or None.

    This is the limit the wired figure is measured against: without a setting
    of ``iogpu.wired_limit_mb`` the system's own recommendation applies, and
    a setting is reported by the same value, so one reading covers both. It is
    below the machine's whole memory, so a bar measured against the whole
    would not be full when the limit already holds. None off the Mac or where
    the value cannot be read — then nothing is guessed. Only on Apple Silicon,
    where the graphics side shares the one pool: on an Intel Mac the device
    reports its own video memory, which is no limit for the wired figure."""
    global _limit_cache
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return None
    with _limit_lock:
        now = time.monotonic()
        if _limit_cache is not None:
            age = now - _limit_cache[0]
            if age < (_LIMIT_MAX_AGE if _limit_cache[1] is not None else _LIMIT_FAILED_MAX_AGE):
                return _limit_cache[1]
        try:
            size = _metal_working_set_bytes()
        except (OSError, ValueError, AttributeError):
            size = None
        limit = round(size / 1024**3, 1) if size else None
        _limit_cache = (now, limit)
        return limit
