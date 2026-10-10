"""Interface milestones B + C: native capability detection and feature switches."""

from __future__ import annotations

import pytest

from app.config import Capabilities, EndpointConfig
from app.discovery import (
    EndpunktZustand,
    _faehigkeiten_aus_props,
    _faehigkeiten_erkennen,
    werkzeuge_im_template,
)


# The stand-in id every call hands in: the log line names the endpoint, so
# there is no default and no nameless line.
ID = "x"


def _zustand(caps: dict, erkannt: dict | None = None) -> EndpunktZustand:
    endpunkt = EndpointConfig(
        id="x", base_url="http://127.0.0.1:9/v1", capabilities=Capabilities(**caps)
    )
    zustand = EndpunktZustand(endpunkt=endpunkt, provider=None)
    zustand.faehigkeiten_erkannt = erkannt
    return zustand


# --- B: Detection ----------------------------------------------------------


def test_werkzeuge_im_template():
    assert werkzeuge_im_template("{%- if tools %}…{% endif %}") is True
    assert werkzeuge_im_template("nichts dergleichen") is False
    assert werkzeuge_im_template("") is False


def test_template_caps_gewinnen_gegen_das_template():
    # The server's own word counts, in both directions — a template full of
    # tool syntax does not overrule an explicit no, and a bare template does
    # not overrule an explicit yes.
    nein = _faehigkeiten_aus_props(
        {
            "chat_template": "{%- if tools %}{{ tool_call }}{% endif %}",
            "chat_template_caps": {"supports_tool_calls": False},
        },
        ID,
    )
    assert nein["tool_calls"] is False
    ja = _faehigkeiten_aus_props(
        {"chat_template": "nichts", "chat_template_caps": {"supports_tool_calls": True}},
        ID,
    )
    assert ja["tool_calls"] is True


def test_ein_caps_das_kein_objekt_ist_zaehlt_nicht():
    """The same care as for `modalities`: a build that answers with something
    else where a table belongs has simply claimed nothing — and the template
    below still says what it says."""
    for unsinn in (["supports_tool_calls"], "none", 1):
        assert _faehigkeiten_aus_props({"chat_template_caps": unsinn}, ID) == {
            "thinking": {
                "supports_reasoning_effort": None,
                "vorlage_variablen": [],
                "effort_werte": None,
            },
            "tool_calls": False,
            "vision": False,
        }, unsinn


def test_ohne_caps_zaehlt_das_template():
    # Older servers serve no chat_template_caps — there the template remains.
    alt = _faehigkeiten_aus_props({"chat_template": "{%- if tools %}…{% endif %}"}, ID)
    assert alt["tool_calls"] is True
    assert _faehigkeiten_aus_props({}, ID)["tool_calls"] is False


async def test_props_anfrage_traegt_den_schluessel(monkeypatch):
    # Newer llama-server builds guard /props like every other route: without
    # the key the answer is 401 and the detection read as "can nothing".
    import httpx

    gesehen = {}

    def handler(request):
        gesehen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "chat_template_caps": {"supports_tool_calls": True},
                "modalities": {"vision": False},
            },
        )

    echter_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: echter_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setenv("EXE_TEST_SCHLUESSEL", "geheim")
    ergebnis = await _faehigkeiten_erkennen("http://127.0.0.1:9/v1", 1.0, "EXE_TEST_SCHLUESSEL", ID)
    assert gesehen["auth"] == "Bearer geheim"
    assert ergebnis == {
        "thinking": {
            "supports_reasoning_effort": None,
            "vorlage_variablen": [],
            "effort_werte": None,
        },
        "tool_calls": True,
        "vision": False,
    }


async def test_ohne_antwort_bleibt_die_frage_offen(monkeypatch):
    """A timeout is not an answer.

    It used to be turned into `{}` at the call site, and `{}` settles the
    question for as long as the endpoint stays reachable — so a server that
    was merely slow to start had its capabilities frozen at "can nothing"
    for the whole session, without a line in the log.
    """
    import httpx

    def handler(request):
        raise httpx.ConnectTimeout("zu langsam", request=request)

    echter_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: echter_client(transport=httpx.MockTransport(handler), **kw),
    )
    assert await _faehigkeiten_erkennen("http://127.0.0.1:9/v1", 1.0, None, ID) is None


