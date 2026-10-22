/*
  The main model server's start choice — moved out of the browser (Stufe 11).

  Everything below used to live in `localStorage` under `runner:*`: the model
  file, the window, the layers, the port and the speed and vision module
  remembered per file. That was fine while the page that kept the numbers was
  the only thing that ever used them.

  It is not fine any more, and for one reason: the program cannot say which
  file with which settings "the main model" would be. At program start there
  is no browser to ask, so anything that wanted to bring this server up on its
  own would have to guess — which is why the loading table has to say "main
  model, nobody loads it automatically".

  So the choice lives in one setting on the server now
  (app/runnermodellwahl.py), read back here when a page opens. The agent
  slot's field made the same move first and for the same reason; this store
  is deliberately shaped like its (lib/agentenserver.svelte.js), down to the queue that
  keeps two writes from losing each other.

  `null` and `''` are different answers everywhere in here. `null` is "never
  chosen" — the form then pre-picks, from the running server or the folder
  manifest. `''` is "chosen: none". Collapsing them is how a pairing somebody
  switched off walks back in on the next reload.
*/

import { api } from './api.js'

const SCHLUESSEL = 'runnermodell'

/* Where all of this stood before. Kept as a constant because the one-time
   hand-over below is the only code left that may touch it. */
const ALT = 'runner:'

export const runnermodell = $state({
  modell: null,
  kontext: null,
  schichten: null,
  /* Null is a real answer: "the server's own port". */
  port: null,
  /* `{ datei: { drafter, vision } }` — the module pair remembered for exactly
     that file. Per file because this server is switched between models and a
     projector that belongs to one is nonsense for the next. */
  module: {},
  /* Whether the program may bring this server up by itself, ahead of a due
     cron entry (app/runnermodellwahl.py). Null while unread, the same as
     every other field here — the page fills it in from `vorgaben` until
     then. */
  vorladen: null,
  /* Whether a run the program places itself may land on this server. Null
     while unread; the window shows the shipped answer until then. */
  use_for_runs: null,
  /* Whether the values above have been read. A page must not write before it
     has read, or its first pass would store its own placeholders over what
     was there. */
  geladen: false,
})

/* One at a time. The window writes the pick, the debounce writes the numbers
   and each module row writes itself when it is picked — three writers on one
   row, and two in flight would land in whichever order the network felt like.
   (The start button was a fourth until 7c49647; it writes nothing of the
   modules any more, but the queue was never about how many there are.)

   This orders the writers inside ONE window. It says nothing about a second
   window, which is why nothing here sends more than it changed any more —
   see `einstellungMischen`. */
let schlange = Promise.resolve()

function nacheinander(arbeit) {
  const naechste = schlange.then(arbeit, arbeit)
  schlange = naechste.then(
    () => {},
    () => {},
  )
  return naechste
}

/* The stored part of the store, for putting back what a failed write
   changed. NOT what goes out on a write — see `werteSetzen`. */
function alsObjekt() {
  return {
    modell: runnermodell.modell,
    kontext: runnermodell.kontext,
    schichten: runnermodell.schichten,
    port: runnermodell.port,
    module: runnermodell.module,
    vorladen: runnermodell.vorladen,
    use_for_runs: runnermodell.use_for_runs,
  }
}

/* What a previous version left in the browser, as the object this store
   keeps — or `null` when there is nothing there.

   Read once, on the first load that finds the setting empty. An install that
   predates Stufe 11 has a whole choice sitting in `localStorage` and no way
   of its own to tell anybody about it; dropping it would mean somebody's
   window, port and module pairings silently going back to defaults on the
   day they updated. */
