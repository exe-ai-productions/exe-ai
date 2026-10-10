"""Logging."""

from __future__ import annotations

import json
import logging

import pytest

from app.protokoll import (
    JSONFormatter,
    KennungFilter,
    logging_einrichten,
    neue_request_id,
    request_id,
    speicher_mb,
)


def _zeile_bauen(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Meldung %s", args=("hier",), exc_info=None,
    )
    for name, wert in extra.items():
        setattr(record, name, wert)
    return record


def test_kennung_ist_kurz_und_eindeutig():
    kennungen = {neue_request_id() for _ in range(200)}
    assert len(kennungen) == 200
    assert all(len(k) == 12 for k in kennungen)


def test_speicher_wird_gemessen():
    """The silence side of the Windows branch below: on this system the
    number comes from `resource`, as before, and is more than nothing."""
    assert speicher_mb() > 0


# --- the Windows branch, with the platform pretended ------------------------
#
# ctypes answers only what it is told: without `restype` and `argtypes` the
# 64-bit pseudo-handle of the process is cut to a C int, the memory call
# fails quietly, and the counter stays 0. The fake kernel below behaves
# exactly like that — it fills the counter only when it has been told the
# types — so the test falls over without the fix.


class _FakeFunction:
    def __init__(self, kernel, name):
        self.kernel = kernel
        self.name = name
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        return self.kernel.call(self, args)


class _FakeKernel:
    """`ctypes.WinDLL("kernel32")` as a Mac can pretend it."""

    instances: list = []
    peak_bytes = 123 * 1024 * 1024
    refuse = False

    def __init__(self, name, use_last_error=False):
        self.name = name
        self.use_last_error = use_last_error
        self.GetCurrentProcess = _FakeFunction(self, "GetCurrentProcess")
        self.K32GetProcessMemoryInfo = _FakeFunction(self, "K32GetProcessMemoryInfo")
        _FakeKernel.instances.append(self)

    def call(self, function, args):
        from ctypes import wintypes

        if function.name == "GetCurrentProcess":
            # The real pseudo-handle: -1 as a 64-bit HANDLE. Read as a C int
            # it is still -1, but ctypes hands over a 32-bit value then —
            # a handle the memory call does not accept.
            return 2**64 - 1 if function.restype is wintypes.HANDLE else -1
        handle, counter, size = args
        if (
            function.restype is not wintypes.BOOL
            or function.argtypes is None
            or handle != 2**64 - 1
            or _FakeKernel.refuse
        ):
            return 0
        counter._obj.PeakWorkingSetSize = _FakeKernel.peak_bytes
        return 1


@pytest.fixture
def pretended_windows(monkeypatch):
    import ctypes

    from app import protokoll

    _FakeKernel.instances = []
    _FakeKernel.refuse = False
    monkeypatch.setattr(ctypes, "WinDLL", _FakeKernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(protokoll, "_memory_warned", False, raising=False)
    return protokoll


def test_on_windows_the_peak_working_set_comes_back_in_mb(pretended_windows):
    import ctypes
    from ctypes import wintypes

    assert pretended_windows._spitzenspeicher_windows() == 123.0
    kernel = _FakeKernel.instances[-1]
    assert kernel.use_last_error is True
    assert kernel.GetCurrentProcess.restype is wintypes.HANDLE
    handle, counter, size = kernel.K32GetProcessMemoryInfo.argtypes
    assert handle is wintypes.HANDLE
    assert size is wintypes.DWORD
    assert issubclass(counter, ctypes._Pointer)
    assert "PeakWorkingSetSize" in dict(counter._type_._fields_)
    assert kernel.K32GetProcessMemoryInfo.restype is wintypes.BOOL


def test_on_windows_a_refused_call_gives_zero_and_says_so_once(pretended_windows, caplog):
    _FakeKernel.refuse = True
    with caplog.at_level(logging.WARNING, logger="app.protokoll"):
        assert pretended_windows._spitzenspeicher_windows() == 0.0
        assert pretended_windows._spitzenspeicher_windows() == 0.0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "error 5" in warnings[0].getMessage()


def test_json_format_ist_eine_zeile_json():
    record = _zeile_bauen(request_id="abc123")
    ausgabe = JSONFormatter().format(record)
    assert "\n" not in ausgabe

    eintrag = json.loads(ausgabe)
    assert eintrag["meldung"] == "Meldung hier"
    assert eintrag["stufe"] == "INFO"
    assert eintrag["request_id"] == "abc123"


def test_zusatzfelder_landen_im_json():
    record = _zeile_bauen(request_id="x", endpunkt="mana", tokens_pro_sekunde=12.4)
    eintrag = json.loads(JSONFormatter().format(record))
    assert eintrag["endpunkt"] == "mana"
    assert eintrag["tokens_pro_sekunde"] == 12.4


def test_interne_felder_landen_nicht_im_json():
    eintrag = json.loads(JSONFormatter().format(_zeile_bauen(request_id="x")))
    assert "pathname" not in eintrag
    assert "levelno" not in eintrag


def test_ausnahme_wird_mitprotokolliert():
    try:
        raise ValueError("kaputt")
    except ValueError:
        import sys

        record = _zeile_bauen(request_id="x")
        record.exc_info = sys.exc_info()
        eintrag = json.loads(JSONFormatter().format(record))
    assert "ValueError: kaputt" in eintrag["ausnahme"]


def test_filter_setzt_die_kennung_aus_dem_kontext():
    marke = request_id.set("kontextkennung")
    try:
        record = _zeile_bauen()
        KennungFilter().filter(record)
        assert record.request_id == "kontextkennung"
    finally:
        request_id.reset(marke)


def test_ohne_kontext_steht_ein_strich_drin():
    record = _zeile_bauen()
    KennungFilter().filter(record)
    assert record.request_id == "-"


def test_logdatei_wird_angelegt_und_beschrieben(config, tmp_path):
    config.logging.file = "test.log"
    config.logging.format = "json"
    logging_einrichten(config)

    logging.getLogger("probe").info("Testeintrag", extra={"marke": 1})

    for handler in logging.getLogger().handlers:
        handler.flush()

    datei = config.logverzeichnis / "test.log"
    assert datei.exists()
    inhalt = datei.read_text(encoding="utf-8")
    assert "Testeintrag" in inhalt
    assert json.loads(inhalt.strip().splitlines()[-1])["marke"] == 1


def test_rotation_ist_eingerichtet(config):
    import logging.handlers

    config.logging.file = "rotation.log"
    config.logging.max_bytes = 1024
    config.logging.file_count = 2
    logging_einrichten(config)

    rotierend = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert rotierend, "There must be a rotating handler"
    assert rotierend[0].maxBytes == 1024
    assert rotierend[0].backupCount == 2


def test_ohne_dateiname_nur_konsole(config):
    import logging.handlers

    config.logging.file = ""
    logging_einrichten(config)
    assert not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        for h in logging.getLogger().handlers
    )


