/*
  The one live line the window keeps open, and what it does with what
  arrives.

  The program used to ask. Fourteen timers, the slowest of them fifteen
  seconds, every one of them asking a service that already knew — and an
  agent that finished was news a quarter of a minute later. The service
  says it now (app/ereignisstrom.py); this is the ear.

  WHAT ARRIVES IS A FACT, NOT A LIST. "This job ended", not the job. So the
  answer to every one of them is the same shape: fetch the one list this
  concerns, once. That keeps one shape of a job in the program instead of a
  second one that would have to be kept in step — what the line saves is
  the ASKING, not the answer.

  ONE LINE FOR THE WINDOW, not one per panel. `EventSource` reconnects by
  itself when the line drops, and it only ever goes one way — which is the
  whole reason this is not a websocket.

  WHAT THE FREE RECONNECT DOES NOT COVER, measured: a restart of the
  SERVICE. The session key is minted fresh on every start, so the retry
  carries a key from a process that is gone and is refused — and an
  EventSource stops for good on a refusal rather than on a dropped
  connection. Nothing here can mend that: every other request this page
  could still make is refused for the same reason, and what recovers is a
  reload of the page.

  THE NET UNDER IT. A line that is down asks nothing, and a window that
  asks nothing while the line is down learns nothing. So there is one slow
  fetch, once a minute, and it runs ONLY while the line is not standing.
  Not a timer that was made slower — that would be the same fault with more
  delay — but a net for a line that dropped while the service kept running.
*/

import { api } from './api.js'
import { standLaden as cronStandLaden } from './cronjobampel.svelte.js'
import {
  laden as serverzustandLaden,
  serverzustand,
  uebernehmen as serverzustandUebernehmen,
} from './serverzustand.svelte.js'
import { auftraegeStillLaden, chatOeffnen, modelleLaden, zustand } from './zustand.svelte.js'

export const leitung = $state({
  /* Has the line carried anything yet? `EventSource.onopen` is what says
     so; until then, and after a drop, the net below does the asking. */
  steht: false,
})

/* For the panels that keep a list of their own and cannot be fetched from
   here — the schedules panel loads every entry's runs, which is its
   business and nobody else's. They read the counter that concerns them in
   an `$effect` and reload when it moves. A counter rather than a callback
   list: a panel that is not on screen has no effect running, so it costs
   nothing and needs no unsubscribing. */
export const neuigkeit = $state({ auftraege: 0, termine: 0, endpunkte: 0 })

/* Once a minute, and only while the line is down. */
const NETZ_MS = 60_000

let quelle = null
let netz = 0

/* What each announcement means for the window. Every one of them is "go and
   look at this list", which is why they are one line each. */
const HANDLUNG = {
  auftrag_begonnen: () => {
    auftraegeStillLaden()
    neuigkeit.auftraege += 1
  },
  auftrag_beendet: () => {
    auftraegeStillLaden()
    neuigkeit.auftraege += 1
  },
  /* A run that stopped on a question, or one that was just given an answer
     and is going again. The only state change a run makes without ending,
     and the list is where the question, the group and the banner all read
     it from. */
  auftrag_fragt: () => {
    auftraegeStillLaden()
    neuigkeit.auftraege += 1
  },
  /* A run wrote a new context reading. The list carries each run's newest
     one, and the tile's context line reads it from there. */
  auftrag_kontext: () => {
    auftraegeStillLaden()
  },
  /* A schedule that fired changed two things: its own row, and — usually —
     the job list it just added a run to. */
  termin_gefeuert: () => {
    cronStandLaden()
    auftraegeStillLaden()
    neuigkeit.termine += 1
    neuigkeit.auftraege += 1
  },
  /* Reachability rides on the model list, which is where the windows read
     it from. */
  endpunkt_status: () => {
    modelleLaden()
    neuigkeit.endpunkte += 1
  },
  /* The one announcement that is not "go and look": three flags are the
     whole answer, there is no list behind them, and the three readouts that
     used to fetch them on beats of their own read them straight off it.
     Which is also why a dropped one is a fact that is simply gone — and
     why `onopen` below asks for it again. */
  modellserver_zustand: serverzustandUebernehmen,
  /* A chat of ours is being compacted before its answer can start. The
     placeholder this window pushed for that answer is the row the waiting
     mark stands on, so its activity is what says "compressing" — until
     the answer's own stream opens and says something else. Not "go and
     look": there is no list, and nothing to fetch. */
  verdichtung_laeuft: (ereignis) => {
    const platzhalter = zustand.laufenderPlatzhalter[ereignis.chat_id]
    if (!platzhalter) return
    platzhalter.taetigkeit = 'verdichtung'
    platzhalter.taetigkeitSeit = Date.now()
  },
  /* An answer started in a chat — on the service's own initiative, when a
     finished background command woke the model — while this window sat
     idle on that chat: nothing here knew. It typed into a chat the
     service had claimed, got a 409, and saw the answer only on the next
     open. Owed as a reattachment, through the same door a cold open uses
     (App.svelte acts on it for the chat on screen; another chat's entry
     waits until that chat is opened). A run this window started itself is
     already held in `laeuft` and is not attached to twice. */
  antwort_begonnen: (ereignis) => {
    const chatId = ereignis.chat_id
    /* `sendet` as well as `laeuft`: a send of this window's own is held
       in `sendet` while its document uploads, before the run exists — the
       start it hears in that stretch is its own, and attaching to it would
       run the same answer into its own 409. */
    if (!chatId || !ereignis.generation_id || zustand.laeuft[chatId] || zustand.sendet[chatId]) return
    zustand.wiederanhaengen[chatId] = {
      chatId,
      generationId: ereignis.generation_id,
      messageId: ereignis.message_id ?? null,
    }
  },
}

