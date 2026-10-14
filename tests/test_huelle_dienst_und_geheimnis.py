"""The Electron shell: port fallback, secrets in a copied
address, the image-copy address, and the started service's error listener.

`fenster-electron/main.js` requires electron and therefore cannot run
outside a packaged window (see tests/test_adressregel.py for the same
reasoning) — the functions under test are extracted from its source by
name and run for real in node, mocking only the electron globals each one
touches. The service-start listener test and the copy-image test are
electron-shaped (a real child process; nativeImage/clipboard) but neither
actually needs a BrowserWindow,
so both run here too, against real node child_process behaviour and thin
stand-ins for the two electron calls.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
MODUL = WURZEL / "fenster-electron" / "main.js"


def _quelle() -> str:
    return MODUL.read_text()


def _stueck(muster: str, name: str) -> str:
    treffer = re.search(muster, _quelle(), re.S)
    assert treffer, f"{name} not found"
    return treffer.group(0).strip() + "\n"


def _portLesen() -> str:
    return _stueck(r"\nfunction portLesen\(\) \{\n.*?\n\}\n", "portLesen")


def _geheimnis_teile() -> str:
    return "\n".join([
        _stueck(r"\nconst GEHEIME_WOERTER = new Set\(\[\n.*?\n\]\)\n", "GEHEIME_WOERTER"),
        _stueck(r"\nconst GEHEIME_TEILE = \[\n.*?\n\]\n", "GEHEIME_TEILE"),
        _stueck(r"\nfunction istGeheimerParameter\(.*?\n\}\n", "istGeheimerParameter"),
        _stueck(r"\nfunction parameterSaeubern\(.*?\n\}\n", "parameterSaeubern"),
        _stueck(r"\nfunction ohneGeheimnis\(.*?\n\}\n", "ohneGeheimnis"),
    ])


def _bildKopieren() -> str:
    return _stueck(r"\nasync function bildKopieren\(.*?\n\}\n", "bildKopieren")


def _dienstStarten() -> str:
    return "\n".join([
        _stueck(r"\nfunction alsFehlgeschlagenZeigen\(\) \{\n.*?\n\}\n", "alsFehlgeschlagenZeigen"),
        _stueck(r"\nfunction fehlstartSchreiben\(\) \{\n.*?\n\}\n", "fehlstartSchreiben"),
        _stueck(r"\nlet dienstFehlgeschlagen = false\n", "dienstFehlgeschlagen"),
        _stueck(r"\nlet dienstAntwortete = false\n", "dienstAntwortete"),
        _stueck(r"\nfunction fehlstartMelden\(grund\) \{\n.*?\n\}\n", "fehlstartMelden"),
        _stueck(r"\nasync function dienstStarten\(\) \{\n.*?\n\}\n", "dienstStarten"),
    ])


def _warten() -> str:
    return _stueck(r"\nasync function warten\(\) \{\n.*?\n\}\n", "warten")


def _laufe(skript: str) -> dict:
    if not shutil.which("node"):
        pytest.skip("node is missing")
    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.strip().splitlines()[-1])


# --- an invalid EXE_AI_PORT falls back to 8090 ------------------------------


@pytest.mark.parametrize(
    "wert,erwartet",
    [
        (None, 8090),
        ("", 8090),
        ("abc", 8090),
        ("0", 8090),
        ("-1", 8090),
        ("65536", 8090),
        ("8091.5", 8090),
        ("8091", 8091),
        ("1", 1),
        ("65535", 65535),
    ],
)
def test_ungueltiger_port_faellt_auf_8090_zurueck(wert, erwartet):
    umgebung = "" if wert is None else f"process.env.EXE_AI_PORT = {json.dumps(wert)};"
    skript = f"""
{umgebung}
{_portLesen()}
console.log(JSON.stringify(portLesen()))
"""
    ergebnis = _laufe(skript)
    assert ergebnis == erwartet


def test_ein_zurueckgefallener_port_meldet_sich_im_protokoll():
    skript = f"""
