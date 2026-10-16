/*
  The one field: which model drives agents and cron jobs (Stufe 8).

  One field, three kinds of answer, and no second switch anywhere:

    the main model   whatever the chat server currently has loaded; nothing
                     is loaded on top, which is the point of that choice
    a local file     the slot — this program starts a second small server for
                     it and keeps it up (app/agentenserver.py)
    a cloud model    an id the discovery already knows; nothing to start

  Nothing chosen is not a fourth answer, it is the first one: the row shows
  the main model, and a run without a pick takes the main model
  (app/api/v1/auftraege.py) — and when that server is not up,
  the next reachable LOCAL one. The list carries no "none" entry
  to pick any more, and there is no switch beside it either:
  a fresh installation and a hand that never chose are the same
  state, and both mean the main model.

  The kind and the value travel together as one string — `slot:datei.gguf` or
  `kennung:endpunkt:modell` — so the list stays one list and the field stays
  one value. Split on the FIRST colon only; a model id may carry more.

  The slot's start is deliberately NOT awaited by the pick. It takes seconds,
  and a field that stays half-pressed while a file is read from disk reads as
  a program that hung.
*/

import { api } from './api.js'

export const agentenmodell = $state({
  /* What the user decided. This is the setting; everything else follows. */
  /* 'slot' or 'kennung' — see the header. Empty while nothing is chosen. */
  sorte: '',
  wert: '',
  /* HOW the slot runs, in the same object as WHICH file it runs — one place,
     and deliberately not the browser.

     This server starts by itself at every program launch (app/main.py), and
     at that moment there is no browser at all. A window that only the page
     knew would be replaced by a default on every restart — which is the same
     failure as nailing it into the code, arrived at from the other side. The
     model server kept its numbers in `localStorage` while nothing but a hand
     on its button ever started it; Stufe 11 moved them for the same reason,
     into a key of their own (lib/runnermodell.svelte.js).

     So they live in the setting, next to the choice, and the server reads
     them from there for both start paths (app/agentenmodellwahl.py). Null
     here means "not read yet"; the numbers arrive with `standLaden`. */
  kontext: null,
  schichten: null,
  /* Null is a real answer: "the slot's own port". */
  port: null,
  /* `{ datei: { drafter, vision } }` — the module pair remembered for exactly
     that file, the way the model server keeps it (lib/runnermodell.svelte.js):
     this server is switched between files, and a projector that belongs to
     one is nonsense for the next. */
  module: {},
  fein: null,
  /* Whether the program may bring the slot up by itself at program start,
     ahead of anybody asking for it (app/agentenmodellwahl.py —
     the same lever the main model's own key carries). Null while unread. */
  vorladen: null,
  /* Whether the values above have been read. The page must not write before
     it has read, or the first pass would store its own initial state over
     what was there. */
  geladen: false,
  /* Whether the slot process is up. Not the same question as the choice: it
     can be made while the model is still coming, and a cloud or main model
     choice has no process at all. */
  laeuft: false,
  laedt: false,
  /* A start that was tried and did not work. Kept apart from `laeuft`
     because "not up yet" and "will not come up" are different facts. */
  fehler: false,
  /* What the server would load if nobody named a file. */
  vorgabe: '',
})

const SCHLUESSEL = 'agentenmodell'

/* The one value the field holds, as the list writes and reads it. */
export function alsWahl() {
  if (!agentenmodell.wert) return ''
  return `${agentenmodell.sorte}:${agentenmodell.wert}`
}

/* The endpoint id the slot answers under — its own, fixed, never the name of
   the file it happens to hold (app/agentenserver.py `ENDPUNKT_ID`). The file is
   what gets started; the id is what gets asked. */
export const SLOT_ENDPUNKT = 'agentenmodell'

/* The other of the two servers a run may take: the main model server, which
   this program starts too (app/api/v1/runner.py `RUNNER_ID`,
   app/agentenmodellwahl.py `HAUPTMODELL`). Named here beside the slot's id so
   a window that offers the two does not carry either of them itself. */
export const HAUPTMODELL = 'runner'

/* Which endpoint this field points at, or '' while it names no model.

   The other half of `agentenmodellwahl.kennung`: a slot means the slot's own
   endpoint, anything else IS an id already, and no value means no endpoint
   is named here. Empty is NOT "this field has nothing to say" any more —
   without an off state, an empty field means the main model,
   and that meaning has a name of its own (`agentenmodellwahl.HAUPTMODELL`),
   which a window offering it has to use. Here so a window does not have to
   know how the field is put together. */
export function feldKennung() {
  if (!agentenmodell.wert) return ''
  return agentenmodell.sorte === 'slot' ? SLOT_ENDPUNKT : agentenmodell.wert
}

function zerlegen(wahl) {
  const roh = String(wahl ?? '')
  const schnitt = roh.indexOf(':')
  if (schnitt < 0) return { sorte: '', wert: '' }
  return { sorte: roh.slice(0, schnitt), wert: roh.slice(schnitt + 1) }
}

