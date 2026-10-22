"""The structured server routes of the tile gallery.

GET reads the entries including live state, PUT creates and makes targeted
changes, DELETE cleans up — all through mcp_servers.json as the single
source of truth that the raw text field uses too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import paketierung
from app.tools.registry import konfiguration_pruefen


@pytest.fixture(autouse=True)
def eigene_serverdatei(config):
    """Never touch the project's real file."""
    config.mcp.servers_file = str(Path(config.app.data_dir) / "mcp_servers.json")


@pytest.fixture
def eigener_ordner(tmp_path, monkeypatch):
    """Redirects the writable data root, so a key never reaches the
    project's own .env — the same isolation test_anbieter.py already uses
    for the provider window's key."""
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    return tmp_path


def _datei(config) -> dict:
    pfad = config.pfad(config.mcp.servers_file)
    return json.loads(pfad.read_text(encoding="utf-8"))


def test_leere_welt_ist_eine_leere_liste(client):
    assert client.get("/api/v1/tools/servers").json() == []


def test_anlegen_und_lesen(client, config, monkeypatch):
    monkeypatch.setenv("GALERIE_TEST_TOKEN", "geheim")
    antwort = client.put(
        "/api/v1/tools/servers/github",
        json={
            "type": "http",
            "url": "https://beispiel.invalid/mcp",
            "api_key_env": "GALERIE_TEST_TOKEN",
            "enabled": True,
        },
    )
    assert antwort.status_code == 200
    assert antwort.json()["kaputt"] is None

    (eintrag,) = client.get("/api/v1/tools/servers").json()
    assert eintrag["name"] == "github"
    assert eintrag["type"] == "http"
    assert eintrag["enabled"] is True
    assert eintrag["schluessel_gesetzt"] is True
    assert eintrag["laeuft"] is False  # features.mcp is off in tests
    assert eintrag["alle_werkzeuge"] == []

    # The file is the same truth the text field sees.
    assert _datei(config)["mcpServers"]["github"]["url"] == "https://beispiel.invalid/mcp"


def test_gezieltes_aendern_laesst_den_rest_stehen(client, config):
    client.put(
        "/api/v1/tools/servers/recraft",
        json={"type": "http", "url": "https://beispiel.invalid/mcp", "enabled": True,
              "allowed_tools": ["bild_erzeugen"]},
    )
    antwort = client.put("/api/v1/tools/servers/recraft", json={"enabled": False})
    assert antwort.status_code == 200

    eintrag = _datei(config)["mcpServers"]["recraft"]
    assert eintrag["enabled"] is False
    assert eintrag["url"] == "https://beispiel.invalid/mcp"
    assert eintrag["allowed_tools"] == ["bild_erzeugen"]


def test_null_loescht_die_positivliste(client, config):
    client.put(
        "/api/v1/tools/servers/recraft",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "allowed_tools": ["eins"]},
    )
    client.put("/api/v1/tools/servers/recraft", json={"allowed_tools": None})
    assert "allowed_tools" not in _datei(config)["mcpServers"]["recraft"]


def test_kaputtes_wird_nicht_geschrieben(client, config):
    antwort = client.put("/api/v1/tools/servers/kaputt", json={"type": "http"})
    assert antwort.status_code == 400
    assert "url" in antwort.json()["detail"]
    assert not config.pfad(config.mcp.servers_file).exists()


def test_fehlender_schluessel_zeigt_rot(client, monkeypatch):
    monkeypatch.delenv("GALERIE_TEST_TOKEN", raising=False)
    client.put(
        "/api/v1/tools/servers/github",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "api_key_env": "GALERIE_TEST_TOKEN"},
    )
    (eintrag,) = client.get("/api/v1/tools/servers").json()
    assert eintrag["schluessel_gesetzt"] is False