function ausBrowserHolen() {
  let etwas = false
  const werte = { modell: null, kontext: null, schichten: null, port: null, module: {} }
  try {
    const modell = localStorage.getItem(ALT + 'modell')
    if (modell !== null) {
      werte.modell = modell
      etwas = true
    }
    for (const name of ['kontext', 'schichten', 'port']) {
      const roh = localStorage.getItem(ALT + name)
      const zahl = Number(roh)
      /* Zero is a value, not an absence: `schichten` 0 is "run this on the
         processor alone", which is a thing people set on purpose. The reader
         this replaced took it (`gemerkteZahl`, guarded on '' and NaN only);
         a falsy test here handed those users 99 back on the day they
         updated. */
      if (roh !== null && roh !== '' && Number.isFinite(zahl)) {
        werte[name] = zahl
        etwas = true
      }
    }
    for (let i = 0; i < localStorage.length; i++) {
      const schluessel = localStorage.key(i)
      if (!schluessel) continue
      for (const rolle of ['drafter', 'vision']) {
        const vorsatz = `${ALT}${rolle}:`
        if (!schluessel.startsWith(vorsatz)) continue
        const datei = schluessel.slice(vorsatz.length)
        const eintrag = werte.module[datei] ?? { drafter: null, vision: null }
        eintrag[rolle] = localStorage.getItem(schluessel)
        werte.module[datei] = eintrag
        etwas = true
      }
    }
  } catch {
    /* A browser that refuses storage has nothing to hand over. */
    return null
  }
  return etwas ? werte : null
}

/* What the setting does NOT answer, out of what the browser still holds —
   or `null` when it answers all of it.

   The hand-over used to be an all-or-nothing decision made on one question:
   is the setting empty? It is the wrong question, because the setting stops
   being empty without anybody having handed anything over. `POST /runner/
   start` records the file that started (`modell_merken`, app/api/v1/
   runner.py), and it records it into the same row. So an install that
   predates the move, whose user updates and then starts a model straight
   from the catalogue — never opening the server page on the way — has a row
   holding `{modell: …}` and a browser holding the entire rest of the choice.
   The next load read "not empty", called that a completed hand-over, and
   deleted window, layers, port and every module pairing.

   Asked per value instead, that case answers itself: the file the setting
   names is the newer truth and stays, and the four the browser alone knows
   are the four that get carried over. A value the setting has an answer for
   is a value nothing can be lost on — which is what makes clearing safe
   afterwards. */
function nachzutragen(w, alt) {
  const nachtrag = {}
  for (const name of ['modell', 'kontext', 'schichten', 'port']) {
    if (!(name in w) && alt[name] !== null) nachtrag[name] = alt[name]
  }
  /* Per file AND per role: the table is a set of sets, and a row the setting
     already answers for one model says nothing about the model next to it. */
  const habe = w.module && typeof w.module === 'object' ? w.module : {}
  const module = {}
  for (const [datei, eintrag] of Object.entries(alt.module)) {
    const da = habe[datei]
    const fehlend = {}
    for (const rolle of ['drafter', 'vision']) {
      if (typeof eintrag[rolle] !== 'string') continue
      if (typeof da?.[rolle] === 'string') continue
      fehlend[rolle] = eintrag[rolle]
    }
    if (Object.keys(fehlend).length) module[datei] = fehlend
  }
  if (Object.keys(module).length) nachtrag.module = module
  return Object.keys(nachtrag).length ? nachtrag : null
}

/* The carried-over values into the store, once they are stored. Applied
   here rather than by re-reading, so the page has them without a second
   round trip. */
function nachtragUebernehmen(nachtrag) {
  for (const name of ['modell', 'kontext', 'schichten', 'port']) {
    if (name in nachtrag) runnermodell[name] = nachtrag[name]
  }
  if (!nachtrag.module) return
  const zusammen = { ...runnermodell.module }
  for (const [datei, teil] of Object.entries(nachtrag.module)) {
    zusammen[datei] = { ...(zusammen[datei] ?? {}), ...teil }
  }
  runnermodell.module = zusammen
}

