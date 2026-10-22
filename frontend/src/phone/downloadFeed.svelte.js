/*
  The one reading of the download that runs, shared by the catalogue page
  and the downloads page.

  The service holds one download at a time; the rest wait in the queue of
  `lib/downloads.svelte.js`. Whoever has a page open on a download asks for
  the feed with `watchDownloads()` and gives it back when the page closes —
  one timer serves all of them, and it stops when nobody is left.
*/
import { api } from '../lib/api.js'
import { t } from '../lib/texte.svelte.js'
import { melde } from '../lib/zustand.svelte.js'
import { downloads, einreihen, antreiben, fertigMerken } from '../lib/downloads.svelte.js'

/* `stand`: the running download as the service reports it; `speed` its
   bytes per second, lightly smoothed; `present` every file in a model
   folder; `partLists` the picture side's parts by sub-folder, `memoryGb` what the
   machine holds (null until read). */
export const feed = $state({ stand: null, speed: 0, present: [], partLists: null, memoryGb: null })

let users = 0
let timer = null
let watched = null
let lastFailure = null
let measure = null

function measureSpeed(running) {
  const now = Date.now()
  if (running && measure && measure.file === running.datei && now > measure.at) {
    const fresh = ((running.geladen - measure.loaded) / (now - measure.at)) * 1000
    feed.speed = feed.speed ? feed.speed * 0.4 + fresh * 0.6 : fresh
  } else {
    feed.speed = 0
  }
  measure = running ? { file: running.datei, loaded: running.geladen, at: now } : null
}

/** Reads every folder that holds models once more. A server that does not
    answer is left out: its models then show as not installed. */
export async function refreshPresent() {
  const [runner, picture, embedding, speech] = await Promise.all([
    api.runnerAuskunft().catch(() => null),
    api.bildmodelle().catch(() => null),
    api.einbettungAuskunft().catch(() => null),
    api.spracheAuskunft().catch(() => null),
  ])
  const names = []
  if (runner) {
    feed.memoryGb = runner.speicher_gb ?? null
    names.push(...(runner.modelle ?? []).map((m) => m.name), ...(runner.mmproj ?? []), ...(runner.mtp ?? []).map((m) => m.name))
  }
  if (picture) {
    feed.partLists = {
      vae: picture.vaes ?? [],
      text_encoders: [...(picture.textversteher ?? []), ...(picture.sehteile ?? [])],
    }
    names.push(
      ...(picture.modelle ?? []), ...(picture.vaes ?? []), ...(picture.loras ?? []),
      ...(picture.yolos ?? []), ...(picture.textversteher ?? []), ...(picture.sehteile ?? []),
    )
  }
  if (embedding) names.push(...(embedding.modelle ?? []).map((m) => m.name))
  if (speech) names.push(...(speech.modelle ?? []).map((m) => m.name), ...(speech.mmproj ?? []))
  feed.present = names
}

let beating = false

async function beat() {
  // A slow beat is not joined by the next one.
  if (beating) return
  beating = true
  try {
    await readOnce()
  } finally {
    beating = false
    stopWhenIdle()
  }
}

async function readOnce() {
  let running = null
  try {
    const stand = await api.modellHolenStand()
    running = stand && !stand.fertig && !stand.fehler ? stand : null
    const finished = Boolean(feed.stand && !feed.stand.fertig && !feed.stand.fehler && !running)
    feed.stand = stand
    measureSpeed(running)
    downloads.laufend = running
    if (stand?.fertig && !stand.fehler) fertigMerken(stand.datei, stand.gesamt)
    if (running) watched = stand.datei
    // A download that broke says so once, and only one this feed saw start:
    // the service keeps the state of an old failure until the next one.
    if (stand?.fehler && stand.fehler !== 'abgebrochen' && stand.datei === watched) {
      const mark = `${stand.datei}:${stand.fehler}`
      if (mark !== lastFailure) {
        lastFailure = mark
        melde(t('bildserver.generator_fehler'), 'fehler')
      }
    } else if (!stand?.fehler) {
      lastFailure = null
    }
    if (finished) await refreshPresent()
  } catch {
    // A service that does not answer holds no download: nothing is running
    // as far as this feed can tell, and the reading may stop when no page
    // is left.
    feed.stand = null
    downloads.laufend = null
    return
  }
  // Nothing running any more: the next in the row goes.
  if (!running && downloads.warteschlange.length) {
    try {
      const next = await antreiben(feed.present)
      if (next) {
        feed.stand = next
        watched = next.datei
        lastFailure = null
      }
    } catch (error) {
      melde(error.message, 'fehler')
    }
  }
}

/* The reading goes on after the last page closed for as long as a download
   runs or waits — the queue is driven from here, and a queue nobody drives
   stalls behind a download that finished. */
function stopWhenIdle() {
  if (users > 0 || !timer) return
  if (feed.stand && !feed.stand.fertig && !feed.stand.fehler) return
  if (downloads.warteschlange.length) return
  clearInterval(timer)
  timer = null
}

/** Starts the shared reading (or joins it) and returns the way to give it
    back. */
export function watchDownloads() {
  users += 1
  if (!timer) {
    refreshPresent()
    beat()
    timer = setInterval(beat, 2000)
  }
  let given = false
  return () => {
    if (given) return
    given = true
    users -= 1
    stopWhenIdle()
  }
}

/** Puts the downloads of a plan in the queue and starts the first, `art`
    being the kind of model they are (chat, einbettung, sprache, bild). */
export async function enqueue(queue, art) {
  if (!timer) timer = setInterval(beat, 2000)
  for (const job of queue) einreihen({ ...job, art })
  try {
    const fresh = await antreiben(feed.present)
    if (fresh) {
      feed.stand = fresh
      watched = fresh.datei
      lastFailure = null
    }
  } catch (error) {
    melde(error.message, 'fehler')
  }
}

/** Cancels the running download; the ones waiting go on afterwards. */
export async function cancelDownload() {
  try {
    await api.modellHolenAbbrechen()
  } catch (error) {
    melde(error.message, 'fehler')
  }
}

/** Whether a download is running right now. */
export const running = () => Boolean(feed.stand) && !feed.stand.fertig && !feed.stand.fehler