def test_the_names_of_the_missing_keys_come_with_the_list(client, monkeypatch):
    """The card says WHICH variable is missing — its name, never a value."""
    monkeypatch.delenv("GALERIE_TEST_TOKEN", raising=False)
    monkeypatch.delenv("GALERIE_TEST_HEADER", raising=False)
    client.put(
        "/api/v1/tools/servers/github",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "api_key_env": "GALERIE_TEST_TOKEN",
              "headers": {"X-Test-Key": "${GALERIE_TEST_HEADER}"}},
    )
    (eintrag,) = client.get("/api/v1/tools/servers").json()
    assert eintrag["missing_keys"] == ["GALERIE_TEST_TOKEN", "GALERIE_TEST_HEADER"]


def test_silence_a_set_key_names_nothing_and_an_entry_without_a_key_says_null(client, monkeypatch):
    monkeypatch.setenv("GALERIE_TEST_TOKEN", "da")
    client.put(
        "/api/v1/tools/servers/mit-schluessel",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "api_key_env": "GALERIE_TEST_TOKEN"},
    )
    client.put(
        "/api/v1/tools/servers/ohne-schluessel",
        json={"type": "http", "url": "https://beispiel.invalid/mcp"},
    )
    zeilen = {z["name"]: z for z in client.get("/api/v1/tools/servers").json()}
    assert zeilen["mit-schluessel"]["missing_keys"] == []
    assert zeilen["ohne-schluessel"]["missing_keys"] is None
    # The value of a key is never in the answer.
    assert "da" not in json.dumps(zeilen["mit-schluessel"]["missing_keys"])


def test_a_half_set_pair_names_only_the_one_that_is_missing(client, monkeypatch):
    monkeypatch.setenv("GALERIE_TEST_TOKEN", "da")
    monkeypatch.delenv("GALERIE_TEST_HEADER", raising=False)
    client.put(
        "/api/v1/tools/servers/halb",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "api_key_env": "GALERIE_TEST_TOKEN",
              "headers": {"X-Test-Key": "${GALERIE_TEST_HEADER}"}},
    )
    (eintrag,) = client.get("/api/v1/tools/servers").json()
    assert eintrag["missing_keys"] == ["GALERIE_TEST_HEADER"]


def test_entfernen_samt_zugang(client, config):
    client.put(
        "/api/v1/tools/servers/recraft",
        json={"type": "http", "url": "https://beispiel.invalid/mcp"},
    )
    # A remembered credential must disappear along with the entry.
    client.app.state.mcp_oauth.speicher.setzen("recraft", access_token="zugang-1")

    antwort = client.delete("/api/v1/tools/servers/recraft")
    assert antwort.status_code == 204
    assert _datei(config)["mcpServers"] == {}
    assert client.app.state.mcp_oauth.speicher.eintrag("recraft") is None


def test_entfernen_ohne_eintrag_ist_404(client):
    assert client.delete("/api/v1/tools/servers/nie-da").status_code == 404


def test_api_key_geht_in_die_env_nicht_in_die_datei(client, config, eigener_ordner, monkeypatch):
    """The MCP sheet's own key field: it lands in .env, and only the name
    of the variable — never the key itself — stands in mcp_servers.json."""
    monkeypatch.delenv("GITHUB_TEST_TOKEN", raising=False)
    antwort = client.put(
        "/api/v1/tools/servers/github",
        json={
            "type": "http", "url": "https://beispiel.invalid/mcp", "enabled": True,
            "api_key_env": "GITHUB_TEST_TOKEN", "api_key": "ghp_geheim",
        },
    )
    assert antwort.status_code == 200

    eintrag = _datei(config)["mcpServers"]["github"]
    assert eintrag["api_key_env"] == "GITHUB_TEST_TOKEN"
    assert "api_key" not in eintrag
    assert "ghp_geheim" not in json.dumps(eintrag)

    assert os.environ["GITHUB_TEST_TOKEN"] == "ghp_geheim"
    assert "GITHUB_TEST_TOKEN=ghp_geheim" in (eigener_ordner / ".env").read_text()


def test_api_key_ohne_umgebungsnamen_wird_nicht_geschrieben(client, eigener_ordner):
    """A key with nothing to name it would land nowhere sensible — so it is
    simply not written, rather than guessing a variable name."""
    client.put(
        "/api/v1/tools/servers/namenlos",
        json={"type": "http", "url": "https://beispiel.invalid/mcp", "api_key": "geheim"},
    )
    assert not (eigener_ordner / ".env").exists()


