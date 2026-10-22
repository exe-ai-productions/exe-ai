"""A background run's ending lands on the card of the call that started it.

The finished run used to show up only as a row of its own at the end of the
chat — created seconds after the call, and therefore the newest message for
as long as the answer above it kept writing: a card that never moved under
text that kept growing, wearing the command and "background: true" and no
time, and read as a call that hung. The row stays, for the model (it is the
report the next answer reads) and for the wake that hangs on it; the window
no longer draws it. What the reader gets instead is the call's own card,
filled with the ending — and a dot that moves until an answer has read the
report.

These tests cover the four handles: the call's entry learns its run number,
the ending is written onto the stored entry when the run ends after the
answer, an answer still being written is left to its own closing write, and
the start of the next answer marks the run as read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import hintergrund
from tests.conftest import provider_setzen
from tests.fensterquelle import WINDOW_SOURCE

WURZEL = Path(__file__).resolve().parents[1]


class _Werkstatt:
    """A shell that starts a background run the way the real tool does —
    registered with the run manager, answered with the start sentence — and
    runs nothing at all."""

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
        return [{"type": "function", "function": {"name": "run_command", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return "shell"

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        shell_zeitgrenze=None, **_rest,
    ):
        # Stripped, the way the real tool names its run (app/tools/shell.py).
        lauf = hintergrund.laeufe.anlegen(chat_id, str(argumente["command"]).strip(), True)
        return f"Started in the background as run #{lauf.nummer}."


def _antwort_mit_hintergrundlauf(client, chat_id, befehl="npm install"):
    client.app.state.werkzeuge = _Werkstatt()
    client.app.state.config.features.mcp = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gestartet."],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1", name="run_command",
                    argumente={"command": befehl, "background": True},
                )
            ],
        ),
    )
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Installier das."},
    )
    return [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]


def _antwortzeile(client, chat_id):
    zeilen = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    return [z for z in zeilen if z["role"] == "assistant" and z.get("art", "nachricht") == "nachricht"][-1]


def test_der_aufruf_kennt_seinen_lauf(client, chat_id):
    """The call's entry and the live event both carry the run's number —
    the handle everything below hangs on. The run is still going, so the
    entry has no ending yet."""
    ereignisse = _antwort_mit_hintergrundlauf(client, chat_id)
    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["lauf_nummer"] == 1
    eintrag = _antwortzeile(client, chat_id)["stats"]["werkzeuge"][0]
    assert eintrag["lauf_nummer"] == 1
    assert "exit_code" not in eintrag
    assert eintrag["ergebnis"].startswith("Started in the background")


def test_das_ende_steht_am_aufruf_wenn_die_antwort_vorbei_ist(client, chat_id):
    """The run ends after the answer did: the stored entry gets output, exit
    code and duration — and the report row for the model is still written."""
    from app.hintergrundmeldung import anmelden

    _antwort_mit_hintergrundlauf(client, chat_id)
    repositories = client.app.state.repositories
    anmelden(repositories)
    lauf = hintergrund.laeufe.holen(chat_id, 1)
    lauf.anhaengen("added 70 packages")
    hintergrund.laeufe.beenden(lauf, 0)
    hintergrund.laeufe.abschluss(lauf, "added 70 packages")

    eintrag = _antwortzeile(client, chat_id)["stats"]["werkzeuge"][0]
    assert eintrag["lauf_nummer"] == 1
    assert eintrag["exit_code"] == 0
    assert eintrag["fehlgeschlagen"] is False
    assert eintrag["ergebnis"] == "added 70 packages"
    assert eintrag["dauer_sekunden"] is not None
    # The window gets the output; the model's copy of the CALL stays the
    # sentence the run itself sent. The output reaches the model in the
    # report row of its own, and a call rewritten with it here would hand
    # the model its own result twice.
    assert eintrag["ergebnis_modell"].startswith("Started in the background")

    zeilen = repositories.messages.auflisten(chat_id=chat_id)
    assert zeilen[-1].art == "werkzeugmeldung"
    assert zeilen[-1].stats["werkzeuge"][0]["lauf_nummer"] == 1
    assert zeilen[-1].stats["werkzeuge"][0]["ergebnis_modell"] == "added 70 packages"


def test_ein_gescheiterter_lauf_traegt_seinen_code_an_den_aufruf(client, chat_id):
    from app.hintergrundmeldung import anmelden

    _antwort_mit_hintergrundlauf(client, chat_id, befehl="npm test")
    anmelden(client.app.state.repositories)
    lauf = hintergrund.laeufe.holen(chat_id, 1)
    hintergrund.laeufe.beenden(lauf, 1)
    hintergrund.laeufe.abschluss(lauf, "1 test failed")

    eintrag = _antwortzeile(client, chat_id)["stats"]["werkzeuge"][0]
    assert eintrag["exit_code"] == 1
    assert eintrag["fehlgeschlagen"] is True
    assert eintrag["ergebnis"] == "1 test failed"


def test_eine_laufende_antwort_wird_von_aussen_nicht_angefasst(client, chat_id):
    """While the answer is still being written its log lives in memory and is
    stored at its own end; a row rewritten from outside would only be
    overwritten. So the handler leaves a row that says `laeuft` alone."""
    from app.hintergrundmeldung import anmelden

    repositories = client.app.state.repositories
    lauf = hintergrund.laeufe.anlegen(chat_id, "make", True)
    zeile = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft",
        stats={"werkzeuge": [{
            "name": "run_command", "server": "shell",
            "argumente": {"command": "make", "background": True},
            "fehlgeschlagen": False, "ergebnis": "Started in the background as run #1.",
            "bild": None, "dauer_sekunden": 0.001, "lauf_nummer": lauf.nummer,
        }]},
    )
    anmelden(repositories)
    hintergrund.laeufe.beenden(lauf, 0)
    hintergrund.laeufe.abschluss(lauf, "built")

    eintrag = repositories.messages.holen(zeile.id).stats["werkzeuge"][0]
    assert eintrag["ergebnis"].startswith("Started in the background")
    assert "exit_code" not in eintrag


def test_die_schlussschrift_traegt_ein_waehrend_der_antwort_beendetes_ende_nach(chat_id):
    """The closing write's half: an in-memory log whose run has ended gets
    the ending; a run still going is left as it is."""
    from app.hintergrundmeldung import nachtragen

    fertig = hintergrund.laeufe.anlegen(chat_id, "npm run build", True)
    fertig.anhaengen("built in 3s")
    hintergrund.laeufe.beenden(fertig, 0)
    offen = hintergrund.laeufe.anlegen(chat_id, "npm start", True)
    protokoll = [
        {"name": "run_command", "lauf_nummer": fertig.nummer, "ergebnis": "Started", "fehlgeschlagen": False},
        {"name": "run_command", "lauf_nummer": offen.nummer, "ergebnis": "Started", "fehlgeschlagen": False},
        {"name": "read_file", "ergebnis": "text", "fehlgeschlagen": False},
    ]
    nachtragen(protokoll, chat_id)
    assert protokoll[0]["ergebnis"] == "built in 3s"
    assert protokoll[0]["exit_code"] == 0
    assert protokoll[1]["ergebnis"] == "Started"
    assert "exit_code" not in protokoll[1]
    assert protokoll[2] == {"name": "read_file", "ergebnis": "text", "fehlgeschlagen": False}


def test_der_start_der_naechsten_antwort_markiert_den_lauf_als_gelesen(client, chat_id):
    """The next answer's history carries the report, so its start is the
    moment the model has read it: the run says so, the panel's snapshot says
    so, and the chat's stream carries one `lauf_gelesen` for it."""
    _antwort_mit_hintergrundlauf(client, chat_id)
    lauf = hintergrund.laeufe.holen(chat_id, 1)
    hintergrund.laeufe.beenden(lauf, 0)
    assert lauf.gelesen is False
    vorher = client.get(f"/api/v1/laeufe/{chat_id}").json()["ab"]

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Und?"},
    )

    assert lauf.gelesen is True
    schnappschuss = client.get(f"/api/v1/laeufe/{chat_id}").json()
    assert schnappschuss["laeufe"][0]["gelesen"] is True
    assert schnappschuss["ab"] == vorher + 1


