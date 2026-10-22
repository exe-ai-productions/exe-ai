"""Adding a cloud provider from the window, end to end.

The window's whole promise is "key in, models appear". What the endpoint
must leave behind is checked here: the entry in config.yaml, the key in
.env and in the running environment, and — without any restart — the
candidate in discovery. The last one is the difference between a window
and a dead end.
"""

from __future__ import annotations

import os

import pytest
import yaml

from app import paketierung


@pytest.fixture
def eigener_ordner(tmp_path, monkeypatch):
    """Redirects the user folder, so no test writes the project's own
    config.yaml or .env."""
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text("endpoints: []\n", encoding="utf-8")
    # Whatever the endpoint puts into the environment is rolled back by
    # monkeypatch, because the name is registered here first.
    monkeypatch.setenv("EIGENE_API_KEY", "vorher")
    return tmp_path


def test_ein_anbieter_erscheint_ohne_neustart(client, eigener_ordner):
    antwort = client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    assert antwort.status_code == 200
    # Nothing listens on this port, so the one-time reachability check that
    # `anmelden()` runs right away comes back negative.
    assert antwort.json() == {
        "id": "eigene",
        "api_key_env": "EIGENE_API_KEY",
        "erreichbar": False,
        "hinweis": None,
    }

    # The candidate is there while the window is still open.
    zustand = client.app.state.discovery.zustaende.get("eigene")
    assert zustand is not None
    assert zustand.endpunkt.group == "cloud"

    # The running service can use the key at once; the file serves the next
    # start.
    assert os.environ["EIGENE_API_KEY"] == "sk-test-1234"
    assert "EIGENE_API_KEY=sk-test-1234" in (eigener_ordner / ".env").read_text()

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert gespeichert["endpoints"][0]["id"] == "eigene"


def test_dieselbe_kennung_gibt_es_nur_einmal(client, eigener_ordner):
    daten = {
        "art": "eigen",
        "kennung": "doppelt",
        "url": "http://127.0.0.1:9/v1",
        "schluessel": "sk-test-1234",
    }
    assert client.post("/api/v1/providers", json=daten).status_code == 200
    assert client.post("/api/v1/providers", json=daten).status_code == 409


def test_ein_bekannter_anbieter_braucht_keine_adresse(client, eigener_ordner, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vorher")
    antwort = client.post(
        "/api/v1/providers",
        json={"art": "anthropic", "schluessel": "sk-ant-test-1234"},
    )
    assert antwort.status_code == 200
    zustand = client.app.state.discovery.zustaende.get("anthropic")
    assert zustand is not None
    assert zustand.endpunkt.base_url == "https://api.anthropic.com/v1"


# --- Hand-set capabilities ---------------------------------------------------


def test_vision_laesst_sich_von_hand_setzen(client, eigener_ordner):
    """Cloud model lists say nothing about modalities — whoever knows their
    model sees images must be able to say so, and the word must hold."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.kann("vision") is False

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"vision": True}
    )
    assert antwort.status_code == 200
    assert antwort.json()["capabilities"]["vision"] is True
    # The running service answers with the new word at once …
    assert zustand.kann("vision") is True
    # … and the file carries it to the next start.
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["vision"] is True


def test_vision_wort_laesst_sich_zuruecknehmen(client, eigener_ordner):
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    client.put("/api/v1/providers/eigene/capabilities", json={"vision": True})
    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"vision": None}
    )
    assert antwort.status_code == 200
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert "vision" not in (eintrag.get("capabilities") or {})
    assert client.app.state.discovery.zustaende["eigene"].kann("vision") is False


def test_faehigkeit_nur_genannte_felder(client, eigener_ordner):
    """A request naming only vision must not wipe an explicit tool_calls."""
    client.post(
        "/api/v1/providers",
        json={"art": "anthropic", "schluessel": "sk-test-1234"},
    )
    client.put("/api/v1/providers/anthropic/capabilities", json={"vision": False})
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "anthropic")
    assert eintrag["capabilities"] == {"tool_calls": True, "vision": False}


def test_denken_laesst_sich_von_hand_setzen(client, eigener_ordner):
    """An unknown host is offered the plain OpenAI field's stages; the
    switch in the window says otherwise either way, and the hand wins."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.kann("thinking") is True

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"thinking": False}
    )
    assert antwort.status_code == 200
    assert zustand.kann("thinking") is False

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"thinking": True}
    )
    assert antwort.status_code == 200
    assert antwort.json()["capabilities"]["thinking"] is True
    assert zustand.kann("thinking") is True

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["thinking"] is True