/* Only after the hand-over is safely stored. The old keys are removed so
   there is one place and not two — a leftover copy would be read again the
   day somebody deliberately clears the setting, and an answer nobody gave
   would come back. */
function browserRaeumen() {
  try {
    const weg = []
    for (let i = 0; i < localStorage.length; i++) {
      const schluessel = localStorage.key(i)
      if (schluessel && schluessel.startsWith(ALT)) weg.push(schluessel)
    }
    for (const schluessel of weg) localStorage.removeItem(schluessel)
  } catch {
    /* Nothing to clean up if the browser will not say what it holds. */
  }
}

function uebernehmen(w) {
  runnermodell.modell = typeof w.modell === 'string' ? w.modell : null
  runnermodell.kontext = Number(w.kontext) || null
  runnermodell.schichten =
    w.schichten === null || w.schichten === undefined ? null : Number(w.schichten)
  runnermodell.port = Number(w.port) || null
  runnermodell.module = w.module && typeof w.module === 'object' ? w.module : {}
  runnermodell.vorladen = typeof w.vorladen === 'boolean' ? w.vorladen : null
  runnermodell.use_for_runs = typeof w.use_for_runs === 'boolean' ? w.use_for_runs : null
}

let laden = null

/* Read once per page life. Several panels want it — the server page and the
   window's head figure — and they mount together.

   `erneut` asks for it again anyway. Once per page life is right for the
   mount storm and wrong afterwards: a second window stores something and
   this copy knows nothing of it, so whoever falls back on "the stored
   choice" falls back on a copy as old as the moment this page opened. The
   server page asks for a fresh read when a run ends, which is the one moment
   it hands the fields back to the setting.

   Through the same queue the writers go through, and for the same reason.
   A read is a writer of this store like any other: an answer still on the
   wire while a PATCH lands puts the store back to the state BEFORE that
   PATCH — the value on screen is then this window's own choice, undone by
   its own read. Queued, the read simply happens after the write it crossed.

   `erneut` also makes the read STRICT. A read that did not reach the setting
   leaves the old copy standing, and the old copy wearing the face of a fresh
   one is worse than no read at all: whoever asked for it asked because they
   are about to act on it. The mount read stays lenient — nothing has been
   read yet there, the defaults are the honest answer, and every page on the
   screen would otherwise go dark over one refused request. */
export function standLaden(erneut = false) {
  if (runnermodell.geladen && !erneut) return Promise.resolve()
  /* Not shared with the mount storm's promise: a lenient read already in
     flight would swallow the failure the strict caller is asking about. */
  if (erneut) return nacheinander(() => einlesen(true))
  if (!laden) laden = nacheinander(() => einlesen(false)).finally(() => (laden = null))
  return laden
}

async function einlesen(streng = false) {
  let stand = null
  try {
    stand = await api.einstellungAufgeloest(SCHLUESSEL)
  } catch (fehler) {
    /* Nothing readable: the defaults stand, and the page fills them in from
       what the server sends as `vorgaben`. Unless somebody asked for this
       read on purpose — then they hear about it instead of being handed a
       copy that is as old as it ever was. */
    runnermodell.geladen = true
    if (streng) throw fehler
    return
  }
  const w = stand?.wert && typeof stand.wert === 'object' ? stand.wert : {}
  uebernehmen(w)

  /* Whatever a version before the move left behind. Nothing there is the
     normal case — a fresh install, or one that has already handed over. */
  const alt = ausBrowserHolen()
  const nachtrag = alt ? nachzutragen(w, alt) : null
  /* Into the store BEFORE anything counts as read. `geladen` is what the
     page waits for; the moment it turns true the form fills itself from
     these values, and whatever is still missing it takes from the defaults
     — and writes back a debounce later. Waiting for the write to come back
     first cost exactly that: the carried-over window and port were stored
     and then overwritten by the numbers the form had meanwhile picked. */
  if (nachtrag) nachtragUebernehmen(nachtrag)
  runnermodell.geladen = true

  if (!alt) return
  if (nachtrag) {
    try {
      /* Merged, not replaced: the setting's own answers are what this is
         careful not to touch. */
      await api.einstellungMischen('global', SCHLUESSEL, nachtrag)
    } catch {
      /* Left where it is, to be handed over on the next attempt. Nothing is
         cleared — a hand-over that did not get stored has not happened. The
         values stand in the store either way, so the page behaves as it
         always did. */
      return
    }
  }
  /* Now, and only now. Everything the browser held is either stored or was
     already answered by the setting, so there is nothing left in it that
     could be lost. */
  browserRaeumen()
}