def test_a_key_in_a_header_goes_to_the_env_not_the_file(
    client, config, eigener_ordner, monkeypatch
):
    """The key of a header stands as `${NAME}` in the file and as a value in
    the .env; the list says whether it is set."""
    monkeypatch.delenv("MAPS_TEST_KEY", raising=False)
    antwort = client.put(
        "/api/v1/tools/servers/maps",
        json={
            "type": "http", "url": "https://beispiel.invalid/mcp", "enabled": True,
            "auth": None, "headers": {"X-Goog-Api-Key": "${MAPS_TEST_KEY}"},
            "api_key": "maps_geheim",
        },
    )
    assert antwort.status_code == 200
    eintrag = _datei(config)["mcpServers"]["maps"]
    assert eintrag["headers"] == {"X-Goog-Api-Key": "${MAPS_TEST_KEY}"}
    assert "maps_geheim" not in json.dumps(eintrag)
    assert "MAPS_TEST_KEY=maps_geheim" in (eigener_ordner / ".env").read_text()

    (zeile,) = client.get("/api/v1/tools/servers").json()
    assert zeile["headers"] == {"X-Goog-Api-Key": "${MAPS_TEST_KEY}"}
    assert zeile["schluessel_gesetzt"] is True
    assert zeile["auth"] is None


def test_a_header_without_a_set_key_shows_red(client, monkeypatch):
    monkeypatch.delenv("MAPS_TEST_KEY", raising=False)
    client.put(
        "/api/v1/tools/servers/maps",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "headers": {"X-Goog-Api-Key": "${MAPS_TEST_KEY}"}},
    )
    (zeile,) = client.get("/api/v1/tools/servers").json()
    assert zeile["schluessel_gesetzt"] is False


def test_an_own_authorization_header_replaces_the_old_key_in_the_lamp_too(
    client, monkeypatch
):
    monkeypatch.delenv("ALT_TEST_KEY", raising=False)
    monkeypatch.setenv("NEU_TEST_KEY", "da")
    client.put(
        "/api/v1/tools/servers/gemischt",
        json={"type": "http", "url": "https://beispiel.invalid/mcp",
              "api_key_env": "ALT_TEST_KEY",
              "headers": {"Authorization": "Bearer ${NEU_TEST_KEY}"}},
    )
    (zeile,) = client.get("/api/v1/tools/servers").json()
    assert zeile["schluessel_gesetzt"] is True


def test_auth_oauth_is_written_and_read(client, config):
    client.put(
        "/api/v1/tools/servers/notion",
        json={"type": "http", "url": "https://beispiel.invalid/mcp", "auth": "oauth"},
    )
    assert _datei(config)["mcpServers"]["notion"]["auth"] == "oauth"
    (zeile,) = client.get("/api/v1/tools/servers").json()
    assert zeile["auth"] == "oauth"
    # An unknown way of signing in is refused, not saved.
    antwort = client.put("/api/v1/tools/servers/notion", json={"auth": "browser"})
    assert antwort.status_code == 400
    assert _datei(config)["mcpServers"]["notion"]["auth"] == "oauth"


@pytest.mark.parametrize("name", ["FOO\nEVIL_VAR", "FOO BAR", "1FOO", "FOO=BAR"])
def test_ein_falscher_umgebungsname_wird_abgewiesen(client, config, eigener_ordner, name):
    """The name lands in .env as `NAME=value`, one per line. A line break in
    it would write a second, foreign variable into the shared file."""
    (eigener_ordner / ".env").write_text("SCHON_DA=1\n", encoding="utf-8")
    antwort = client.put(
        "/api/v1/tools/servers/github",
        json={
            "type": "http", "url": "https://beispiel.invalid/mcp",
            "api_key_env": name, "api_key": "geheim",
        },
    )
    assert antwort.status_code == 400
    assert "api_key_env" in antwort.json()["detail"]
    # Silent case: the .env is exactly what it was, and no entry was written.
    assert (eigener_ordner / ".env").read_text(encoding="utf-8") == "SCHON_DA=1\n"
    assert not config.pfad(config.mcp.servers_file).exists()


