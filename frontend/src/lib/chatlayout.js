/* The chat layout the user sets in the layout mode.

   One table for everything the layout mode window offers: the font size of
   the chat, the column width, the two bubble widths, the two anchors, the
   room between messages and the picture tile. Each entry carries its range,
   its factory value and the key it is stored under; the service checks the
   same ranges (`app/darstellungwahl.py`).

   The values act through CSS variables on the root element. An inline style
   there outranks every rule from the stylesheet, so the variables' fallbacks
   in the components only matter before the first value is applied. The
   picture tile is not a CSS variable: App.svelte reads it from the state. */

export const CHATLAYOUT = [
  { id: 'schrift', von: 10, bis: 26, standard: 17, text: 'layoutmodus.schrift' },
  { id: 'breite', von: 600, bis: 2000, standard: 1400, text: 'layoutmodus.breite' },
  { id: 'blase_eigen', von: 15, bis: 100, standard: 80, einheit: '%', text: 'layoutmodus.blase_eigen' },
  { id: 'blase_ki', von: 15, bis: 100, standard: 100, einheit: '%', text: 'layoutmodus.blase_ki' },
  { id: 'anker_eigen', von: 0, bis: 100, standard: 100, einheit: '%', text: 'layoutmodus.anker_eigen' },
  { id: 'anker_ki', von: 0, bis: 100, standard: 0, einheit: '%', text: 'layoutmodus.anker_ki' },
  { id: 'abstand', von: 0, bis: 120, standard: 40, text: 'layoutmodus.abstand' },
  { id: 'bildkachel', von: 200, bis: 700, standard: 700, text: 'layoutmodus.bildkachel' },
]

export const VORGABE_CHATLAYOUT = Object.fromEntries(CHATLAYOUT.map((r) => [r.id, r.standard]))

/* A stored layout over the factory values. A value outside its range never
   comes from the service, which checks the same table; it is clamped all the
   same, so a hand-edited row cannot push the chat off the screen. */
export function chatlayoutAusGespeichert(gespeichert) {
  const werte = { ...VORGABE_CHATLAYOUT }
  for (const r of CHATLAYOUT) {
    const zahl = gespeichert?.[r.id]
    if (Number.isInteger(zahl)) werte[r.id] = Math.min(r.bis, Math.max(r.von, zahl))
  }
  return werte
}

/* Only what differs from the factory goes into storage: a layout set back
   to "Standard" then follows the factory values, even if they move later. */
export function chatlayoutZumSpeichern(werte) {
  return Object.fromEntries(
    CHATLAYOUT.filter((r) => werte[r.id] !== r.standard).map((r) => [r.id, werte[r.id]]),
  )
}

/* The anchors run from 0 (hard left) to 1 (hard right) in the components,
   measured against the room left over beside the bubble. */
export function chatlayoutAnwenden(werte) {
  if (typeof document === 'undefined') return
  const wurzel = document.documentElement.style
  wurzel.setProperty('--chat-schrift', werte.schrift + 'px')
  wurzel.setProperty('--chat-breite', werte.breite + 'px')
  wurzel.setProperty('--blase-eigen-breite', werte.blase_eigen + '%')
  wurzel.setProperty('--blase-ki-breite', werte.blase_ki + '%')
  wurzel.setProperty('--blase-eigen-stelle', String(werte.anker_eigen / 100))
  wurzel.setProperty('--blase-ki-stelle', String(werte.anker_ki / 100))
  wurzel.setProperty('--chat-abstand', werte.abstand + 'px')
}
