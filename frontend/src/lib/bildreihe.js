/*
  The row of pictures a reader can step through, and what a swipe of a
  finger means for it.

  A picture opened in the reader belongs to a row: the pictures of the open
  chat, or the pictures of the studio's gallery. The row is the first one
  that holds the picture on show; a swipe to the left goes to the next, a
  swipe to the right to the one before, and at either end nothing happens.

  No imports, so the decisions can be tried without a window around them.
*/

/* An address without its query: the same file is asked for with a session
   key in one place and without it in another. */
export const ohneAbfrage = (adresse) => String(adresse ?? '').split(/[?#]/)[0]

/* The pictures one message carries: the list of a run (an entry is empty
   while its picture is not there yet), or the single picture of an older
   message. */
export function bilderVon(nachricht) {
  if (Array.isArray(nachricht?.bilder)) {
    const echte = nachricht.bilder.filter(Boolean)
    if (echte.length) return echte
  }
  return nachricht?.bild ? [nachricht.bild] : []
}

/* The row the picture on show stands in: the first of the given rows that
   holds it, as it is; none when no row does. */
export function reiheMit(adresse, reihen) {
  const wanted = ohneAbfrage(adresse)
  if (!wanted) return []
  return reihen.find((reihe) => reihe.some((eintrag) => ohneAbfrage(eintrag) === wanted)) ?? []
}

/* Where the picture on show stands in its row, counted from one, and how
   long the row is. Both zero while it stands in none. */
export function stelleIn(reihe, adresse) {
  const wanted = ohneAbfrage(adresse)
  const at = reihe.findIndex((eintrag) => ohneAbfrage(eintrag) === wanted)
  return at < 0 ? { nummer: 0, von: 0 } : { nummer: at + 1, von: reihe.length }
}

/* The picture `schritt` places on from the one on show, or null at the end
   of the row. */
export function nachbar(reihe, adresse, schritt) {
  const wanted = ohneAbfrage(adresse)
  const at = reihe.findIndex((eintrag) => ohneAbfrage(eintrag) === wanted)
  if (at < 0) return null
  return reihe[at + schritt] ?? null
}

/* What a finger's way across the screen asks for: +1 for a swipe to the
   left (the next picture), -1 for one to the right, 0 for anything else —
   too short, too slow, or more up and down than across (a scroll or a drag
   of the sheet is no page turn). */
export function wischSchritt({ dx, dy, dauer }, { weite = 56, frist = 700 } = {}) {
  if (Math.abs(dx) < weite) return 0
  if (Math.abs(dx) < Math.abs(dy) * 1.5) return 0
  if (dauer > frist) return 0
  return dx < 0 ? 1 : -1
}