def test_werkzeuge_lassen_sich_von_hand_setzen(client, eigener_ordner):
    """A new custom provider takes tool calls from the start, like the
    presets: a cloud entry has no /props to sniff, and without tools a model
    that could call one writes its call into the chat as text. A hand-set
    "no" stays."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.kann("tool_calls") is True

    client.put("/api/v1/providers/eigene/capabilities", json={"tool_calls": False})
    assert zustand.kann("tool_calls") is False
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["tool_calls"] is False

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"tool_calls": True}
    )
    assert antwort.status_code == 200
    assert antwort.json()["capabilities"]["tool_calls"] is True
    assert zustand.kann("tool_calls") is True

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["tool_calls"] is True


def test_faehigkeit_unbekannter_endpunkt_gibt_404(client, eigener_ordner):
    assert (
        client.put(
            "/api/v1/providers/phantom/capabilities", json={"vision": True}
        ).status_code
        == 404
    )


# --- The "Zeitgrenze" switch -------------------------------------------------


def test_zeitgrenze_laesst_sich_von_hand_ausschalten(client, eigener_ordner):
    """A server this window's user trusts to eventually answer switches the
    600 s cutoff off — the word must hold in the running service AND the
    file, the same as the three capability switches above."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.endpunkt.timeout_enabled is True

    antwort = client.put(
        "/api/v1/providers/eigene/timeout", json={"timeout_enabled": False}
    )
    assert antwort.status_code == 200
    assert antwort.json()["timeout_enabled"] is False
    assert zustand.endpunkt.timeout_enabled is False

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["timeout_enabled"] is False


def test_zeitgrenze_zurueck_auf_an_raeumt_das_feld_wieder_weg(client, eigener_ordner):
    """Schweigeprobe: switched back on, the file carries no line at all —
    on is what an absent entry has always meant."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    client.put("/api/v1/providers/eigene/timeout", json={"timeout_enabled": False})
    client.put("/api/v1/providers/eigene/timeout", json={"timeout_enabled": True})

    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.endpunkt.timeout_enabled is True
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert "timeout_enabled" not in eintrag


def test_zeitgrenze_unbekannter_endpunkt_gibt_404(client, eigener_ordner):
    assert (
        client.put(
            "/api/v1/providers/phantom/timeout", json={"timeout_enabled": False}
        ).status_code
        == 404
    )


# --- Removing a provider ------------------------------------------------------


def test_ein_anbieter_laesst_sich_entfernen(client, eigener_ordner):
    """The counterpart of adding one: gone from the file, gone from
    discovery, gone from the running config — and its key line with it."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    assert os.environ["EIGENE_API_KEY"] == "sk-test-1234"

    antwort = client.delete("/api/v1/providers/eigene")
    assert antwort.status_code == 204

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert all(e["id"] != "eigene" for e in gespeichert["endpoints"])
    assert client.app.state.discovery.zustaende.get("eigene") is None
    assert not any(e.id == "eigene" for e in client.app.state.config.endpoints)
    # The key goes with the provider: out of the file and out of the
    # running environment.
    assert "EIGENE_API_KEY" not in os.environ
    assert "EIGENE_API_KEY" not in (eigener_ordner / ".env").read_text()