def test_der_aufruf_traegt_den_startsatz_und_das_ergebnis_genau_einmal(client, chat_id):
    """The run goes back exactly as it was sent.

    Inside the run the call read "Started in the background as run #1 …";
    the next request rebuilds that round from the stored row
    (app/verlaufsbau.py), so it has to meet the same sentence there. The
    output belongs where it is news — in the report row of its own, which
    the model reads as a service report. It used to stand in both places:
    the call was rewritten with it, and the request carried the same output
    twice.
    """
    from app.hintergrundmeldung import anmelden

    provider = provider_setzen(
        client,
        MockProvider(mock_endpunkt("test"), haeppchen=["Gestartet."]),
    )
    client.app.state.werkzeuge = _Werkstatt()
    client.app.state.config.features.mcp = True
    provider.werkzeugaufrufe = [
        Werkzeugaufruf(
            id="a1", name="run_command",
            argumente={"command": "npm install", "background": True},
        )
    ]
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Installier das."},
    )
    anmelden(client.app.state.repositories)
    lauf = hintergrund.laeufe.holen(chat_id, 1)
    hintergrund.laeufe.beenden(lauf, 0)
    hintergrund.laeufe.abschluss(lauf, "added 70 packages")

    provider.haeppchen = ["Fertig."]
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Und?"},
    )

    gesamter_text = " ".join(n.content for n in provider.letzte_anfrage.nachrichten)
    assert gesamter_text.count("added 70 packages") == 1
    assert "Started in the background" in gesamter_text


