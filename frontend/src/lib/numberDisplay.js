/*
  How a number with a fractional step is written in a field, and how what is
  typed into one is read.

  A value with a fractional step carries at least one fractional digit and at
  most as many as its step has (1 → "1,0", 0.95 → "0,95", 0.8 at a step of
  0.05 → "0,8"), with the decimal sign of the language and no thousands
  separator. A whole step stays a plain whole number. Typed, the sign of the
  language and a point both count.

  The language comes in as an argument, so this module reads nothing from the
  page and runs in node as it is.
*/

/* One formatter per language and digit range: a panel draws a dozen fields.
   A field has at least one digit and as many as its step; a size has exactly
   as many as it is given (`minimum` = `digits`). */
const formatters = new Map()

function formatterFor(language, digits, minimum = 1) {
  const key = `${language}|${minimum}|${digits}`
  let formatter = formatters.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat(language === 'de' ? 'de-DE' : 'en-US', {
      minimumFractionDigits: minimum,
      maximumFractionDigits: Math.max(minimum, digits),
      useGrouping: false,
    })
    formatters.set(key, formatter)
  }
  return formatter
}

/* How many fractional digits a step has, from the way it is written. */
export function fractionDigits(step) {
  const text = String(step)
  const exponent = /e-(\d+)$/i.exec(text)
  if (exponent) return Number(exponent[1])
  return text.split('.')[1]?.length ?? 0
}

/* The number as the field shows it. `digits` is the step's digits. */
export function formatNumber(value, digits, language) {
  const number = Number(value)
  if (!digits) return number.toFixed(0)
  return formatterFor(language, digits).format(number)
}

/* What was typed, as a number: `null` for nothing, `NaN` for something that
   is no number. The first comma stands for the point. */
export function parseNumber(text) {
  const cleaned = String(text ?? '').trim().replace(',', '.')
  if (!cleaned) return null
  return Number(cleaned)
}

/* A size in GB as the catalogue and the download page write it: under 1 GB
   exactly two fractional digits ("0,01"), from 1 GB exactly one ("14,8",
   "7,0"), the decimal sign of the language. Not a number: a hyphen. */
export function formatGb(value, language) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  /* Decided on the rounded value: 0.996 is written "1,0", not "1,00", and a
     hair under zero is a plain zero. */
  const rounded = Math.round(value * 100) / 100
  const digits = Math.abs(rounded) < 1 ? 2 : 1
  return formatterFor(language, digits, digits).format(rounded === 0 ? 0 : value)
}