def test_entfernter_anbieter_laesst_sich_erneut_anlegen(client, eigener_ordner):
    """The case from the field: a dead entry blocked every future add under
    the same name — removing it has to open that name up again."""
    daten = {
        "art": "eigen",
        "kennung": "eigene",
        "url": "http://127.0.0.1:9/v1",
        "schluessel": "sk-test-1234",
    }
    client.post("/api/v1/providers", json=daten)
    client.delete("/api/v1/providers/eigene")

    antwort = client.post("/api/v1/providers", json=daten)
    assert antwort.status_code == 200
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert sum(1 for e in gespeichert["endpoints"] if e["id"] == "eigene") == 1


def test_andere_anbieter_bleiben_beim_entfernen_unberuehrt(client, eigener_ordner):
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eins",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1111",
        },
    )
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "zwei",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-2222",
        },
    )

    client.delete("/api/v1/providers/eins")

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert [e["id"] for e in gespeichert["endpoints"]] == ["zwei"]
    zustand = client.app.state.discovery.zustaende.get("zwei")
    assert zustand is not None
    assert zustand.endpunkt.base_url == "http://127.0.0.1:9/v1"


def test_anbieter_loeschen_unbekannt_gibt_404(client, eigener_ordner):
    assert client.delete("/api/v1/providers/phantom").status_code == 404


# --- The key goes with the provider, unless another provider reads it ----------


def _add_own(client, kennung: str, schluessel: str = "sk-test-1234"):
    return client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": kennung,
            "url": "http://127.0.0.1:9/v1",
            "schluessel": schluessel,
        },
    )


def test_removing_a_provider_leaves_the_other_env_lines_byte_equal(client, eigener_ordner):
    before = "# my keys\nOTHER_KEY=abc\n\n# note\nLAST_KEY=xyz\n"
    # Bytes, not text: a text write would turn each line break into CRLF on
    # Windows, and the file would not be the one the test means to keep.
    (eigener_ordner / ".env").write_bytes(before.encode("utf-8"))
    _add_own(client, "eigene")
    assert "EIGENE_API_KEY=sk-test-1234" in (eigener_ordner / ".env").read_text()

    assert client.delete("/api/v1/providers/eigene").status_code == 204

    assert (eigener_ordner / ".env").read_bytes() == before.encode("utf-8")


def test_a_env_file_with_windows_line_ends_keeps_them_through_a_key_coming_and_going(
    client, eigener_ordner
):
    """The same file as above, written by a Windows editor: the key's line is
    added and taken out again, and every other line comes back with its own
    line end. Silence probe: a file with plain line ends gets no CR."""
    crlf = b"# my keys\r\nOTHER_KEY=abc\r\n\r\n# note\r\nLAST_KEY=xyz\r\n"
    (eigener_ordner / ".env").write_bytes(crlf)
    _add_own(client, "eigene")
    mid = (eigener_ordner / ".env").read_bytes()
    assert b"EIGENE_API_KEY=sk-test-1234\r\n" in mid
    assert mid.count(b"\r\n") == mid.count(b"\n")

    assert client.delete("/api/v1/providers/eigene").status_code == 204

    assert (eigener_ordner / ".env").read_bytes() == crlf
    (eigener_ordner / ".env").write_bytes(b"OTHER_KEY=abc\n")
    _add_own(client, "eigene")
    assert b"\r" not in (eigener_ordner / ".env").read_bytes()


def test_a_key_another_provider_reads_stays_until_the_last_one_goes(client, eigener_ordner, monkeypatch):
    """`ab-c` and `ab_c` both name `AB_C_API_KEY`: two providers, one line."""
    monkeypatch.setenv("AB_C_API_KEY", "vorher")
    assert _add_own(client, "ab-c").status_code == 200
    assert _add_own(client, "ab_c").status_code == 200
    env_file = eigener_ordner / ".env"
    assert "AB_C_API_KEY=sk-test-1234" in env_file.read_text()

    assert client.delete("/api/v1/providers/ab-c").status_code == 204
    # The other provider still reads it, in the file and in the process.
    assert "AB_C_API_KEY=sk-test-1234" in env_file.read_text()
    assert os.environ["AB_C_API_KEY"] == "sk-test-1234"

    assert client.delete("/api/v1/providers/ab_c").status_code == 204
    assert "AB_C_API_KEY" not in env_file.read_text()
    assert "AB_C_API_KEY" not in os.environ


