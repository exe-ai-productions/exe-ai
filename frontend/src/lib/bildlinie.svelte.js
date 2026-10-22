/*
  The line of pictures the studio draws, one after the other, on this
  machine — shared by the desktop window and the phone page, which both hand
  it to the studio.

  Not $state: only the counts written into the store drive the badge and the
  studio's row of pictures.
*/
import { api } from './api.js'
import { seedlage } from './bildseed.svelte.js'
import { meldeText } from './meldewesen.svelte.js'
import { melde, zustand } from './zustand.svelte.js'

/* A picture made on this machine by the picture studio, from the click
   to the frame.

   The studio belongs to no chat: its pictures are drawn, listed and shown
   in the studio, whichever chat is open, and nothing of it is written
   into a chat. The request names none (`studio`); the finished picture
   lies in the pictures folder and on the studio's own list, which the
   studio reads again when a picture leaves the line. */
let bildLokalLaeuft = false
/* Pictures asked for while one is drawing wait here and run one after the
   other — pressing "draw" three times queues three, it does not throw two
   away. Not $state: only the count in the store drives the badge. One GPU
   draws them serially. */
let bildQueue = []
/* The wish being drawn right now, or null between wishes — kept out of
   `bildQueue` while it draws (it was shifted off), so the line shown has
   to add it back explicitly. */
let bildLaufWunsch = null

/* The count shown is every picture still to come — the one drawing now
   plus the ones queued behind it. The badge appears whenever it is at
   least one and vanishes when the last picture lands. */
function bildZahlSetzen() {
  zustand.bildWarteschlange = bildQueue.length + (bildLokalLaeuft ? 1 : 0)
}

/* The line of pictures still to come, rebuilt from the one live wish plus
   the queue whenever either changes: the studio's row of pictures shows
   it. */
function pictureLineRefresh() {
  const entry = (w, running) => ({ id: w.queue_id, prompt: w.prompt, running })
  // A picture already drawn is no picture to come, even before the
  // studio has caught up with it.
  zustand.pictureQueue = [
    ...(bildLaufWunsch && !bildLaufWunsch.drawn ? [entry(bildLaufWunsch, true)] : []),
    ...bildQueue.map((w) => entry(w, false)),
  ]
}

/* The picture drawing now, and only that one — the stop on its tile in
   the studio's row of pictures. The line behind it goes on: each waiting
   picture there has its own way out. Only while that very picture is the
   one drawing: the stop names no picture on the server, and a tile that
   had not caught up yet would otherwise stop the next one in line. */
export function stopOnePicture(id) {
  if (bildLaufWunsch?.queue_id === id && !bildLaufWunsch.drawn) {
    api.bildZeichnenStoppen().catch(() => {})
  }
}

/* One waiting picture taken out of the line — only a waiting one: the
   one drawing is stopped with its stop. A run with nothing left of it,
   neither waiting nor drawing, ends here (it otherwise ends with its last
   picture, see `bildEinesZeichnen`'s `finally`). */
export function removeWaitingPicture(id) {
  const gone = bildQueue.find((w) => w.queue_id === id)
  if (!gone) return
  bildQueue = bildQueue.filter((w) => w !== gone)
  const run = gone.lauf_kennung
  if (run && !bildQueue.some((w) => w.lauf_kennung === run) && bildLaufWunsch?.lauf_kennung !== run) {
    laufFehlerZahl.delete(run)
  }
  bildZahlSetzen()
  pictureLineRefresh()
}
/* How many requests of each in-flight run of the studio have failed so
   far — plain bookkeeping, not rendered directly, so it does not need to
   be reactive. One picture failing is not reported on its own; the whole
   run reports once, when its own last request finishes. */
const laufFehlerZahl = new Map()

/* Counted per page: the id only tells the wishes of this one line apart. */
let queueCounter = 0
/* Enqueue and, if nothing is drawing yet, start working the queue off. */
export function bildLokalZeichnen(wunsch) {
  queueCounter += 1
  bildQueue.push({ ...wunsch, queue_id: queueCounter })
  bildZahlSetzen()
  pictureLineRefresh()
  if (!bildLokalLaeuft) workPictureLine()
}

async function workPictureLine() {
  bildLokalLaeuft = true
  try {
    while (bildQueue.length) {
      const naechste = bildQueue.shift()
      bildLaufWunsch = naechste
      bildZahlSetzen()
      pictureLineRefresh()
      await bildEinesZeichnen(naechste)
      bildLaufWunsch = null
      pictureLineRefresh()
    }
  } finally {
    bildLokalLaeuft = false
    bildLaufWunsch = null
    // The queue is empty here, so this clears the line.
    pictureLineRefresh()
    bildZahlSetzen()
  }
}

async function bildEinesZeichnen(wunsch) {
  try {
    // The line's own marks stay here; the service takes no field it does
    // not know.
    const { queue_id: _, ...request } = wunsch
    const antwort = await api.bildZeichnen(request)
    // Drawn: it leaves the line to come at once, not only once the studio
    // has read its list again.
    wunsch.drawn = true
    pictureLineRefresh()
    // The seed the picture was ACTUALLY drawn with — also when the server
    // picked it. The studio shows it and the seed plan continues from it.
    if (Number.isInteger(antwort?.seed)) seedlage.letzter = antwort.seed
  } catch (fehler) {
    /* A stopped picture is not an error. It is what was just asked for,
       and the tile disappearing IS the answer. */
    if (fehler.status !== 499) {
      if (wunsch.lauf_kennung) {
        // One picture of a run failing is not news on its own — the run's
        // own last request (below) reports once for however many failed,
        // not once per failure.
        laufFehlerZahl.set(wunsch.lauf_kennung, (laufFehlerZahl.get(wunsch.lauf_kennung) ?? 0) + 1)
      } else {
        melde(String(fehler.message || fehler), 'fehler')
      }
    }
  } finally {
    /* The request carrying the run's own last position is the one point
       that always runs, whichever pictures around it succeeded or failed
       — the run is done exactly when it finishes, never before. The last
       picture left of its run ends it — by position, or because the ones
       after it were taken out of the line. */
    const lauf = wunsch.lauf_kennung
    if (lauf && (wunsch.nr === wunsch.von || !bildQueue.some((w) => w.lauf_kennung === lauf))) {
      const gescheitert = laufFehlerZahl.get(lauf) ?? 0
      laufFehlerZahl.delete(lauf)
      if (gescheitert > 0) {
        meldeText('bild.lauf_teilweise', { gescheitert, von: wunsch.von }, 'fehler')
      }
    }
  }
}
