"""The list of the settings in the sidebar: its rows, its dots, its hand-offs.

Five groups of rows; a server's dot only while the server runs (the picture
server keeps its own states); a row of the other menus hands the part to show
over once; the version row stands only where the shell reports one.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

WURZEL = Path(__file__).resolve().parent.parent
SRC = WURZEL / "frontend" / "src"


def _lesen(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def _such(muster: str, text: str) -> re.Match[str]:
    treffer = re.search(muster, text)
    assert treffer, muster
    return treffer


def _node(code: str) -> Any:
    ergebnis = subprocess.run(
        ["node", "--input-type=module", "-e", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return json.loads(ergebnis.stdout)


def _daten() -> dict[str, Any]:
    return _node(
        f"""
        import {{ GRUPPEN, SERVER, SEITEN }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        console.log(JSON.stringify({{ GRUPPEN, SERVER, SEITEN }}))
        """
    )


def _katalog(sprache: str) -> dict[str, Any]:
    return json.loads(_lesen(WURZEL / "app" / "locales" / f"{sprache}.json"))


def _text(katalog: dict[str, Any], schluessel: str) -> str | None:
    teil = katalog
    for stueck in schluessel.split("."):
        if not isinstance(teil, dict) or stueck not in teil:
            return None
        teil = teil[stueck]
    return teil if isinstance(teil, str) else None


def test_five_groups_with_their_rows_in_order():
    gruppen = _daten()["GRUPPEN"]
    assert [g["name"] for g in gruppen] == ["oberflaeche", "verhalten", "modelle", "server", "system"]
    zeilen = {g["name"]: [z["id"] for z in g["zeilen"]] for g in gruppen}
    assert zeilen["oberflaeche"] == ["darstellung", "sprache", "meldungen", "shortcuts"]
    assert zeilen["verhalten"] == ["system", "memory", "skills", "cronjobs", "agent"]
    assert zeilen["modelle"] == ["lokal", "cloud", "katalog", "downloads"]
    assert zeilen["server"] == [
        "overview",
        "server:server",
        "server:agent",
        "server:einbettung",
        "server:sprache",
        "server:bereinigung",
        "server:bild",
        "tools",
        "werkzeuge",
        "web_app",
    ]
    assert zeilen["system"] == ["zugangsdaten", "konfiguration", "tools_datei", "hilfe", "updates"]


def test_every_row_has_a_sign_a_text_in_both_languages_and_a_target():
    daten = _daten()
    hauszeichen = _lesen(SRC / "teile" / "Hauszeichen.svelte")
    fensterzeichen = _lesen(SRC / "teile" / "Fensterzeichen.svelte")
    en, de = _katalog("en"), _katalog("de")
    gesehen = set()
    for gruppe in daten["GRUPPEN"]:
        assert _text(en, gruppe["titel"]) and _text(de, gruppe["titel"]), gruppe["titel"]
        for zeile in gruppe["zeilen"]:
            assert zeile["id"] not in gesehen, zeile["id"]
            gesehen.add(zeile["id"])
            assert ("zeichen" in zeile) != ("fenster" in zeile), zeile["id"]
            if "zeichen" in zeile:
                assert re.search(rf"\b{zeile['zeichen']}\b", hauszeichen), zeile
            else:
                assert zeile["fenster"] in fensterzeichen, zeile
            assert _text(en, zeile["titel"]) and _text(de, zeile["titel"]), zeile["titel"]
            assert len(zeile["ziel"]) >= 1, zeile["id"]


def test_the_servers_are_the_ones_the_local_page_keeps():
    lokal = _lesen(SRC / "teile" / "ModelleLokal.svelte")
    namen = re.findall(r"^  const [A-Z]+ = '([a-z]+)'$", lokal, re.M)
    server = [s["name"] for s in _daten()["SERVER"]]
    # The model server is the page's fallback window and has no constant of its own.
    assert server[0] == "server" and server[1:] == [n for n in namen if n in server]
    assert sorted(server) == sorted(["server", "agent", "einbettung", "sprache", "bereinigung", "bild"])


def test_a_row_of_the_page_itself_leads_to_a_page_with_a_title():
    seiten = _daten()["SEITEN"]
    assert {"darstellung", "sprache", "meldungen", "shortcuts", "system", "memory", "skills",
            "cronjobs", "agent", "tools", "werkzeuge", "web_app", "zugangsdaten", "konfiguration",
            "tools_datei"} == set(seiten)


def _serverpunkt(stand: dict[str, Any], name: str) -> Any:
    quelle = _lesen(SRC / "lib" / "serverstand.svelte.js")
    farbe = _such(r"export const BILDFARBE = (\{[^}]*\})", quelle).group(1)
    funktion = _such(r"export function serverPunkt\(name\) \{([\s\S]*?)\n\}\n", quelle).group(1)
    return _node(
        f"""
        const BILDFARBE = {farbe}
        const serverstand = {json.dumps(stand)}
        function serverPunkt(name) {{{funktion}}}
        console.log(JSON.stringify(serverPunkt({json.dumps(name)})))
        """
    )


def test_a_server_has_a_dot_only_while_it_runs():
    stand = {
        "server": {"laeuft": True},
        "agent": {"laeuft": False},
        "einbettung": None,
        "sprache": {},
    }
    assert _serverpunkt(stand, "server") == "gruen"
    # Silence probe: stopped, unknown and empty reports draw nothing.
    for name in ("agent", "einbettung", "sprache", "bereinigung"):
        assert _serverpunkt(stand, name) is None, name


def test_the_picture_server_keeps_its_own_states():
    for zustand, erwartet in (("bereit", "gruen"), ("zeichnet", "blau"), ("fehler", "rot"),
                              ("gestoppt", None), ("", None)):
        assert _serverpunkt({"bild": {"zustand": zustand}}, "bild") == erwartet, zustand
    assert _serverpunkt({"bild": None}, "bild") is None


def test_the_local_page_reads_the_reports_the_list_reads():
    """One rhythm and one place for what the six servers report: the dot beside
    a server and the dot of the overview cannot disagree, and the page asks for
    nothing the list already asks for."""
    lokal = _lesen(SRC / "teile" / "ModelleLokal.svelte")
    assert "serverstand.svelte.js" in lokal
    assert "return serverstandHalten()" in lokal
    assert not re.search(r"const BILDFARBE\b", lokal)
    for anfrage in ("einbettungAuskunft", "spracheAuskunft", "bereinigungAuskunft", "turboStand", "agentenmodellAuskunft"):
        assert f"api.{anfrage}(" not in lokal, anfrage
    # The faster beat of the model server also moves its dot in the list.
    assert "reportServerState('server', a)" in lokal


def test_the_servers_are_asked_only_while_a_list_stands():
    quelle = _lesen(SRC / "lib" / "serverstand.svelte.js")
    assert "if (halter === 1)" in quelle and "if (halter === 0)" in quelle
    assert "pollWithoutOverlap(holen, TAKT_MS)" in quelle and "stoppen?.()" in quelle
    liste = _lesen(SRC / "teile" / "Einstellungsliste.svelte")
    assert "$effect(() => serverstandHalten())" in liste


def test_the_version_row_stands_only_where_the_shell_reports_a_version():
    liste = _lesen(SRC / "teile" / "Einstellungsliste.svelte")
    assert "updates.present && Boolean(updates.version)" in liste
    assert "zeile.id !== 'updates' || mitUpdates" in liste
    assert "g.zeilen.filter(sichtbar)" in liste


def _gewaehlt(ziel: dict[str, Any], stand: str = "none", innen: bool = False) -> dict[str, Any]:
    """What `chooseRow` does with a row, read off its source. `innen`: called
    from the settings window, which takes its own pages itself."""
    quelle = _lesen(SRC / "lib" / "settingsrow.js")
    waehlen = _such(
        r"export function chooseRow\(row, \{ page = openSettingsPage, look = \(\) => \{\} \} = \{\}\) \{([\s\S]*?)\n\}\n", quelle
    ).group(1)
    oeffnen = _such(r"export function openSettingsPage\(art\) \{([\s\S]*?)\n\}\n", quelle).group(1)
    return _node(
        f"""
        const zustand = {{ lokalWunsch: null, katalogArtWunsch: null, promptStart: null }}
        const spur = []
        const handbuchOeffnen = () => spur.push(['hilfe'])
        const updates = {{ state: {json.dumps(stand)} }}
        const seiteZeigen = (menu) => spur.push(['menu', menu])
        function openSettingsPage(art) {{{oeffnen}}}
        function chooseRow(row, {{ page = openSettingsPage, look = () => {{}} }} = {{}}) {{{waehlen}}}
        const optionen = {{ look: () => spur.push(['update']) }}
        if ({json.dumps(innen)}) optionen.page = (art) => spur.push(['seite', art])
        chooseRow({{ ziel: {json.dumps(ziel)} }}, optionen)
        console.log(JSON.stringify({{ spur, zustand }}))
        """
    )


def test_a_row_does_what_its_target_says():
    assert _gewaehlt({"art": "sprache"}, innen=True)["spur"] == [["seite", "sprache"]]
    assert _gewaehlt({"hilfe": True})["spur"] == [["hilfe"]]
    assert _gewaehlt({"update": True})["spur"] == [["update"]]
    # A copy kept current by a store, and a look already running, are not asked for again.
    assert _gewaehlt({"update": True}, "store")["spur"] == []
    assert _gewaehlt({"update": True}, "checking")["spur"] == []


def test_a_row_of_the_settings_chosen_outside_them_opens_the_settings_on_its_page():
    """The list stands on the local models and the server pages as well: a row
    of the settings' own pages leads there, and the settings read it once."""
    fuer = _gewaehlt({"art": "cronjobs"})
    assert fuer["spur"] == [["menu", "prompt"]]
    assert fuer["zustand"]["promptStart"] == "cronjobs"
    # Inside the settings the window switches its own page, asking first.
    innen = _gewaehlt({"art": "cronjobs"}, innen=True)
    assert innen["spur"] == [["seite", "cronjobs"]]
    assert innen["zustand"]["promptStart"] is None


def test_a_row_of_the_other_menus_hands_the_part_over_once():
    lokal = _gewaehlt({"menu": "lokal", "server": "sprache"})
    assert lokal["spur"] == [["menu", "lokal"]]
    assert lokal["zustand"]["lokalWunsch"] == "sprache"
    assert lokal["zustand"]["katalogArtWunsch"] is None
    # "Local models" itself: the page without a server window.
    plain = _gewaehlt({"menu": "lokal"})
    assert plain["zustand"]["lokalWunsch"] == "lokal"
    katalog = _gewaehlt({"menu": "katalog", "seite": "downloads"})
    assert katalog["zustand"]["katalogArtWunsch"] == "downloads"
    assert katalog["zustand"]["lokalWunsch"] is None
    cloud = _gewaehlt({"menu": "cloud"})
    assert cloud["spur"] == [["menu", "cloud"]]
    assert cloud["zustand"] == {"lokalWunsch": None, "katalogArtWunsch": None, "promptStart": None}


def test_the_local_models_row_names_no_server():
    zeile = next(z for g in _daten()["GRUPPEN"] for z in g["zeilen"] if z["id"] == "lokal")
    assert zeile["ziel"] == {"menu": "lokal"}


def _aktuelle_zeile(gezeigt: str) -> str:
    """The row of the list the local page stands for, read off its source."""
    quelle = _lesen(SRC / "teile" / "ModelleLokal.svelte")
    ausdruck = _such(r"const currentRow = \$derived\((.*)\)\n", quelle).group(1)
    overview_expr = _such(r"const overview = \$derived\((.*)\)\n", quelle).group(1)
    return _node(
        f"""
        import {{ SERVER }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        const SERVER_PAGES = SERVER
        const OVERVIEW = 'overview'
        const gezeigt = {json.dumps(gezeigt)}
        const serverPage = SERVER_PAGES.find((page) => page.name === gezeigt) ?? null
        const overview = {overview_expr}
        console.log(JSON.stringify({ausdruck}))
        """
    )


def test_the_list_marks_the_server_page_or_local_models_on_the_local_page():
    for name in ("server", "agent", "einbettung", "sprache", "bereinigung", "bild"):
        assert _aktuelle_zeile(name) == f"server:{name}", name
    assert _aktuelle_zeile("overview") == "overview"
    # The table, and a model whose parameters are open: both are "Local models".
    assert _aktuelle_zeile("lokal") == "lokal"
    assert _aktuelle_zeile("some-provider/some-model") == "lokal"


def test_the_list_is_one_component_on_every_page_that_carries_it():
    nav = _lesen(SRC / "teile" / "SettingsNav.svelte")
    lokal = _lesen(SRC / "teile" / "ModelleLokal.svelte").split("<style>", 1)[0]
    prompt = _lesen(SRC / "teile" / "SystemPrompt.svelte")
    cloud = _lesen(SRC / "teile" / "ModelleCloud.svelte").split("<style>", 1)[0]
    assert "<SettingsNav current={currentRow} />" in lokal
    assert '<SettingsNav current="cloud" />' in cloud
    assert "<SettingsNav bind:this={nav} current={art} pick={zeileGewaehlt} jump={schalterGewaehlt} own />" in prompt
    # Without a `pick` a row goes the shared way.
    assert "chooseRow(r, { look })" in nav
    # The figures stand in one place and the settings write theirs into it.
    assert "settingsState.cronjobsAktiv = aktiv" in prompt
    assert "settingsState.look = modus" in prompt
    assert "settingsState.memoryLocal = gedaechtnisSchalter.lokal" in prompt
    # Neither page builds a list of its own any more.
    assert "<Einstellungsliste" not in prompt and "<Einstellungsliste" not in lokal
    assert "<Einstellungsliste" not in cloud
    assert "Menuezeile" not in lokal


def test_the_wishes_are_read_once_and_cleared():
    lokal = _lesen(SRC / "teile" / "ModelleLokal.svelte")
    assert re.search(
        r"if \(offen && zustand\.lokalWunsch\) \{\s*gezeigt = zustand\.lokalWunsch\s*zustand\.lokalWunsch = null",
        lokal,
    )
    katalog = _lesen(SRC / "teile" / "Katalog.svelte")
    assert "'downloads'" in katalog and "dlOeffnen" in katalog


def _suche(code: str) -> Any:
    return _node(
        f"""
        import {{ GRUPPEN, FELDER, zeile }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        import {{ glatt, zeilenFiltern, schalterTreffer, schalterAnspringen }} from '{SRC.as_uri()}/lib/einstellungssuche.js'
        import {{ readFileSync }} from 'node:fs'
        const katalog = JSON.parse(readFileSync('{WURZEL.as_posix()}/app/locales/de.json', 'utf8'))
        const text = (schluessel) => schluessel.split('.').reduce((t, k) => t?.[k], katalog) ?? schluessel
        {textwrap.dedent(code)}
        """
    )


def test_the_search_filters_the_rows_by_their_title_and_drops_empty_groups():
    ergebnis = _suche(
        """
        const namen = (f) => zeilenFiltern(GRUPPEN, f, text).flatMap((g) => g.zeilen.map((z) => z.id))
        console.log(JSON.stringify({
          alle: zeilenFiltern(GRUPPEN, '', text).length,
          sprach: namen('sprach'),
          akzent: namen('TASTENKURZEL'),
          nichts: zeilenFiltern(GRUPPEN, 'xyzxyz', text).length,
          gruppen: zeilenFiltern(GRUPPEN, 'cronjobs', text).map((g) => g.name),
        }))
        """
    )
    assert ergebnis["alle"] == 5
    assert ergebnis["sprach"] == ["sprache", "server:sprache"]
    assert ergebnis["akzent"] == ["shortcuts"]
    assert ergebnis["nichts"] == 0
    assert ergebnis["gruppen"] == ["verhalten"]


def test_the_search_finds_single_switches_as_page_then_switch():
    ergebnis = _suche(
        """
        const hits = (f) => schalterTreffer(FELDER, f, text, zeile).map((h) => h.text)
        console.log(JSON.stringify({
          cloud: hits('cloud'),
          leer: hits(''),
          nichts: hits('xyzxyz'),
          indikator: hits('indikator').length,
        }))
        """
    )
    assert ergebnis["cloud"] and ergebnis["cloud"][0].endswith("›") is False
    assert all(" › " in zeile for zeile in ergebnis["cloud"])
    assert any(zeile.startswith("Gedächtnis › ") for zeile in ergebnis["cloud"])
    assert ergebnis["leer"] == []
    assert ergebnis["nichts"] == []
    assert ergebnis["indikator"] == 4


def test_every_findable_switch_is_on_its_page_and_in_both_catalogues():
    daten = _node(
        f"""
        import {{ FELDER, zeile }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        console.log(JSON.stringify(FELDER.map((f) => ({{ ...f, gefunden: Boolean(zeile(f.zeile)) }}))))
        """
    )
    seiten = {
        "meldungen": "Meldewahl.svelte",
        "system": "SystemPrompt.svelte",
        "memory": "SystemPrompt.svelte",
        "skills": "Skillmaske.svelte",
        "server:server": "Serverregler.svelte",
        "server:sprache": "Sprachserver.svelte",
    }
    en, de = _katalog("en"), _katalog("de")
    for feld in daten:
        assert feld["gefunden"], feld
        quelle = _lesen(SRC / "teile" / seiten[feld["zeile"]])
        schluessel = feld["titel"]
        if schluessel.startswith("meldewesen.") and f"t('{schluessel}')" not in quelle:
            # The notifications page builds some names from two lists.
            assert f"'{schluessel.split('.', 1)[1].removeprefix('punkt_')}'" in quelle, feld
        else:
            assert f"beschriftung={{t('{schluessel}')}}" in quelle, feld
        assert _text(en, schluessel) and _text(de, schluessel), feld


def test_no_permanent_switch_of_a_searched_page_is_missing_from_the_list():
    """Silence probe the other way round: a switch added to one of these pages
    without a place in the search list stays unfindable."""
    felder = {f["titel"] for f in _daten_felder()}
    for name in ("Meldewahl", "Skillmaske", "Serverregler", "Sprachserver"):
        quelle = _lesen(SRC / "teile" / f"{name}.svelte")
        for schluessel in re.findall(r"<Schalter[\s\S]*?beschriftung=\{t\('([a-z_.]+)'\)\}", quelle):
            assert schluessel in felder, (name, schluessel)
    praegen = _lesen(SRC / "teile" / "Meldewahl.svelte")
    namen = re.findall(r"const (?:PUNKTE|MELDER) = \[([^\]]*)\]", praegen)
    assert len(namen) == 2
    for liste in namen:
        for name in re.findall(r"'([a-z]+)'", liste):
            assert f"meldewesen.{name}" in felder or f"meldewesen.punkt_{name}" in felder, name
    prompt = _lesen(SRC / "teile" / "SystemPrompt.svelte")
    for schluessel in re.findall(r"<Schalter[^>]*beschriftung=\{t\('([a-z_.]+)'\)\}", prompt):
        assert schluessel in felder, schluessel


def _daten_felder() -> list[dict[str, str]]:
    return _node(
        f"""
        import {{ FELDER }} from '{SRC.as_uri()}/lib/einstellungsliste.js'
        console.log(JSON.stringify(FELDER))
        """
    )


def test_the_jump_scrolls_to_the_switch_and_focuses_it_and_can_be_stopped():
    ergebnis = _suche(
        """
        const spur = []
        const schalter = {
          getAttribute: () => 'Sounds', offsetParent: {},
          scrollIntoView: () => spur.push('scroll'), focus: () => spur.push('fokus'),
          animate: () => spur.push('blitz'),
        }
        const wurzel = { querySelectorAll: () => [schalter] }
        globalThis.requestAnimationFrame = (f) => setTimeout(f, 0)
        schalterAnspringen('Sounds', wurzel)
        const keiner = { querySelectorAll: () => [] }
        let abfragen = 0
        const zaehler = { querySelectorAll: () => { abfragen += 1; return [] } }
        const stopp = schalterAnspringen('Nicht da', zaehler)
        stopp()
        await new Promise((r) => setTimeout(r, 30))
        console.log(JSON.stringify({ spur, abfragen }))
        """
    )
    assert ergebnis["spur"] == ["scroll", "fokus", "blitz"]
    # One look at the start, none after the stop.
    assert ergebnis["abfragen"] == 1


def test_the_search_field_is_bound_and_a_hit_hands_the_switch_to_the_page():
    liste = _lesen(SRC / "teile" / "Einstellungsliste.svelte")
    assert "bind:value={frage}" in liste
    assert "e.key === 'Escape' && frage" in liste
    assert "onclick={() => springen(hit.feld)}" in liste
    # No ⌘K badge in the settings: ⌘K stays the chat search.
    assert "kbd" not in liste
    prompt = _lesen(SRC / "teile" / "SystemPrompt.svelte")
    assert "jump={schalterGewaehlt}" in prompt
    # Where the page passes none, the list jumps by itself: its page opens, then the switch.
    nav = _lesen(SRC / "teile" / "SettingsNav.svelte")
    assert "springen={jump ?? jumpToSwitch}" in nav
    assert re.search(
        r"await choose\(rowOfList\(field\.zeile\)\)\s*stopJump = schalterAnspringen\(t\(field\.titel\)\)", nav
    )
    assert "async function schalterGewaehlt(feld)" in prompt
    # The jump follows the page change, and only a page that really changed.
    assert re.search(
        r"await zeileGewaehlt\(zeile\)\s*//[^\n]*\n\s*if \(zeile\.ziel\.art && art !== zeile\.ziel\.art\) return\s*"
        r"anspringenStopp = schalterAnspringen\(t\(feld\.titel\)\)",
        prompt,
    )
    assert "anspringenStopp?.()" in prompt


def test_the_updates_row_wears_the_update_sign():
    zeile = next(
        z
        for g in _daten()["GRUPPEN"]
        for z in g["zeilen"]
        if z["id"] == "updates"
    )
    assert zeile["zeichen"] == "update_available"
    assert "zeichen === 'update_available'" in _lesen(SRC / "teile" / "Hauszeichen.svelte")
    assert "update_available" in _lesen(WURZEL / "THIRD_PARTY_NOTICES.md")


def test_the_update_answer_stands_in_the_row_of_the_list_and_no_block_under_it():
    nav = _lesen(SRC / "teile" / "SettingsNav.svelte")
    assert "Updatezeile" not in nav
    assert "nurErgebnis" not in _lesen(SRC / "teile" / "Updatezeile.svelte")
    # The settings ask through the list for the look; a copy a store keeps
    # current and a look or a fetch already running are not asked again.
    assert "nav?.look()" in _lesen(SRC / "teile" / "SystemPrompt.svelte")
    assert "['store', 'checking', 'downloading'].includes(updates.state)" in _lesen(SRC / "lib" / "settingsrow.js")


def test_a_failed_report_clears_the_dot_and_the_last_list_leaving_clears_all():
    quelle = _lesen(SRC / "lib" / "serverstand.svelte.js")
    assert ".catch(() => setzen(name, null))" in quelle
    assert re.search(r"stoppen\?\.\(\)\s*stoppen = null\s*leeren\(\)", quelle)


def test_the_look_picture_uses_the_frames_own_brightness_rule():
    """The picture of the own gradient decides light or dark the way the frame
    does: same mean brightness, same threshold."""
    zustand = _lesen(SRC / "lib" / "zustand.svelte.js")
    vorschau = _lesen(SRC / "lib" / "looksvorschau.js")
    formel = "0.2126 * r + 0.7152 * g + 0.0722 * b"
    assert formel in zustand and formel in vorschau
    assert "farben.length > 0.45" in zustand and "farben.length > 0.45" in vorschau


def test_a_late_report_never_overwrites_a_newer_round_or_a_cleared_list():
    quelle = _lesen(SRC / "lib" / "serverstand.svelte.js")
    assert "const mein = ++runde" in quelle
    assert "if (mein === runde) serverstand[name] = wert" in quelle
    assert re.search(r"function leeren\(\) \{\s*runde \+= 1", quelle)


def test_the_first_card_takes_the_tab_stop_when_no_card_is_chosen():
    quelle = _lesen(SRC / "teile" / "Looktafel.svelte")
    assert "optionen.some(([look]) => look === wert)" in quelle
    assert "tabindex={wert === look || (!bekannt && i === 0) ? 0 : -1}" in quelle


def test_a_search_without_a_hit_says_so_with_the_text_of_the_chat_list():
    liste = _lesen(SRC / "teile" / "Einstellungsliste.svelte")
    assert re.search(
        r"\{#if frage\.trim\(\) && !gruppen\.length && !treffer\.length\}\s*<!--[^>]*-->\s*"
        r"<div class=\"menuegruppe\">\{t\('chat\.keine_treffer'\)\}</div>",
        liste,
    )
    # No key of its own: the chat list's text is the one that is read.
    for sprache, text in (("de", "Keine Treffer"), ("en", "No matches")):
        assert _katalog(sprache)["chat"]["keine_treffer"] == text
