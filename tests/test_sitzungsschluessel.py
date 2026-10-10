"""The session key guards every /api/v1 call, reading included —
measured against the running service:
``GET /api/v1/chats`` answered 200 with no login, no token, nothing at
all. ``app/herkunftswaechter.py`` does not help here; it turns away a
foreign web PAGE, not a foreign PROCESS calling the API directly.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import sprachwahl
from app.i18n import t
from app.main import app_erstellen


def test_ohne_schluessel_wird_ein_lesender_aufruf_abgewiesen(client):
    """The concrete case the auftrag measured: a plain GET, no key at all."""
    client.headers.pop("X-Sitzungsschluessel", None)
    antwort = client.get("/api/v1/chats")
    assert antwort.status_code == 401


def test_ohne_schluessel_wird_ein_schreibender_aufruf_abgewiesen(client):
    client.headers.pop("X-Sitzungsschluessel", None)
    antwort = client.post("/api/v1/chats", json={"title": "x"})
    assert antwort.status_code == 401


def test_mit_falschem_schluessel_wird_abgewiesen(client):
    client.headers["X-Sitzungsschluessel"] = "irgendwas-falsches"
    antwort = client.get("/api/v1/chats")
    assert antwort.status_code == 401


def test_mit_dem_echten_schluessel_kommt_der_aufruf_durch(client):
    """The header the frontend actually sends (via the client fixture)
    — the ordinary path, not the exception."""
    antwort = client.get("/api/v1/chats")
    assert antwort.status_code == 200


def test_ohne_kopf_faellt_ein_gewoehnlicher_weg_jetzt_um(client):
    """The query parameter used to stand in for the
    header on every route — now only on the five a browser truly cannot
    attach a header to (below)."""
    schluessel = client.headers.pop("X-Sitzungsschluessel")
    antwort = client.get(f"/api/v1/chats?schluessel={schluessel}")
    assert antwort.status_code == 401


def test_the_allowed_routes_still_take_the_query_key(client):
    """Three of the five (app/sitzungsschluessel.py:ABFRAGE_ERLAUBT) answer
    directly: an <img src> and a plain <a href> cannot attach a custom
    header. A 404 for a made-up id is fine here — the point is that the
    guard itself lets the request through, not what the route answers.

    The other two are the SSE routes (an EventSource cannot attach a header
    either) — calling them for real would open a live stream and hang the
    test, so :func:`test_the_query_key_is_allowed_on_exactly_these_routes` checks
    those against the same function this dispatch uses, not over HTTP."""
    schluessel = client.headers.pop("X-Sitzungsschluessel")
    wege = [
        "/api/v1/agentendock/irgendeine-kennung",
        "/api/v1/images/irgendein-bild.png",
        "/api/v1/documents/irgendein-dokument/file",
    ]
    for weg in wege:
        antwort = client.get(f"{weg}?schluessel={schluessel}")
        assert antwort.status_code != 401, weg


def test_the_query_key_is_allowed_on_exactly_these_routes():
    from app.sitzungsschluessel import _abfrageparameter_erlaubt

    erlaubt = [
        "/api/v1/agentendock/irgendeine-kennung",
        "/api/v1/laeufe/irgendein-chat/stream",
        "/api/v1/events/stream",
        "/api/v1/images/irgendein-bild.png",
        "/api/v1/documents/irgendein-dokument/file",
    ]
    for weg in erlaubt:
        assert _abfrageparameter_erlaubt(weg), weg

    nicht_erlaubt = [
        "/api/v1/chats",
        "/api/v1/agentendock/alle",
        "/api/v1/laeufe/irgendein-chat",
        "/api/v1/laeufe/irgendein-chat/stream/mehr",
        "/api/v1/agentendock/",  # a trailing slash is not a value
        "/api/v1/images/",
        "/api/v1/documents/irgendein-dokument",
        "/api/v1/documents//file",
    ]
    for weg in nicht_erlaubt:
        assert not _abfrageparameter_erlaubt(weg), weg


def test_die_ausnahmen_passen_noch_zu_den_registrierten_wegen(client):
    """``KEIN_WERT`` is a hand-maintained exclusion list, not derived from
    the real routes — this guard runs ahead of FastAPI's own routing and
    sees only the raw path. Pinned here against the actually registered GET
    routes under the same two prefixes, so a later literal route added
    there (besides "alle") does not silently inherit the fallback without
    someone noticing this test fail."""
    from app.sitzungsschluessel import KEIN_WERT

    gefunden: dict[str, set[str]] = {muster: set() for muster in KEIN_WERT}
    for weg in client.app.routes:
        pfad = getattr(weg, "path", "")
        if "GET" not in getattr(weg, "methods", set()):
            continue
        for muster in KEIN_WERT:
            praefix = muster.removesuffix("{}")
            if not pfad.startswith(praefix):
                continue
            rest = pfad[len(praefix):]
            if rest and "/" not in rest and "{" not in rest:
                gefunden[muster].add(rest)

    assert gefunden == KEIN_WERT


def test_ein_erlaubter_weg_nimmt_weiterhin_den_kopf(client):
    """The parameter is an addition to the five, not a replacement of the
    header there."""
    antwort = client.get("/api/v1/images/irgendein-bild.png")
    assert antwort.status_code != 401


def test_schreiben_auf_einem_erlaubten_pfad_nimmt_den_abfrageparameter_nicht(client):
    """The allow-list is GET-only: the very same path that
    takes the parameter on GET still needs the header on DELETE."""
    schluessel = client.headers.pop("X-Sitzungsschluessel")
    antwort = client.delete(f"/api/v1/agentendock/irgendeine-kennung?schluessel={schluessel}")
    assert antwort.status_code == 401


def test_jeder_start_erzeugt_einen_anderen_schluessel(config):
    with TestClient(app_erstellen(config)) as erster:
        with TestClient(app_erstellen(config)) as zweiter:
            assert (
                erster.app.state.sitzungsschluessel
                != zweiter.app.state.sitzungsschluessel
            )


def test_der_schluessel_landet_nirgends_auf_der_platte(config, tmp_path):
    """Never written to disk — a key that outlives the process would defeat
    minting a new one on every start."""
    with TestClient(app_erstellen(config)) as testclient:
        schluessel = testclient.app.state.sitzungsschluessel
    for datei in tmp_path.rglob("*"):
        if datei.is_file():
            assert schluessel not in datei.read_text(encoding="utf-8", errors="ignore")


def test_die_eigene_oberflaeche_traegt_den_schluessel_eingebettet(client):
    """The frontend gets it without the user noticing
    anything — stitched into the page it is served."""
    client.headers.pop("X-Sitzungsschluessel", None)
    antwort = client.get("/app/")
    assert antwort.status_code == 200
    schluessel = client.app.state.sitzungsschluessel
    assert f"window.__SITZUNGSSCHLUESSEL__={json.dumps(schluessel)}" in antwort.text


def test_die_oauth_rueckkehr_bleibt_ohne_schluessel_erreichbar(client):
    """The one legitimate exception: the browser lands here straight from
    the OAuth provider's own redirect, which knows nothing of this
    session's key and cannot be made to send it. A missing/wrong state is
    its own, separate rejection — not a 401 from this guard."""
    client.headers.pop("X-Sitzungsschluessel", None)
    antwort = client.get("/api/v1/tools/oauth/callback?state=phantom&code=x")
    assert antwort.status_code != 401


def test_gesundheitscheck_und_oberflaeche_brauchen_keinen_schluessel(client):
    """Monitoring/systemd and the served frontend shell carry no per-run
    data — only /api/v1 needs the key."""
    client.headers.pop("X-Sitzungsschluessel", None)
    assert client.get("/health").status_code == 200
    assert client.get("/app/").status_code == 200


def test_ein_abgewiesener_aufruf_ohne_schluessel_nennt_missing_key(client, caplog):
    client.headers.pop("X-Sitzungsschluessel", None)
    with caplog.at_level("WARNING", logger="app.sitzungsschluessel"):
        client.get("/api/v1/chats")
    (eintrag,) = caplog.records
    assert "/api/v1/chats" in eintrag.message
    assert "missing key" in eintrag.message
    assert "wrong key" not in eintrag.message


def test_ein_abgewiesener_aufruf_mit_falschem_schluessel_nennt_wrong_key(client, caplog):
    client.headers["X-Sitzungsschluessel"] = "irgendwas-falsches"
    with caplog.at_level("WARNING", logger="app.sitzungsschluessel"):
        client.get("/api/v1/chats")
    (eintrag,) = caplog.records
    assert "/api/v1/chats" in eintrag.message
    assert "wrong key" in eintrag.message
    assert "missing key" not in eintrag.message


def test_ein_gueltiger_aufruf_hinterlaesst_keine_zusaetzliche_zeile(client, caplog):
    with caplog.at_level("WARNING", logger="app.sitzungsschluessel"):
        antwort = client.get("/api/v1/chats")
    assert antwort.status_code == 200
    assert caplog.records == []


def test_der_vergleich_laeuft_konstant_ueber_compare_digest():
    """The accept/reject cases above cannot tell ``!=`` and
    ``secrets.compare_digest`` apart — both return the same true/false, only
    the timing differs, and that is exactly the property a plain assertion
    on the response cannot see. Pinned in the source instead:
    a present-but-wrong key must go through ``compare_digest``, never a bare
    ``!=`` that returns at its first mismatched character."""
    import inspect

    import app.sitzungsschluessel as modul

    quelle = inspect.getsource(modul.Sitzungswaechter.dispatch)
    assert "secrets.compare_digest(" in quelle
    assert "!= request.app.state.sitzungsschluessel" not in quelle


def test_the_401_refusal_answers_in_the_language_of_the_request(client):
    """The guard's one sentence is built like every other refusal of the
    service: from the catalogue, in the language the request asks for. An
    English window reads the rejection of a stale key in English."""
    client.headers.pop("X-Sitzungsschluessel", None)
    response = client.get("/api/v1/chats", headers={"X-Ui-Language": "en"})
    assert response.status_code == 401
    assert response.json()["detail"] == t("fehler.sitzungsschluessel", "en")
    # The silence probe: a wrong language argument stays invisible to the
    # English side alone — ``t`` falls back to English for anything unknown.
    assert response.json()["detail"] != t("fehler.sitzungsschluessel", "de")


def test_the_401_refusal_stays_german_for_a_german_request(client):
    client.headers.pop("X-Sitzungsschluessel", None)
    response = client.get("/api/v1/chats", headers={"X-Ui-Language": "de"})
    assert response.status_code == 401
    assert response.json()["detail"] == t("fehler.sitzungsschluessel", "de")


def test_a_wrong_key_is_answered_like_a_missing_one(client):
    """Both rejections carry the same sentence — the log line is where the
    two are told apart, and it stays as it was."""
    client.headers["X-Sitzungsschluessel"] = "irgendwas-falsches"
    response = client.get("/api/v1/chats", headers={"X-Ui-Language": "en"})
    assert response.status_code == 401
    assert response.json()["detail"] == t("fehler.sitzungsschluessel", "en")


def test_the_page_carries_the_boot_texts_in_the_chosen_language(client):
    """Two sentences have to be readable before the catalogue is there: the
    message of a start that failed and the name of a refusal without a
    reason. The served page carries them, in the language the service knows
    for the interface (app/main.py).

    Pinned with the placeholder still in them: the page fills `{status}` and
    `{error}` in (frontend/src/lib/api.js), so a sentence that lost its
    placeholder would show a numberless "Error" — and a comparison that only
    asked for the sentence would not see it."""
    client.app.state.repositories.einstellungen.setzen(
        "global", sprachwahl.SCHLUESSEL, {"sprache": "en"}
    )
    client.headers.pop("X-Sitzungsschluessel", None)
    response = client.get("/app/")
    assert response.status_code == 200
    for key in ("fehler.status", "fehler.dienst_antwortet_nicht"):
        assert json.dumps(t(key, "en"), ensure_ascii=False) in response.text
        assert t(key, "de") not in response.text
    assert "{status}" in response.text
    assert "{error}" in response.text


def test_the_page_carries_the_boot_texts_in_german(client):
    """The default is the configured language (the test configuration says
    ``de``) — the ordinary case, seen from the other side."""
    client.headers.pop("X-Sitzungsschluessel", None)
    response = client.get("/app/")
    assert t("fehler.status", "de") in response.text
    assert t("fehler.status", "en") not in response.text


def test_on_auto_the_page_request_decides_the_language(client):
    """``auto`` means "the device decides" — and for the page the device is
    the browser asking for it, so its own header counts. Without this the
    page would always fall back to the configured language."""
    client.headers.pop("X-Sitzungsschluessel", None)
    response = client.get("/app/", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert t("fehler.status", "en") in response.text
    assert t("fehler.status", "de") not in response.text


def test_a_catalogue_text_cannot_end_the_script_block(client, monkeypatch):
    """The texts travel inside a <script> block. JSON does not escape `<`, so
    a text carrying "</script>" would end the element early — the page would
    come without session key, diagnosis flag and texts, and every call would
    be refused. Measured with a text of that shape, because no catalogue
    entry has one today: the escape is what keeps it that way."""
    import app.main as main

    monkeypatch.setattr(main, "t", lambda key, sprache, **werte: "x</script>y")
    client.headers.pop("X-Sitzungsschluessel", None)
    response = client.get("/app/")
    assert response.status_code == 200
    # The block ends where it should, the key is still in it, and the text
    # arrived escaped — it reads back as the same character in the page.
    assert "</script></head>" in response.text
    assert "x</script>y" not in response.text
    assert "x\\u003c/script>y" in response.text

