/*
  The search of the settings: what it finds and how it takes a hit there.

  Plain functions with no imports, so a test can run them without a window.
  `text` is the catalogue's `t`: everything is searched by the words the
  language in use shows, never by key.

  A search finds rows by their title and single switches by their label; a
  hit on a switch stands as "Page › Switch" and leads to the switch itself.
*/

/* One spelling of a word for comparing: no accents, no case, no edges. */
export function glatt(wort) {
  return String(wort ?? '')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .trim()
}

/** The groups with only the rows whose title holds the question; a group
 *  without a row is gone. An empty question keeps everything. */
export function zeilenFiltern(gruppen, frage, text) {
  const gesucht = glatt(frage)
  if (!gesucht) return gruppen
  return gruppen
    .map((gruppe) => ({
      ...gruppe,
      zeilen: gruppe.zeilen.filter((zeile) => glatt(text(zeile.titel)).includes(gesucht)),
    }))
    .filter((gruppe) => gruppe.zeilen.length > 0)
}

/** The switches whose label holds the question, each with the row of its
 *  page and the line to show: "Page › Switch". `zeileFuer(id)` answers the
 *  row an id of the list names. */
export function schalterTreffer(felder, frage, text, zeileFuer) {
  const gesucht = glatt(frage)
  if (!gesucht) return []
  const treffer = []
  for (const feld of felder) {
    const schalter = text(feld.titel)
    if (!glatt(schalter).includes(gesucht)) continue
    const zeile = zeileFuer(feld.zeile)
    if (!zeile) continue
    treffer.push({ feld, zeile, text: `${text(zeile.titel)} › ${schalter}` })
  }
  return treffer
}

/** Scrolls to the switch with this label once its page is on screen, and lets
 *  it flash once. The page appears a moment after the row was picked, so the
 *  switch is looked for until it is there, or for four seconds. Returns the
 *  way to stop looking. */
export function schalterAnspringen(beschriftung, wurzel = globalThis.document) {
  const bis = Date.now() + 4000
  let lauf = true
  const suchen = () => {
    if (!lauf) return
    const schalter = [...wurzel.querySelectorAll('[role="switch"]')].find(
      (el) => el.getAttribute('aria-label') === beschriftung && el.offsetParent,
    )
    if (schalter) {
      schalter.scrollIntoView({ block: 'center' })
      schalter.focus({ preventScroll: true })
      schalter.animate?.(
        [{ boxShadow: '0 0 0 4px currentColor' }, { boxShadow: '0 0 0 0 transparent' }],
        { duration: 1200 },
      )
      return
    }
    if (Date.now() < bis) requestAnimationFrame(suchen)
  }
  suchen()
  return () => {
    lauf = false
  }
}
