"""The server overview of the settings: one row for the page in the list, a table
of the six local servers with state, port, chosen model and a button that
starts or stops each without its window, a bar for the wired memory measured
against the system's limit, and a table of the MCP servers that are set up.

The rules of a row run as written (lib/serverOverviewRows.js) in node; the
pages are read from their source, like the other pages of the settings; the
answers of the servers are asked of the running service.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from app import runnermodellwahl

WURZEL = Path(__file__).resolve().parent.parent
SRC = WURZEL / "frontend" / "src"


def _read(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def _node(code: str) -> Any:
    ergebnis = subprocess.run(
        ["node", "--input-type=module", "-e", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return json.loads(ergebnis.stdout)


def _rows(reports: dict[str, Any], busy: dict[str, bool] | None = None, agent_loading: bool = False) -> list[dict]:
    """The rows the overview draws for these reports, one per server of the list."""
    return _node(
        f"""
        import {{ SERVER }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        import {{ overviewRow }} from '{SRC.as_uri()}/lib/serverOverviewRows.js'
        const reports = {json.dumps(reports)}
        const busy = {json.dumps(busy or {})}
        const rows = SERVER.map((server) =>
          overviewRow(server, reports[server.name], {{ busy: Boolean(busy[server.name]), agentLoading: {json.dumps(agent_loading)} }}))
        console.log(JSON.stringify(rows.map((r) => ({{ ...r, mark: r.mark ? true : false }}))))
        """
    )


READY = {"laeuft": False, "selected_model": "model.gguf", "programm": "/bin/llama", "port": 8081}


# --- The row of the list --------------------------------------------------------


def test_the_list_has_a_row_overview_first_in_the_group_of_the_servers():
    daten = _node(
        f"""
        import {{ GRUPPEN }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        console.log(JSON.stringify(GRUPPEN.find((g) => g.name === 'server').zeilen[0]))
        """
    )
    assert daten == {
        "id": "overview",
        "zeichen": "ranking_bars",
        "titel": "server_overview.row",
        "ziel": {"menu": "lokal", "server": "overview"},
    }


def test_the_row_says_how_many_of_the_six_run():
    state = _read(SRC / "lib" / "settingsState.svelte.js")
    expression = re.search(r"case 'overview':\s*//[^\n]*\n\s*return (.*)\n", state)
    assert expression
    serverstand = _read(SRC / "lib" / "serverstand.svelte.js")
    active_fn = re.search(r"export function serverActive\(name\) \{[\s\S]*?\n\}\n", serverstand)
    assert active_fn
    # It asks the one rule of what runs, the same the rows of the table use.
    assert "return isRunning(name, serverstand[name])" in active_fn.group(0)

    def count(reports: dict[str, Any]) -> str:
        return _node(
            f"""
            import {{ SERVER }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
            import {{ isRunning }} from '{SRC.as_uri()}/lib/serverOverviewRows.js'
            const serverstand = {json.dumps(reports)}
            {active_fn.group(0).replace("export ", "")}
            console.log(JSON.stringify({expression.group(1)}))
            """
        )

    assert count({}) == "0/6"
    assert count({"server": {"laeuft": True}}) == "1/6"
    # The picture server counts while it draws, not while it has failed.
    assert count({"bild": {"zustand": "zeichnet"}, "agent": {"laeuft": True}}) == "2/6"
    assert count({"bild": {"zustand": "fehler"}}) == "0/6"


# --- The rows of the table -----------------------------------------------------


def test_there_are_six_rows_in_the_order_of_the_list():
    rows = _rows({})
    assert [r["name"] for r in rows] == ["server", "agent", "einbettung", "sprache", "bereinigung", "bild"]
    assert [r["zeichen"] for r in rows] == ["server", "agent", "einbettung", "sprache_welle", "besen", "bild"]


def test_the_state_is_a_word_by_what_the_server_reports():
    rows = {
        r["name"]: r
        for r in _rows(
            {
                "server": {"laeuft": True},
                "agent": {"laeuft": False},
                "bild": {"zustand": "zeichnet"},
            }
        )
    }
    assert rows["server"]["state"] == "active"
    assert rows["agent"]["state"] == "inactive"
    # A server nobody could read is not claimed to run.
    assert rows["einbettung"]["state"] == "inactive"
    # The picture server drawing counts as active; failed is its own word.
    assert rows["bild"]["state"] == "active"
    assert _rows({"bild": {"zustand": "fehler"}})[5]["state"] == "failed"
    assert _rows({"bild": {"zustand": "aus"}})[5]["state"] == "inactive"
    # Only the picture server has a failed state.
    assert _rows({"server": {"laeuft": False, "zustand": "fehler"}})[0]["state"] == "inactive"


def test_the_port_comes_from_the_answer_also_while_the_server_stands():
    rows = _rows({"server": {"laeuft": False, "port": 8080}, "bild": {"zustand": "aus", "port": 8191}})
    assert rows[0]["port"] == 8080
    assert rows[5]["port"] == 8191
    assert rows[1]["port"] is None


def test_the_model_is_the_chosen_one_also_while_the_server_stands_and_a_dash_without_a_choice():
    rows = _rows(
        {
            "server": {"laeuft": False, "selected_model": "qwen3-8b-q4.gguf", "modell": None},
            "agent": {"laeuft": False, "selected_model": None},
        }
    )
    assert rows[0]["model"] == "qwen3-8b-q4.gguf"
    assert rows[1]["model"] == ""
    # The logo only where the house finds one for the name; a name it does not know gets its first letter.
    assert rows[0]["mark"] is True
    assert rows[1]["mark"] is False
    unknown = _rows({"server": {"selected_model": "zzz-unknown-model.gguf"}})[0]
    assert unknown["mark"] is False and unknown["letter"] == "Z"
    assert rows[1]["letter"] == ""


# --- The button ----------------------------------------------------------------


def test_each_button_is_locked_where_the_one_in_the_window_is():
    # Nothing chosen to start: the model server and the agent server.
    assert _rows({"server": {"laeuft": False, "selected_model": None}})[0]["blocked"] is True
    assert _rows({"server": {**READY}})[0]["blocked"] is False
    assert _rows({"agent": {"laeuft": False, "selected_model": None}})[1]["blocked"] is True
    # The three that need a program as well as a file.
    for index, name in ((2, "einbettung"), (3, "sprache"), (4, "bereinigung")):
        assert _rows({name: {**READY}})[index]["blocked"] is False, name
        assert _rows({name: {**READY, "programm": None}})[index]["blocked"] is True, name
        assert _rows({name: {**READY, "selected_model": None}})[index]["blocked"] is True, name
        # A running server can always be stopped.
        assert _rows({name: {"laeuft": True, "selected_model": None, "programm": None}})[index]["blocked"] is False, name
    # The picture server: a program, and no picture being drawn.
    assert _rows({"bild": {"zustand": "aus", "programm_da": True}})[5]["blocked"] is False
    assert _rows({"bild": {"zustand": "aus", "programm_da": False}})[5]["blocked"] is True
    assert _rows({"bild": {"zustand": "bereit", "programm_da": True, "picture_running": True}})[5]["blocked"] is True


def test_a_server_under_way_waits_and_so_does_the_agent_slot_while_it_loads():
    assert _rows({"server": {**READY}}, busy={"server": True})[0]["blocked"] is True
    assert _rows({"agent": {"laeuft": False, "selected_model": "a.gguf"}}, agent_loading=True)[1]["blocked"] is True
    assert _rows({"agent": {"laeuft": False, "selected_model": "a.gguf"}})[1]["blocked"] is False
    # Nothing known about a server: nothing to start.
    assert _rows({})[0]["blocked"] is True


def test_a_start_goes_out_on_what_is_stored_and_writes_no_number_by_hand():
    control = _read(SRC / "lib" / "serverControl.js")
    # The model server's request carries only the file, as its window's does.
    assert "api.runnerStarten({ modell: report.selected_model })" in control
    # The speech server takes the stored numbers; only the file goes along.
    assert "api.spracheStarten(report.selected_model)" in control
    assert "api.agentenmodellStarten(report.selected_model)" in control
    assert "api.turboStarten(report.selected_model)" in control
    # No second way: nothing is written to the settings from here.
    for writer in ("einstellungSetzen", "einstellungMischen", "werteSetzen"):
        assert writer not in control, writer
    # The picture server without a chosen model says where it is chosen.
    assert "bildserver.kein_standardmodell" in control


def test_the_state_is_read_again_at_once_after_a_start_or_a_stop():
    page = _read(SRC / "teile" / "ServerOverview.svelte")
    body = re.search(r"async function toggle\(row\) \{[\s\S]*?\n  \}\n", page)
    assert body
    # In the `finally`, so a refused start is read again as well as an accepted one,
    # and the button waits for that read before it unlocks.
    assert re.search(r"finally \{[\s\S]*await refreshServerState\(\)[\s\S]*busy\[row\.name\] = false", body.group(0))
    # What the server does now decides between start and stop, not a report up to fifteen seconds old.
    assert re.search(r"await refreshServerState\(\)\s*const report = serverstand\[row\.name\]", body.group(0))
    # A failed start says so, as the window does.
    assert "melde(String(error.message || error), 'fehler')" in body.group(0)
    serverstand = _read(SRC / "lib" / "serverstand.svelte.js")
    refresh = re.search(r"export async function refreshServerState\(\) \{[\s\S]*?\n\}\n", serverstand)
    assert refresh
    # It waits for the newest round: one that began meanwhile (the list's own beat) replaced its answers.
    assert "while (lauf !== neueste)" in refresh.group(0)


# --- The page --------------------------------------------------------------------


def test_the_page_has_the_bar_the_table_and_the_mcp_table():
    page = _read(SRC / "teile" / "ServerOverview.svelte").split("<style>", 1)[0]
    assert "<MemoryBar inline {wired} {total} />" in page
    for key in ("server_overview.local_servers", "server_overview.status", "modell.spalte_server",
                "modell.feld_port", "modell.spalte_modell", "server_overview.mcp_heading"):
        assert key in page, key
    # The word of the state, in its own colour, with no box and no dot beside it.
    assert "{t('status.fehler')}" in page and "{t('einstellungen.aktiv')}" in page
    assert "Leuchtpunkt" not in page
    # The button is the existing one, unchanged.
    assert "<Startknopf" in page and "modell.server_anhalten" in page and "modell.server_starten" in page
    # The MCP table: the rows are the cards the MCP page draws, each one a way in to that page.
    assert "setUpCards(cardsOf(mcpEntries), mcpStatus)" in page
    assert 'zeichen="chevron_right"' in page and "openSettingsPage('tools')" in page
    assert "stateText(card, stand, t)" in page and "punktFarbe(stand)" in page
    # Its head carries the words of the local table's head, over the same tracks.
    mcp_table = page.split("server_overview.mcp_heading", 2)[2]
    assert "modell.spalte_server" in mcp_table and "server_overview.status" in mcp_table
    # The chosen model wears the logo of its maker.
    assert "<OwnerMark mark={row.mark} letter={row.letter} size={18} />" in page
    assert "serverStand" not in page


def test_the_local_page_shows_the_overview_with_its_own_head_and_without_the_bar_in_it():
    page = _read(SRC / "teile" / "ModelleLokal.svelte").split("<style>", 1)[0]
    head = page.split("{#snippet kopf()}", 1)[1].split("{/snippet}", 1)[0]
    assert "t('server_overview.heading')" in head
    # The bar stands in the body of the overview; the head's bar and facts are the other pages'.
    assert "{#if !overview}" in head
    assert "<ServerOverview wired={speicher?.wired_gb ?? null} total={wiredTotal} />" in page
    assert "const wiredTotal = $derived(speicher?.wired_limit_gb ?? speicher?.gesamt_gb ?? maschineGb)" in page


def test_the_bar_has_a_one_line_form_and_keeps_its_two_line_form():
    bar = _read(SRC / "teile" / "MemoryBar.svelte")
    assert "inline = false" in bar and "{#if inline}" in bar
    inline = bar.split("{#if inline}", 1)[1].split("{:else}", 1)[0]
    # No sign in the line.
    assert "Hauszeichen" not in inline and "modell.wired_label" in inline
    assert 'zeichen="chip_bolt"' in bar.split("{:else}", 1)[1]


def test_the_server_windows_are_not_touched():
    for name in ("Modellserver", "Agentserver", "Einbettungsserver", "Sprachserver", "Bereinigungsserver", "Bildserver"):
        source = _read(SRC / "teile" / f"{name}.svelte")
        assert "selected_model" not in source, name


def test_the_texts_stand_in_both_languages():
    de = json.loads(_read(WURZEL / "app" / "locales" / "de.json"))["server_overview"]
    en = json.loads(_read(WURZEL / "app" / "locales" / "en.json"))["server_overview"]
    assert de == {
        "row": "Übersicht",
        "heading": "Server",
        "local_servers": "Lokale Server",
        "status": "Zustand",
        "inactive": "Inaktiv",
        "mcp_heading": "MCP-Verbindungen",
    }
    assert en == {
        "row": "Overview",
        "heading": "Servers",
        "local_servers": "Local servers",
        "status": "Status",
        "inactive": "Inactive",
        "mcp_heading": "MCP connections",
    }


# --- What the services answer ---------------------------------------------------


class _StoredChoice:
    """A stand-in for the stored settings that answers one stored choice."""

    def __init__(self, stored):
        self.einstellungen = self
        self._stored = stored

    def zusammengefuehrt(self, schluessel, vorgabe=None):
        return {"modell": self._stored}


def test_the_chosen_file_of_the_model_server_follows_the_window_rule():
    names = ["a.gguf", "b.gguf"]
    # A stored choice that is still in the folder.
    assert runnermodellwahl.selected_file(_StoredChoice("b.gguf"), names) == "b.gguf"
    # Nobody has chosen yet, or the file has gone: the first one, as the window pre-picks it.
    assert runnermodellwahl.selected_file(_StoredChoice(None), names) == "a.gguf"
    assert runnermodellwahl.selected_file(_StoredChoice("gone.gguf"), names) == "a.gguf"
    # A chosen "no model" stays none.
    assert runnermodellwahl.selected_file(_StoredChoice(""), names) is None
    # An empty folder.
    assert runnermodellwahl.selected_file(_StoredChoice(None), []) is None


def test_every_server_answers_the_chosen_model_next_to_the_running_one(client):
    for pfad in (
        "/api/v1/runner",
        "/api/v1/agentenmodell",
        "/api/v1/einbettungsserver",
        "/api/v1/sprachserver",
        "/api/v1/bereinigungsserver",
        "/api/v1/bild/turbo",
    ):
        antwort = client.get(pfad)
        assert antwort.status_code == 200, pfad
        daten = antwort.json()
        assert "selected_model" in daten, pfad
        assert daten["selected_model"] is None or isinstance(daten["selected_model"], str), pfad
        # `modell` keeps its meaning: the file that runs — nothing runs here.
        assert daten["modell"] is None or not daten.get("laeuft", False), pfad


def test_the_picture_server_answers_its_port_also_while_it_stands(client):
    daten = client.get("/api/v1/bild/turbo").json()
    assert daten["zustand"] == "aus"
    assert isinstance(daten["port"], int) and daten["port"] > 1024
    assert daten["modell"] is None


def test_the_chosen_agent_file_is_only_one_that_is_in_the_folder(client):
    # Nothing is chosen here, so nothing is offered — a name that is not in the folder would unlock a start that cannot work.
    assert client.get("/api/v1/agentenmodell").json()["selected_model"] is None


def test_the_chosen_picture_model_is_looked_for_as_one_entry_not_in_the_whole_folder(tmp_path):
    from app import bildrunner

    (tmp_path / "model.safetensors").write_bytes(b"\0" * 64)
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert bildrunner.is_image_model(tmp_path, "model.safetensors") is True
    # Not a model file, not there, and names that are paths.
    assert bildrunner.is_image_model(tmp_path, "notes.txt") is False
    assert bildrunner.is_image_model(tmp_path, "gone.safetensors") is False
    assert bildrunner.is_image_model(tmp_path, "../model.safetensors") is False
    assert bildrunner.is_image_model(tmp_path, "") is False
    # The list and the single look agree.
    assert bildrunner.modelle(tmp_path) == ["model.safetensors"]


def test_a_picture_model_unchanged_since_the_last_look_is_not_read_again(tmp_path, monkeypatch):
    from app import bildinhalt, bildrunner

    reads = []

    def sorte(path):
        reads.append(path)
        return bildinhalt.UNBEKANNT if hasattr(bildinhalt, "UNBEKANNT") else "unbekannt"

    monkeypatch.setattr(bildinhalt, "sorte", sorte)
    bildrunner._image_model_memory.clear()
    (tmp_path / "model.safetensors").write_bytes(b"\0" * 64)
    assert bildrunner.is_image_model(tmp_path, "model.safetensors") is True
    assert bildrunner.is_image_model(tmp_path, "model.safetensors") is True
    assert len(reads) == 1
    # A changed file is looked at again.
    (tmp_path / "model.safetensors").write_bytes(b"\0" * 128)
    bildrunner.is_image_model(tmp_path, "model.safetensors")
    assert len(reads) == 2


# --- The logo of a chosen model --------------------------------------------------


def _file_marks(names: list[str]) -> list[str | None]:
    """The key of the logo `fileMark` finds for each file name (the logo's own svg stands for itself)."""
    return _node(
        f"""
        import {{ fileMark }} from '{SRC.as_uri()}/lib/fileMark.js'
        import {{ LOGOS }} from '{SRC.as_uri()}/lib/logos.js'
        const keys = Object.fromEntries(Object.entries(LOGOS).map(([key, mark]) => [key, mark]))
        const find = (mark) => (mark ? Object.keys(keys).find((key) => keys[key] === mark) ?? '?' : null)
        console.log(JSON.stringify({json.dumps(names)}.map((name) => find(fileMark(name)))))
        """
    )


def test_a_file_of_the_catalogue_wears_the_logo_of_the_maker_of_its_card():
    qwen, accio, projector = _file_marks(
        ["Qwen3.8-27B-Q4_K_M.gguf", "Occamy-1.0.APEX-I-MiniPlus-V2.1.gguf", "mmproj-Accio-Lab_occamy-1.0-Q8_0.gguf"]
    )
    assert qwen == "qwen"
    # The accessory of a card wears the logo of that card, with the file's name in any case.
    assert accio == "accio" and projector == "accio"


def test_a_file_the_catalogue_does_not_list_gets_the_logo_of_its_name_or_none():
    marks = _file_marks(["my-own-qwen3-copy.gguf", "zzz-unknown-model.gguf", ""])
    assert marks[0] == "qwen"
    assert marks[1] is None and marks[2] is None


def test_a_projector_name_several_repositories_share_does_not_wear_the_logo_of_one_card():
    # The catalogue saves such a projector under a name of its own; the plain
    # repository name says nothing about whose it is.
    assert _file_marks(["mmproj-F16.gguf"]) == [None]


def test_the_overview_and_the_mcp_page_read_their_cards_from_one_module():
    shared = _read(SRC / "lib" / "mcpCards.js")
    for name in ("setUpCards", "stateText", "zustand", "titelVon", "logoVon", "punktFarbe"):
        assert re.search(rf"export (function|const) {name}\b", shared), name
    page = _read(SRC / "teile" / "Verbindungen.svelte").split("<style>", 1)[0]
    overview = _read(SRC / "teile" / "ServerOverview.svelte").split("<style>", 1)[0]
    assert "from '../lib/mcpCards.js'" in page and "from '../lib/mcpCards.js'" in overview
    # Neither page keeps a copy of the rules.
    for source in (page, overview):
        assert "function punktFarbe" not in source and "function zustand(" not in source


def test_no_server_set_up_gives_no_row_and_a_dash():
    # The silent case: nothing on file, nothing half set up.
    rows = _node(
        f"""
        import {{ cardsOf, setUpCards }} from '{SRC.as_uri()}/lib/mcpCards.js'
        console.log(JSON.stringify(setUpCards(cardsOf([]), {{}})))
        """
    )
    assert rows == []
    page = _read(SRC / "teile" / "ServerOverview.svelte").split("<style>", 1)[0]
    # The dash stands only for an answer that came and held no server; a failed read says so instead.
    assert re.search(r'\{#if mcpLoaded && !mcpRows\.length\}\s*<p class="empty">-</p>', page)
    assert "mcpLoaded = true" in page and "melde(String(error.message || error), 'fehler')" in page.split("async function loadMcp", 1)[1].split("$effect", 1)[0]
