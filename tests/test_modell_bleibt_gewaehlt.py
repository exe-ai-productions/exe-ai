"""The chosen model stays chosen while it is not reachable — run, not read.

``modelleLaden`` in ``frontend/src/lib/zustand.svelte.js`` used to take the
first model of the list, and store it as the new choice, whenever the chosen
one was missing from the list of reachable models: on every outage, silently
and for good. Now the choice stands and nothing is stored; the first of the
list is taken only where none is chosen yet or where the service no longer
carries the server of the chosen one.

A model is named by its server, and a server that does not answer names
nothing. So the name goes into the service with the choice, and a window
that starts while the server is away shows the model under that name. The
stored name follows the list: where the service names the chosen model
otherwise than stored, the choice is stored again under that name.

The state module is compiled with the Svelte compiler (it uses runes) and
its imports are bent to stand-ins that only record — all but one: the
module that stores the choice (``lib/anzeige.js``) runs as it is, against a
stand-in of the API. What is stored and what is read back at a start is its
work, and the state module's reading of it is what these tests are about.
The two model lists the service would hand out are set per scenario.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import modellwahl

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
STATE = FRONTEND / "src/lib/zustand.svelte.js"
DISPLAY = FRONTEND / "src/lib/anzeige.js"
EVENT_LINE = FRONTEND / "src/lib/ereignisstrom.svelte.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# Everything the state module imports, but for the module that stores the
# choice, as stand-ins. `log` is what the assertions read: which list was
# asked for, and what was written to the service.
STAND_INS = """
export const log = []
export const lists = {
  reachable: [], all: [], failAll: false, hold: null, holdRead: null, kept: null,
}
export const api = {
  // The answer is what the service held when it was asked; `hold` keeps it
  // on the way for as long as the scenario wants.
  modelle: async (fresh) => {
    log.push(['api.modelle', Boolean(fresh)])
    const answer = lists.reachable
    if (lists.hold) await lists.hold
    return answer
  },
  modelleAlle: async () => {
    log.push(['api.modelleAlle'])
    if (lists.failAll) throw new Error('no answer')
    return lists.all
  },
  // The settings as the service keeps them: the stored choice is handed
  // out at a start, and every write is noted.
  einstellungAufgeloestViele: async () => {
    const held = lists.kept ? { modell_zuletzt: { wert: lists.kept, herkunft: 'global' } } : {}
    // Like the lists: the answer is what the service held when it was asked,
    // and `holdRead` keeps it on the way.
    if (lists.holdRead) await lists.holdRead
    return held
  },
  einstellungSetzen: async (scope, key, value) => { log.push(['stored', scope, key, value]) },
}
export const melde = (text, kind) => log.push(['notice', text, kind])
export const melden = () => {}
// Handed on by the state module to the rest of the window.
export const aktualisiereMeldung = () => {}
export const meldungen = []
export const meldungenZuAuftragSchliessen = () => {}
export const schliesseMeldung = () => {}
export const t = (key) => key
export const farbtonDrehen = () => {}
export const chatZustandLaden = async () => {}
export const chatanzeige = {}
export const chatless = () => false
export const VORGABE_CHATLAYOUT = {}
export const chatlayoutAnwenden = () => {}
export const chatlayoutAusGespeichert = () => ({})
export const chatlayoutZumSpeichern = () => ({})
export const ausFenster = () => null
export const ohneWeg = () => {}
export const leeren = () => {}
"""

# Compiles the state module for the client, bends its relative imports and
# runs the scenario handed in. The compiled module is rewritten, not the
# source; the storing module is copied with only its API bent.
DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const standIns = "from './chosen-model.standins.mjs'"
writeFileSync(
  'chosen-model.display.mjs',
  readFileSync(%(display)r, 'utf-8').replace(/from '\\.\\/api\\.js'/g, standIns),
)
let code = compileModule(readFileSync(%(state)r, 'utf-8'), {
  filename: 'zustand.svelte.js', generate: 'client',
}).js.code
code = code
  .replace(/from '\\.\\/anzeige\\.js'/g, "from './chosen-model.display.mjs'")
  .replace(/from '\\.\\/(?!chosen-model\\.)[^']+'/g, standIns)
writeFileSync('chosen-model.state.mjs', code)

// The module sets the look on the page's root element while it loads; a
// root that takes the calls and keeps nothing is all that needs.
globalThis.document = { documentElement: {
  setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
  style: { setProperty() {}, removeProperty() {} },
} }
const { log, lists } = await import('./chosen-model.standins.mjs')
// The storing module hangs itself on the page's going away, to send what
// still waits. Only that is caught here; the page itself is not there.
const pageEvents = {}
globalThis.window = { addEventListener: (name, run) => { pageEvents[name] = run } }
const display = await import('./chosen-model.display.mjs')
delete globalThis.window
const state = await import('./chosen-model.state.mjs')
const { zustand, modelleLaden, aktuellesModell, modellAnwenden, modellWaehlen } = state
// A window's start, in the order the app keeps: what the service holds is
// read, and the choice stored there is applied.
const start = async (kept = null) => {
  lists.kept = kept
  const loaded = await display.anzeigeLaden()
  if (loaded.modell) modellAnwenden(loaded.modell)
}
// Every choice written to the service. A write waits a moment for the next
// one; the page going away sends what waits, and that is how it is read.
const stored = () => {
  pageEvents.pagehide()
  return log
    .filter((entry) => entry[0] === 'stored' && entry[2] === 'modell_zuletzt')
    .map((entry) => entry[3])
}
const asked = () => log.map((entry) => entry[0])
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""

# The two lists as the service hands them out: `/models` names reachable
# models only, `/models?alle=true` names every server it carries.
SERVICE = """
    // `name_gemeldet`: the name is one the server reports, not the one the
    // configuration gives it.
    const alpha = {
      id: 'alpha', anbieter: 'alpha', name: 'Alpha 35B', name_gemeldet: true, server_state: 'idle',
    }
    const beta = {
      id: 'beta', anbieter: 'beta', name: 'Beta 9B', name_gemeldet: true, server_state: 'idle',
    }
    // A model of a catalogue: many models on one server.
    const large = {
      id: 'cloud:large-1', anbieter: 'cloud', name: 'Large 1', name_gemeldet: true,
      server_state: 'idle',
    }
    // What the service still says of a server that is not reachable: its
    // configured name, no reported one, and the word `offline` — once per
    // server, under its bare id, whether it carries a catalogue or not.
    const alphaGone = {
      id: 'alpha', anbieter: 'alpha', name: 'alpha', name_gemeldet: false, server_state: 'offline',
    }
    const cloudGone = {
      id: 'cloud', anbieter: 'cloud', name: 'cloud', name_gemeldet: false, server_state: 'offline',
    }
