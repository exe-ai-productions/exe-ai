/*
  One clock for every running reading in the chat.

  The thinking head and the waiting mark both show how long something has
  been going, often one right above the other. Each used to keep its own
  ticker, started at its own moment, so the two turned over at different
  instants and stood a second apart while counting from the same start.
  Both now read the same `takt.jetzt`. It is sampled four times a second,
  and only while somebody holds it — fine enough that a fresh stretch shows
  its 0:00 at once instead of up to a second late.
*/

export const takt = $state({ jetzt: Date.now() })

let halter = 0
let uhr = null

/** Keeps the clock going while the caller needs it; returns the release. */
export function taktHalten() {
  if (halter++ === 0) {
    takt.jetzt = Date.now()
    uhr = setInterval(() => { takt.jetzt = Date.now() }, 250)
  }
  let frei = false
  return () => {
    if (frei) return
    frei = true
    if (--halter === 0) {
      clearInterval(uhr)
      uhr = null
    }
  }
}
