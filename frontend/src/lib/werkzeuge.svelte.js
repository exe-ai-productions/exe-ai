/*
  The tools: which ones a source offers, which of them were picked, and which
  of those are switched on right now.

  Its own module for the same reason the models have one: the window is not
  the place to decide what a tool is, and the connections gallery has no
  business knowing it at all.

  Two separate things live here, and they are stored in two different places
  on purpose:

    gewaehlt  WHICH of a server's tools exist for us. Stored in
              mcp_servers.json as `allowed_tools`, because the registry has to
              hold that line while it is starting — long before a window is
              open. One server reports nineteen tools; nobody ordered that.

    an / aus  Which of the picked ones go to the model right now. Stored in
              the settings cascade as `werkzeuge_aus` — the negative again, so
              a tool a server newly offers is simply there instead of hiding
              until somebody remembers to allow it.

  Keeping them apart is what lets a tool be silenced for an afternoon without
  losing the pick behind it.

  The built-in tool is its own source. It has no catalogue to pick from — it
  is either there or the feature is off — but it takes the switch like every
  other, and the registry refuses it just the same.
*/

import { api } from './api.js'
import { serverTitel } from './serverkatalog.js'

/* What is switched OFF. Same key the server checks — app/werkzeugwahl.py. */
const SCHLUESSEL_AUS = 'werkzeuge_aus'

/* The words for the built-in sources. Which source is a built-in one is NOT
   asked here — that comes from the API (`builtin` per row,
   app/tools/registry.py) and never from the name, see `quellen()`; a server
   may carry the same name as a built-in source.

   Every built-in source of the registry stands here with a word of its own:
   `shell` (the shell and the six file tools, and the job start — nine rows),
   `memory`, `skills`, `image` (the drawing tool), `cronjob` (schedule and
   schedule note), `goal` (the report), `dock` (the delivered files) and
   `clock` (the time). Without a
   word the row shows the raw server name — and a server called "clock"
   beside the built-in clock would then put two rows of the same name and
   the same sign in the window, one of them not even switchable
   (`test_i18n.py` holds the list). */
export const EINGEBAUTE_NAMEN = {
  /* The key stays `shell` — it is the server name in mcp_servers.json and
     what the tools are registered under. Only the word on screen changed:
     this source carries five file tools and the question tool besides the
     shell, so "Shell" had stopped being true. */
  shell: 'werkzeuge.eingebaut',
  memory: 'gedaechtnis.quelle',
  skills: 'skills.quelle',
  image: 'bild.quelle',
  cronjob: 'cronjobs.quelle',
  goal: 'werkzeuge.quelle_goal',
  dock: 'werkzeuge.quelle_dock',
  clock: 'werkzeuge.quelle_clock',
}

export const werkzeugwahl = $state({
  aus: [],
  /* GET /tools — what the registry currently approves, with descriptions. */
  freigegeben: [],
  /* GET /tools/servers — the entries with their full catalogue. */
  server: [],
})

/* What the tools view shows and which sources it has unfolded. Kept here and
   not in the view: the view is built anew on every visit to its section,
   and a selection that vanished on a round trip to Connections would send
   the hand looking for it again.

   `gezeigt` names its kind as well as its key — `{ art: 'quelle', id }` for
   a source, `{ art: 'werkzeug', name, quelle }` for a tool, `quelle` being
   the id of the source row it was opened from. One plain text for both mixed
   them up: a server called "fetch" with a tool called "fetch", or two
   servers offering a tool of the same name, opened the wrong one. */
export const werkzeugansicht = $state({ gezeigt: null, aufgeklappt: {} })

/* Every load counts; only the newest one may write. The list is fetched
   again each time the settings open and each time the tools section is
   shown, so two loads can be on the way at once, and the older answer must
   not land on top of the newer. */
let ladung = 0
/* A switch flipped while a load is on its way: the load may have read the
   setting before the switch was stored, and would put the old state back
   under the hand that just moved it. Counted at the start and at the end of
   every switch, with the ones still running beside it. */
let schaltungen = 0
let offeneSchaltungen = 0