def test_a_variable_without_a_line_in_the_file_is_not_taken_from_the_environment(
    client, eigener_ordner
):
    """The silence probe: the value came from the shell, not from .env —
    removing the provider neither fails nor takes it from the process."""
    _add_own(client, "eigene")
    (eigener_ordner / ".env").unlink()

    assert client.delete("/api/v1/providers/eigene").status_code == 204
    assert not (eigener_ordner / ".env").exists()
    assert os.environ["EIGENE_API_KEY"] == "sk-test-1234"


def _key_goes(client) -> dict[str, bool]:
    antwort = client.get("/api/v1/models", params={"alle": "true"})
    assert antwort.status_code == 200
    return {m["anbieter"]: m["key_goes_with_provider"] for m in antwort.json()}


def test_the_list_says_for_each_provider_whether_its_key_goes_with_it(
    client, eigener_ordner, monkeypatch
):
    """The window asks before the removal; it reads the same rule the route
    applies — also for a provider that is down."""
    monkeypatch.setenv("AB_C_API_KEY", "vorher")
    _add_own(client, "eigene")
    _add_own(client, "ab-c")
    _add_own(client, "ab_c")

    seen = _key_goes(client)
    assert seen["eigene"] is True
    assert seen["ab-c"] is False
    assert seen["ab_c"] is False

    client.delete("/api/v1/providers/ab-c")
    assert _key_goes(client)["ab_c"] is True


def test_the_question_names_the_key_in_both_languages():
    from app.i18n import t

    assert (
        t("modell.anbieter_loeschen_frage_mit_schluessel", "en", name="Acme")
        == "Remove provider “Acme” and its key?"
    )
    assert (
        t("modell.anbieter_loeschen_frage_mit_schluessel", "de", name="Acme")
        == "Anbieter „Acme“ und seinen Schlüssel entfernen?"
    )
    # The sentence for a shared key is the one that already stood there.
    assert "key remains in .env" in t("modell.anbieter_loeschen_frage", "en", name="Acme")
    assert "bleibt in der .env erhalten" in t("modell.anbieter_loeschen_frage", "de", name="Acme")


# --- config.yaml is written back as it was, only the entry changes -----------

HAND_WRITTEN = """\
# Exe AI — configuration, written by hand.
# The comments say why a value stands where it does.

app:
  port: 8090   # the service port
  data_dir: "./data"
  runner_programm: null

endpoints:
  # The model server on this machine.
  - id: omlx
    group: local
    provider: openai_compatible
    base_url: "http://127.0.0.1:8001/v1"   # oMLX
    modell: 'Qwen3.5-4B'

  # The server in the cellar.
  - id: cellar
    group: local
    base_url: https://cellar.example/v1
"""


def _lines_changed(before: str, after: str) -> tuple[list[str], list[str]]:
    """The lines only the old text has, and the lines only the new one has."""
    import difflib

    gone, added = [], []
    for line in difflib.ndiff(before.splitlines(), after.splitlines()):
        if line.startswith("- "):
            gone.append(line[2:])
        elif line.startswith("+ "):
            added.append(line[2:])
    return gone, added


def test_adding_a_provider_keeps_comments_quotes_and_blank_lines(client, eigener_ordner):
    datei = eigener_ordner / "config.yaml"
    datei.write_text(HAND_WRITTEN, encoding="utf-8")

    assert _add_own(client, "eigene").status_code == 200

    nachher = datei.read_text(encoding="utf-8")
    # Everything that stood there still stands there, byte for byte; the
    # new entry is the only thing that came.
    assert nachher.startswith(HAND_WRITTEN)
    gone, added = _lines_changed(HAND_WRITTEN, nachher)
    assert gone == []
    assert "  - id: eigene" in added
    # The entry came in the file's own list style (dash two in).
    assert yaml.safe_load(nachher)["endpoints"][-1]["id"] == "eigene"