"""


def _node(written: dict[str, str], built: tuple[str, ...]) -> dict:
    """Runs the first of the files written beside the frontend's modules
    and hands back what its scenario reported. The files, and the ones the
    run builds, are gone afterwards."""
    files = {FRONTEND / name: content for name, content in written.items()}
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    try:
        run = subprocess.run(
            ["node", next(iter(written))], cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for path in [*files, *(FRONTEND / name for name in built)]:
            path.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in run.stdout, run.stdout[-3000:]
    return json.loads(run.stdout.split(mark, 1)[1].strip())


def _run(scenario: str) -> dict:
    driver = DRIVER % {"state": str(STATE), "display": str(DISPLAY), "scenario": SERVICE + scenario}
    return _node(
        {"chosen-model.check.mjs": driver, "chosen-model.standins.mjs": STAND_INS},
        ("chosen-model.state.mjs", "chosen-model.display.mjs"),
    )


@needs_node
def test_a_chosen_model_that_drops_out_stays_chosen_and_nothing_is_stored():
    """The outage while the window is open: the chosen model leaves the list
    of reachable ones. The choice stands, nothing is written, and the model
    keeps the name the window had of it with the word of its server."""
    report = _run("""
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await start({ id: 'alpha', name: 'Alpha 35B' })
    await modelleLaden()
    const before = { ...aktuellesModell() }
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await modelleLaden()
    return {
      before, chosen: zustand.modellId, stored: stored(), current: aktuellesModell(),
      listed: zustand.modelle.map((model) => model.id),
    }
    """)
    assert report["before"]["name"] == "Alpha 35B"
    assert report["chosen"] == "alpha"
    assert report["stored"] == []
    # The name the window had, not the configured one the service falls back
    # to for a server it cannot ask — and the server's own word.
    assert report["current"]["name"] == "Alpha 35B"
    assert report["current"]["server_state"] == "offline"
    assert report["current"]["erreichbar"] is False
    # The picker's list is the reachable ones, as before.
    assert report["listed"] == ["beta"]


@needs_node
def test_silence_probe_without_a_choice_the_first_of_the_list_is_chosen_and_stored():
    report = _run("""
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await start()
    await modelleLaden()
    return { chosen: zustand.modellId, stored: stored(), asked: asked(), current: aktuellesModell() }
    """)
    assert report["chosen"] == "alpha"
    assert report["stored"] == [{"id": "alpha", "name": "Alpha 35B"}]
    assert report["current"]["name"] == "Alpha 35B"
    # A reachable choice never costs a second request.
    assert "api.modelleAlle" not in report["asked"]


@needs_node
def test_a_server_the_service_no_longer_carries_gives_way_to_the_first_of_the_list():
    """The provider was removed: its model is nobody's to wait for."""
    report = _run("""
    lists.reachable = [beta]
    lists.all = [beta]
    await start({ id: 'alpha', name: 'Alpha 35B' })
    await modelleLaden()
    return { chosen: zustand.modellId, stored: stored(), current: aktuellesModell() }
    """)
    assert report["chosen"] == "beta"
    assert report["stored"] == [{"id": "beta", "name": "Beta 9B"}]
    assert report["current"]["name"] == "Beta 9B"