process.env.EXE_AI_PORT = 'abc'
let gewarnt = null
console.warn = (text) => {{ gewarnt = text }}
{_portLesen()}
portLesen()
console.log(JSON.stringify(gewarnt))
"""
    gewarnt = _laufe(skript)
    assert gewarnt is not None
    assert "abc" in gewarnt
    assert "8090" in gewarnt


# --- ohneGeheimnis -----------------------------------------------------------


def _ohneGeheimnis(adresse: str) -> dict:
    skript = f"""
{_geheimnis_teile()}
console.log(JSON.stringify(ohneGeheimnis({json.dumps(adresse)})))
"""
    return _laufe(skript)


def test_fragment_mit_route_verliert_nur_den_abfrageteil():
    """The route survives, only what follows '?' is cleaned."""
    ergebnis = _ohneGeheimnis("https://app.example.com/#/seite/1?token=abc")
    assert ergebnis == {"adresse": "https://app.example.com/#/seite/1", "entfernt": True}


def test_fragment_ohne_fragezeichen_bleibt_unveraendert():
    ergebnis = _ohneGeheimnis("https://app.example.com/#/seite/1")
    assert ergebnis == {"adresse": "https://app.example.com/#/seite/1", "entfernt": False}


def test_nackter_oauth_anhang_ohne_fragezeichen_wird_gesaeubert():
    """A review finding: a fragment with no '?' at all is not a route, it IS
    the OAuth implicit-flow query string (`#access_token=...`) the fragment
    scan exists for in the first place — the '?'-split fix must not leave it
    untouched."""
    ergebnis = _ohneGeheimnis("https://app.example.com/#access_token=SECRET123")
    assert ergebnis == {"adresse": "https://app.example.com/", "entfernt": True}


def test_gewoehnlicher_seitenanker_ohne_gleichheitszeichen_bleibt_unveraendert():
    """A second review finding: without the '=' guard, a same-page anchor
    like '#auth' or '#key-features' was itself run through
    istGeheimerParameter — which splits on punctuation — so the hyphenated
    slug's own words ('auth', 'key') falsely matched a secret name and the
    whole anchor was deleted."""
    for anker in ("https://app.example.com/docs#auth", "https://app.example.com/docs#key-features"):
        ergebnis = _ohneGeheimnis(anker)
        assert ergebnis == {"adresse": anker, "entfernt": False}, anker


def test_zusammengeschriebene_namen_werden_erkannt():
    """sessionid/jsessionid/authkey as part of a name; pin/otp/
    passcode only as the whole name, so ordinary words are left alone."""
    entfernt = _ohneGeheimnis(
        "https://example.com/?SESSIONID=1&jsessionid=2&authkey=3"
    )
    assert entfernt["adresse"] == "https://example.com/"
    assert entfernt["entfernt"] is True

    unveraendert = _ohneGeheimnis("https://example.com/?shipping=free&spinner=1")
    assert unveraendert == {
        "adresse": "https://example.com/?shipping=free&spinner=1",
        "entfernt": False,
    }


def test_pin_bleibt_als_ganzer_name_ein_treffer():
    ergebnis = _ohneGeheimnis("https://example.com/?pin=1234")
    assert ergebnis["entfernt"] is True
    assert "pin=1234" not in ergebnis["adresse"]


def test_benutzer_und_passwort_werden_aus_der_adresse_entfernt():
    """Userinfo, and the three newly named whole-word secrets."""
    ergebnis = _ohneGeheimnis("https://user:hunter2@example.com/?otp=1")
    assert ergebnis == {"adresse": "https://example.com/", "entfernt": True}


def test_eine_adresse_ohne_benutzerteil_bleibt_unveraendert():
    ergebnis = _ohneGeheimnis("https://example.com/")
    assert ergebnis == {"adresse": "https://example.com/", "entfernt": False}


def test_lateinischer_link_ohne_geheimnis_bleibt_byte_fuer_byte():
    """Silence test: an ordinary link with nothing to strip is handed back
    untouched, not re-serialised."""
    ergebnis = _ohneGeheimnis("https://example.com/a/b?x=1&y=2")
    assert ergebnis == {"adresse": "https://example.com/a/b?x=1&y=2", "entfernt": False}


# --- "not available" only for our own addresses -----------------------------


def test_die_nicht_verfuegbar_beschriftung_prueft_die_eigene_seite():
    quelle = _quelle()
    treffer = re.search(
        r"linkLabel: link && link\.entfernt && istEigeneSeite\(params\.linkURL\)",
        quelle,
    )
    assert treffer, (
        "the label must also check istEigeneSeite(params.linkURL), "
        "otherwise 'not available' applies to foreign links too"
    )


# --- Copy Image goes by address, not by the click spot ----------------------


def test_bild_kopieren_holt_ein_data_bild_ohne_netzzugriff():
    skript = f"""
