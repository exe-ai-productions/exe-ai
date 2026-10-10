/* The running picture's step counter, asked for in one place.

   Every surface that shows a picture being drawn — the working frame in the
   chat, the generation area and the drawing tile of the picture studio —
   reads this one answer instead of asking the service each on its own. The
   service is asked only while at least one of them is watching, one
   question at a time. */
import { untrack } from 'svelte'
import { api } from './api.js'

// `preview`: the stamp of the running picture's newest live preview, 0
// while there is none. `previewUrl`: that preview, fetched once for every
// surface that shows it, or '' while there is none to show.
export const pictureProgress = $state({
  running: false, share: 0, step: 0, total: 0, preview: 0, previewUrl: '',
})

let watchers = 0
let timer = null
// The generation a question is on its way for, or -1 with none.
let askingFor = -1
/* Counted up each time the watching ends: an answer still on its way from
   a watch that has ended belongs to a picture that is gone. */
let generation = 0

/* The live preview, fetched in one place and one at a time, for every
   surface that shows it. Each preview arrives whole or not at all (the
   service answers 404 to one caught half written), and is only shown when
   it is newer than the one on screen.

   A fetch no answer has begun for when a newer preview is reported is
   given up and the newer one fetched: one that never answers must not hold
   every later preview back until the picture ends. An answer that has
   begun is read to its end and shown — it is slow, not stuck, and giving
   it up for every newer stamp would leave a slow line with no preview at
   all; the newest stamp is fetched after it. */
let previewWatchers = 0
// The fetch on its way — the stamp it was asked for, the handle that ends
// it, and whether its answer has begun — or null with none.
let previewFetch = null
let shownStamp = 0
// The picture the preview on screen belongs to, as its watchers name it.
let previewOf = null

function clearPreview() {
  // An answer on its way belongs to what was let go.
  previewFetch?.abort.abort()
  previewFetch = null
  if (pictureProgress.previewUrl) URL.revokeObjectURL(pictureProgress.previewUrl)
  pictureProgress.previewUrl = ''
  shownStamp = 0
}

function fetchPreview(stamp) {
  if (!previewWatchers || stamp <= shownStamp) return
  if (previewFetch) {
    // That very preview is on its way already, or an answer is being read.
    if (stamp <= previewFetch.stamp || previewFetch.answering) return
    previewFetch.abort.abort()
  }
  const fetching = { stamp, abort: new AbortController(), answering: false }
  previewFetch = fetching
  api.previewAnswer(fetching.abort.signal)
    .then((answer) => {
      fetching.answering = true
      return answer.blob()
    })
    .then((blob) => {
      if (previewFetch !== fetching) return
      if (pictureProgress.previewUrl) URL.revokeObjectURL(pictureProgress.previewUrl)
      pictureProgress.previewUrl = URL.createObjectURL(blob)
      shownStamp = stamp
    })
    .catch(() => {})
    .finally(() => {
      if (previewFetch !== fetching) return
      previewFetch = null
      /* A newer stamp reported while this one was read is fetched now. Only
         a newer one: the same stamp again (a preview caught half written)
         waits for the counter's next answer, as before. */
      if (pictureProgress.preview > stamp) fetchPreview(pictureProgress.preview)
    })
}

/* Show the live preview of `picture` while mounted; the returned function
   stops. Meant as an effect's own return, beside `watchPictureProgress`.
   `picture` names the picture being drawn — whatever tells one from the
   next.

   The preview is not cleared when the last surface stops watching: a
   surface rebuilt while the same picture is drawn finds it still standing
   and fetches nothing again. It goes with the picture — when a watch names
   another one, when the counter reports no preview any more, or when the
   counter itself is no longer watched (`set` below). */
export function watchPicturePreview(picture) {
  previewWatchers += 1
  if (picture !== previewOf) {
    /* Another picture: what stands is not its preview, and the stamp last
       reported is not its stamp either — the counter's next answer brings
       its own. */
    clearPreview()
    pictureProgress.preview = 0
    previewOf = picture
  } else {
    // Read without tracking: the caller's effect must not start over with
    // every new stamp.
    fetchPreview(untrack(() => pictureProgress.preview))
  }
  return () => {
    previewWatchers -= 1
  }
}

function set(running, share, step, total, preview = 0) {
  // No preview (the next picture began, or nothing runs): the last one goes,
  // once — polls with nothing to clear leave the fetch state alone.
  if (preview) fetchPreview(preview)
  else if (shownStamp || previewFetch || pictureProgress.previewUrl) clearPreview()
  pictureProgress.preview = preview
  pictureProgress.running = running
  pictureProgress.share = share
  pictureProgress.step = step
  pictureProgress.total = total
}

async function ask() {
  // One question at a time — but one left over from an ended watch does
  // not hold up the new one.
  if (askingFor === generation) return
  const asked = generation
  askingFor = asked
  try {
    const answer = await api.bildFortschritt()
    if (asked !== generation) return
    if (answer.laeuft) set(true, answer.anteil, answer.schritt, answer.gesamt, answer.preview ?? 0)
    else set(false, 0, 0, 0)
  } catch {
    /* no counter is no error — the surfaces just show no number */
  } finally {
    if (askingFor === asked) askingFor = -1
  }
}

/* Watch the counter while mounted; the returned function stops watching.
   Meant as an effect's own return: `$effect(() => watchPictureProgress())`. */
export function watchPictureProgress() {
  watchers += 1
  if (watchers === 1) {
    ask()
    timer = setInterval(ask, 700)
  }
  return () => {
    watchers -= 1
    if (watchers === 0) {
      clearInterval(timer)
      timer = null
      generation += 1
      set(false, 0, 0, 0)
    }
  }
}