# The choice as a window writes it, and the lists a later window finds while
# the model's server is away: a model that is its server's only one, and a
# model of a catalogue.
AWAY_AT_THE_START = [
    pytest.param("alpha", "Alpha 35B", "alpha", "[alphaGone, beta]", id="a server's only model"),
    pytest.param("cloud:large-1", "Large 1", "cloud", "[cloudGone, beta]", id="a model of a catalogue"),
]


@needs_node
@pytest.mark.parametrize(("model", "name", "server", "carried"), AWAY_AT_THE_START)
def test_a_window_that_starts_while_the_server_is_away_shows_the_name_stored_with_the_choice(
    model: str, name: str, server: str, carried: str
):
    """Falls over without the name in the stored choice: the service names
    a server it cannot ask by its configured name, and a model of a
    catalogue not at all. Two windows, one after the other: the first
    chooses, the second starts on what the first wrote."""
    first = _run(f"""
    lists.reachable = [alpha, beta, large]
    lists.all = [alpha, beta, large]
    await start({{ id: 'beta', name: 'Beta 9B' }})
    await modelleLaden()
    modellWaehlen({json.dumps(model)})
    return {{ stored: stored() }}
    """)
    assert first["stored"] == [{"id": model, "name": name}]
    # What the service keeps of a write is what its own check lets through.
    kept = modellwahl.zuletzt_pruefen(first["stored"][-1])

    second = _run(f"""
    lists.reachable = [beta]
    lists.all = {carried}
    await start({json.dumps(kept)})
    await modelleLaden()
    return {{ chosen: zustand.modellId, stored: stored(), current: aktuellesModell() }}
    """)
    assert second["chosen"] == model
    assert second["stored"] == []
    assert second["current"]["name"] == name
    assert second["current"]["anbieter"] == server
    assert second["current"]["erreichbar"] is False
    assert second["current"]["server_state"] == "offline"


