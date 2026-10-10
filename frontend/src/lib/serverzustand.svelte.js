/*
  Is the model server up, did flash attention end up on, did the drafter
  really engage? Three facts, in one place, told to the window instead of
  asked for.

  Three readouts show them — the two dots in the header
  (`Serverpunkt.svelte`, `Flashpunkt.svelte`) and the lamp in the input bar
  (`Eingabeleiste.svelte`) — all three live the whole session, and each used
  to fetch `/runner` on a beat of its own for an answer that changes about
  twice a day: measured, 29 fetches in the first 120 seconds of an idle
  window. The service announces it now (app/runnerzustand.py); this is where
  the announcement lands.

  ITS OWN STORE, AND THE THREE READOUTS STAY THREE. They show different
  things and sit in different places on purpose — what is shared here is the
  ANSWER, not the readout.

  WHO ASKS, AND WHEN. Not the readouts: `verbinden()` does it, on the same
  breath as everything else this line feeds (lib/ereignisstrom.svelte.js).
  That is one place instead of three, and it covers what three mount effects
  could not — a line that dropped and came back has heard none of what
  happened meanwhile, and nothing on this line is replayed.

  WHY AN ANSWER CAN BE THROWN AWAY. The fetch and the announcement race, and
  the fetch always loses: the service answered it BEFORE the change it is
  now carrying an older view of. So every answer that arrives after an
  announcement is dropped rather than applied.
*/

import { api } from './api.js'

export const serverzustand = $state({
  laeuft: false,
  /* Kept apart from `false`: "running and nobody knows yet" is its own
     answer, and the dot owes the user the difference — grey, not red. */
  flash_aktiv: null,
  /* null, "aktiv" or "fehler" — the same three the service answers with.
     "configured" is not "running", and only the middle one is the lamp. */
  mtp_aktiv: null,
  /* Whether this has ever been filled at all. A window that opened while
     the service was still coming up asked once, was refused, and would
     otherwise sit on the defaults for the whole session — so the slow net
     next door retries while this is false. */
  geladen: false,
})

/* The chat model server. The announcement says which server it speaks for,
   and these three readouts speak for exactly one of them. */
const CHAT = 'chat'

/* How many announcements have landed. A fetch remembers the count it was
   sent under and drops its answer if the count moved. */
let gemeldet = 0

function setzen(daten) {
  serverzustand.laeuft = Boolean(daten?.laeuft)
  serverzustand.flash_aktiv = daten?.flash_aktiv ?? null
  serverzustand.mtp_aktiv = daten?.mtp_aktiv ?? null
  serverzustand.geladen = true
}

/* What is announced carries all three facts with it, unlike everything else
   on the live line: there is no list behind them, and a window sent to
   fetch them would be back to asking. */
export function uebernehmen(ereignis) {
  /* An older service sends no name; there was only ever one server
     announcing, so an unnamed announcement is that one. */
  if (ereignis?.runner && ereignis.runner !== CHAT) return
  gemeldet += 1
  setzen(ereignis)
}

/* The ask in flight. Two of them race each other exactly as a fetch races an
   announcement, and with no counter between them the older one can land
   last — so there is only ever one. */
let unterwegs = null

export function laden() {
  if (unterwegs) return unterwegs
  const stand = gemeldet
  unterwegs = api
    .runnerAuskunft()
    .then((a) => {
      /* Something was announced while this was in flight. That is the newer
         truth by construction — keep it. */
      if (gemeldet === stand) setzen(a)
    })
    .catch(() => {})
    .finally(() => {
      unterwegs = null
    })
  return unterwegs
}
