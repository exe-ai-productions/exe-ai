"""Whether the machine is set to dark or to light.

The look that follows the machine asks this. The answer comes from the
system itself: on macOS from the user defaults, which the system keeps
current, on Windows from an entry of the registry. No program is started and
nothing is waited for, so asking never holds anything up. A system that
keeps no word on it and a look that failed both answer with nothing.
"""

from __future__ import annotations

import sys

# The entry the user defaults of macOS carry for as long as the machine is
# set to dark. Set to light, the entry is missing. Asked of the system
# rather than read from the file the defaults are kept in, which the system
# writes when it likes.
_MAC_ENTRY = b"AppleInterfaceStyle"
_MAC_DARK = "Dark"
_OBJC_LIBRARY = "/usr/lib/libobjc.A.dylib"
_FOUNDATION_LIBRARY = "/System/Library/Frameworks/Foundation.framework/Foundation"

# Where Windows keeps it: a number that is 0 where programs are to be dark.
_WINDOWS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_WINDOWS_ENTRY = "AppsUseLightTheme"


def _mac_style() -> str | None:
    """The interface style the user defaults of this Mac carry — ``"Dark"``
    while it is set to dark, ``None`` while there is no entry. A system that
    cannot be asked raises."""
    # Imported here: only a Mac asks, and a Python without ctypes then
    # raises inside the question like any other failure of it.
    import ctypes

    objc = ctypes.CDLL(_OBJC_LIBRARY)
    ctypes.CDLL(_FOUNDATION_LIBRARY)
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    send_address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    if send_address is None:
        raise OSError("no objc_msgSend")

    def send(receiver: int | None, selector: bytes, *arguments: int | None) -> int | None:
        pointers = [ctypes.c_void_p] * (2 + len(arguments))
        call = ctypes.CFUNCTYPE(ctypes.c_void_p, *pointers)(send_address)
        answer: int | None = call(receiver, objc.sel_registerName(selector), *arguments)
        return answer

    def class_of(name: bytes) -> int:
        found = objc.objc_getClass(name)
        if not found:
            raise OSError(f"no class {name.decode()}")
        return int(found)

    # What the system hands out is released with the pool, which this thread
    # has none of by itself.
    pool = send(send(class_of(b"NSAutoreleasePool"), b"alloc"), b"init")
    try:
        key_bytes = ctypes.c_char_p(_MAC_ENTRY)
        key = send(
            class_of(b"NSString"),
            b"stringWithUTF8String:",
            ctypes.cast(key_bytes, ctypes.c_void_p).value,
        )
        defaults = send(class_of(b"NSUserDefaults"), b"standardUserDefaults")
        value = send(defaults, b"stringForKey:", key)
        if not value:
            return None
        text = send(value, b"UTF8String")
        return ctypes.string_at(text).decode("utf-8") if text else None
    finally:
        send(pool, b"release")


def _mac_is_dark() -> bool:
    """Whether the system says dark. A system that cannot be asked raises."""
    return _mac_style() == _MAC_DARK


def _windows_is_dark() -> bool:
    """Whether Windows says dark. A machine that keeps no such entry
    raises, and so does one that is no Windows."""
    if sys.platform != "win32":
        raise OSError("no registry on this system")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_KEY) as key:
        light, _ = winreg.QueryValueEx(key, _WINDOWS_ENTRY)
    return bool(light == 0)


def machine_is_dark() -> bool | None:
    """Whether the machine is set to dark, as it stands at this moment —
    ``None`` where the system keeps no word on it, or where looking failed."""
    try:
        if sys.platform == "darwin":
            return _mac_is_dark()
        if sys.platform == "win32":
            return _windows_is_dark()
    except Exception:  # noqa: BLE001
        # Whatever went wrong while looking: nothing is known.
        return None
    return None
