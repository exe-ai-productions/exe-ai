/*
  The three shapes a schedule can have, read in one place (app/terminplan.py
  knows the same three):

    08:00              a daily time
    0 * * * *          a cron expression
    2026-09-04T09:00   one fixed moment

  The schedule card and the form both read them, and two copies of the
  same patterns are how the two come to disagree the first time a shape
  changes.
*/

export const TAEGLICH = /^([01]\d|2[0-3]):([0-5]\d)$/
export const ZEITPUNKT = /^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):([0-5]\d)$/

/** The time of day a schedule leads with, "HH:MM" — for a daily time and a
 *  fixed moment; a cron expression has none of its own. */
export function uhrzeit(zeitplan) {
  const wert = String(zeitplan ?? '').trim()
  if (TAEGLICH.test(wert)) return wert
  const einmal = ZEITPUNKT.exec(wert)
  return einmal ? `${einmal[4]}:${einmal[5]}` : ''
}

/** The date of a fixed moment, "YYYY-MM-DD", or '' for the other shapes. */
export function datum(zeitplan) {
  const einmal = ZEITPUNKT.exec(String(zeitplan ?? '').trim())
  return einmal ? `${einmal[1]}-${einmal[2]}-${einmal[3]}` : ''
}

/* The form's repetitions, and the shape each is stored in — the three of
   today, nothing new:

     once      a daily time with the one-off flag and its day
     daily     a daily time
     weekly    a cron expression "M H * * d,d" (the weekdays picked)
     monthly   a cron expression "M H D * *"
     custom    the cron expression as typed

   Read back the same way: what matches none of the first four opens as
   custom, with the expression as it stands. */
export const REPEATS = ['once', 'daily', 'weekly', 'monthly', 'custom']

const WEEKLY = /^(\d{1,2}) (\d{1,2}) \* \* ([0-6](?:,[0-6])*)$/
const MONTHLY = /^(\d{1,2}) (\d{1,2}) ([1-9]|[12]\d|3[01]) \* \*$/

const pad = (n) => String(n).padStart(2, '0')

/* The chips run Monday to Sunday; cron counts Sunday as 0. */
const chipToCron = (chip) => (chip + 1) % 7
const cronToChip = (dow) => (dow + 6) % 7

/** The weekday chip (0 = Monday) of a day 'YYYY-MM-DD'. */
export function chipOf(day) {
  const [y, m, d] = day.split('-').map(Number)
  return cronToChip(new Date(y, m - 1, d).getDay())
}

function clockOf(minute, hour) {
  const h = Number(hour)
  const m = Number(minute)
  return h < 24 && m < 60 ? `${pad(h)}:${pad(m)}` : null
}

/** The form's fields for a stored schedule, `day` standing in where the
 *  schedule names no day of its own. */
export function formFromEntry(entry, day) {
  const zeitplan = String(entry?.zeitplan ?? '').trim()
  const form = {
    repeat: 'custom', time: '', day, weekdays: [chipOf(day)],
    monthDay: Number(day.slice(8)), cron: '',
  }
  if (entry?.einmalig) {
    const moment = ZEITPUNKT.exec(zeitplan)
    if (moment) {
      return { ...form, repeat: 'once', time: `${moment[4]}:${moment[5]}`, day: `${moment[1]}-${moment[2]}-${moment[3]}` }
    }
    if (TAEGLICH.test(zeitplan)) return { ...form, repeat: 'once', time: zeitplan, day: entry.datum || day }
  }
  if (TAEGLICH.test(zeitplan)) return { ...form, repeat: 'daily', time: zeitplan }
  const weekly = WEEKLY.exec(zeitplan)
  const weeklyTime = weekly && clockOf(weekly[1], weekly[2])
  if (weeklyTime) {
    const weekdays = [...new Set(weekly[3].split(',').map((d) => cronToChip(Number(d))))].sort()
    return { ...form, repeat: 'weekly', time: weeklyTime, weekdays }
  }
  const monthly = MONTHLY.exec(zeitplan)
  const monthlyTime = monthly && clockOf(monthly[1], monthly[2])
  if (monthlyTime) return { ...form, repeat: 'monthly', time: monthlyTime, monthDay: Number(monthly[3]) }
  return { ...form, cron: zeitplan }
}

/** What the form stores: the schedule field, the one-off flag and its day. */
export function storedFromForm(form) {
  const [h, m] = String(form.time || '').split(':').map(Number)
  switch (form.repeat) {
    case 'once':
      return { zeitplan: form.time, einmalig: true, datum: form.day }
    case 'daily':
      return { zeitplan: form.time, einmalig: false, datum: null }
    case 'weekly': {
      const days = [...form.weekdays].map(chipToCron).sort((a, b) => a - b)
      return { zeitplan: `${m} ${h} * * ${days.join(',')}`, einmalig: false, datum: null }
    }
    case 'monthly':
      return { zeitplan: `${m} ${h} ${form.monthDay} * *`, einmalig: false, datum: null }
    default:
      return { zeitplan: String(form.cron || '').trim(), einmalig: false, datum: null }
  }
}

/** The schedule fields a change has to send: only what differs from what
 *  the form opened with. A one-off's time and day travel together once
 *  either changes — a one-off may be stored as one fixed moment
 *  ("2026-10-02T09:30"), and the tool takes a new day only beside a time
 *  of day. */
export function changedSchedule(entry, form, day) {
  const before = storedFromForm(formFromEntry(entry, day))
  const after = storedFromForm(form)
  const fields = {}
  if (after.einmalig !== before.einmalig) fields.einmalig = after.einmalig
  if (after.einmalig && (after.zeitplan !== before.zeitplan || after.datum !== before.datum)) {
    fields.zeitplan = after.zeitplan
    fields.datum = after.datum
  } else if (after.zeitplan !== before.zeitplan) {
    fields.zeitplan = after.zeitplan
  }
  return fields
}