const aufrufe = []
const nativeImage = {{
  createFromDataURL: (u) => {{ aufrufe.push(['data', u]); return {{ isEmpty: () => false }} }},
  createFromBuffer: (b) => {{ aufrufe.push(['buffer', b.length]); return {{ isEmpty: () => false }} }},
}}
let geschrieben = null
const clipboard = {{ write: (w) => {{ geschrieben = w }} }}
global.fetch = async () => {{ throw new Error('must not fetch a data: address') }}
{_bildKopieren()}
bildKopieren('data:image/png;base64,QUFB').then(() => {{
  console.log(JSON.stringify({{ aufrufe, geschrieben: geschrieben !== null }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["aufrufe"] == [["data", "data:image/png;base64,QUFB"]]
    assert ergebnis["geschrieben"] is True


def test_bild_kopieren_holt_eine_http_adresse_per_fetch():
    skript = f"""
const aufrufe = []
const nativeImage = {{
  createFromDataURL: (u) => {{ aufrufe.push(['data', u]); return {{ isEmpty: () => false }} }},
  createFromBuffer: (b) => {{ aufrufe.push(['buffer', b.toString()]); return {{ isEmpty: () => false }} }},
}}
let geschrieben = null
const clipboard = {{ write: (w) => {{ geschrieben = w }} }}
let angefragt = null
global.fetch = async (adresse) => {{
  angefragt = adresse
  return {{ arrayBuffer: async () => Buffer.from('PNGBYTES') }}
}}
{_bildKopieren()}
bildKopieren('http://127.0.0.1:8090/api/v1/images/x.png?schluessel=abc').then(() => {{
  console.log(JSON.stringify({{ aufrufe, geschrieben: geschrieben !== null, angefragt }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["angefragt"] == "http://127.0.0.1:8090/api/v1/images/x.png?schluessel=abc"
    assert ergebnis["aufrufe"] == [["buffer", "PNGBYTES"]]
    assert ergebnis["geschrieben"] is True


def test_bild_kopieren_schreibt_nichts_wenn_nichts_ankommt():
    skript = f"""
const nativeImage = {{
  createFromDataURL: () => ({{ isEmpty: () => true }}),
  createFromBuffer: () => ({{ isEmpty: () => true }}),
}}
let geschrieben = null
const clipboard = {{ write: (w) => {{ geschrieben = w }} }}
global.fetch = async () => ({{ arrayBuffer: async () => Buffer.from('') }})
{_bildKopieren()}
bildKopieren('data:image/png;base64,').then(() => {{
  console.log(JSON.stringify({{ geschrieben: geschrieben !== null }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["geschrieben"] is False


# --- a service that fails to start shows up immediately ---------------------


def test_ein_fehlender_dienst_zeigt_fehlgeschlagen_statt_den_prozess_zu_reissen():
    skript = f"""
const {{ spawn }} = require('child_process')
const PORT = 8090
async function antwortet() {{ return false }}
function dienstpfad() {{ return '/this/path/does/not/exist/at/all/exe-ai' }}
let kind = null
let angezeigt = false
let beendet = false
const fenster = {{
  isDestroyed: () => false,
  webContents: {{
    isLoading: () => false,
    executeJavaScript: (js) => {{ if (js.includes('fehlgeschlagen')) angezeigt = true; return Promise.resolve() }},
  }},
}}
{_dienstStarten()}
dienstStarten().then(() => {{
  setTimeout(() => {{
    console.log(JSON.stringify({{ angezeigt, kindIstNull: kind === null, dienstFehlgeschlagen }}))
  }}, 500)
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["angezeigt"] is True
    assert ergebnis["kindIstNull"] is True
    assert ergebnis["dienstFehlgeschlagen"] is True


def _absturz(*, antwortete: bool, beendet: bool, laedt: bool = False) -> dict:
    """A real child that starts and exits at once, the way a service with a
    missing library or a taken port does: node itself, started without a
    script and with its input closed, which is over at once on every
    system — /usr/bin/false exists on none but a POSIX one."""
    skript = f"""
const {{ spawn }} = require('child_process')
const PORT = 8090
async function antwortet() {{ return false }}
function dienstpfad() {{ return process.execPath }}
let kind = null
let beendet = {str(beendet).lower()}
let angezeigt = false
console.error = () => {{}}
const fenster = {{
  isDestroyed: () => false,
  webContents: {{
    isLoading: () => {str(laedt).lower()},
    executeJavaScript: (js) => {{ if (js.includes('fehlgeschlagen')) angezeigt = true; return Promise.resolve() }},
  }},
}}
{_dienstStarten()}
dienstAntwortete = {str(antwortete).lower()}
dienstStarten().then(() => setTimeout(() => {{
  console.log(JSON.stringify({{ angezeigt, dienstFehlgeschlagen, kindIstNull: kind === null }}))
}}, 1000))
"""
    return _laufe(skript)


def test_ein_absturz_vor_der_ersten_antwort_ist_ein_fehlstart():
    """A service that starts and dies a second later fires 'exit', not
    'error' — and used to leave the splash waiting for two minutes."""
    assert _absturz(antwortete=False, beendet=False) == {
        "angezeigt": True, "dienstFehlgeschlagen": True, "kindIstNull": True,
    }


def test_ein_ende_nach_der_ersten_antwort_ist_kein_fehlstart():
    """The silence probe: a service that answered and stopped later did
    start; the splash is long gone by then."""
    assert _absturz(antwortete=True, beendet=False)["dienstFehlgeschlagen"] is False


def test_ein_ende_beim_beenden_ist_kein_fehlstart():
    assert _absturz(antwortete=False, beendet=True)["dienstFehlgeschlagen"] is False


def test_die_meldung_schreibt_nicht_in_eine_ladende_seite():
    """A verdict that comes while the splash is still loading is not
    written into the document about to be replaced — it is recorded, and the
    splash's own 'did-finish-load' writes it."""
    ergebnis = _absturz(antwortete=False, beendet=False, laedt=True)
    assert ergebnis["dienstFehlgeschlagen"] is True
    assert ergebnis["angezeigt"] is False
    quelle = _quelle()
    bauen = quelle.split("function fensterBauen() {", 1)[1].split("\n}\n", 1)[0]
    assert "'did-finish-load'" in bauen
    assert "if (dienstFehlgeschlagen) fehlstartSchreiben()" in bauen


def test_der_gestartete_dienst_bekommt_den_geprueften_port_nicht_den_rohen():
    """A follow-up review finding: the raw, unvalidated EXE_AI_PORT reached
    the spawned service's own environment, so an invalid value (that
    portLesen() already caught for the shell itself) still crashed the
    child's own startup — defeating the port fallback for the child process."""
    skript = f"""
process.env.EXE_AI_PORT = 'abc'
const PORT = 8090
let gesehenerPort = null
function spawn(pfad, args, optionen) {{
  gesehenerPort = optionen.env.EXE_AI_PORT
  // The child handle the shell lets go of: unref() has to be there.
  return {{ on: () => {{}}, unref: () => {{}} }}
}}
async function antwortet() {{ return false }}
function dienstpfad() {{ return '/unused' }}
let kind = null
let beendet = false
const fenster = null
{_dienstStarten()}
dienstStarten().then(() => {{
  console.log(JSON.stringify({{ gesehenerPort }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["gesehenerPort"] == "8090"


def test_ein_vorhandener_dienst_ruft_spawn_nicht_auf():
    skript = f"""
const {{ spawn }} = require('child_process')
const PORT = 8090
let aufgerufen = false
async function antwortet() {{ return true }}
function dienstpfad() {{ aufgerufen = true; return '/unused' }}
let kind = null
let beendet = false
let fenster = null
{_dienstStarten()}
dienstStarten().then(() => {{
  console.log(JSON.stringify({{ dienstpfadAufgerufen: aufgerufen }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["dienstpfadAufgerufen"] is False


def test_warten_bricht_sofort_ab_wenn_der_dienst_schon_gescheitert_ist():
    """A review finding: without this check, warten() kept polling a port
    nothing would ever answer for up to two more minutes after the error
    listener had already shown 'fehlgeschlagen'."""
    skript = f"""
let dienstFehlgeschlagen = true
let beendet = false
let aufrufe = 0
async function antwortet() {{ aufrufe += 1; return false }}
let dienstAntwortete = false
function fehlstartMelden() {{}}
const fenster = null
const ZIEL = 'unused'
{_warten()}
const start = Date.now()
warten().then(() => {{
  console.log(JSON.stringify({{ dauerMs: Date.now() - start, aufrufe }}))
}})
"""
    ergebnis = _laufe(skript)
    assert ergebnis["aufrufe"] == 0
    assert ergebnis["dauerMs"] < 100


# --- the shell's start and stop ---------------------------------------------


def _warten_lauf(*, zerstoert_nach_antwort: bool, beendet: bool, laden_scheitert: bool,
                 zerstoert_beim_laden: bool = False) -> dict:
    """Runs warten() against a port that answers at once, with a window
    stand-in that can be destroyed the moment the answer comes."""
    skript = f"""
let dienstFehlgeschlagen = false
let beendet = {str(beendet).lower()}
let fehlgeschlagen = 0
let geladen = 0
let unbehandelt = 0
let protokolliert = 0
process.on('unhandledRejection', () => {{ unbehandelt += 1 }})
console.error = () => {{ protokolliert += 1 }}
const ZIEL = 'http://127.0.0.1:1/app/'
const fenster = {{
  zerstoert: false,
  isDestroyed() {{ return this.zerstoert }},
  loadURL() {{
    geladen += 1
    if ({str(zerstoert_beim_laden).lower()}) this.zerstoert = true
    return {str(laden_scheitert).lower()} ? Promise.reject(new Error('ERR_ABORTED')) : Promise.resolve()
  }},
}}
async function antwortet() {{
  if ({str(zerstoert_nach_antwort).lower()}) fenster.zerstoert = true
  return true
}}
let dienstAntwortete = false
function fehlstartMelden() {{ fehlgeschlagen += 1 }}
{_warten()}
warten().then(() => setTimeout(() => {{
  console.log(JSON.stringify({{ geladen, fehlgeschlagen, unbehandelt, protokolliert }}))
}}, 50))
"""
    return _laufe(skript)


def test_warten_laedt_nicht_in_ein_geschlossenes_fenster():
    ergebnis = _warten_lauf(zerstoert_nach_antwort=True, beendet=False, laden_scheitert=False)
    assert ergebnis["geladen"] == 0


def test_warten_laedt_nicht_waehrend_das_programm_endet():
    ergebnis = _warten_lauf(zerstoert_nach_antwort=False, beendet=True, laden_scheitert=False)
    assert ergebnis["geladen"] == 0


def test_warten_laedt_bei_offenem_fenster_wie_bisher():
    ergebnis = _warten_lauf(zerstoert_nach_antwort=False, beendet=False, laden_scheitert=False)
    assert ergebnis == {"geladen": 1, "fehlgeschlagen": 0, "unbehandelt": 0, "protokolliert": 0}


def test_ein_gescheitertes_laden_bei_offenem_fenster_steht_im_protokoll():
    ergebnis = _warten_lauf(zerstoert_nach_antwort=False, beendet=False, laden_scheitert=True)
    assert ergebnis == {"geladen": 1, "fehlgeschlagen": 0, "unbehandelt": 0, "protokolliert": 1}


def test_ein_beim_laden_geschlossenes_fenster_ist_kein_fehler():
    ergebnis = _warten_lauf(zerstoert_nach_antwort=False, beendet=False, laden_scheitert=True,
                            zerstoert_beim_laden=True)
    assert ergebnis == {"geladen": 1, "fehlgeschlagen": 0, "unbehandelt": 0, "protokolliert": 0}


def test_die_navigationsregel_haelt_fremdes_draussen_und_laesst_eigenes_durch():
    """The listeners themselves, run in node with the real rule module: every
    frame's navigation and every redirect is decided once — own pages stay,
    a foreign address is stopped without opening anything, and only a link
    the PDF viewer started goes to the browser. The developer tools are the
    pages noted in `toolsPages`, whatever their type."""
    guard = _stueck(r"\nfunction navigationSperren\(inhalt\) \{\n.*?\n\}\n", "navigationSperren")
    noted = _stueck(r"\nconst toolsPages = new WeakSet\(\)\n", "toolsPages")
    decide = _stueck(r"\nfunction navigationDecide\(contents, details, redirect\) \{\n.*?\n\}\n", "navigationDecide")
    starter = _stueck(r"\nfunction starterOf\(details\) \{\n.*?\n\}\n", "starterOf")
    rule_module = json.dumps(str(MODUL.with_name("adressregel.js")))
    script = f"""
const regel = require({rule_module})
const PORT = 8090
const opened = []
function nachDraussen(address) {{ opened.push(address) }}
const listeners = {{}}
const inhalt = {{ id: 1, on(name, f) {{ listeners[name] = f }} }}
const tools = {{}}
const toolsPage = {{ id: 2, on(name, f) {{ tools[name] = f }} }}
// The PDF viewer's page: of type 'remote' like the tools, but no one's tools.
const pdf = {{}}
const pdfPage = {{ id: 3, on(name, f) {{ pdf[name] = f }} }}
{noted}
{guard}
{starter}
{decide}
// What 'devtools-opened' does for the tools page (see the hook test).
toolsPages.add(toolsPage)
navigationSperren(inhalt)
const logged = []
console.log = (line) => logged.push(line)
const result = {{}}
const viewerPage = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/34b3c741'
const ownPage = {{ url: 'http://127.0.0.1:8090/app/' }}
const cases = [
  // A page's own navigation always names the frame that started it.
  ['will-frame-navigate', 'https://example.com/', true, {{ initiator: ownPage }}],
  ['will-frame-navigate', 'file:///etc/hosts', true, {{ initiator: ownPage }}],
  ['will-frame-navigate', 'http://127.0.0.1:8090/hilfe/seite', true, {{ initiator: ownPage }}],
  ['will-frame-navigate', 'https://example.com/', false, {{ initiator: ownPage }}],
  ['will-frame-navigate', 'about:srcdoc', false, {{ initiator: ownPage }}],
  ['will-redirect', 'https://example.com/', true, {{ initiator: ownPage }}],
  ['will-redirect', 'http://127.0.0.1:8090/app/', true, {{ initiator: ownPage }}],
  ['will-frame-navigate', 'https://user:pw@example.com/reset/9f3c?code=SECRET', true, {{ initiator: ownPage }}],
  // Nobody started it (the person, through the PDF viewer): the initiator is null.
  ['will-frame-navigate', 'https://example.com/pdf-link', true, {{ initiator: null }}],
  ['will-frame-navigate', 'https://example.com/pdf-in-frame', false, {{ initiator: null }}],
  ['will-frame-navigate', 'javascript:alert(1)', true, {{ initiator: null }}],
  ['will-redirect', 'https://example.com/pdf-redirect', true, {{ initiator: null }}],
  // Started by one of the viewer's own frames.
  ['will-frame-navigate', 'https://example.com/viewer-frame', false, {{ initiator: {{ url: viewerPage }} }}],
  // Started by a page of ours: a script's `location`.
  ['will-frame-navigate', 'https://example.com/own-page', true, {{ initiator: ownPage }}],
  // A frame that is gone answers with an error: unknown, and unknown goes nowhere.
  ['will-frame-navigate', 'https://example.com/gone', false, {{
    initiator: {{ get url() {{ throw new Error('disposed') }} }},
  }}],
]
for (const [event, url, isMainFrame, extra] of cases) {{
  let prevented = false
  const before = opened.length
  listeners[event]({{
    url, isMainFrame, frame: null, preventDefault() {{ prevented = true }}, ...extra,
  }})
  result[`${{event}} ${{isMainFrame ? 'main' : 'sub'}} ${{url}}`] = {{ prevented, opened: opened.length > before }}
}}
result.listeners = Object.keys(listeners).sort()
result.logged = logged.slice()
// The developer tools: their frames stay, their main frame stays on devtools:.
navigationSperren(toolsPage)
navigationSperren(pdfPage)
const prevented = (page, url, isMainFrame) => {{
  let stopped = false
  page['will-frame-navigate']({{ url, isMainFrame, preventDefault() {{ stopped = true }} }})
  return stopped
}}
const viewer = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/34b3c741'
const openedBefore = opened.length
result.tools = {{
  sub_data: prevented(tools, 'data:text/html,<p>x', false),
  main_devtools: prevented(tools, 'devtools://devtools/bundled/devtools_app.html', true),
  main_foreign: prevented(tools, 'https://example.com/', true),
  sub_pdf_viewer: prevented(tools, viewer, false),
}}
// A redirect to one of our pages: a program window keeps it, the tools stop it.
let redirectStopped = false
tools['will-redirect']({{
  url: 'http://127.0.0.1:8090/app/', isMainFrame: true, preventDefault() {{ redirectStopped = true }},
}})
result.tools.redirect_own = redirectStopped
result.tools.opened = opened.length - openedBefore
// The PDF viewer's page gets the rule of a program window.
result.pdf = {{
  sub_pdf_viewer: prevented(pdf, viewer, false),
  main_devtools: prevented(pdf, 'devtools://devtools/bundled/devtools_app.html', true),
}}
process.stdout.write(JSON.stringify(result) + "\\n")
"""
    result = _laufe(script)
    assert result == {
        "will-frame-navigate main https://example.com/": {"prevented": True, "opened": False},
        "will-frame-navigate main file:///etc/hosts": {"prevented": True, "opened": False},
        "will-frame-navigate main http://127.0.0.1:8090/hilfe/seite": {"prevented": False, "opened": False},
        "will-frame-navigate sub https://example.com/": {"prevented": True, "opened": False},
        "will-frame-navigate sub about:srcdoc": {"prevented": False, "opened": False},
        "will-redirect main https://example.com/": {"prevented": True, "opened": False},
        "will-redirect main http://127.0.0.1:8090/app/": {"prevented": False, "opened": False},
        "will-frame-navigate main https://user:pw@example.com/reset/9f3c?code=SECRET": {
            "prevented": True, "opened": False,
        },
        "will-frame-navigate main https://example.com/pdf-link": {"prevented": True, "opened": True},
        "will-frame-navigate sub https://example.com/pdf-in-frame": {"prevented": True, "opened": True},
        "will-frame-navigate main javascript:alert(1)": {"prevented": True, "opened": False},
        "will-redirect main https://example.com/pdf-redirect": {"prevented": True, "opened": False},
        "will-frame-navigate sub https://example.com/viewer-frame": {"prevented": True, "opened": True},
        "will-frame-navigate main https://example.com/own-page": {"prevented": True, "opened": False},
        "will-frame-navigate sub https://example.com/gone": {"prevented": True, "opened": False},
        "listeners": ["will-frame-navigate", "will-redirect"],
        "tools": {
            "sub_data": False, "main_devtools": False, "main_foreign": True,
            "sub_pdf_viewer": True, "redirect_own": True, "opened": 0,
        },
        "pdf": {"sub_pdf_viewer": False, "main_devtools": True},
        # The log names the place only — never a path, a query or a user.
        "logged": [
            "Navigation block: https://example.com",
            "Navigation block: file:",
            "Navigation block: https://example.com",
            "Navigation block (redirect): https://example.com",
            "Navigation block: https://example.com",
            "Navigation outside: https://example.com",
            "Navigation outside: https://example.com",
            "Navigation block: javascript:",
            "Navigation block (redirect): https://example.com",
            "Navigation outside: https://example.com",
            "Navigation block: https://example.com",
            "Navigation block: https://example.com",
        ],
    }


def test_jede_seite_bekommt_beide_regeln():
    """Set in the one hook every page passes through, not per window: a window
    opened from a window gets them too."""
    quelle = _quelle()
    haken = re.search(r"app\.on\('web-contents-created', \(ereignis, inhalt\) => \{\n(.*?)\n\}\)", quelle, re.S)
    assert haken, "web-contents-created hook not found"
    assert "inhalt.setWindowOpenHandler((angaben) => fensterweiche(angaben, inhalt))" in haken.group(1)
    # Run for a program window and the PDF viewer's page (type 'remote'):
    # each gets the navigation rule, the hook does not sort them by type, and
    # only the page the window opens as its tools is noted as such.
    noted = re.search(r"\nconst toolsPages = new WeakSet\(\)\n", quelle)
    assert noted, "toolsPages not found"
    script = f"""
const calls = []
const manual = []
function kontextmenueSetzen() {{}}
function rememberManual(inhalt) {{ manual.push(inhalt.name) }}
const fensterweiche = null
function navigationSperren(inhalt, ...rest) {{ calls.push([inhalt.name, rest.length]) }}
const app = {{ on(name, f) {{ this.hook = f }} }}
{noted.group(0)}
{haken.group(0)}
const tools = {{ name: 'tools' }}
const pages = {{}}
for (const name of ['window', 'pdf']) {{
  const listeners = {{}}
  pages[name] = {{
    name, listeners, devToolsWebContents: name === 'window' ? tools : null,
    setWindowOpenHandler() {{}}, on(event, f) {{ listeners[event] = f }},
  }}
  app.hook(null, pages[name])
}}
const before = toolsPages.has(tools)
pages.window.listeners['devtools-opened']()
// A page whose tools are already gone again when the event arrives.
pages.pdf.listeners['devtools-opened']()
process.stdout.write(JSON.stringify({{
  calls, manual, before, after: toolsPages.has(tools), pdf: toolsPages.has(pages.pdf),
}}) + "\\n")
"""
    # The manual is noted from every page too, whichever window opened it.
    assert _laufe(script) == {
        "calls": [["window", 0], ["pdf", 0]], "manual": ["window", "pdf"],
        "before": False, "after": True, "pdf": False,
    }


# --- an update ends the service on the way `exe service stop` goes --------------------

DIENSTSUCHE = WURZEL / "fenster-electron" / "dienstsuche.js"

# A stand-in for the terminal client: it says its own arguments, or the words
# it is given, and ends with the code it is given.
CLIENT_STAND_IN = (
    "const [code, words] = [Number(process.env.STAND_IN_CODE || 0), process.env.STAND_IN_WORDS];"
    "const said = words || JSON.stringify(process.argv.slice(1));"
    "(code ? process.stderr : process.stdout).write(said + '\\n', () => process.exit(code))"
)


def _end_service_piece() -> str:
    return "\n".join([
        _stueck(r"\nfunction clientStop\(\) \{\n.*?\n\}\n", "clientStop"),
        _stueck(r"\nconst LOOK_PAUSE_MS = \d+\n", "LOOK_PAUSE_MS"),
        _stueck(r"\nasync function endRunningService\(running\) \{\n.*?\n\}\n", "endRunningService"),
        _stueck(r"\nasync function endServiceForUpdate\(\) \{\n.*?\n\}\n", "endServiceForUpdate"),
    ])


def _restart_piece() -> str:
    return _stueck(r"\nfunction restartServiceAfterUpdate\(\) \{\n.*?\n\}\n", "restartServiceAfterUpdate")


def _end_service(
    *,
    program: str | None = None,
    arguments: list[str] | None = None,
    code: int = 0,
    words: str = "",
    found: bool = False,
    running: bool = True,
    alive: tuple[bool, ...] = (),
) -> dict:
    """Runs the shell's end of the service for real, with a real child
    process in the client's place, and reports how it ended and what the
    shell knows of a service afterwards. `found`: the service is one this
    shell did not start. `running`: a service of ours runs here, as process
    31337. `alive`: what the looks at that process answer, one after the
    other, and "gone" from then on."""
    client = {
        "file": program or shutil.which("node"),
        "args": ["-e", CLIENT_STAND_IN] if arguments is None else arguments,
        "cwd": str(WURZEL),
    }
    script = f"""
const {{ spawn }} = require('child_process')
const path = require('path')
Object.assign(process.env, {json.dumps({"STAND_IN_CODE": str(code), "STAND_IN_WORDS": words})})
const PORT = 8123
const ADDRESS = 'http://127.0.0.1:8123'
const app = {{ isPackaged: true }}
const clientProgram = {json.dumps(client)}
const asked = []
const answers = {json.dumps(list(alive))}
const dienstsuche = {{
  dataRoot: (options) => {{ asked.push(['root', options.packaged]); return '/root' }},
  runningService: async (options) => {{
    asked.push(['service', options.port, options.root])
    return {"{ pid: 31337, port: 8123 }" if running else "null"}
  }},
  processAlive: (pid) => {{
    // Only once the client's stop is through is the process looked at.
    asked.push(['alive', pid, stopped])
    return answers.shift() ?? false
  }},
}}
let stopped = false
const signals = []
process.kill = (pid, signal) => {{ signals.push([pid, signal]) }}
const logged = []
console.log = (line) => logged.push(line)
let dienstVorgefunden = {"{ pid: 31337, port: 8123 }" if found else "null"}
let kind = {"null" if found else "{ pid: 31337 }"}
{_end_service_piece()}
const stop = clientStop
clientStop = () => stop().then((said) => {{ stopped = true; return said }})
endServiceForUpdate().then(
  () => 'ended',
  (failure) => `refused: ${{failure.message}}`,
).then((outcome) => {{
  process.stdout.write(JSON.stringify({{
    outcome, logged, signals, asked, found: dienstVorgefunden, started: kind,
  }}) + "\\n")
}})
"""
    return _laufe(script)


STOP_ARGUMENTS = ["service", "stop", "--url", "http://127.0.0.1:8123", "--lang", "en"]


def test_before_an_update_the_service_is_ended_with_the_clients_stop_at_the_own_address():
    """Falls over without the fix: there was no such call at all. The shell
    runs the terminal client's `service stop` for its own address — the
    command of `exe service stop` — and signals no process itself."""
    result = _end_service()
    assert result["outcome"] == "ended"
    said = json.dumps(STOP_ARGUMENTS, separators=(",", ":"))
    assert result["logged"] == [f"Service: ended before the update is installed (pid 31337; {said})"]
    assert result["signals"] == []
    # The way out then has no service left to say "stays" about.
    assert result["found"] is None and result["started"] is None


def test_the_program_is_handed_over_only_once_the_service_process_is_gone():
    """The stop is through when the port is free, and the service shuts
    down after that. The process of the service that ran here is looked at
    until it is gone — after the stop, not before — and only then is the
    end an end."""
    result = _end_service(alive=(True, True))
    assert result["outcome"] == "ended"
    assert result["asked"] == [
        ["root", True], ["service", 8123, "/root"],
        ["alive", 31337, True], ["alive", 31337, True], ["alive", 31337, True],
    ]
    assert len(result["logged"]) == 1


def test_a_service_this_shell_only_found_is_ended_the_same_way():
    """Whoever started it — an earlier window, the terminal client: it is
    the service of this installation, and the release replaces its files."""
    result = _end_service(found=True, words="Service on port 8123 stopped.")
    assert result["outcome"] == "ended"
    assert result["logged"] == [
        "Service: ended before the update is installed (pid 31337; Service on port 8123 stopped.)"
    ]
    assert result["found"] is None and result["started"] is None


def test_silence_probe_without_a_running_service_there_is_no_process_to_wait_for():
    """Nothing of ours ran here — or only a note was left, by a service that
    crashed: nobody's process is waited for, whatever number the note
    names."""
    result = _end_service(running=False, words="No Exe AI service is running on port 8123.")
    assert result["outcome"] == "ended"
    assert [look[0] for look in result["asked"]] == ["root", "service"]
    assert result["logged"] == [
        "Service: ended before the update is installed (No Exe AI service is running on port 8123.)"
    ]


def test_a_service_that_did_not_end_is_refused_in_the_clients_own_words():
    """Nothing is installed then (the updater's side of it is in
    tests/test_shell_updater.py), nobody waits for a process that was not
    asked to go, and the shell goes on knowing its service."""
    result = _end_service(code=1, words="The service on port 8123 is still running.", found=True)
    assert result["outcome"] == "refused: The service on port 8123 is still running."
    assert result["logged"] == []
    assert [look[0] for look in result["asked"]] == ["root", "service"]
    assert result["found"] == {"pid": 31337, "port": 8123}


def test_a_client_that_cannot_be_run_is_refused_in_the_systems_words():
    result = _end_service(program=str(WURZEL / "no-such-folder" / "exe"))
    assert result["outcome"].startswith("refused: ")
    assert "ENOENT" in result["outcome"]
    assert result["started"] == {"pid": 31337}


def test_a_client_that_fails_without_a_word_still_gives_a_reason():
    result = _end_service(arguments=["-e", "process.exit(3)"])
    assert result["outcome"] == "refused: exe service stop: 3"


def test_the_real_client_takes_the_call_the_shell_makes(tmp_path):
    """The shell's arguments are the client's own command line, checked
    against the client itself, and the running service is looked for with
    the shell's own finder: asked to stop at a port where nothing runs, the
    client says so in the catalogue's sentence and ends with zero — an end
    the update goes on from."""
    from cli.texts import Texts

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    script = f"""
const {{ spawn }} = require('child_process')
const path = require('path')
const dienstsuche = require({json.dumps(str(DIENSTSUCHE))})
process.env.EXE_AI_DATEN = {json.dumps(str(tmp_path))}
const PORT = {port}
const ADDRESS = 'http://127.0.0.1:{port}'
const app = {{ isPackaged: false }}
const clientProgram = {json.dumps({"file": sys.executable, "args": ["-m", "cli"], "cwd": str(WURZEL)})}
const logged = []
console.log = (line) => logged.push(line)
let dienstVorgefunden = null
let kind = null
{_end_service_piece()}
endServiceForUpdate().then(() => 'ended', (failure) => `refused: ${{failure.message}}`).then((outcome) => {{
  process.stdout.write(JSON.stringify({{ outcome, logged }}) + "\\n")
}})
"""
    result = _laufe(script)
    assert result["outcome"] == "ended"
    said = Texts("en").t("cli.service_not_running", port=port)
    assert result["logged"] == [f"Service: ended before the update is installed ({said})"]


def test_after_a_failed_installation_the_service_starts_again_and_the_window_loads_anew():
    """The page the window shows belonged to the service that ended, so the
    interface is loaded again once the new one answers; and a service that
    does not come up counts as a failed start, not as one that had already
    answered."""
    script = f"""
const order = []
const logged = []
console.log = (line) => logged.push(line)
let dienstAntwortete = true
async function dienstStarten() {{ order.push(['start', dienstAntwortete]) }}
async function warten() {{ order.push(['wait']) }}
{_restart_piece()}
restartServiceAfterUpdate()
setImmediate(() => process.stdout.write(JSON.stringify({{ order, logged }}) + "\\n"))
"""
    assert _laufe(script) == {
        "order": [["start", False], ["wait"]],
        "logged": ["Service: starting again, the update was not installed"],
    }


def test_the_late_exit_of_a_service_ended_for_an_update_says_nothing_about_the_next_one():
    """Falls over without the listeners bound to their own process: the
    ended service's 'exit' comes when its shutdown is through — after the
    shell let go of it and started the next one. It forgot the new process
    and called the start failed."""
    script = f"""
const PORT = 8090
const children = []
function spawn() {{
  const child = {{ listeners: {{}}, on(name, f) {{ this.listeners[name] = f }}, unref() {{}} }}
  children.push(child)
  return child
}}
async function antwortet() {{ return false }}
function dienstpfad() {{ return '/unused' }}
let kind = null
let beendet = false
let shown = false
console.error = () => {{}}
const fenster = {{
  isDestroyed: () => false,
  webContents: {{
    isLoading: () => false,
    executeJavaScript: (js) => {{ if (js.includes('fehlgeschlagen')) shown = true; return Promise.resolve() }},
  }},
}}
{_dienstStarten()}
;(async () => {{
  await dienstStarten()
  dienstAntwortete = true
  // Ended before an update, and the installation then failed: the shell
  // lets go of the old service and starts the next.
  kind = null
  dienstAntwortete = false
  await dienstStarten()
  const [old, next] = children
  old.listeners.exit(0, null)
  const afterOld = {{ keepsNext: kind === next, failed: dienstFehlgeschlagen, shown }}
  // The silence probe: the service that IS the shell's still speaks.
  next.listeners.exit(1, null)
  process.stdout.write(JSON.stringify({{
    afterOld, afterNext: {{ forgotten: kind === null, failed: dienstFehlgeschlagen, shown }},
  }}) + "\\n")
}})()
"""
    assert _laufe(script) == {
        "afterOld": {"keepsNext": True, "failed": False, "shown": False},
        "afterNext": {"forgotten": True, "failed": True, "shown": True},
    }