def test_ein_laufender_lauf_gilt_nicht_als_gelesen(chat_id):
    offen = hintergrund.laeufe.anlegen(chat_id, "sleep 100", True)
    fertig = hintergrund.laeufe.anlegen(chat_id, "ls", True)
    hintergrund.laeufe.beenden(fertig, 0)
    assert hintergrund.laeufe.als_gelesen_melden(chat_id) == [fertig.nummer]
    assert offen.gelesen is False and fertig.gelesen is True
    # Said once: a second start finds nothing new to say.
    assert hintergrund.laeufe.als_gelesen_melden(chat_id) == []


def test_das_fenster_zeichnet_die_berichtszeile_nicht_und_fuellt_die_karte():
    """The window's half, pinned at the source: the chat skips report rows,
    the terminal stream writes the ending onto the call's card and hears
    the read mark, and the card wears the dot."""
    app = WINDOW_SOURCE.read_text(encoding="utf-8")
    assert "(nachricht.art ?? 'nachricht') !== 'werkzeugmeldung'" in app
    assert "eintrag.lauf_nummer = ereignis.lauf_nummer" in app
    strom = (WURZEL / "frontend/src/lib/terminalfenster.svelte.js").read_text(encoding="utf-8")
    assert "ereignis.typ === 'lauf_gelesen'" in strom
    assert "aufrufkarte(ereignis.lauf)" in strom
    karte = (WURZEL / "frontend/src/teile/Nachricht.svelte").read_text(encoding="utf-8")
    assert "hintergrundStand(werkzeug)" in karte
    assert "t('werkzeug.hintergrund_laeuft')" in karte
    # Green and red only while nobody has looked — read, the dot steps back.
    assert "if (lauf.gelesen || werkzeug.gesehen) return null" in karte


def test_die_leiste_wird_rot_fuer_einen_abgelehnten_aufruf_und_tritt_nach_dem_blick_zurueck():
    """The rail's terminal sign used to follow the last RUN only: a shell
    call refused before it started left the sign as it was, and a finished
    run kept it green for the session. Pinned at the source: the sign reads
    the panel's history, a refused call is red, and colour stands only while
    there is something to look at."""
    leiste = (WURZEL / "frontend/src/teile/ToolSigns.svelte").read_text(encoding="utf-8")
    # A running command outranks everything; then a refused call is red;
    # then the last run's own colour.
    stufen = re.sub(r"\s+", " ", leiste)
    assert "laufGeht ? 'blau' : abgelehnterAufruf ? 'rot' : letzterLauf ? laufampel(letzterLauf.zustand) : null" in stufen
    assert "const laufGeht = $derived(terminal.laeufe.some((l) => l.zustand === 'laeuft'))" in leiste
    # The runs first, the pairing second: the sign must not go dark over a
    # row that paired oddly.
    assert "const letzterLauf = $derived(terminal.laeufe[terminal.laeufe.length - 1] ?? null)" in leiste
    # Red stands until the next call; green only until somebody looked.
    assert "if (laufzustand === 'blau' || laufzustand === 'rot') return laufzustand" in leiste
    assert "return laufWachsam ? laufzustand : null" in leiste
    strom = (WURZEL / "frontend/src/lib/terminalfenster.svelte.js").read_text(encoding="utf-8")
    # Named, not counted: the last failed line's key is what was seen.
    assert "terminal.gesehenerAufruf = aufrufe.length ? aufrufe[aufrufe.length - 1].schluessel : null" in strom
    assert "letzterEintrag.schluessel !== terminal.gesehenerAufruf" in leiste


