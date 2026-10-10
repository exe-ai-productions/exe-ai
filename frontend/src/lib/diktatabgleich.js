/*
  The text that appears while somebody is still dictating.

  The speech model only reads a finished recording; it cannot listen along.
  So the recording is read again about once a second, and every reading
  comes back a little different at its end — the last word is half spoken,
  the one before it may still change its mind. A word is shown as settled
  once THREE readings in a row agree on it; what is not settled yet stands
  grey behind it. The idea is VoiceInk's (a word agreement across repeated
  readings of a model that is not a streaming one); the code is our own.

  The readings are of the recording from the last settled point on, not
  from its start. There is no word timing to cut at, so the point moves
  only when the last three readings have nothing left unsettled: then every
  word up to the end of that recording is on screen, and nothing that comes
  after can change them. Until then the reading keeps starting where it
  started.

  Pure functions, no state of their own: the input bar keeps the state and
  node runs these in the tests.
*/

/* How many readings in a row have to agree before a word is settled. */
export const EINIG = 3

/* The words of one reading. */
export function woerter(text) {
  return String(text || '').split(/\s+/).filter(Boolean)
}

/* Two words are the same word when they differ only in case and in the
   punctuation stuck to them — a reading that ends mid-sentence has no full
   stop yet, and the next one adds it. */
function gleich(a, b) {
  const form = (w) => w.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '')
  return form(a) === form(b)
}

/* A block at this level or above counts as speech — the level the live
   conversation already listens for (RMS on the 16-bit scale). */
export const SPRACHPEGEL = 200

/**
  Whether the next reading is due. Never while one is still out — two at
  once would only queue behind each other. After something was said since
  the last one began, always. In silence only while words of this stretch
  are still unsettled, and then no more than `EINIG` times: those readings
  are what settles the last words and closes the stretch, so the next
  reading starts behind it instead of reading the whole recording again.
  Past that, silence brings no new word and a reading of it would only cost
  the speech server its time.
*/
export function lesenFaellig({ gehoert, liest, offen = false, stilleLesungen = 0 }) {
  if (liest) return false
  return Boolean(gehoert) || (Boolean(offen) && stilleLesungen < EINIG)
}

/** An empty state: nothing settled, no readings yet. */
export function neuerStand() {
  return { fest: [], lesungen: [] }
}

/**
  One more reading of the recording from the last settled point.

  `stand.fest` are the settled words of this stretch, `stand.lesungen` the
  unsettled ends of the last readings (never more than `EINIG`). Returns the
  next state and what to show: `fest` settled, `unsicher` still grey.
*/
export function abgleichen(stand, text) {
  const alle = woerter(text)
  // What this reading says past the words already settled. A reading that
  // disagrees about a settled word does not unsettle it: settled is settled.
  // One that comes back with FEWER words than are settled (a dropout, two
  // words heard as one) says nothing about the end: it is kept as `null`,
  // agrees with nothing and closes nothing.
  const kurz = alle.length < stand.fest.length
  const ende = kurz ? [] : alle.slice(stand.fest.length)
  const lesungen = [...stand.lesungen, kurz ? null : ende].slice(-EINIG)
  let neuFest = 0
  if (lesungen.length === EINIG && lesungen.every(Array.isArray)) {
    const kuerzeste = Math.min(...lesungen.map((l) => l.length))
    while (
      neuFest < kuerzeste
      && lesungen.every((l) => gleich(l[neuFest], ende[neuFest]))
    ) neuFest++
  }
  const fest = [...stand.fest, ...ende.slice(0, neuFest)]
  return {
    stand: { fest, lesungen: lesungen.map((l) => (l ? l.slice(neuFest) : null)) },
    fest: fest.join(' '),
    unsicher: ende.slice(neuFest).join(' '),
  }
}

/**
  Whether the stretch is closed: words were settled, and the last `EINIG`
  readings all end exactly there. Then the next reading may start where
  this one's recording ended. One reading that merely came back short is
  not enough — it may have dropped words that were spoken.
*/
export function abgeschlossen(stand) {
  return stand.fest.length > 0
    && stand.lesungen.length === EINIG
    && stand.lesungen.every((l) => Array.isArray(l) && l.length === 0)
}

/** Whether this stretch still has words that are not settled — the
    readings in silence are for exactly these. */
export function offen(stand) {
  return stand.lesungen.length > 0 && !abgeschlossen(stand)
}