def test_ein_schluessel_mit_zeilenumbruch_wird_abgewiesen(client, config, eigener_ordner):
    """The key goes into the same line: a break inside it would write a
    foreign variable just the same."""
    (eigener_ordner / ".env").write_text("SCHON_DA=1\n", encoding="utf-8")
    antwort = client.put(
        "/api/v1/tools/servers/github",
        json={
            "type": "http", "url": "https://beispiel.invalid/mcp",
            "api_key_env": "GITHUB_TOKEN", "api_key": "abc\nEVIL_VAR=x",
        },
    )
    assert antwort.status_code == 422
    assert (eigener_ordner / ".env").read_text(encoding="utf-8") == "SCHON_DA=1\n"
    assert not config.pfad(config.mcp.servers_file).exists()


def test_ein_richtiger_umgebungsname_kommt_durch(client, eigener_ordner, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    antwort = client.put(
        "/api/v1/tools/servers/github",
        json={
            "type": "http", "url": "https://beispiel.invalid/mcp",
            "api_key_env": "GITHUB_TOKEN", "api_key": "geheim",
        },
    )
    assert antwort.status_code == 200
    assert "GITHUB_TOKEN=geheim" in (eigener_ordner / ".env").read_text(encoding="utf-8")


def test_ein_neuer_server_ueberschreibt_keinen_vorhandenen(client, config):
    """"GitHub" becomes `github` and meets the entry already on file. Added
    as new, it is refused and the old entry stands as it was."""
    client.put(
        "/api/v1/tools/servers/github",
        json={"type": "http", "url": "https://alt.invalid/mcp", "api_key_env": "ALT_TOKEN"},
    )
    vorher = _datei(config)["mcpServers"]["github"]
    antwort = client.put(
        "/api/v1/tools/servers/github?neu=true",
        json={"type": "http", "url": "https://neu.invalid/mcp", "api_key_env": "NEU_TOKEN"},
    )
    assert antwort.status_code == 409
    assert "github" in antwort.json()["detail"]
    assert _datei(config)["mcpServers"]["github"] == vorher


def test_ein_bestehender_server_laesst_sich_weiter_aendern(client, config):
    """Silent case: without `neu` the same route changes the entry."""
    client.put("/api/v1/tools/servers/github", json={"type": "http", "url": "https://alt.invalid/mcp"})
    antwort = client.put("/api/v1/tools/servers/github", json={"url": "https://neu.invalid/mcp"})
    assert antwort.status_code == 200
    assert _datei(config)["mcpServers"]["github"]["url"] == "https://neu.invalid/mcp"


def test_ein_neuer_server_mit_freier_kennung_wird_angelegt(client, config):
    antwort = client.put(
        "/api/v1/tools/servers/frei?neu=true", json={"type": "http", "url": "https://x.invalid/mcp"}
    )
    assert antwort.status_code == 200
    assert "frei" in _datei(config)["mcpServers"]


def test_stdio_server_traegt_befehl_und_argumente(client, config):
    """The raw file editor's escape hatch, not the sheet: the sheet no
    longer asks for a kind at all, but a typed command line still splits
    into `command` and `args`, the two fields the registry's
    ServerEintrag dataclass actually reads."""
    antwort = client.put(
        "/api/v1/tools/servers/eigenbau",
        json={"type": "stdio", "command": "npx", "args": ["-y", "@beispiel/server"], "enabled": True},
    )
    assert antwort.status_code == 200

    eintrag = _datei(config)["mcpServers"]["eigenbau"]
    assert eintrag["command"] == "npx"
    assert eintrag["args"] == ["-y", "@beispiel/server"]


def test_sondieren_gibt_das_ergebnis_weiter(client, monkeypatch):
    """The route is a thin pass-through — the real protocol logic is
    test_mcp_sondierung.py's job. What this checks is the wiring: the
    URL reaches `sondieren()`, and its answer reaches the response."""
    gesehen = {}

    async def fake_sondieren(url):
        gesehen["url"] = url
        return {"verlangt": "anmeldung", "name": None}

    monkeypatch.setattr("app.api.v1.werkzeuge.sondieren", fake_sondieren)
    antwort = client.post(
        "/api/v1/tools/mcp/sondieren", json={"url": "https://mcp.beispiel.invalid/mcp"}
    )
    assert antwort.status_code == 200
    assert antwort.json() == {"verlangt": "anmeldung", "name": None}
    assert gesehen["url"] == "https://mcp.beispiel.invalid/mcp"


def test_sondieren_meldet_einen_fehler_als_400(client, monkeypatch):
    """Schweigeprobe's other half: a server that cannot be reached at all
    must not look like 200 with an empty answer."""
    from app.tools.mcp_client import MCPFehler

    async def fake_sondieren(url):
        raise MCPFehler("Der Server ist nicht erreichbar")

    monkeypatch.setattr("app.api.v1.werkzeuge.sondieren", fake_sondieren)
    antwort = client.post(
        "/api/v1/tools/mcp/sondieren", json={"url": "https://tot.beispiel.invalid/mcp"}
    )
    assert antwort.status_code == 400
    assert "nicht erreichbar" in antwort.json()["detail"]


# --- Names on file, an unreadable file, the page's language ---


def test_a_name_with_a_hyphen_on_file_stays_readable_and_writable(client, config, eigener_ordner):
    """An entry already on file names its key `github-token`: the gallery
    reads it and can still change it."""
    path = config.pfad(config.mcp.servers_file)
    path.write_text(json.dumps({"mcpServers": {"github": {
        "type": "http", "url": "https://beispiel.invalid/mcp", "api_key_env": "github-token",
    }}}), encoding="utf-8")
    assert [e["api_key_env"] for e in client.get("/api/v1/tools/servers").json()] == ["github-token"]
    answer = client.put("/api/v1/tools/servers/github", json={"enabled": False})
    assert answer.status_code == 200
    assert _datei(config)["mcpServers"]["github"]["enabled"] is False
    assert _datei(config)["mcpServers"]["github"]["api_key_env"] == "github-token"


@pytest.mark.parametrize("broken", ["{ kaputt", '{"servers": {}}', "[]"])
@pytest.mark.parametrize("new", [True, False])
def test_an_unreadable_file_is_never_written_over(client, config, eigener_ordner, broken, new):
    """No JSON, or no object `mcpServers`: the gallery refuses with the
    check's own reason in the page's language, and the file stays byte for
    byte as it was."""
    path = config.pfad(config.mcp.servers_file)
    path.write_text(broken, encoding="utf-8")
    answer = client.put(
        f"/api/v1/tools/servers/github{'?neu=true' if new else ''}",
        json={"type": "http", "url": "https://beispiel.invalid/mcp"},
        headers={"X-Ui-Language": "en"},
    )
    assert answer.status_code == 409
    assert answer.json()["detail"] == konfiguration_pruefen(broken, "en")
    assert path.read_text(encoding="utf-8") == broken
    # Removing an entry from it is refused the same way, in German here.
    removed = client.delete("/api/v1/tools/servers/github", headers={"X-Ui-Language": "de"})
    assert removed.status_code == 409
    assert removed.json()["detail"] == konfiguration_pruefen(broken, "de")
    # A translated sentence, not a bare catalogue key, and not the same in both.
    for detail in (answer.json()["detail"], removed.json()["detail"]):
        assert not detail.startswith("mcp_datei.")
    assert removed.json()["detail"] != answer.json()["detail"]
    english = {"{ kaputt": "Invalid JSON", '{"servers": {}}': "'mcpServers' is missing",
               "[]": "The top level must be an object."}[broken]
    german = {"{ kaputt": "Ungültiges JSON", '{"servers": {}}': "'mcpServers' fehlt",
              "[]": "Die oberste Ebene muss ein Objekt sein."}[broken]
    assert english in answer.json()["detail"]
    assert german in removed.json()["detail"]
    assert path.read_text(encoding="utf-8") == broken


@pytest.mark.parametrize("empty", ["", "\n", "  \n  "])
def test_an_empty_file_takes_the_first_server(client, config, eigener_ordner, empty):
    """Silence probe: an empty file holds nothing that could be lost, so the
    gallery writes the first server into it."""
    path = config.pfad(config.mcp.servers_file)
    path.write_text(empty, encoding="utf-8")
    answer = client.put(
        "/api/v1/tools/servers/github?neu=true",
        json={"type": "http", "url": "https://beispiel.invalid/mcp"},
    )
    assert answer.status_code == 200
    assert list(_datei(config)["mcpServers"]) == ["github"]


def test_the_messages_come_in_the_language_of_the_page(client, config, eigener_ordner):
    """The 409 of a taken name and a check message, English and German."""
    path = config.pfad(config.mcp.servers_file)
    path.write_text(json.dumps({"mcpServers": {"github": {
        "type": "http", "url": "https://beispiel.invalid/mcp",
    }}}), encoding="utf-8")
    for language, taken, wrong in (
        ("en", "'github' is already registered.", "'api_key_env' must be a name"),
        ("de", "'github' ist bereits eingetragen.", "'api_key_env' muss ein Name sein"),
    ):
        headers = {"X-Ui-Language": language}
        answer = client.put("/api/v1/tools/servers/github?neu=true", json={}, headers=headers)
        assert answer.status_code == 409
        assert answer.json()["detail"] == taken
        answer = client.put(
            "/api/v1/tools/servers/github", json={"api_key_env": "1FOO"}, headers=headers
        )
        assert answer.status_code == 400
        assert wrong in answer.json()["detail"]


# --- One reading rule for the server file --------------------------------

UNUSABLE_FILES = {
    "empty": b"",
    "broken": b"{ kaputt",
    "not_utf8": '{"mcpServers": {"grüße": {"type": "stdio"}}}'.encode("latin-1"),
    "entry_not_object": b'{"mcpServers": {"github": "x"}}',
}


@pytest.mark.parametrize("kind", list(UNUSABLE_FILES))
def test_the_service_builds_its_registry_from_an_unusable_server_file(client, config, kind):
    """A file that is empty, no JSON, no UTF-8 or holds an entry that is no
    object loads no server and stops nothing: the registry stands with the
    program's own tools."""
    from app.tools.aufbau import registry_bauen

    path = config.pfad(config.mcp.servers_file)
    path.write_bytes(UNUSABLE_FILES[kind])

    registry = registry_bauen(client.app, config)

    assert registry.eintraege == []
    assert any(e["builtin"] for e in registry.uebersicht())
    assert path.read_bytes() == UNUSABLE_FILES[kind]


@pytest.mark.parametrize("kind", ["broken", "not_utf8", "entry_not_object"])
def test_the_gallery_list_and_the_sign_in_say_why_the_file_is_unusable(client, config, kind):
    """409 with the check's sentence in the page's language, never 500."""
    path = config.pfad(config.mcp.servers_file)
    path.write_bytes(UNUSABLE_FILES[kind])

    for language in ("en", "de"):
        headers = {"X-Ui-Language": language}
        listing = client.get("/api/v1/tools/servers", headers=headers)
        sign_in = client.post(
            "/api/v1/tools/oauth/start", json={"server": "github"}, headers=headers
        )
        assert listing.status_code == 409
        assert sign_in.status_code == 409
        assert listing.json()["detail"] == sign_in.json()["detail"]
        assert not listing.json()["detail"].startswith("mcp_datei.")
    assert client.get("/api/v1/tools/servers", headers={"X-Ui-Language": "de"}).json()[
        "detail"
    ] != client.get("/api/v1/tools/servers", headers={"X-Ui-Language": "en"}).json()["detail"]
    # Never written by a reading.
    assert path.read_bytes() == UNUSABLE_FILES[kind]


def test_a_file_that_is_no_utf8_names_the_decoder_as_the_json_sentence_does(client, config):
    path = config.pfad(config.mcp.servers_file)
    path.write_bytes(UNUSABLE_FILES["not_utf8"])

    detail = client.get("/api/v1/tools/servers", headers={"X-Ui-Language": "en"}).json()["detail"]

    assert detail.startswith("Invalid JSON")
    assert "utf-8" in detail


def test_an_empty_file_lists_nothing_and_a_gallery_put_on_an_entry_that_is_no_object_says_409(
    client, config
):
    path = config.pfad(config.mcp.servers_file)
    path.write_bytes(UNUSABLE_FILES["empty"])
    listing = client.get("/api/v1/tools/servers")
    assert listing.status_code == 200 and listing.json() == []

    path.write_bytes(UNUSABLE_FILES["entry_not_object"])
    answer = client.put("/api/v1/tools/servers/github", json={"enabled": False})
    assert answer.status_code == 409
    assert path.read_bytes() == UNUSABLE_FILES["entry_not_object"]


def test_a_byte_order_mark_does_not_count(client, config):
    path = config.pfad(config.mcp.servers_file)
    body = json.dumps({"mcpServers": {"github": {"type": "http", "url": "https://beispiel.invalid/mcp"}}})
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))

    listing = client.get("/api/v1/tools/servers")

    assert listing.status_code == 200
    assert [e["name"] for e in listing.json()] == ["github"]


