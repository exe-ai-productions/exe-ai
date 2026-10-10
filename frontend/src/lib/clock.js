/*
  A moment read on a given zone's clock — plain, with nothing reactive in
  it, so the modules that read schedules (terminform.js, zeitpunkt.js) can
  share it and still run on their own.
*/

/* One formatter per zone, built once: a history of a few hundred rows asks
   for its times several times each. */
const formatters = new Map()
function formatterFor(zone) {
  if (!formatters.has(zone)) {
    formatters.set(zone, new Intl.DateTimeFormat('en-GB', {
      timeZone: zone, year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric', hourCycle: 'h23',
    }))
  }
  return formatters.get(zone)
}

/**
 * Year, month, day, hour and minute of a moment as a clock in `zone` shows
 * them — an IANA name such as 'Europe/Berlin' — or as the browser's own
 * clock does when no zone is given, or one the browser does not know.
 *
 * The schedules are read by the service in the zone of its configuration,
 * and a schedule shown in the browser's zone names a second time for the
 * same moment: "08:00" as the plan and another hour as its next run.
 */
export function partsIn(date, zone = '') {
  if (zone) {
    try {
      const parts = {}
      for (const part of formatterFor(zone).formatToParts(date)) {
        parts[part.type] = Number(part.value)
      }
      return {
        year: parts.year, month: parts.month, day: parts.day,
        hour: parts.hour, minute: parts.minute,
      }
    } catch {
      /* An unknown zone: the browser's clock below. */
    }
  }
  return {
    year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate(),
    hour: date.getHours(), minute: date.getMinutes(),
  }
}

const pad = (n) => String(n).padStart(2, '0')

/** The day a moment falls on in `zone`, 'YYYY-MM-DD' — the day the
 *  service's calendar files it under. */
export function dayIn(date, zone = '') {
  const { year, month, day } = partsIn(date, zone)
  return `${year}-${pad(month)}-${pad(day)}`
}