async def test_ein_koerper_der_kein_objekt_ist_startet_weiter(monkeypatch, caplog):
    """Readable JSON that is not a table of what the server reveals — a list,
    a number, a bare word. The answer is "nothing learned", said out loud;
    the pass for every endpoint after this one goes on, and so does the
    program."""
    import httpx

    # Read ONCE, before the loop: after the first round the name is the
    # patch, and building the next stand-in out of that would chase itself.
    echter_client = httpx.AsyncClient
    for koerper in ("[]", "null", '"x"', "7"):
        def handler(request, koerper=koerper):
            return httpx.Response(200, content=koerper.encode())

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kw: echter_client(transport=httpx.MockTransport(handler), **kw),
        )
        caplog.clear()
        with caplog.at_level("INFO", logger="app.discovery"):
            assert await _faehigkeiten_erkennen(
                "http://127.0.0.1:9/v1", 1.0, None, ID
            ) == {}, koerper
        assert any("not an object" in satz.getMessage() or "body" in satz.getMessage()
                   for satz in caplog.records), koerper


async def test_eine_abweisung_ist_eine_antwort(monkeypatch):
    """An mlx server has no /props and says so with a 404. That is settled:
    knocking again every pass would beat on a door that is not there."""
    import httpx

    def handler(request):
        return httpx.Response(404, text="not found")

    echter_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: echter_client(transport=httpx.MockTransport(handler), **kw),
    )
    assert await _faehigkeiten_erkennen("http://127.0.0.1:9/v1", 1.0, None, ID) == {}


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_belegt_oder_bewacht_ist_keine_antwort(monkeypatch, status):
    """503 while a model file is still being read from disk is not "this
    server can nothing", and neither is a 401 issued before the key is in
    the environment. Both pass, and both are asked again — the discovery
    keeps what it learns for the life of a server, so a silence written down
    as a capability would follow that server until it stops."""
    import httpx

    def handler(request):
        return httpx.Response(status, text="nicht jetzt")

    echter_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: echter_client(transport=httpx.MockTransport(handler), **kw),
    )
    assert await _faehigkeiten_erkennen("http://127.0.0.1:9/v1", 1.0, None, ID) is None


async def test_eine_unlesbare_antwort_ist_auch_eine(monkeypatch):
    """It answered, and what it said is not JSON. Still an answer."""
    import httpx

    def handler(request):
        return httpx.Response(200, text="<html>kein json</html>")

    echter_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: echter_client(transport=httpx.MockTransport(handler), **kw),
    )
    assert await _faehigkeiten_erkennen("http://127.0.0.1:9/v1", 1.0, None, ID) == {}


def test_erkennung_fuellt_nur_die_luecken():
    # Config is silent, nothing detected -> everything off.
    leer = _zustand({})
    assert not leer.kann("vision")
    assert not leer.kann("tool_calls")
    # Config is silent, the server reveals it -> the detection counts.
    # Thinking answers in its own shape now: what the chat template gave
    # away, not a yes. A template carrying the switch word means a control
    # with two positions.
    voll = _zustand(
        {},
        {
            "vision": True,
            "tool_calls": True,
            "thinking": {
                "supports_reasoning_effort": None,
                "vorlage_variablen": ["enable_thinking"],
            },
        },
    )
    assert voll.kann("vision")
    assert voll.kann("tool_calls")
    assert voll.kann("thinking")


def test_config_gewinnt_immer_auch_ein_nein():
    # The Gemma rule: an explicit no beats any detection.
    gemma = _zustand(
        {"tool_calls": False, "vision": True},
        {
            "tool_calls": True,
            "vision": True,
            "thinking": {
                "supports_reasoning_effort": None,
                "vorlage_variablen": ["enable_thinking"],
            },
        },
    )
    assert not gemma.kann("tool_calls")
    assert gemma.kann("vision")
    # And an explicit yes applies even without detection.
    assert _zustand({"tool_calls": True}).kann("tool_calls")