/* The numbers, stored — without touching the process. Awaited by the page
   before a start, so what comes up is what stands in the field rather than
   whatever a debounce had got round to. */
export function werteSetzen(werte) {
  return nacheinander(async () => {
    if (!runnermodell.geladen) await einlesen()
    const vorher = alsObjekt()
    Object.assign(runnermodell, werte)
    try {
      /* Only what changed. Sending the whole object would mean sending this
         window's copy of the values it did NOT change — and that copy is as
         old as the moment this page read it. A second window open on the
         same server would get its pick undone by the next slider drag over
         here. */
      await api.einstellungMischen('global', SCHLUESSEL, werte)
    } catch {
      Object.assign(runnermodell, vorher)
      throw new Error('einstellung')
    }
  })
}

/* The module pair remembered for one file. Written when a row is changed by
   hand and at no other moment, exactly where the browser keys were written.

   The start button wrote them too until 7c49647, and that is precisely what
   it must not do: a pre-pick the form only offers is not yet an answer, and
   storing it froze the folder manifest's pairing into a choice nobody made —
   where the row read "none" about a projector the name heuristic had
   attached, pressing start DELETED that projector. */
export function modulSetzen(datei, werte) {
  return nacheinander(async () => {
    if (!runnermodell.geladen) await einlesen()
    const vorher = runnermodell.module
    const alt = vorher[datei] ?? {}
    runnermodell.module = { ...vorher, [datei]: { ...alt, ...werte } }
    try {
      /* This file's row, and of it only the role that changed — the table is
         a set of sets, and the rest of it is this window's stale copy just
         as much as the numbers are. */
      await api.einstellungMischen('global', SCHLUESSEL, { module: { [datei]: werte } })
    } catch {
      runnermodell.module = vorher
      throw new Error('einstellung')
    }
  })
}

/* Which local file the main model server would come up on: the remembered
   choice where it still names something, and only where it does not the
   folder's first file.

   The rule of it is the middle line, and it stood twice word for word — in
   the server page's poll and in the command line's `/server start`. What held
   the two together was one guard matching the front of the line, so the
   `.some(...)` half could have drifted with both tests green; and that half
   is the whole point. `''` is a chosen "none" and counts as an answer, a name
   whose file has gone does not, and `null` is nobody having chosen.

   `dateien` is the folder listing the caller already holds, entries carrying
   `name`. Nothing is written here — this only answers "which file", and what
   the two callers then DO with the answer is not the same thing: the page
   pre-picks it into a field and writes nothing, while a start records
   whatever came up as the main model (app/api/v1/runner.py `modell_merken`).
   That difference is older than this function and is left exactly where it
   was. */
export function gemerkteDatei(dateien) {
  const gemerkt = runnermodell.modell
  const gilt =
    gemerkt !== null && (gemerkt === '' || dateien.some((m) => m.name === gemerkt))
  return gilt ? gemerkt : dateien[0]?.name
}

/* What was chosen for this file — `null` per entry when nothing ever was. */
export function modulFuer(datei) {
  const eintrag = runnermodell.module?.[datei]
  return {
    drafter: typeof eintrag?.drafter === 'string' ? eintrag.drafter : null,
    vision: typeof eintrag?.vision === 'string' ? eintrag.vision : null,
  }
}