@needs_node
def test_a_choice_made_before_the_first_read_is_back_is_sent_with_its_name():
    """The model list can answer before the settings do: the first of the
    list is then chosen while nothing may be written yet. It is held, wins
    over the older choice the read brings, and goes out with its name."""
    report = _run("""
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await modelleLaden()
    const held = stored()
    await start({ id: 'beta', name: 'Beta 9B' })
    const sent = stored()
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await modelleLaden()
    return { held, sent, chosen: zustand.modellId, away: aktuellesModell().name }
    """)
    assert report["held"] == []
    assert report["sent"] == [{"id": "alpha", "name": "Alpha 35B"}]
    assert report["chosen"] == "alpha"
    assert report["away"] == "Alpha 35B"


@needs_node
def test_a_known_entry_without_a_name_does_not_hide_the_stored_one():
    """The window's own entry of the model comes first for the name — but
    only where it has one."""
    report = _run("""
    const nameless = { id: 'alpha', anbieter: 'alpha', server_state: 'idle' }
    lists.reachable = [nameless, beta]
    lists.all = [nameless, beta]
    await start({ id: 'alpha', name: 'Alpha 35B' })
    await modelleLaden()
    const listed = aktuellesModell().name ?? null
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await modelleLaden()
    return { listed, away: aktuellesModell().name }
    """)
    assert report["listed"] is None
    assert report["away"] == "Alpha 35B"


@needs_node
@pytest.mark.parametrize(("model", "name", "server", "carried"), AWAY_AT_THE_START)
def test_the_stored_name_follows_the_name_the_list_gives_the_chosen_model(
    model: str, name: str, server: str, carried: str
):
    """Falls over without the fix: the name was written at the choice only.
    A server that names its model anew — or runs another one behind the same
    id — left the old name stored, and the next start with the server away
    showed it again. Now the load that finds the other name stores the
    choice once under it, without a notice and without choosing anything; a
    second load finds nothing left to write. Two windows, one after the
    other: the second starts on what the first wrote, with the server away."""
    first = _run(f"""
    lists.reachable = [alpha, beta, large]
    lists.all = [alpha, beta, large]
    await start({{ id: {json.dumps(model)}, name: 'An older name' }})
    await modelleLaden()
    const once = stored()
    await modelleLaden()
    return {{
      once, stored: stored(), chosen: zustand.modellId, listed: aktuellesModell().name,
      notices: log.filter((entry) => entry[0] === 'notice'),
    }}
    """)
    assert first["once"] == [{"id": model, "name": name}]
    assert first["stored"] == first["once"]
    assert first["chosen"] == model
    assert first["listed"] == name
    assert first["notices"] == []
    # What the service keeps of a write is what its own check lets through.
    kept = modellwahl.zuletzt_pruefen(first["stored"][-1])

    second = _run(f"""
    lists.reachable = [beta]
    lists.all = {carried}
    await start({json.dumps(kept)})
    await modelleLaden()
    return {{ chosen: zustand.modellId, stored: stored(), current: aktuellesModell() }}
    """)
    assert second["chosen"] == model
    assert second["stored"] == []
    assert second["current"]["name"] == name
    assert second["current"]["anbieter"] == server


@needs_node
def test_a_model_named_anew_while_the_window_is_open_is_stored_under_the_new_name():
    """The server comes back with another model behind the same id while the
    window stands: the next load of the list stores the choice under the new
    name, and when the server then drops out the window shows that name."""
    report = _run("""
    const renamed = { ...alpha, name: 'Alpha 70B' }
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await start({ id: 'alpha', name: 'Alpha 35B' })
    await modelleLaden()
    const before = stored()
    lists.reachable = [renamed, beta]
    lists.all = [renamed, beta]
    await modelleLaden()
    const after = stored()
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await modelleLaden()
    return { before, after, chosen: zustand.modellId, away: aktuellesModell().name, stored: stored() }
    """)
    # Silence probe: the list names the model as stored, nothing is written.
    assert report["before"] == []
    assert report["after"] == [{"id": "alpha", "name": "Alpha 70B"}]
    assert report["chosen"] == "alpha"
    assert report["away"] == "Alpha 70B"
    # The outage itself writes nothing.
    assert report["stored"] == report["after"]