def test_aufgeloeste_faehigkeiten_gehen_ans_frontend():
    zustand = _zustand(
        {},
        {
            "vision": True,
            "tool_calls": False,
            "thinking": {
                "supports_reasoning_effort": None,
                "vorlage_variablen": ["enable_thinking"],
            },
        },
    )
    eintrag = zustand.als_dict()
    caps = eintrag["capabilities"]
    assert caps["vision"] is True
    assert caps["tool_calls"] is False
    # A list of stages, not a yes. Two positions here, because that is all
    # the template's own word can offer.
    assert caps["thinking"] == ["off", "on"]
    assert eintrag["denkprofil"]["art"] == "schalter"


# --- C: Feature switches -----------------------------------------------------


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Schalter"}).json()


def test_document_upload_aus_sperrt_die_api(client):
    client.app.state.config.features.document_upload = False
    try:
        chat = _chat(client)
        antwort = client.post(
            f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt",
            content=b"egal",
        )
        assert antwort.status_code == 403
    finally:
        client.app.state.config.features.document_upload = True


def test_meta_traegt_die_schalter(client):
    daten = client.get("/api/v1/meta").json()
    assert daten["features"]["document_upload"] is True


# --- Vision: a table OR a list ---------------------------------------------


def test_vision_aus_der_tabelle():
    assert _faehigkeiten_aus_props({"modalities": {"vision": True}}, ID)["vision"] is True
    assert _faehigkeiten_aus_props({"modalities": {"vision": False}}, ID)["vision"] is False


def test_vision_aus_der_liste():
    """llama.cpp's own documentation has `modalities` as the LIST of what the
    server takes; its client code reads a table. Both say the same thing."""
    assert _faehigkeiten_aus_props({"modalities": ["text", "vision"]}, ID)["vision"] is True
    assert _faehigkeiten_aus_props({"modalities": ["vision"]}, ID)["vision"] is True
    assert _faehigkeiten_aus_props({"modalities": ["text"]}, ID)["vision"] is False
    assert _faehigkeiten_aus_props({"modalities": []}, ID)["vision"] is False


def test_eine_unbekannte_form_startet_weiter_und_sagt_es(caplog):
    """A shape this side cannot read is SAID and read as no vision; keeping
    the program from starting would be the worst of the three answers.

    Every form gets its own line — one assertion over the whole loop would
    stay green after a change that lets all but one of them through quietly.
    """
    for unsinn in (123, 4.5, "vision", True):
        caplog.clear()
        with caplog.at_level("INFO", logger="app.discovery"):
            caps = _faehigkeiten_aus_props({"modalities": unsinn}, ID)
        assert caps["vision"] is False, unsinn
        assert any("modalities" in satz.getMessage() for satz in caplog.records), (
            f"the form {unsinn!r} is not in the log"
        )


def test_ein_wort_als_schalter_zaehlt_nicht_als_ja(caplog):
    """``"false"``, ``"no"``, ``"0"`` are strings a server that serialises its
    answer can produce. Reading one of them as a yes would open the
    attachment surface for a server that cannot see — and the model would
    then invent what it cannot see. None of them is a plain boolean, so each
    is said out loud instead."""
    for wort in ("false", "no", "0", "off", 1):
        caplog.clear()
        with caplog.at_level("INFO", logger="app.discovery"):
            caps = _faehigkeiten_aus_props({"modalities": {"vision": wort}}, ID)
        assert caps["vision"] is False, wort
        assert any("'vision'" in satz.getMessage() for satz in caplog.records), wort
    # And a real yes stays a real yes — without a line.
    caplog.clear()
    with caplog.at_level("INFO", logger="app.discovery"):
        assert _faehigkeiten_aus_props({"modalities": {"vision": True}}, ID)["vision"] is True
    assert not caplog.records


def test_ohne_modalitaeten_bleibt_es_bei_kein_bild(caplog):
    """Saying nothing is not a "no" either — and it is not worth a line.

    The silence is measured, not promised: a melder that speaks about every
    server on every pass is noise of its own.
    """
    leere = ({}, {"modalities": None}, {"modalities": ""}, {"modalities": {"a": [1]}})
    for fehlt in leere:
        caplog.clear()
        with caplog.at_level("INFO", logger="app.discovery"):
            assert _faehigkeiten_aus_props(fehlt, ID)["vision"] is False, fehlt
        assert not caplog.records, (fehlt, [satz.getMessage() for satz in caplog.records])
