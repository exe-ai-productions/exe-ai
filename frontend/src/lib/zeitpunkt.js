/*
  A moment, written the way this house writes moments.

  Day, month, hour and minute — no year, because everything shown with it is
  recent enough that the year would be noise, and no seconds, because nobody
  reads them.

  DIGITS, AND THE SAME NUMBER OF THEM IN EVERY LANGUAGE. This used to be the
  locale's own long form: "3. September um 14:32" in German, "September 3 at
  02:32 PM" in English. Both stand in FRONT of the line they belong to now,
  in a column of their own — and a column whose width changes with the
  interface language eats exactly the room the report needs. Twelve
  characters, always: `03.09. 14:32`. Twenty-four hours, because half of
  the length of the English form was an am/pm nobody needed to read.

  NO COMMA between the two halves. The day already ends in its own full
  stop, so the comma was a second punctuation mark doing the first one's
  job — and where this stands, a hairline separates the reading from what
  follows it (`zeittrenner`, Klappkachel.svelte). Two dividers for one gap
  is one too many.

  It lives here rather than in the panel that needed it first: two panels now
  show run times side by side, and a formatter copied into the second is the
  kind of copy that survives every change to the first.
*/

import { texte } from './texte.svelte.js'
import { partsIn } from './clock.js'

function sprachkennung() {
  return texte.sprache === 'de' ? 'de-DE' : 'en-GB'
}

function zweistellig(zahl) {
  return String(zahl).padStart(2, '0')
}

/** A full moment: day, month and time of day, in digits — in `zone` when
 *  one is given (see `partsIn`). */
export function zeitpunkt(stempel, zone = '') {
  if (!stempel) return ''
  const wann = new Date(stempel)
  if (Number.isNaN(wann.getTime())) return ''
  const { day, month, hour, minute } = partsIn(wann, zone)
  return `${zweistellig(day)}.${zweistellig(month)}. ${zweistellig(hour)}:${zweistellig(minute)}`
}

/** Whether this moment is today.
 *
 *  What a display does with the answer is brightness, never a shorter
 *  reading: dropping the date from today's rows would make the column a
 *  different width per row, and the whole point of the format above is that
 *  it never is. The time stays whole, the newer line is simply lighter.
 */
export function heute(stempel, zone = '') {
  if (!stempel) return false
  const wann = new Date(stempel)
  if (Number.isNaN(wann.getTime())) return false
  const a = partsIn(wann, zone)
  const b = partsIn(new Date(), zone)
  return a.year === b.year && a.month === b.month && a.day === b.day
}

/** A date without a time — for a schedule that names a day and nothing else. */
export function tag(iso) {
  if (!iso) return ''
  return new Date(`${iso}T00:00:00`).toLocaleDateString(sprachkennung(), {
    day: 'numeric',
    month: 'long',
  })
}