def test_a_provider_added_and_removed_again_leaves_the_file_byte_equal(client, eigener_ordner):
    datei = eigener_ordner / "config.yaml"
    datei.write_text(HAND_WRITTEN, encoding="utf-8")
    _add_own(client, "eigene")

    assert client.delete("/api/v1/providers/eigene").status_code == 204

    assert datei.read_text(encoding="utf-8") == HAND_WRITTEN


def test_changing_a_providers_word_touches_only_its_own_lines(client, eigener_ordner):
    datei = eigener_ordner / "config.yaml"
    datei.write_text(HAND_WRITTEN, encoding="utf-8")
    _add_own(client, "eigene")
    vorher = datei.read_text(encoding="utf-8")

    assert client.put(
        "/api/v1/providers/eigene/capabilities", json={"vision": True}
    ).status_code == 200
    mitte = datei.read_text(encoding="utf-8")
    gone, added = _lines_changed(vorher, mitte)
    assert gone == []
    assert any("vision: true" in line for line in added)
    assert mitte.startswith(HAND_WRITTEN)

    assert client.put(
        "/api/v1/providers/eigene/timeout", json={"timeout_enabled": False}
    ).status_code == 200
    ende = datei.read_text(encoding="utf-8")
    assert ende.startswith(HAND_WRITTEN)
    assert yaml.safe_load(ende)["endpoints"][-1]["timeout_enabled"] is False


def test_removing_a_provider_in_the_middle_keeps_the_comment_of_the_next_one(
    client, eigener_ordner
):
    """The comment lines in front of an entry hang on the entry before it
    in the parser: removing one must not take the next one's comment along,
    nor leave its own standing over a stranger."""
    _add_own(client, "eigene")
    _add_own(client, "zweite", schluessel="sk-test-5678")
    datei = eigener_ordner / "config.yaml"
    datei.write_text(
        HAND_WRITTEN
        + "\n  # Mine, the first one.\n  - id: eigene\n    group: cloud   # cloud\n"
        + "    provider: openai_compatible\n"
        + "\n  # Mine, the second one.\n  - id: zweite\n    group: cloud\n"
        + "    provider: openai_compatible\n"
        + "# The end of the list.\n",
        encoding="utf-8",
    )

    assert client.delete("/api/v1/providers/eigene").status_code == 204

    nachher = datei.read_text(encoding="utf-8")
    assert "# Mine, the second one." in nachher
    assert "# Mine, the first one." not in nachher
    assert "# The end of the list." in nachher
    assert "# The server in the cellar." in nachher
    assert nachher.index("# Mine, the second one.") < nachher.index("id: zweite")


def test_a_file_with_the_other_list_style_keeps_it(client, eigener_ordner):
    """Dash flush with its key, the way this program has always written the
    file: the entry comes in that style, not in the other one."""
    flach = "endpoints:\n- id: omlx\n  group: local\n  base_url: http://127.0.0.1:8001/v1\n"
    datei = eigener_ordner / "config.yaml"
    datei.write_text(flach, encoding="utf-8")

    assert _add_own(client, "eigene").status_code == 200

    nachher = datei.read_text(encoding="utf-8")
    assert nachher.startswith(flach)
    assert "\n- id: eigene\n" in nachher
    assert "  - id" not in nachher


def test_a_file_without_comments_reads_back_the_same(client, eigener_ordner):
    """Silence probe: nothing to keep, nothing changes but the new entry."""
    plain = "app:\n  port: 8090\nendpoints:\n- id: omlx\n  group: local\n"
    datei = eigener_ordner / "config.yaml"
    datei.write_text(plain, encoding="utf-8")
    before = yaml.safe_load(plain)

    _add_own(client, "eigene")

    after = yaml.safe_load(datei.read_text(encoding="utf-8"))
    assert after["app"] == before["app"]
    assert after["endpoints"][0] == before["endpoints"][0]
    assert [e["id"] for e in after["endpoints"]] == ["omlx", "eigene"]