@needs_node
def test_a_name_that_is_followed_never_changes_which_model_is_stored():
    """Falls over without the fix: the follow wrote the whole choice from
    this window's own copy. Another window on the same service chose a
    different model after this one read its copy; this window's list then
    named its model anew, and the old model was stored over the new choice —
    the next start took it. Now the service is read again first, nothing is
    written where it holds another model, and this window keeps showing the
    one it has."""
    report = _run("""
    await start({ id: 'alpha', name: 'Alpha 35B' })
    lists.reachable = [{ ...alpha, name: 'Alpha 70B' }, beta]
    lists.all = lists.reachable
    // Another window chose beta in the meantime.
    lists.kept = { id: 'beta', name: 'Beta 9B' }
    await modelleLaden()
    const other = stored()
    // Silence probe: the choice is the same again, and the name follows.
    lists.kept = { id: 'alpha', name: 'Alpha 35B' }
    await modelleLaden()
    return {
      other, stored: stored(), chosen: zustand.modellId, listed: aktuellesModell().name,
    }
    """)
    assert report["other"] == []
    assert report["stored"] == [{"id": "alpha", "name": "Alpha 70B"}]
    assert report["chosen"] == "alpha"
    assert report["listed"] == "Alpha 70B"


@needs_node
def test_a_model_picked_while_the_name_is_being_followed_is_not_stored_over():
    """Falls over without the check: the service is read again before the
    name is written, and the answer says alpha is still the stored one. The
    user picks beta while that read is out; writing alpha's name then would
    put alpha over the pick, and the next start would open on it."""
    report = _run("""
    await start({ id: 'alpha', name: 'Alpha 35B' })
    lists.reachable = [{ ...alpha, name: 'Alpha 70B' }, beta]
    lists.all = lists.reachable
    let release
    lists.holdRead = new Promise((resolve) => { release = resolve })
    const load = modelleLaden()
    // The load has its list and waits for the read of the stored choice.
    while (!zustand.modelle.length) await new Promise((resolve) => setTimeout(resolve, 0))
    modellWaehlen('beta')
    lists.holdRead = null
    release()
    await load
    return { stored: stored(), chosen: zustand.modellId }
    """)
    assert report == {"stored": [{"id": "beta", "name": "Beta 9B"}], "chosen": "beta"}


@needs_node
def test_the_name_the_configuration_gives_a_server_is_not_stored_as_the_models():
    """Falls over without the fix: a reachable server that reports no model
    name is listed under the name the configuration gives it, and the stored
    name followed that — a start with the server away then showed the
    server's name where the model's last name should stand. A name that is
    reported is followed as before."""
    report = _run("""
    const unreported = { ...alpha, name: 'my server', name_gemeldet: false }
    await start({ id: 'alpha', name: 'Alpha 35B' })
    lists.reachable = [unreported, beta]
    lists.all = lists.reachable
    await modelleLaden()
    const unnamed = stored()
    lists.reachable = [{ ...alpha, name: 'Alpha 70B' }, beta]
    lists.all = lists.reachable
    await modelleLaden()
    return { unnamed, stored: stored() }
    """)
    assert report["unnamed"] == []
    assert report["stored"] == [{"id": "alpha", "name": "Alpha 70B"}]


@needs_node
def test_a_choice_stored_without_a_name_takes_the_name_the_list_gives():
    """A choice stored before names were kept with it, and its model is
    listed: no name is another name than the list's, so the choice is stored
    once with it — and has one to show when the server is away."""
    report = _run("""
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await start({ id: 'alpha' })
    await modelleLaden()
    const once = stored()
    await modelleLaden()
    return { once, stored: stored(), chosen: zustand.modellId }
    """)
    assert report["once"] == [{"id": "alpha", "name": "Alpha 35B"}]
    assert report["stored"] == report["once"]
    assert report["chosen"] == "alpha"