def test_wiederholtes_einrichten_haengt_nicht_doppelt_an(config):
    logging_einrichten(config)
    anzahl = len(logging.getLogger().handlers)
    logging_einrichten(config)
    assert len(logging.getLogger().handlers) == anzahl


# --- Middleware ----------------------------------------------------------


def test_kennung_steht_im_antwortkopf(client):
    antwort = client.get("/api/v1/meta")
    assert len(antwort.headers["x-request-id"]) == 12


def test_jede_anfrage_bekommt_eine_eigene_kennung(client):
    erste = client.get("/api/v1/meta").headers["x-request-id"]
    zweite = client.get("/api/v1/meta").headers["x-request-id"]
    assert erste != zweite


def test_dauer_wird_protokolliert(client, caplog):
    with caplog.at_level(logging.INFO, logger="zugriff"):
        client.get("/api/v1/meta")
    eintrag = next(e for e in caplog.records if e.name == "zugriff")
    assert eintrag.pfad == "/api/v1/meta"
    assert eintrag.status == 200
    assert eintrag.dauer_ms >= 0
    assert eintrag.speicher_mb > 0


def test_health_wird_nicht_mitprotokolliert(client, caplog):
    """Uptime Kuma polls every second — that would clutter up the log."""
    with caplog.at_level(logging.INFO, logger="zugriff"):
        client.get("/health")
    assert not [e for e in caplog.records if e.name == "zugriff"]


@pytest.mark.asyncio
async def test_middleware_laesst_den_abbruch_weiterhin_durch(laufender_server):
    """Logging must not wedge itself between the stream and the client.

    That is exactly what happens with a BaseHTTPMiddleware — which is why
    the logging is a pure ASGI component. This test pins that down.
    """
    import httpx

    from app.providers import MockProvider, mock_endpunkt

    app, adresse = laufender_server
    provider = MockProvider(
        mock_endpunkt("test"), haeppchen=[f"T{i} " for i in range(40)], verzoegerung=0.05
    )
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True

    kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=adresse, timeout=30, headers=kopfzeilen) as client:
        chat_id = (await client.post("/api/v1/chats", json={"title": "x"})).json()["id"]
        gelesen = []
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "los"},
        ) as antwort:
            assert "x-request-id" in antwort.headers
            async for zeile in antwort.aiter_lines():
                if not zeile.startswith("data:"):
                    continue
                ereignis = json.loads(zeile[5:].strip())
                gelesen.append(ereignis)
                if ereignis["typ"] == "start":
                    kennung = ereignis["generation_id"]
                elif ereignis["typ"] == "content" and len(gelesen) == 4:
                    await client.post("/api/v1/chat/stop", json={"generation_id": kennung})

    assert gelesen[-1]["abgebrochen"] is True
    assert provider.ausgegebene_haeppchen < 40