function netzStellen() {
  clearInterval(netz)
  netz = setInterval(() => {
    if (leitung.steht) {
      /* The one thing a standing line cannot heal by itself: a first ask
         that failed. Everything after it arrives on the line — but a window
         that never got an answer reports "server off" under a running
         server, and nothing else would ever ask again. */
      if (!serverzustand.geladen) serverzustandLaden()
      return
    }
    auftraegeStillLaden()
    cronStandLaden()
    serverzustandLaden()
    neuigkeit.auftraege += 1
    neuigkeit.termine += 1
  }, NETZ_MS)
}

export function verbinden() {
  if (quelle) return
  netzStellen()
  /* Whether the open below is the first of THIS line or a return. Held in
     the closure of the line it belongs to rather than beside the module, so
     a window that closes the line and opens a new one starts over — that is
     a first open again, not a return. */
  let erstesOeffnen = true
  quelle = new EventSource(api.ereignisStrom())
  quelle.onopen = () => {
    leitung.steht = true
    /* Whatever happened while the line was down is not replayed — nothing
       here is numbered, on purpose. Asking once on arrival is what makes
       that safe, and it is also the first fetch of the session.

       The server state belongs here MORE than the lists above it, not less:
       it is the one announcement that carries its answer rather than
       pointing at a list, so a missed one is a fact that is simply gone.
       The runner speaks on change, and a change that was dropped has no
       next one behind it.

       The model list is asked for on a RETURN only, never on the first
       open. Reachability rides on that list (`endpunkt_status` above), and
       an endpoint that went down or came back while the line was gone kept
       the mark it had until the list was next fetched. Not forever: the list
       has a slow beat of its own while the window lives (App.svelte,
       30 s), so what this closes is up to that beat, not an open-ended
       staleness — the same shape as the three above, where an announcement
       asks at once and a slow net is only the floor under it.

       Not on the first open, because that one races the settings the window
       is loading beside it: `modelleLaden` picks the first endpoint of the
       list when it finds none chosen, and WRITES that choice down
       (zustand.svelte.js), so asking before the remembered model has
       arrived replaces it. The mount asks for the list itself, in the right
       order (`anzeigeUebernehmen().then(modelleLaden)`, App.svelte), and
       that is the one ask the first open needs.

       The net above does not repeat it, for the same reason: the list
       already has that beat, and the three above have none. */
    auftraegeStillLaden()
    cronStandLaden()
    serverzustandLaden()
    if (!erstesOeffnen) {
      modelleLaden()
      /* And the chat that is on screen, exactly once.

         The line hands out FACTS, and nothing here is numbered — a burst of
         more than two hundred announcements is dropped rather than queued
         (app/ereignisstrom.py). `antwort_begonnen` is one of them, and the
         run it announced goes on writing into a chat that never hears about
         it: the answer looks like it never started until the next reload.

         `chatOeffnen` is the ONE way this window picks up a running answer
         — it asks the chat and hangs the existing stream onto it — so
         calling it again is all a return needs. Nothing new is built here.

         The chat ON SCREEN, not any chat still open elsewhere: a chat that
         was left behind while the line was down is not the one the reader is
         looking at, and fetching it would hang a run's stream onto a page
         that is not showing it.

         Asking again through the whole open path is deliberate (and
         app/lib/terminalfenster.svelte.js:236 does the same for an event
         that arrives for the chat on screen). The path knows a second look
         at the chat that is already on screen from a switch and asks it for
         the fetch alone — the sentence typed into the picture window, the
         model pick and the open drawer stay as the reader left them
         so this caller costs nothing but the fetch. */
      const sichtbar = zustand.aktiverChat
      if (sichtbar) chatOeffnen(sichtbar)
    }
    erstesOeffnen = false
    neuigkeit.auftraege += 1
    neuigkeit.termine += 1
  }
  quelle.onmessage = (nachricht) => {
    let ereignis
    try {
      ereignis = JSON.parse(nachricht.data)
    } catch {
      return
    }
    HANDLUNG[ereignis?.typ]?.(ereignis)
  }
  /* A dropped line is not worth a red message: the browser reconnects by
     itself. What it is worth is the net above, which starts asking again
     until `onopen` says the line is back. */
  quelle.onerror = () => {
    leitung.steht = false
  }
}

export function trennen() {
  quelle?.close()
  quelle = null
  clearInterval(netz)
  netz = 0
  leitung.steht = false
}