@needs_node
def test_silence_probe_the_stored_name_is_left_alone_where_the_list_says_nothing_new():
    """Nothing is written where the list names the chosen model as stored,
    where another model is named anew, where the chosen one's entry carries
    no name, and where it is not on the list at all — a server that is away
    stands in the full list under its configured name, which is not the
    model's."""
    report = _run("""
    const nameless = { id: 'alpha', anbieter: 'alpha', server_state: 'idle' }
    await start({ id: 'alpha', name: 'Alpha 35B' })
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await modelleLaden()
    const same = stored()
    lists.reachable = [alpha, { ...beta, name: 'Beta 12B' }]
    lists.all = lists.reachable
    await modelleLaden()
    const anotherModel = stored()
    lists.reachable = [nameless, beta]
    lists.all = [nameless, beta]
    await modelleLaden()
    const noName = stored()
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await modelleLaden()
    return {
      same, anotherModel, noName, away: stored(),
      chosen: zustand.modellId, name: aktuellesModell().name,
    }
    """)
    assert report == {
        "same": [], "anotherModel": [], "noName": [], "away": [],
        "chosen": "alpha", "name": "Alpha 35B",
    }


@needs_node
def test_of_two_loads_in_flight_only_the_one_started_last_stores_a_name():
    """An older answer that arrives late names the model as it was named
    then: it writes nothing, or the stored name would step back."""
    report = _run("""
    await start({ id: 'alpha', name: 'Alpha 35B' })
    let release
    lists.hold = new Promise((resolve) => { release = resolve })
    lists.reachable = [{ ...alpha, name: 'A name in between' }, beta]
    const older = modelleLaden()
    lists.hold = null
    lists.reachable = [{ ...alpha, name: 'Alpha 70B' }, beta]
    await modelleLaden()
    release()
    await older
    return { stored: stored(), chosen: zustand.modellId, listed: aktuellesModell().name }
    """)
    assert report == {
        "stored": [{"id": "alpha", "name": "Alpha 70B"}], "chosen": "alpha", "listed": "Alpha 70B",
    }


@needs_node
def test_at_the_start_a_choice_stored_without_a_name_stands_under_the_name_the_service_gives():
    """A choice stored before names were kept with it: the list of reachable
    models does not carry it, the full list does, and its entry there is
    all there is to show."""
    report = _run("""
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await start({ id: 'alpha' })
    await modelleLaden()
    return { chosen: zustand.modellId, stored: stored(), current: aktuellesModell() }
    """)
    assert report["chosen"] == "alpha"
    assert report["stored"] == []
    assert report["current"] == {
        "id": "alpha", "anbieter": "alpha", "name": "alpha", "name_gemeldet": False,
        "erreichbar": False, "server_state": "offline",
    }


@needs_node
def test_a_model_of_a_catalogue_stored_without_a_name_stands_while_its_server_is_carried():
    """A model named `provider:model`: the service lists an unreachable
    provider once, under its bare id. The choice stands on that entry, takes
    its word, and — stored without a name — carries no name the service did
    not give for it."""
    report = _run("""
    lists.reachable = [beta]
    lists.all = [cloudGone, beta]
    await start({ id: 'cloud:large-1' })
    await modelleLaden()
    return { chosen: zustand.modellId, stored: stored(), current: aktuellesModell() }
    """)
    assert report["chosen"] == "cloud:large-1"
    assert report["stored"] == []
    assert report["current"] == {
        "id": "cloud:large-1", "anbieter": "cloud", "erreichbar": False, "server_state": "offline",
    }


