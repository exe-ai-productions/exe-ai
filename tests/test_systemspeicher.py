"""The machine memory readout: a plausible number on this machine, and the
wired part read from a fixed ``vm_stat`` report together with the sum."""

import os
import platform
import subprocess
import sys

from app import systemspeicher
from app.systemspeicher import belegt_gb, used_and_wired_gb, gesamt_gb, wired_limit_gb

# A report as macOS prints it: 16 KiB pages, 1000 of them wired, 3000 active,
# 500 held by the compressor, plenty free that no figure may count.
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               90000.
Pages active:                              3000.
Pages inactive:                            2000.
Pages speculative:                          100.
Pages wired down:                          1000.
Pages occupied by compressor:               500.
"""


def _on_mac(monkeypatch, output=VM_STAT, returncode=0):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "sysconf", lambda name: 16384, raising=False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=output, stderr=""),
    )


def test_liefert_plausible_zahl():
    gb = gesamt_gb()
    assert gb is not None
    assert 1 <= gb <= 4096


def test_wired_is_the_wired_down_line_alone(monkeypatch):
    _on_mac(monkeypatch)
    # 1000 pages of 16 KiB, in GiB with one decimal.
    assert used_and_wired_gb()[1] == round(1000 * 16384 / 1024**3, 1)


def test_the_sum_stays_active_wired_and_compressor_and_comes_from_the_same_report(monkeypatch):
    _on_mac(monkeypatch)
    used, wired = used_and_wired_gb()
    assert used == round((3000 + 1000 + 500) * 16384 / 1024**3, 1)
    assert used == belegt_gb()
    assert used > wired


def test_one_report_is_read_for_both_figures(monkeypatch):
    _on_mac(monkeypatch)
    runs = []
    real = subprocess.run

    def counting(*args, **kwargs):
        runs.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counting)
    used_and_wired_gb()
    assert len(runs) == 1


def test_without_a_value_there_is_none_and_no_guessed_figure(monkeypatch):
    # No wired line, a failing tool, and a platform without the figure.
    _on_mac(monkeypatch, output="Pages free: 5.\n")
    assert used_and_wired_gb() == (None, None)
    _on_mac(monkeypatch, returncode=1)
    assert used_and_wired_gb() == (None, None)
    monkeypatch.setattr(sys, "platform", "linux")
    assert used_and_wired_gb()[1] is None
    monkeypatch.setattr(sys, "platform", "darwin")

    def failing(*args, **kwargs):
        raise OSError()

    monkeypatch.setattr(subprocess, "run", failing)
    assert used_and_wired_gb() == (None, None)


def _apple_silicon(monkeypatch, working_set=lambda: 59392 * 1024**2):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(systemspeicher, "_limit_cache", None)
    monkeypatch.setattr(systemspeicher, "_metal_working_set_bytes", working_set)


def test_the_wired_limit_is_the_recommended_working_set_of_the_graphics_device(monkeypatch):
    # 59392 MiB, as the device reports it where the limit is set to that.
    _apple_silicon(monkeypatch)
    assert wired_limit_gb() == 58.0


def test_the_wired_limit_is_none_off_the_mac_and_where_it_cannot_be_read(monkeypatch):
    _apple_silicon(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    assert wired_limit_gb() is None
    _apple_silicon(monkeypatch, working_set=lambda: None)
    assert wired_limit_gb() is None

    def broken():
        raise OSError("no such framework")

    _apple_silicon(monkeypatch, working_set=broken)
    assert wired_limit_gb() is None


def test_an_intel_mac_has_no_such_limit(monkeypatch):
    # There the device reports its own video memory, which limits nothing about the wired figure.
    _apple_silicon(monkeypatch, working_set=lambda: 4 * 1024**3)
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert wired_limit_gb() is None


def test_the_limit_is_read_once_in_a_while_not_at_every_poll(monkeypatch):
    calls = []

    def working_set():
        calls.append(1)
        return 59392 * 1024**2

    _apple_silicon(monkeypatch, working_set=working_set)
    assert wired_limit_gb() == 58.0 and wired_limit_gb() == 58.0
    assert len(calls) == 1
    # Later than the age it may have, it is read again.
    monkeypatch.setattr(systemspeicher, "_LIMIT_MAX_AGE", -1.0)
    wired_limit_gb()
    assert len(calls) == 2
