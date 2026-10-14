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

/* One formatter per language and digit count: a panel draws a dozen fields. */
const formatters = new Map()

function formatterFor(language, digits) {
  const key = `${language}|${digits}`
  let formatter = formatters.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat(language === 'de' ? 'de-DE' : 'en-US', {
      minimumFractionDigits: 1,
      maximumFractionDigits: Math.max(1, digits),
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