/* The stored choice, into the store.

   Not exported: everything from outside comes through `standLaden` below, so
   it goes through the queue. This one is for the callers that are ALREADY in
   the queue — a queued call joining the same queue would wait for itself. */
async function einlesen(streng = false) {
  try {
    const stand = await api.einstellungAufgeloest(SCHLUESSEL)
    const w = stand?.wert
    if (w && typeof w === 'object') {
      agentenmodell.sorte = typeof w.sorte === 'string' ? w.sorte : ''
      agentenmodell.wert = typeof w.wert === 'string' ? w.wert : ''
      /* Null for anything that was never stored — the resolved route hands
         back what the scopes hold, not what the module would fall back to.
         The page fills those in from `vorgaben` in the slot's own answer, so
         the fallback is asked of the one place that owns it rather than
         guessed at twice. */
      agentenmodell.kontext = Number(w.kontext) || null
      agentenmodell.schichten = w.schichten === null || w.schichten === undefined
        ? null
        : Number(w.schichten)
      agentenmodell.port = Number(w.port) || null
      agentenmodell.module = w.module && typeof w.module === 'object' ? w.module : {}
      agentenmodell.fein = w.fein && typeof w.fein === 'object' ? w.fein : null
      agentenmodell.vorladen = typeof w.vorladen === 'boolean' ? w.vorladen : null
      agentenmodell.geladen = true
    }
  } catch (fehler) {
    /* Leaves the default standing — shipped with nothing chosen. Unless
       somebody asked for this read on purpose: a read that did not reach the
       setting leaves the OLD copy standing, and handing that back as "the
       stored choice" is the same silence this whole key was moved out of the
       browser to end. */
    if (streng) throw fehler
  }
  await serverStandLaden()
}

/* The stored choice, read again — through the queue the writers use.

   A read is a writer of this store: an answer still on the wire while a
   PATCH lands puts the store back to the state BEFORE that PATCH. Picking a
   slot model does exactly that pair — `waehlen` writes, then stops and
   starts the process, and the two-second poll that sees the gap reads. The
   field then falls back to the model that was picked BEFORE, while the
   setting holds the new one.

   `streng` says the caller is about to act on the answer and would rather
   hear that it never arrived than be handed the old copy. */
export function standLaden(streng = false) {
  return nacheinander(() => einlesen(streng))
}

/* The stored part of the store, for putting back what a failed write
   changed. NOT what goes out on a write.

   It used to be both, because the settings route REPLACES what a scope
   holds. That meant every writer had to resend the values it was not
   changing — and what it resent was the copy it read when its page opened.
   Two windows on this field then took turns undoing each other: B's next
   slider drag carried B's stale copy out over the model A had just picked.
   `einstellungMischen` writes only what changed, so there is no stale copy
   to carry (app/db/repositories/einstellungen.py `zusammenlegen`). */
function alsObjekt(aenderung = {}) {
  return {
    sorte: agentenmodell.sorte,
    wert: agentenmodell.wert,
    kontext: agentenmodell.kontext,
    schichten: agentenmodell.schichten,
    port: agentenmodell.port,
    module: agentenmodell.module,
    fein: agentenmodell.fein,
    vorladen: agentenmodell.vorladen,
    ...aenderung,
  }
}

/* How the slot runs, stored — without touching the process.

   Separate from `waehlen` because they are different acts: this one records
   what the next start will use, and the fields it writes are locked while
   something is running anyway. It is awaited by the page before a start, so
   the value the button acts on is the value that was just typed rather than
   whatever a debounce had got round to.

   Takes only the keys that changed, so nothing has to be resent to keep it. */
export function werteSetzen(werte) {
  return nacheinander(async () => {
    const vorher = alsObjekt()
    Object.assign(agentenmodell, werte)
    try {
      await api.einstellungMischen('global', SCHLUESSEL, werte)
    } catch {
      Object.assign(agentenmodell, vorher)
      throw new Error('einstellung')
    }
  })
}

/* The module pair remembered for one file. Written when a row is changed by
   hand and at no other moment: a pre-pick the form only offers is not yet an
   answer, and storing it would freeze the folder manifest's pairing into a
   choice nobody made.

   Only the role that changed goes out, and only this file's entry — the table
   is a set of sets, and the rest of it is this window's stale copy as much as
   the numbers are. */
export function setModules(datei, werte) {
  return nacheinander(async () => {
    if (!agentenmodell.geladen) await einlesen()
    const vorher = agentenmodell.module
    const alt = vorher[datei] ?? {}
    agentenmodell.module = { ...vorher, [datei]: { ...alt, ...werte } }
    try {
      await api.einstellungMischen('global', SCHLUESSEL, { module: { [datei]: werte } })
    } catch {
      agentenmodell.module = vorher
      throw new Error('einstellung')
    }
  })
}

