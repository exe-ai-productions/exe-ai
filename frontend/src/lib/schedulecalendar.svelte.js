/*
  The calendar's state, shared by the tool surface (teile/ModulCronjobs.svelte)
  and Settings › Cronjobs (teile/SettingsCronjobs.svelte): day or month, the
  chosen day, the month on show, and the rows the service answers for the
  range on show. One object — `kalender`, below — so both faces read the same
  clock, the same chosen day and the same answer; the faces only draw it —
  ScheduleCalendar.svelte the calendar, ScheduleDayRuns.svelte the chosen
  day's runs. A face holds it while it stands (`hold`): the clock and the
  loading run as long as one of them does.

  The calendar reads one answer from the service per range
  (/cronjobs/calendar): what ran from the history, what is still to come
  from each schedule's rule, one row per schedule and day, all on the clock
  the service fires schedules by. Asked again when the range changes and
  when a schedule fires, is made, changed, paused, resumed or removed — by
  whoever did it, here or elsewhere — or a run ends: the service announces
  each of them, and nothing else asks.
*/
import { untrack } from 'svelte'
import { api } from './api.js'
import { t, texte } from './texte.svelte.js'
import { agentName } from './agentmarke.js'
import { dayIn, partsIn } from './clock.js'
import { neuigkeit } from './ereignisstrom.svelte.js'
import { zustand } from './zustand.svelte.js'