def test_ein_vordergrundaufruf_wird_von_der_schlussschrift_nicht_umgeschrieben(chat_id):
    """A foreground command carries a run number too — the panel pairs by
    it — and its entry already holds the tool's own answer: "(done, no
    output)", stderr, "[exit code 1]". Rewritten from the raw run, that
    answer became nothing and an exit code of one became a failure the
    tool had not called one. The closing write fills background runs only."""
    from app.hintergrundmeldung import nachtragen

    still = hintergrund.laeufe.anlegen(chat_id, "mkdir neu", False)
    hintergrund.laeufe.beenden(still, 0)
    suche = hintergrund.laeufe.anlegen(chat_id, "grep foo datei", False)
    hintergrund.laeufe.beenden(suche, 1)
    protokoll = [
        {"name": "run_command", "lauf_nummer": still.nummer, "ergebnis": "(completed without output)", "fehlgeschlagen": False},
        {"name": "run_command", "lauf_nummer": suche.nummer, "ergebnis": "[exit code 1]", "fehlgeschlagen": False},
    ]
    nachtragen(protokoll, chat_id)
    assert protokoll[0]["ergebnis"] == "(completed without output)"
    assert "exit_code" not in protokoll[0]
    assert protokoll[1]["ergebnis"] == "[exit code 1]"
    assert protokoll[1]["fehlgeschlagen"] is False


def test_das_ende_traegt_den_zustand_und_ein_gestoppter_lauf_ist_kein_fehler(chat_id):
    """A run stopped by hand, at the time limit or by a shutdown ends with
    no exit code at all. Read by the code alone, a card took every one of
    them for "still running" once the run had left memory, and "code is
    not zero" called the stopped one a failure. The state travels with the
    ending, and "failed" is what the state says."""
    from app.hintergrundmeldung import am_aufruf_nachtragen

    gestoppt = hintergrund.laeufe.anlegen(chat_id, "sleep 100", True)
    hintergrund.laeufe.beenden(gestoppt, None, zustand=hintergrund.ABGEBROCHEN)
    eintrag = {"name": "run_command", "lauf_nummer": gestoppt.nummer, "ergebnis": "Started"}
    am_aufruf_nachtragen(eintrag, gestoppt, "")
    assert eintrag["lauf_zustand"] == "abgebrochen"
    assert eintrag["exit_code"] is None
    assert eintrag["fehlgeschlagen"] is False

    abgelaufen = hintergrund.laeufe.anlegen(chat_id, "make", True)
    hintergrund.laeufe.beenden(abgelaufen, None, zustand=hintergrund.FEHLER)
    eintrag = {"name": "run_command", "lauf_nummer": abgelaufen.nummer, "ergebnis": "Started"}
    am_aufruf_nachtragen(eintrag, abgelaufen, "Stopped after 30 seconds")
    assert eintrag["lauf_zustand"] == "fehler"
    assert eintrag["fehlgeschlagen"] is True


def test_das_ende_landet_auf_der_gestempelten_antwort_nicht_auf_einer_anderen(client, chat_id):
    """The run is stamped with the answer whose call started it, and the
    ending goes onto that row — not onto whichever row a search for the
    number finds first. Numbers are per chat; a row from before a restart
    of the old numbering could wear the same one, and a search from the
    end took today's output onto yesterday's card."""
    from app.hintergrundmeldung import _aufruf_nachtragen

    repositories = client.app.state.repositories
    lauf = hintergrund.laeufe.anlegen(chat_id, "npm install", True)

    def eintrag():
        return {
            "name": "run_command", "argumente": {"command": "npm install", "background": True},
            "lauf_nummer": lauf.nummer, "ergebnis": "Started", "fehlgeschlagen": False,
        }

    richtig = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Los.", zustand="fertig",
        stats={"werkzeuge": [eintrag()]},
    )
    lauf.antwort_id = richtig.id
    spaeter = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Spaeter.", zustand="fertig",
        stats={"werkzeuge": [eintrag()]},
    )
    hintergrund.laeufe.beenden(lauf, 0)
    _aufruf_nachtragen(repositories, lauf, "added 70 packages")

    assert repositories.messages.holen(richtig.id).stats["werkzeuge"][0]["ergebnis"] == "added 70 packages"
    assert repositories.messages.holen(spaeter.id).stats["werkzeuge"][0]["ergebnis"] == "Started"


def test_ein_lauf_ohne_stempel_schreibt_auf_keine_karte(client, chat_id):
    """No stamp, no card: a run no answer of this service started has no
    row to fill, and guessing one by number is how the wrong card got
    today's output."""
    from app.hintergrundmeldung import _aufruf_nachtragen

    repositories = client.app.state.repositories
    lauf = hintergrund.laeufe.anlegen(chat_id, "npm install", True)
    zeile = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Los.", zustand="fertig",
        stats={"werkzeuge": [{
            "name": "run_command", "lauf_nummer": lauf.nummer, "ergebnis": "Started", "fehlgeschlagen": False,
        }]},
    )
    hintergrund.laeufe.beenden(lauf, 0)
    _aufruf_nachtragen(repositories, lauf, "done")
    assert repositories.messages.holen(zeile.id).stats["werkzeuge"][0]["ergebnis"] == "Started"