export async function werkzeugeLaden() {
  const meine = ++ladung
  const schaltStand = schaltungen
  const [uebersicht, server, aus] = await Promise.all([
    api.werkzeuge().catch(() => null),
    api.serverUebersicht().catch(() => []),
    api.einstellungAufgeloest(SCHLUESSEL_AUS).catch(() => null),
  ])
  if (meine !== ladung) return
  werkzeugwahl.freigegeben = uebersicht?.werkzeuge ?? []
  werkzeugwahl.server = Array.isArray(server) ? server : []
  if (schaltStand === schaltungen && offeneSchaltungen === 0) {
    werkzeugwahl.aus = Array.isArray(aus?.wert) ? aus.wert : []
  }
}

/* ——— The catalogue: what exists for us at all ——— */

/** Is this tool of the server's picked at all? `null` means: all of them. */
export function istGewaehlt(server, name) {
  return server.allowed_tools === null || server.allowed_tools.includes(name)
}

export async function katalogSchalten(server, name, gewaehlt) {
  const alle = (server.alle_werkzeuge ?? []).map((w) => w.name)
  const bisher = server.allowed_tools === null ? alle : server.allowed_tools
  const neu = gewaehlt
    ? [...new Set([...bisher, name])]
    : bisher.filter((n) => n !== name)
  await katalogSichern(server, neu)
}

/** The "pick all" of a catalogue — and its counterpart, with an empty list. */
export async function katalogAlle(server, alle) {
  await katalogSichern(server, alle ? (server.alle_werkzeuge ?? []).map((w) => w.name) : [])
}

async function katalogSichern(server, namen) {
  /* Always write the explicit list — only whoever never unpicked keeps
     "everything". That way a provider cannot quietly deliver more later. */
  await api.serverSchreiben(server.name, { allowed_tools: namen })
  await werkzeugeLaden()
}

/* ——— The switch: which of them travel right now ——— */

export function istAn(name) {
  return !werkzeugwahl.aus.includes(name)
}

export async function schalten(name, an) {
  const vorher = werkzeugwahl.aus
  const neu = an
    ? vorher.filter((n) => n !== name)
    : [...new Set([...vorher, name])]
  werkzeugwahl.aus = neu
  schaltungen++
  offeneSchaltungen++
  try {
    await api.einstellungSetzen('global', SCHLUESSEL_AUS, neu.length ? neu : null)
  } catch {
    /* Put it back rather than showing a state that was never stored. */
    werkzeugwahl.aus = vorher
  } finally {
    offeneSchaltungen--
    schaltungen++
  }
}

/* ——— Who delivers what ——— */

/** What the registry knows about one tool: description and confirmation. */
function freigabe(name) {
  return werkzeugwahl.freigegeben.find((w) => w.name === name) ?? null
}

/**
 * The sources, each with the tools picked from it.
 *
 * Built-in first: it is the one that works without anybody connecting
 * anything. Then the servers in the order the API reports them, which is by
 * name — a gallery sorts by state, a list of names does not need to.
 */