def test_silence_a_valid_file_reads_entry_for_entry_and_is_never_changed(client, config):
    from app.tools import server_lesen

    path = config.pfad(config.mcp.servers_file)
    body = json.dumps(
        {"mcpServers": {
            "b": {"type": "http", "url": "https://beispiel.invalid/b"},
            "a": {"type": "stdio", "command": "npx", "args": ["-y", "x"], "enabled": False},
        }}
    ).encode("utf-8")
    path.write_bytes(body)

    entries = server_lesen(path)

    assert [(e.name, e.type, e.enabled) for e in entries] == [
        ("b", "http", True), ("a", "stdio", False),
    ]
    assert path.read_bytes() == body
    assert server_lesen(path.with_name("missing.json")) == []


def test_the_text_field_shows_an_unreadable_file_with_its_reason(client, config):
    path = config.pfad(config.mcp.servers_file)
    path.write_bytes(UNUSABLE_FILES["not_utf8"])

    answer = client.get("/api/v1/tools/config", headers={"X-Ui-Language": "en"})

    assert answer.status_code == 200
    assert answer.json()["kaputt"].startswith("Invalid JSON")
    assert path.read_bytes() == UNUSABLE_FILES["not_utf8"]


# --- The placeholder takes the name an environment variable may have ------


def test_a_placeholder_with_a_hyphen_gets_its_light(client, config, monkeypatch):
    monkeypatch.setenv("github-token", "x")
    body = json.dumps({"mcpServers": {"github": {
        "type": "http", "url": "https://beispiel.invalid/mcp",
        "env": {"TOKEN": "${github-token}"},
    }}})
    config.pfad(config.mcp.servers_file).write_text(body, encoding="utf-8")

    names = {p["name"]: p["gesetzt"] for p in client.get("/api/v1/tools/config").json()["platzhalter"]}

    assert names == {"github-token": True}


@pytest.mark.parametrize("written", ["${-x}", "${1x}", "$NAME"])
def test_silence_a_name_that_is_no_environment_name_gets_no_light(client, config, written):
    body = json.dumps({"mcpServers": {"github": {
        "type": "http", "url": "https://beispiel.invalid/mcp", "env": {"TOKEN": written},
    }}})
    config.pfad(config.mcp.servers_file).write_text(body, encoding="utf-8")

    assert client.get("/api/v1/tools/config").json()["platzhalter"] == []


def test_silence_the_old_name_keeps_its_light(client, config, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    body = json.dumps({"mcpServers": {"github": {
        "type": "http", "url": "https://beispiel.invalid/mcp",
        "env": {"TOKEN": "${GITHUB_TOKEN}"},
    }}})
    config.pfad(config.mcp.servers_file).write_text(body, encoding="utf-8")

    names = {p["name"]: p["gesetzt"] for p in client.get("/api/v1/tools/config").json()["platzhalter"]}

    assert names == {"GITHUB_TOKEN": True}