/* What was chosen for this file — `null` per entry when nothing ever was. */
export function modulesFor(datei) {
  const eintrag = agentenmodell.module?.[datei]
  return {
    drafter: typeof eintrag?.drafter === 'string' ? eintrag.drafter : null,
    vision: typeof eintrag?.vision === 'string' ? eintrag.vision : null,
  }
}

/* Start and stop, as the page's foot button. The choice is what the program
   runs on; this is only whether the process for it is up right now — the
   same pair of verbs the other three server pages carry. */
export function slotStarten() {
  return nacheinander(async () => {
    if (!(agentenmodell.sorte === 'slot' && agentenmodell.wert)) return
    agentenmodell.laedt = true
    agentenmodell.fehler = false
    try {
      const a = await api.agentenmodellStarten(agentenmodell.wert)
      agentenmodell.laeuft = Boolean(a.laeuft)
    } catch {
      await serverStandLaden()
      agentenmodell.fehler = !agentenmodell.laeuft
    } finally {
      agentenmodell.laedt = false
    }
  })
}

export function slotStoppen() {
  return nacheinander(async () => {
    try {
      await api.agentenmodellStoppen()
    } catch {
      /* Nothing running is the state we wanted anyway. */
    }
    agentenmodell.laeuft = false
  })
}

export async function serverStandLaden() {
  try {
    const a = await api.agentenmodellAuskunft()
    agentenmodell.laeuft = Boolean(a.laeuft)
    agentenmodell.vorgabe = a.vorgabe || ''
  } catch {
    agentenmodell.laeuft = false
  }
}

/* One at a time.

   The choice starts and stops a process, and a hand can click faster than a
   model loads. Two calls in flight meant two start commands for one port:
   the second came back 409, its catch set `laeuft` to false, and the field
   then said "not running" about a server that was running perfectly well.
   Off-then-on was worse — the stop could land after the start.

   So every operation joins a queue instead of racing. What the user last
   asked for is what the last operation in the queue does, because the state
   is read when the operation runs, not when it was queued. */
let schlange = Promise.resolve()

function nacheinander(arbeit) {
  const naechste = schlange.then(arbeit, arbeit)
  /* The queue itself must never hold on to a rejection, or one failed
     choice would poison every choice after it. The caller still gets it. */
  schlange = naechste.then(
    () => {},
    () => {}
  )
  return naechste
}

/* The field. Writes the setting first — that is what the user actually
   decided — and then brings the slot process into line with it. */
export function waehlen(wahl) {
  return nacheinander(async () => {
    /* Never write before having read. The write below carries only the three
       fields of the choice, so it can no longer take the stored numbers with
       it — but the page still shows what this store holds, and a pick made on
       top of unread nulls would show the user defaults they never chose.
       Normally App.svelte has read long before anybody opens the page; this
       is for the load that failed.

       `einlesen` and not `standLaden`: this runs inside the queue already,
       and a queued call that joins the same queue waits for itself. */
    if (!agentenmodell.geladen) await einlesen()
    const vorher = { ...agentenmodell }
    const { sorte, wert } = zerlegen(wahl)
    agentenmodell.sorte = sorte
    agentenmodell.wert = wert
    try {
      /* The choice, and nothing else — see `alsObjekt`. */
      await api.einstellungMischen('global', SCHLUESSEL, {
        sorte: agentenmodell.sorte,
        wert: agentenmodell.wert,
      })
    } catch {
      agentenmodell.sorte = vorher.sorte
      agentenmodell.wert = vorher.wert
      throw new Error('einstellung')
    }
    await slotNachziehen()
  })
}

async function slotNachziehen() {
  const gewollt = agentenmodell.sorte === 'slot' ? agentenmodell.wert : ''
  if (!gewollt) {
    /* Anything that is not a slot choice means no second process. Stopping
       is asked for even when nothing seems to be running: the state here can
       be a moment behind the server's, and stopping nothing is free. */
    agentenmodell.laedt = false
    agentenmodell.fehler = false
    try {
      await api.agentenmodellStoppen()
    } catch {
      /* Nothing running is the state we wanted anyway. */
    }
    agentenmodell.laeuft = false
    return
  }
  /* A running slot holds the file it was started with — another file means
     restarting it, not asking it to change its mind. */
  if (agentenmodell.laeuft) {
    await api.agentenmodellStoppen().catch(() => {})
    agentenmodell.laeuft = false
  }
  agentenmodell.laedt = true
  agentenmodell.fehler = false
  try {
    const a = await api.agentenmodellStarten(gewollt)
    agentenmodell.laeuft = Boolean(a.laeuft)
  } catch {
    /* A refused start says nothing reliable about what is running. It can
       mean the server is already up (a second click on the same entry) or
       that something else holds the port — 409 for both, and the sentence
       that comes back is a translation, not a key to branch on.

       So the state is not guessed from the error: the server is asked. What
       it says is the truth about the process, which is the whole question
       here. Only if it says nothing is running was this a real failure. */
    await serverStandLaden()
    agentenmodell.fehler = !agentenmodell.laeuft
  } finally {
    agentenmodell.laedt = false
  }
}