export function quellen() {
  const liste = []

  /* Grouped by source: built-ins first — they are the ones that work
     without anybody connecting anything. Which is which is asked of the
     tool itself (`builtin` from the API) and never guessed from its server
     name: a server that happens to be called like a built-in one — a
     server called "clock", say — would otherwise push the built-in clock
     row out of the window, and the clock could not be switched off any
     more.

     A row that arrives without the field counts as a server's, not as a
     built-in: were it the other way round, a tool of somebody's server
     would stand among the built-ins as if it came with the program. This
     way the window shows less and the missing field is noticed. */
  const eigene = new Map()
  const ohneServer = new Map()
  for (const werkzeug of werkzeugwahl.freigegeben) {
    if (!werkzeug.builtin) {
      /* A server tool whose server the list does not know — its request
         failed, say — still needs a row of its own: the model is offered
         it either way, and a window that cannot show it cannot switch it
         off. */
      if (!werkzeugwahl.server.some((s) => s.name === werkzeug.server)) {
        if (!ohneServer.has(werkzeug.server)) ohneServer.set(werkzeug.server, [])
        ohneServer.get(werkzeug.server).push({
          name: werkzeug.name,
          beschreibung: werkzeug.beschreibung,
          quelle: werkzeug.server,
          builtin: false,
          needs_confirmation: werkzeug.needs_confirmation ?? false,
        })
      }
      continue
    }
    if (!eigene.has(werkzeug.server)) eigene.set(werkzeug.server, [])
    eigene.get(werkzeug.server).push({ ...werkzeug, quelle: werkzeug.server })
  }
  for (const [quelle, werkzeuge] of eigene) {
    liste.push({
      /* The row's key: a server may be named like a built-in source — a
         server called "clock" beside the built-in clock — and two rows
         sharing one key would take the whole window down (Svelte's keyed
         each). The plain name stays in ``kennung``; the sign and the word
         are read from it. */
      id: `builtin:${quelle}`,
      kennung: quelle,
      name: quelle,        // the window translates it where we have a word
      eingebaut: true,
      laeuft: true,
      katalog: [],         // nothing to pick from: it is there or it is not
      werkzeuge,
    })
  }

  for (const [quelle, werkzeuge] of ohneServer) {
    liste.push({
      id: `mcp:${quelle}`,
      kennung: quelle,
      name: serverTitel(quelle),
      eingebaut: false,
      laeuft: true,        // its tools are in the offer, so it is running
      katalog: [],
      werkzeuge,
    })
  }

  for (const server of werkzeugwahl.server) {
    const alle = server.alle_werkzeuge ?? []
    liste.push({
      /* Also a key of its own: a server's name is a key in a file somebody
         may write by hand, so it could read `builtin:clock` — and two rows
         with one key take the window down. */
      id: `mcp:${server.name}`,
      kennung: server.name,
      name: serverTitel(server.name),
      eingebaut: false,
      laeuft: server.laeuft,
      enabled: server.enabled,
      eintrag: server,
      katalog: alle.map((w) => ({ id: w.name, name: w.name, beschreibung: w.beschreibung })),
      werkzeuge: alle
        .filter((w) => istGewaehlt(server, w.name))
        .map((w) => ({
          name: w.name,
          beschreibung: w.beschreibung,
          quelle: server.name,
          /* Its own row is the server's, and a `source` name alone does not
             say which of the two rows is meant when a server carries the
             name of a built-in source. Read by the window to pick the
             right row for an opened tool. */
          builtin: false,
          needs_confirmation: freigabe(w.name)?.needs_confirmation ?? false,
        })),
    })
  }

  return liste
}

/**
 * What a remembered selection of the tools view points at in `liste`: an
 * opened tool together with the source row it belongs to, or the source
 * shown. A tool is looked up inside its own source only, so a source and a
 * tool of the same name, or two sources offering the same tool, never stand
 * in for each other. A selection that no longer exists — its server went —
 * falls back to the first source, like no selection at all.
 */
export function auswahlAufloesen(liste, gezeigt) {
  if (gezeigt?.art === 'werkzeug') {
    const quelle = liste.find((q) => q.id === gezeigt.quelle) ?? null
    const werkzeug = quelle?.werkzeuge.find((w) => w.name === gezeigt.name) ?? null
    if (werkzeug) return { werkzeug, quelle }
  }
  const quelle = gezeigt?.art === 'quelle' ? liste.find((q) => q.id === gezeigt.id) : null
  return { werkzeug: null, quelle: quelle ?? liste[0] ?? null }
}

/** How many tools actually reach the model — the number under the title. */
export function anzahlAn(liste = quellen()) {
  return liste
    .filter((q) => q.laeuft)
    .reduce((summe, q) => summe + q.werkzeuge.filter((w) => istAn(w.name)).length, 0)
}

/** The count line's two numbers — the tools that reach the model and the
 *  running sources they come from — for every place that states them. */
export function aktivStand(liste = quellen()) {
  return { zahl: anzahlAn(liste), quellen: liste.filter((q) => q.laeuft).length }
}
