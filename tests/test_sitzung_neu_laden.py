"""A page with the key of a service that is gone reloads itself — once.

The session key is baked into the page. After a service restart every open
window still carries the old one, the service refuses every call with 401,
and the window kept asking for the rest of the day: measured on one window,
27 000 refused calls in just over seven hours, "model could not be loaded"
on screen and no word that a reload would heal it.

The guard is the point of these tests: a 401 reloads the page, a second 401
within a minute does NOT (a key wrong for another reason must not turn into
a reload loop), and any other failure never touches the page. The input
bar's half — parking the unsent words on the way out — is pinned at the
source.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import node_script
from tests.fensterquelle import BAR_SOURCE

WURZEL = Path(__file__).resolve().parents[1]
API = WURZEL / "frontend/src/lib/api.js"
EINGABELEISTE = BAR_SOURCE

# The browser the module expects: a window with a key and a reload that only
# counts, a tab storage that remembers, and a fetch that answers what the
# test says.
UMGEBUNG = """
globalThis.__reloads = 0
globalThis.__events = []
globalThis.window = {
  __SITZUNGSSCHLUESSEL__: 'alt',
  location: { reload() { globalThis.__reloads++ } },
  dispatchEvent(e) { globalThis.__events.push(e.type) },
}
globalThis.CustomEvent = class { constructor(type) { this.type = type } }
const speicher = {}
globalThis.sessionStorage = {
  getItem: (k) => (k in speicher ? speicher[k] : null),
  setItem: (k, v) => { speicher[k] = String(v) },
  removeItem: (k) => { delete speicher[k] },
}
globalThis.__status = 401
globalThis.fetch = async () => ({
  ok: false,
  status: globalThis.__status,
  json: async () => ({ detail: 'Sitzungsschlüssel ungültig' }),
})
"""


def _modul() -> str:
    """api.js as a plain script: the exports become declarations — the two
    async generators included, whose `function*` the pattern has to reach."""
    quelle = API.read_text(encoding="utf-8")
    return re.sub(
        r"^export (?=(?:async )?(?:function\*?|const|let|class) )", "", quelle, flags=re.M
    )


def _node(skript: str) -> dict:
    lauf = node_script(skript)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout.strip().splitlines()[-1])


ohne_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


@ohne_node
def test_ein_abgewiesener_schluessel_laedt_die_seite_einmal_neu():
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  const erster = await ruf('/models').catch((f) => f.status)
  const zweiter = await ruf('/models').catch((f) => f.status)
  console.log(JSON.stringify({{ erster, zweiter, reloads: globalThis.__reloads, events: globalThis.__events }}))
}})()
""")
    # Both calls still fail the way they always did — the reload is a side
    # effect, not a swallowed error — but the page is fetched anew ONCE.
    assert ergebnis["erster"] == 401 and ergebnis["zweiter"] == 401
    assert ergebnis["reloads"] == 1
    # The input bar was told first, so the unsent words can be parked.
    assert ergebnis["events"] == ["exe-ai:vor-neuladen"]


