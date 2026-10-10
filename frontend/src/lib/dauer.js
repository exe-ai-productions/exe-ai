/*
  How long a tool call, a run or a video takes, written for a person.

  Why this is one module and not three lines in three components: the
  duration is shown in three places — the run tile and the tool tile of the
  terminal module (ModulTerminal.svelte) and the length on a video tile
  (Videokachel.svelte) — and they are fed from different measuring points
  (`app/tools/hintergrund.py` for a run, `app/api/v1/generierung.py` for a
  call, the video file itself). The same length of time must read the same
  in all three, whichever side it came from. A copied branch drifts; one
  function cannot. The chat's tool rows show no duration.

  Why it says milliseconds at all: nearly every call on a local disk takes a
  few of them. Rounded to a tenth of a second that became `0.0`, and
  JavaScript writes `0.0` as `0` — so the interface said `0s` for `edit_file`,
  `read_file` and almost everything else, which is true and worthless. It only
  ever meant "shorter than the display could tell".

  The service now hands over the raw number in seconds with millisecond
  precision, and the unit is chosen here. The number travels unformatted
  through the API, as the durations and rates of a model answer do too —
  a text pretending to be a value is a value nobody can compute with.
*/

/* Where the two wordings live in the catalog. Both sections carry the same
   pair — `terminal` for the module's own list, `werkzeug` for the rest. */
export const TERMINAL = 'terminal'
export const WERKZEUG = 'werkzeug'

/**
 * The duration as it is shown: `12ms` under a second, `2.7s` from there on.
 *
 * `t` is handed in rather than imported so this file stays a plain function
 * — the caller already has the reactive one from `texte.svelte.js`.
 *
 * Returns '' for anything that is not a real measurement. A missing duration
 * is an older message that was never timed, and the callers leave the whole
 * span out for it rather than print an invented zero.
 */
export function dauerText(t, sekunden, bereich = WERKZEUG) {
  if (typeof sekunden !== 'number' || !Number.isFinite(sekunden) || sekunden < 0) return ''
  /* Rounded to whole milliseconds first, then compared: 0.9999 s is a
     second to any reader, and `1000ms` would be a silly way to say so. */
  const ms = Math.round(sekunden * 1000)
  if (ms < 1000) return t(`${bereich}.dauer_ms`, { ms })
  /* A tenth of a second is as fine as anyone reads a duration this long —
     the extra digits the service now sends belong to the short end. */
  return t(`${bereich}.dauer`, { s: (Math.round(sekunden * 10) / 10).toFixed(1) })
}

/**
 * A stretch of time as a stopwatch reads it, `m:ss` — a running reading
 * (the thinking head, the waiting mark) and a finished stretch's length say
 * it the same way. Not through the catalogue: it is digits and a colon, the
 * same in every language this program speaks. (A time of day is
 * `uhrzeit` in lib/terminform.js — a different thing.)
 */
export function stoppuhr(ms) {
  const sekunden = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(sekunden / 60)}:${String(sekunden % 60).padStart(2, '0')}`
}