def test_der_aufruf_stempelt_den_lauf_mit_seiner_antwort(client, chat_id):
    """The stamp the two tests above rely on is made where the call
    returns — and a command ending in a newline finds its run: the tool
    strips the command before it names the run, and the answer asks the
    same way."""
    _antwort_mit_hintergrundlauf(client, chat_id, befehl="npm run build\n")
    lauf = hintergrund.laeufe.holen(chat_id, 1)
    assert lauf is not None and lauf.befehl == "npm run build"
    antwort = _antwortzeile(client, chat_id)
    assert lauf.antwort_id == antwort["id"]
    assert antwort["stats"]["werkzeuge"][0]["lauf_nummer"] == 1


def test_ein_aufruf_ohne_eigenen_lauf_bekommt_keinen_alten(chat_id):
    """A call that never started a run — refused before it began — must
    not be handed the last run of the same command by an earlier call."""
    import time

    alt = hintergrund.laeufe.anlegen(chat_id, "ls", False)
    hintergrund.laeufe.beenden(alt, 0)
    vorher = time.monotonic()
    # Certainly earlier, whatever the clock's resolution.
    alt._begonnen = vorher - 1
    assert hintergrund.laeufe.juengster(chat_id, "ls") is alt
    assert hintergrund.laeufe.juengster(chat_id, "ls", seit=vorher) is None
    neu = hintergrund.laeufe.anlegen(chat_id, "ls", False)
    assert hintergrund.laeufe.juengster(chat_id, "ls", seit=vorher) is neu


def test_nur_die_vor_dem_lesen_beendeten_laeufe_gelten_als_gelesen(chat_id):
    """The reading is taken before the rows are read; a run that ends after
    it has its report in no request yet and waits for the next start."""
    fertig = hintergrund.laeufe.anlegen(chat_id, "ls", True)
    hintergrund.laeufe.beenden(fertig, 0)
    spaet = hintergrund.laeufe.anlegen(chat_id, "make", True)
    gelesen = hintergrund.laeufe.abgeschlossene(chat_id)
    assert gelesen == [fertig.nummer]
    # Ends between the read and the mark.
    hintergrund.laeufe.beenden(spaet, 0)
    assert hintergrund.laeufe.als_gelesen_melden(chat_id, gelesen) == [fertig.nummer]
    assert spaet.gelesen is False
    assert hintergrund.laeufe.abgeschlossene(chat_id) == [spaet.nummer]


def test_die_nummern_zaehlen_nach_einem_neustart_weiter(client, chat_id):
    """Runs live in memory, their numbers in the chat's rows, and the
    window pairs call and run by number. Counting from one after every
    restart handed a new run the number of a stored call: the old card
    took the new run's output, the new card showed a bare line."""
    from app.hintergrundmeldung import anmelden

    repositories = client.app.state.repositories
    anmelden(repositories)
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Damals.", zustand="fertig",
        stats={"werkzeuge": [
            {"name": "read_file", "argumente": {"path": "a"}, "ergebnis": "x"},
            {"name": "run_command", "argumente": {"command": "ls"}, "lauf_nummer": 7, "ergebnis": "a", "exit_code": 0},
        ]},
    )
    assert repositories.messages.hoechste_laufnummer(chat_id=chat_id) == 7
    # The service knows nothing of this chat's runs — a restart.
    hintergrund.laeufe.vergessen(chat_id)
    lauf = hintergrund.laeufe.anlegen(chat_id, "pwd", False)
    assert lauf.nummer == 8
    assert hintergrund.laeufe.anlegen(chat_id, "pwd", False).nummer == 9


def test_ein_lesefehler_friert_die_nummerierung_nicht_ein(chat_id):
    """A database locked for a moment must not put the chat back on a
    numbering that collides with its stored calls for the rest of the
    process: the run that hit the failure counts from memory alone, and
    the next one asks the rows again."""
    versuche = {"n": 0}

    def wacklig(_chat_id):
        versuche["n"] += 1
        if versuche["n"] == 1:
            raise RuntimeError("database is locked")
        return 7

    hintergrund.laeufe.nummernstart = wacklig
    erster = hintergrund.laeufe.anlegen(chat_id, "ls", False)
    assert erster.nummer == 1  # read failed: memory alone
    zweiter = hintergrund.laeufe.anlegen(chat_id, "ls", False)
    assert zweiter.nummer == 9  # read again, and it answered 7 this time
    assert versuche["n"] == 2
