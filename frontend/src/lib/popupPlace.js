/*
  Where a pop-up stands beside what opened it.

  To the right of the anchor where there is room, else to its left; the top
  edge level with the anchor's, moved up when the pop-up would pass the
  window's foot, and never out past the window's top or left edge. `anker`
  is the place of the opener on screen (`left`, `right`, `top`), `groesse`
  the pop-up's `breite` and `hoehe`, `fenster` the window's `breite` and
  `hoehe`.
*/
export function popupPlace(anker, groesse, fenster, abstand = 10, rand = 12) {
  let x = anker.right + abstand
  if (x + groesse.breite > fenster.breite - rand) x = anker.left - abstand - groesse.breite
  let y = anker.top
  if (y + groesse.hoehe > fenster.hoehe - rand) y = fenster.hoehe - rand - groesse.hoehe
  return { left: Math.max(rand, x), top: Math.max(rand, y) }
}