const pad = (n) => String(n).padStart(2, '0')
export function dateOf(day) {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(y, m - 1, d)
}
export const dayOf = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`

/* What a row of the calendar says on a face: its colour and the word for
   it. What ran shows how its latest run went; what has not run yet is
   planned. A switched-off schedule with nothing run that day is not news
   here — it is found and switched on in the settings. */
const STATE = {
  laeuft: { colour: 'blau', word: 'jobs.zustand.laeuft' },
  wartet: { colour: 'gelb', word: 'jobs.zustand.wartet' },
  fertig: { colour: 'gruen', word: 'jobs.zustand.fertig' },
  gescheitert: { colour: 'rot', word: 'jobs.zustand.gescheitert' },
  abgebrochen: { colour: 'still', word: 'jobs.zustand.abgebrochen' },
  unterbrochen: { colour: 'still', word: 'jobs.zustand.unterbrochen' },
}
function shown(row) {
  const ran = STATE[row.state]
  if (row.ran > 0 && ran) {
    return { colour: ran.colour, word: t(ran.word), failed: row.state === 'gescheitert' }
  }
  if (row.planned > 0) return { colour: 'still', word: t('cronjobs.geplant'), failed: false }
  return null
}
const rowsOf = (rows) =>
  rows.flatMap((row) => {
    const look = shown(row)
    return look ? [{ ...row, ...look }] : []
  })

/* A schedule that comes once that day names its minute; one that comes
   often names how often. */
export const leadOf = (row) => (row.count > 1 ? `${row.count}×` : row.first)

/* Who does the work, the way the settings name it. */
export const whoOf = (row) =>
  row.kind === 'reminder' ? t('cronjobs.kind_reminder') : row.skript || agentName(row.agent)

const minuteOf = (clock) => Number(clock.slice(0, 2)) * 60 + Number(clock.slice(3, 5))

export class ScheduleCalendar {
  jetzt = $state(new Date())
  /* Day or month, the chosen day, and the month on show. */
  view = $state('day')
  chosen = $state('')
  shownMonth = $state('')
  /* The calendar's rows per day, for the range on show. */
  calendar = $state({})
  /* Drops an answer that a newer question has already overtaken. */
  #asked = 0

  /* How many faces hold it, and the root of what runs while one does. */
  #holders = 0
  #stop = null

  constructor() {
    this.#reset()
  }

  /* A face that stands calls this from an effect and returns what it gets:
     the first one starts the clock and the loading from a fresh day, the
     last one stops them. */
  hold() {
    if (this.#holders++ === 0) {
      untrack(() => this.#reset())
      this.#stop = $effect.root(() => {
        $effect(() => {
          const uhr = setInterval(() => (this.jetzt = new Date()), 60000)
          return () => clearInterval(uhr)
        })
        $effect(() => {
          void neuigkeit.termine
          void neuigkeit.auftraege
          const [first, last] = this.range
          untrack(() => this.#load(first, last))
        })
      })
    }
    return () => {
      if (--this.#holders > 0) return
      this.#stop?.()
      this.#stop = null
    }
  }

  /* The chosen day starts as today on the service's clock. */
  #reset() {
    const today = dayIn(new Date(), zustand.timezone)
    this.jetzt = new Date()
    this.view = 'day'
    this.chosen = today
    this.shownMonth = today.slice(0, 7)
    this.calendar = {}
    /* An answer still on its way from before belongs to a range nobody
       shows now. */
    this.#asked += 1
  }

  today = $derived(dayIn(this.jetzt, zustand.timezone))
  locale = $derived(texte.sprache === 'de' ? 'de-DE' : 'en-GB')

  /* The month grid runs Monday to Sunday, whole weeks. */
  grid = $derived.by(() => {
    const [y, m] = this.shownMonth.split('-').map(Number)
    const first = new Date(y, m - 1, 1)
    const lead = (first.getDay() + 6) % 7
    const length = new Date(y, m, 0).getDate()
    const cells = Math.ceil((lead + length) / 7) * 7
    return Array.from({ length: cells }, (_, i) => dayOf(new Date(y, m - 1, 1 - lead + i)))
  })
  weekdayHeads = $derived(
    Array.from({ length: 7 }, (_, i) =>
      new Date(2026, 0, 5 + i).toLocaleDateString(this.locale, { weekday: 'narrow' })),
  )
  /* The date row names the day short; the heading over its runs names it
     in full, or says "Today". */
  title = $derived(
    this.view === 'day'
      ? dateOf(this.chosen).toLocaleDateString(this.locale, { weekday: 'short', day: 'numeric', month: 'short' })
      : dateOf(`${this.shownMonth}-01`).toLocaleDateString(this.locale, { month: 'long', year: 'numeric' }),
  )
  listTitle = $derived(
    this.chosen === this.today
      ? t('chat.heute')
      : dateOf(this.chosen).toLocaleDateString(this.locale, { weekday: 'short', day: 'numeric', month: 'long' }),
  )

  /* The month asks for its whole grid and, when the arrows have moved away
     from it, the chosen day as well: its runs stay under the calendar. */
  range = $derived(
    this.view === 'day'
      ? [this.chosen, this.chosen]
      : [
          this.chosen < this.grid[0] ? this.chosen : this.grid[0],
          this.chosen > this.grid[this.grid.length - 1] ? this.chosen : this.grid[this.grid.length - 1],
        ],
  )
  shaped = $derived(Object.fromEntries(Object.keys(this.calendar).map((day) => [day, rowsOf(this.calendar[day])])))
  dayRows = $derived(this.shaped[this.chosen] || [])

  /* The day line: a dot for a schedule that comes once that day, at its
     minute, in its state's colour; a band under the line for one that comes
     often. Now's mark only on today. */
  nowMinute = $derived.by(() => {
    const { hour, minute } = partsIn(this.jetzt, zustand.timezone)
    return hour * 60 + minute
  })
  dots = $derived(
    this.dayRows
      .filter((row) => row.count === 1 && row.first)
      .map((row, i) => ({ key: row.cronjob_id || `gone:${i}`, minute: minuteOf(row.first), colour: row.colour })),
  )
  band = $derived(this.dayRows.some((row) => row.count > 1))

  /* ‹ and › step a day in the day, a month in the month. */
  step(by) {
    if (this.view === 'day') {
      const d = dateOf(this.chosen)
      d.setDate(d.getDate() + by)
      this.chosen = dayOf(d)
    } else {
      const [y, m] = this.shownMonth.split('-').map(Number)
      const d = new Date(y, m - 1 + by, 1)
      this.shownMonth = `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
    }
  }
  showDay() {
    this.view = 'day'
  }
  showMonth() {
    this.shownMonth = this.chosen.slice(0, 7)
    this.view = 'month'
  }
  /* A day clicked in the month is chosen, and the month stays. */
  choose(day) {
    this.chosen = day
  }

  async #load(first, last) {
    const ticket = ++this.#asked
    try {
      const answer = await api.cronjobCalendar(first, last)
      if (ticket === this.#asked) this.calendar = answer
    } catch {
      /* The last answer stays; the next firing asks again. */
    }
  }
}

/* The one calendar both faces draw. */
export const kalender = new ScheduleCalendar()
