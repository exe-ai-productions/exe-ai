/*
  A token count, short enough to sit in a line beside other facts.

  Under a thousand it stays as it is — 512 is a number one reads at a glance,
  and "0.5k" is not. Above that it becomes thousands, with one decimal while
  that still says something and none once the number is big enough that the
  decimal is noise.

  Here rather than in the panel that needed it first: two panels show context
  sizes now, and a second copy would be the kind that survives every change
  to the first.
*/

export function kurz(zahl, sprache = 'en') {
  if (!zahl) return null
  if (zahl < 1000) return String(zahl)
  const k = zahl / 1000
  const text = (k >= 100 ? Math.round(k) : Math.round(k * 10) / 10) + 'k'
  /* A comma for the decimal where the language writes one. */
  return sprache === 'de' ? text.replace('.', ',') : text
}
