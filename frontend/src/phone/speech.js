/*
  The answers of the speech server page that are decided without a window:
  what a field shows, whether a change is worth storing, and what a typed
  number turns into.

  Every value of the page lives in one stored setting; the service reads its
  own works answers alongside (`diktat_vorgaben` of the speech report). A
  field shows what is stored, else the works answer, and stores only what
  moved away from it — a works text nobody changed is no choice, and storing
  it would freeze it against a later change of the works text.

  No imports on purpose: values in, answers out, so a test can run it
  without a window around it.
*/

/* The stored word for "Auto" in a generation value of the voice. */
export const AUTO = 'auto'

/* The five generation values of the voice: which stored key each one is, the
   bounds a value is kept to and how fine a step is. The service clamps
   whatever it gets; a value outside these would not be the one that runs.
   Each may be empty: that is "Auto", stored as the word (an empty number
   would take the stored value away, which is the works answer, not Auto),
   and the program of the voice takes its own value. */
export const PARAMETERS = [
  { name: 'temperatur', key: 'stimmtemperatur', label: 'sprachserver.feld_temperatur', min: 0, max: 1, step: 0.05, whole: false },
  { name: 'top_k', key: 'stimmtop_k', label: 'sprachserver.feld_top_k', min: 0, max: 200, step: 1, whole: true },
  { name: 'top_p', key: 'stimmtop_p', label: 'sprachserver.feld_top_p', min: 0, max: 1, step: 0.01, whole: false },
  { name: 'min_p', key: 'stimmmin_p', label: 'sprachserver.feld_min_p', min: 0, max: 1, step: 0.01, whole: false },
  { name: 'strafe', key: 'stimmstrafe', label: 'sprachserver.feld_strafe', min: 1, max: 2, step: 0.01, whole: false },
]

/* The pause before a spoken sentence is sent, in seconds. Empty is "Auto":
   the service goes by its works number. */
export const PAUSE = { min: 0.1, max: 600, step: 0.1 }

/* How long one round of a conversation waits for the first word (seconds)
   and how many rounds without one end it. Empty is "Auto" here as well; the
   upper bound is the number field's own, as in the desktop window. */
export const WAIT = { min: 0.1, max: 999999, step: 0.1 }
export const SILENT_ROUNDS = { min: 1, max: 999999, step: 1 }

/** What a text field shows: what is stored, else the works text. */
export const shownText = (stored, works) => stored || works || ''

/** What a number field shows: what is stored, else the works number. Zero is
    a real number, so `??` and never `||`. */
export const shownNumber = (stored, works) => (stored === AUTO ? null : (stored ?? works ?? null))

/** What a switch shows: a stored "off" is a real answer, so `??`. */
export const shownSwitch = (stored, works, fallback = false) => stored ?? works ?? fallback

/** Whether a changed text or number is worth storing. Equal to what is
    stored: no. Nothing stored and equal to the works answer: no — that is the
    works answer standing, not a choice. Anything else: yes, an empty number
    too (`null` takes a stored number away). */
export function worthStoring(value, stored, works) {
  const nothing = stored === '' || stored === null || stored === undefined
  const kept = nothing ? null : stored
  if (value === kept || (value === '' && nothing)) return false
  if (nothing && value === (works ?? null)) return false
  return true
}

/** The options of the cleaned-up-by choice. The tidy-up model can only be the
    cleaner once a file stands in its own picker: an entry that cannot do
    anything is an entry that lies, so it says it is empty. `label` is the
    catalogue's word for each (a key, passed in as the text of that key). */
export function cleanerOptions(words, hasModel) {
  return [
    { value: 'aus', label: words.aus },
    { value: 'putzmodell', label: hasModel ? words.putzmodell : words.putzmodellLeer },
    { value: 'modell', label: words.modell },
    { value: 'agent', label: words.agent },
  ]
}

/** A number from what was typed, kept to its bounds and its step, or
    `undefined` for nonsense (the field goes back to what it showed) and
    `null` for nothing. A comma is a decimal point. */
export function parseNumber(text, { min, max, step, whole = false }) {
  const raw = String(text ?? '').trim().replace(',', '.')
  if (raw === '') return null
  if (!/^-?\d*\.?\d+$/.test(raw)) return undefined
  let number = Number(raw)
  if (!Number.isFinite(number)) return undefined
  number = Math.min(max, Math.max(min, number))
  if (whole) return Math.round(number)
  const digits = String(step).includes('.') ? String(step).split('.')[1].length : 0
  return Number((Math.round(number / step) * step).toFixed(digits))
}

/** A number as a field shows it: the whole number as it is, a fraction with
    the digits its step has — and an empty field for nothing. */
export function numberText(value, { step = 1, whole = false } = {}) {
  if (value === null || value === undefined) return ''
  if (whole) return String(value)
  const digits = String(step).includes('.') ? String(step).split('.')[1].length : 0
  return Number(value).toFixed(digits)
}
