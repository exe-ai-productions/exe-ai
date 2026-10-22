/*
  What the look pages of the settings share: the code colour packs in the
  order the list offers them, and the colour an untouched chat bubble shows
  at this moment.
*/

/* The code colour packs in the order the list offers them: the house
   pack first, then the eight editor packs (stil/codefarben.css). */
export const CODE_PACKS = [
  ['exe', 'einstellungen.codefarben_exe'],
  ['tokyo', 'einstellungen.codefarben_tokyo'],
  ['onelight', 'einstellungen.codefarben_onelight'],
  ['github', 'einstellungen.codefarben_github'],
  ['githubdark', 'einstellungen.codefarben_githubdark'],
  ['dracula', 'einstellungen.codefarben_dracula'],
  ['nord', 'einstellungen.codefarben_nord'],
  ['solarizedlight', 'einstellungen.codefarben_solarizedlight'],
  ['solarizeddark', 'einstellungen.codefarben_solarizeddark'],
]

export function blasenStandard() {
  // The picker's "current default" swatch must match what an untouched
  // bubble actually shows — a theme may ship its own default (Dark Matter's
  // lavender), so prefer that over the plain house bubble.
  const stil = getComputedStyle(document.documentElement)
  const wert = (
    stil.getPropertyValue('--blase-eigen-standard').trim() ||
    stil.getPropertyValue('--blase').trim()
  )
  return /^#[0-9a-fA-F]{6}$/.test(wert) ? wert : '#232320'
}
