"""A file of gigabytes that costs no disk.

Some tests need the size of a model file and none of its content. Growing
an empty file gives that for free on a POSIX system, where what was never
written is a hole. On Windows growing a file writes every byte of it, so
the helper marks the file sparse there first. This is the check that it
holds on the system the test runs on: the size is what was asked for, and
the disk holds next to nothing of it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tests.conftest import sized_file

GIB = 1024**3


def _on_disk(path: Path) -> int:
    """How many bytes of the file the disk really holds."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetCompressedFileSizeW.restype = wintypes.DWORD
        high = wintypes.DWORD(0)
        ctypes.set_last_error(0)
        low = kernel32.GetCompressedFileSizeW(str(path), ctypes.byref(high))
        if low == 0xFFFFFFFF and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        return (high.value << 32) + low
    return path.stat().st_blocks * 512


def test_a_sized_file_reports_its_size_and_holds_next_to_no_disk(tmp_path: Path):
    path = sized_file(tmp_path / "model.gguf", 3 * GIB)
    assert path.stat().st_size == 3 * GIB
    assert _on_disk(path) < 3 * GIB // 1000


def test_silence_probe_the_measure_sees_a_file_that_is_really_written(tmp_path: Path):
    """The other side of the check above: bytes that were written are bytes
    the measure counts. Without this, a measure that always says nought
    would let every file through. Random bytes, because a file system that
    compresses would keep next to nothing of a single repeated one."""
    path = tmp_path / "written.bin"
    path.write_bytes(os.urandom(4 * 1024 * 1024))
    assert _on_disk(path) >= 4 * 1024 * 1024


def test_a_sized_file_of_no_bytes_is_empty(tmp_path: Path):
    assert sized_file(tmp_path / "empty.gguf", 0).stat().st_size == 0