@needs_node
def test_a_model_that_comes_back_is_read_from_the_list_again():
    report = _run("""
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await start({ id: 'alpha', name: 'An older name' })
    await modelleLaden()
    const away = aktuellesModell().name
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await modelleLaden()
    return {
      away, chosen: zustand.modellId, stored: stored(), current: aktuellesModell(),
      held: zustand.unlistedModel,
    }
    """)
    assert report["away"] == "An older name"
    assert report["chosen"] == "alpha"
    # Back on the list under another name than stored: the stored one follows.
    assert report["stored"] == [{"id": "alpha", "name": "Alpha 35B"}]
    assert report["current"]["name"] == "Alpha 35B"
    assert report["current"]["server_state"] == "idle"
    assert report["held"] is None


@needs_node
def test_with_no_model_reachable_at_all_the_choice_stands():
    report = _run("""
    lists.reachable = []
    lists.all = [alphaGone]
    await start({ id: 'alpha' })
    await modelleLaden()
    return { chosen: zustand.modellId, stored: stored(), current: aktuellesModell() }
    """)
    assert report["chosen"] == "alpha"
    assert report["stored"] == []
    assert report["current"]["server_state"] == "offline"


@needs_node
def test_a_full_list_that_does_not_answer_switches_nothing():
    """Whether the server is still carried is not known: then nothing is
    chosen in its place and nothing is stored."""
    report = _run("""
    lists.reachable = [beta]
    lists.failAll = true
    await start({ id: 'alpha' })
    await modelleLaden()
    return { chosen: zustand.modellId, stored: stored(), notices: log.filter((entry) => entry[0] === 'notice') }
    """)
    assert report["chosen"] == "alpha"
    assert report["stored"] == []
    assert report["notices"] == [["notice", "modell.nicht_geladen", "fehler"]]


@needs_node
def test_of_two_loads_in_flight_the_one_started_last_stands():
    """An older answer that arrives late does not put back the model that
    has dropped out in the meantime."""
    report = _run("""
    lists.reachable = [alpha, beta]
    lists.all = [alpha, beta]
    await start({ id: 'alpha' })
    let release
    lists.hold = new Promise((resolve) => { release = resolve })
    const older = modelleLaden()
    lists.hold = null
    lists.reachable = [beta]
    lists.all = [alphaGone, beta]
    await modelleLaden()
    release()
    await older
    return {
      chosen: zustand.modellId, stored: stored(), current: aktuellesModell(),
      listed: zustand.modelle.map((model) => model.id),
    }
    """)
    assert report["chosen"] == "alpha"
    assert report["stored"] == []
    assert report["listed"] == ["beta"]
    assert report["current"]["server_state"] == "offline"


# --- what the service keeps of a choice ---------------------------------------


def test_the_service_keeps_the_name_beside_the_id():
    assert modellwahl.zuletzt_pruefen({"id": " cloud:large-1 ", "name": " Large 1 "}) == {
        "id": "cloud:large-1", "name": "Large 1",
    }


def test_silence_probe_a_choice_without_a_usable_name_is_kept_without_one():
    """The id is the choice; the name is a memo. A name that is no usable
    text does not cost the choice, and nothing else rides along."""
    for name in (None, "", "   ", 7, ["Large 1"], "x" * 401):
        assert modellwahl.zuletzt_pruefen({"id": "alpha", "name": name}) == {"id": "alpha"}
    assert modellwahl.zuletzt_pruefen({"id": "alpha"}) == {"id": "alpha"}
    assert modellwahl.zuletzt_pruefen({"id": "alpha", "name": "Alpha", "more": 1}) == {
        "id": "alpha", "name": "Alpha",
    }
    # Without an id there is no choice, whatever the name.
    assert modellwahl.zuletzt_pruefen({"name": "Alpha"}) is None


def test_the_name_survives_the_settings_route(client):
    written = client.put(
        "/api/v1/settings/global/modell_zuletzt",
        json={"wert": {"id": "cloud:large-1", "name": "Large 1"}},
    )
    assert written.status_code == 200, written.text
    read = client.get("/api/v1/settings/resolved/modell_zuletzt").json()
    assert read["wert"] == {"id": "cloud:large-1", "name": "Large 1"}