@ohne_node
def test_nach_einer_minute_darf_die_seite_wieder_neu_laden():
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  await ruf('/models').catch(() => null)
  sessionStorage.setItem('exe-ai:sitzung-neu-geladen', String(Date.now() - 61_000))
  await ruf('/models').catch(() => null)
  console.log(JSON.stringify({{ reloads: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["reloads"] == 2


@ohne_node
def test_a_page_without_a_key_never_reloads_on_a_refusal():
    """A page that never had a key — the service demands a password and
    the sign-in is still open — has no stale key to heal: a 401 there is the
    wrong password, which the sign-in shows, and the page stays. Once the
    sign-in has handed the key in (`setSessionKey`), the guard is back."""
    ergebnis = _node(f"""
{UMGEBUNG}
globalThis.window.__SITZUNGSSCHLUESSEL__ = null
{_modul()}
;(async () => {{
  const status = await ruf('/models').catch((f) => f.status)
  const meldung = await ruf('/models').catch((f) => f.message)
  const ohne = globalThis.__reloads
  setSessionKey('neu')
  await ruf('/models').catch(() => null)
  console.log(JSON.stringify({{ status, meldung, ohne, mit: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["status"] == 401
    assert ergebnis["meldung"] == "Sitzungsschlüssel ungültig"
    assert ergebnis["ohne"] == 0
    assert ergebnis["mit"] == 1


@ohne_node
def test_ein_anderer_fehler_laedt_nichts_neu():
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  globalThis.__status = 500
  const status = await ruf('/models').catch((f) => f.status)
  console.log(JSON.stringify({{ status, reloads: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["status"] == 500
    assert ergebnis["reloads"] == 0


@ohne_node
def test_alle_tueren_kennen_den_abgewiesenen_schluessel():
    """The three fetch doors of api.js — the plain calls, the answer stream
    and the stream that resumes a run — go through different fetches; every
    one of them has to reach the same reload. Driven, not counted in the
    source: a fourth fetch door that forgets the reload stays invisible to a
    text count. That no door is missed at all is watched without node, by
    shape (test_jede_fetch_tuer_kennt_die_abgewiesene_antwort)."""
    tueren = (
        ("der einfache Ruf", "await ruf('/models')"),
        (
            "der Antwortstrom",
            "for await (const stueck of antwortStrom({})) break",
        ),
        (
            "der Wiederanhang",
            "for await (const stueck of zusehenStrom('g', 0)) break",
        ),
    )
    for name, aufruf in tueren:
        ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  let meldung = null
  try {{
    {aufruf}
  }} catch (fehler) {{
    meldung = fehler.message
  }}
  console.log(JSON.stringify({{ reloads: globalThis.__reloads, meldung }}))
}})()
""")
        assert ergebnis["reloads"] == 1, name
        # Every door hands out the reason the service sent, not the bare
        # number — that is the half the order is about.
        assert ergebnis["meldung"] == "Sitzungsschlüssel ungültig", name


def test_jede_fetch_tuer_kennt_die_abgewiesene_antwort():
    """The always-on half of the guard, found by shape rather than counted by
    hand: every `await fetch(` in api.js must be followed by the one reading
    of a refusal. A door that forgets it has no `!antwort.ok` of its own —
    exactly the failure this file exists for, and this check needs no node.
    Comment lines are left out: the module talks about this call in its own
    prose, and a quoted `await fetch(` must not fail its own guard."""
    quelle = "\n".join(
        zeile
        for zeile in API.read_text(encoding="utf-8").splitlines()
        if not zeile.lstrip().startswith(("//", "*", "/*"))
    )
    assert quelle.count("await fetch(") == 3
    assert quelle.count("if (!antwort.ok) throw await errorFrom(antwort)") == 3
    assert quelle.count("if (antwort.status === 401) sitzungNeuLaden()") == 1


@ohne_node
def test_ein_grund_des_dienstes_steht_vor_der_nummer():
    """The order of the refusal's parts: the service's own reason where it
    sends one, the number only where it sends none — driven here, because a
    picture of the fallback says nothing about the other half."""
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  const mitGrund = await ruf('/models').catch((f) => f.message)
  globalThis.fetch = async () => ({{ ok: false, status: 502, json: async () => ({{}}) }})
  const ohneGrund = await ruf('/models').catch((f) => f.message)
  console.log(JSON.stringify({{ mitGrund, ohneGrund }}))
}})()
""")
    assert ergebnis["mitGrund"] == "Sitzungsschlüssel ungültig"
    # Without a reason the number is named — and nothing else. The sentence
    # around it comes with the page (app/main.py, `window.__TEXTE__`); this
    # run has no page, so there is no sentence to stand in front of it.
    assert ergebnis["ohneGrund"] == "502"


@ohne_node
def test_the_sentence_before_the_number_comes_with_the_page():
    """The other half of the same rule: every served page carries the two
    sentences for the moment before the catalogue (app/main.py), in the
    language the service knows for the interface. Here the English one, for
    the number a service that sends no reason answers with."""
    ergebnis = _node(f"""
{UMGEBUNG}
globalThis.window.__TEXTE__ = {{ status: 'Error {{status}}' }}
{_modul()}
;(async () => {{
  globalThis.fetch = async () => ({{ ok: false, status: 502, json: async () => ({{}}) }})
  const meldung = await ruf('/models').catch((f) => f.message)
  console.log(JSON.stringify({{ meldung }}))
}})()
""")
    assert ergebnis["meldung"] == "Error 502"


def test_die_eingabeleiste_parkt_die_worte_und_holt_sie_zurueck():
    quelle = EINGABELEISTE.read_text(encoding="utf-8")
    assert "window.addEventListener('exe-ai:vor-neuladen', parken)" in quelle
    assert "sessionStorage.getItem(NEULADE_ENTWURF)" in quelle
    assert "sessionStorage.removeItem(NEULADE_ENTWURF)" in quelle
    # With the chat they belong to — filed under it, not into the field of
    # whatever chat is opened next.
    assert "JSON.stringify({ text, chat: entwurfChat })" in quelle
    assert "entwuerfe.set(wieder.chat, { ...LEERER_ENTWURF, text: wieder.text })" in quelle


@ohne_node
def test_ohne_tab_speicher_wird_nicht_neu_geladen():
    """No storage, no lock — and a reload without one is the loop the mark
    exists to prevent: every 401 reloads, the new page gets the same 401,
    for as long as the tab is open. Then the refusal stands instead."""
    ergebnis = _node(f"""
{UMGEBUNG}
globalThis.sessionStorage = {{
  getItem() {{ throw new Error('blocked') }},
  setItem() {{ throw new Error('blocked') }},
  removeItem() {{ throw new Error('blocked') }},
}}
{_modul()}
;(async () => {{
  const status = await ruf('/models').catch((f) => f.status)
  console.log(JSON.stringify({{ status, reloads: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["status"] == 401
    assert ergebnis["reloads"] == 0


@ohne_node
def test_nach_drei_neuladungen_in_zehn_minuten_bleibt_die_abweisung_stehen():
    """A key that stays wrong after a reload — a cached page still carrying
    the old one — is not healed by reloading again, and a page reloading
    itself every minute all day threw away whatever stood on it each time."""
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  const jetzt = Date.now()
  sessionStorage.setItem('exe-ai:sitzung-neu-geladen', JSON.stringify([jetzt - 500_000, jetzt - 300_000, jetzt - 100_000]))
  await ruf('/models').catch(() => null)
  const nachDrei = globalThis.__reloads
  // Eleven minutes on, the oldest reload has left the window.
  sessionStorage.setItem('exe-ai:sitzung-neu-geladen', JSON.stringify([jetzt - 700_000, jetzt - 300_000, jetzt - 100_000]))
  await ruf('/models').catch(() => null)
  console.log(JSON.stringify({{ nachDrei, spaeter: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["nachDrei"] == 0
    assert ergebnis["spaeter"] == 1


ANSWERS_OK = """globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) })"""
ANSWERS_REFUSAL = """globalThis.fetch = async () => ({
  ok: false, status: 401, json: async () => ({ detail: 'Sitzungsschlüssel ungültig' }),
})"""


@ohne_node
def test_a_reload_the_service_accepted_does_not_count_against_the_lock():
    """A service restarted a fourth time within ten minutes hands out a new
    key again, and the window has to take it: every reload that ended with
    the service answering the page is forgotten, so none of them counts."""
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  for (let restart = 0; restart < 5; restart++) {{
    {ANSWERS_REFUSAL}
    await ruf('/models').catch(() => null)
    // The page came back with the new key, and the service answers it.
    {ANSWERS_OK}
    await ruf('/models')
  }}
  console.log(JSON.stringify({{ reloads: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["reloads"] == 5


@ohne_node
def test_a_key_that_stays_refused_after_the_reload_is_not_reloaded_again():
    """The lock stays for what it was made for: the reload did not help, the
    page was refused again, and no answer ever followed that would forget it."""
    ergebnis = _node(f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  for (let attempt = 0; attempt < 5; attempt++) {{
    await ruf('/models').catch(() => null)
    // The minute is over each time, the ten minutes are not.
    const marks = JSON.parse(sessionStorage.getItem('exe-ai:sitzung-neu-geladen') || '[]')
    sessionStorage.setItem('exe-ai:sitzung-neu-geladen', JSON.stringify(marks.map((m) => m - 61_000)))
  }}
  console.log(JSON.stringify({{ reloads: globalThis.__reloads }}))
}})()
""")
    assert ergebnis["reloads"] == 3


@ohne_node
def test_silence_an_answer_on_a_page_without_a_key_forgets_nothing():
    """The sign-in's own answer is no sign that a key was accepted: without
    one in the page there is nothing it could say about."""
    ergebnis = _node(f"""
{UMGEBUNG}
globalThis.window.__SITZUNGSSCHLUESSEL__ = null
{_modul()}
;(async () => {{
  sessionStorage.setItem('exe-ai:sitzung-neu-geladen', JSON.stringify([Date.now()]))
  {ANSWERS_OK}
  await ruf('/login', {{ method: 'POST', body: '{{}}' }})
  console.log(JSON.stringify({{ mark: sessionStorage.getItem('exe-ai:sitzung-neu-geladen') !== null }}))
}})()
""")
    assert ergebnis["mark"] is True