# --- the server's word reaches the chosen model beside the list ----------------

# Everything the event line imports, as stand-ins. The state is a real
# state proxy, as in the window: a line writing into a dead copy would pass
# on a plain object.
LINE_STAND_INS = """
import { proxy } from 'svelte/internal/client'
export const zustand = proxy({ modelle: [], unlistedModel: null })
export const api = { ereignisStrom: () => 'events' }
export const standLaden = () => {}
export const laden = () => {}
export const serverzustand = { geladen: true }
export const uebernehmen = () => {}
export const auftraegeStillLaden = () => {}
export const chatOeffnen = async () => {}
export const modelleLaden = () => {}
export const auswahlLaden = () => {}
"""

# Compiles the event line, bends its imports, and sends events in through
# the door the browser uses: a stand-in for `EventSource` whose `onmessage`
# the line itself hangs in.
LINE_DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const code = compileModule(readFileSync(%(line)r, 'utf-8'), {
  filename: 'ereignisstrom.svelte.js', generate: 'client',
}).js.code.replace(/from '\\.\\/[^']+'/g, "from './event-line.standins.mjs'")
writeFileSync('event-line.line.mjs', code)

const sources = []
globalThis.EventSource = class {
  constructor(url) { this.url = url; sources.push(this) }
  close() {}
}
const { zustand } = await import('./event-line.standins.mjs')
const line = await import('./event-line.line.mjs')
// The window as it stands while the chosen model is not on the list: one
// listed model on its own server, and the chosen one beside the list.
zustand.modelle = [{ id: 'beta', anbieter: 'beta', name: 'Beta 9B', server_state: 'idle' }]
zustand.unlistedModel = {
  id: 'cloud:large-1', anbieter: 'cloud', name: 'Large 1', erreichbar: false, server_state: 'offline',
}
line.verbinden()
const send = (event) => sources.at(-1).onmessage({ data: JSON.stringify(event) })
const words = () => ({
  beside: zustand.unlistedModel?.server_state ?? null,
  listed: zustand.modelle.map((model) => model.server_state),
})
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
// The line's net is a live interval; without this, node waits for it.
process.exit(0)
"""


def _run_event_line(scenario: str) -> dict:
    driver = LINE_DRIVER % {"line": str(EVENT_LINE), "scenario": scenario}
    return _node({"event-line.check.mjs": driver, "event-line.standins.mjs": LINE_STAND_INS}, ("event-line.line.mjs",))


@needs_node
def test_the_servers_word_reaches_the_chosen_model_beside_the_list_at_once():
    """Falls over without the fix: the word was set on the entries of the
    list only, and the chosen model beside it kept its old one until the
    list was loaded again."""
    report = _run_event_line("""
    send({ typ: 'server_state', endpoint_id: 'cloud', server_state: 'active' })
    return words()
    """)
    assert report == {"beside": "active", "listed": ["idle"]}


@needs_node
def test_silence_probe_another_servers_word_leaves_the_chosen_model_beside_the_list_alone():
    report = _run_event_line("""
    send({ typ: 'server_state', endpoint_id: 'beta', server_state: 'active' })
    const listedOnly = words()
    send({ typ: 'server_state', endpoint_id: 'cloud' })
    const noWord = words()
    zustand.unlistedModel = null
    send({ typ: 'server_state', endpoint_id: 'cloud', server_state: 'idle' })
    return { listedOnly, noWord, noneBeside: words() }
    """)
    # Listed models take the word as before; the one beside the list is not
    # that server's.
    assert report["listedOnly"] == {"beside": "offline", "listed": ["active"]}
    # An event without a word says nothing.
    assert report["noWord"] == {"beside": "offline", "listed": ["active"]}
    # With every chosen model on the list there is nothing beside it to set.
    assert report["noneBeside"] == {"beside": None, "listed": ["active"]}
