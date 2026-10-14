/*
  What the one line under a running thinking head says, and how long it keeps
  saying it.

  The line shows the newest thought that is finished: a sentence closed by
  . ! or ? with white space after it, or a paragraph closed by a line break.
  A sentence that is still being written is not one — it would fall back to
  its first words and grow to the edge with every new sentence. Until the
  first thought is finished, the line says nothing.

  Whatever the line shows stays for at least `minMs` before the next
  thought takes its place, so a run of short sentences is a line that can
  be read, not a flicker.
*/

const isMark = (c) => c === '.' || c === '!' || c === '?'
const isSpace = (c) => c === ' ' || c === '\n' || c === '\t' || c === '\r'

/* The newest finished thought of `text`, or an empty string. The text grows
   by a few characters at a time, so it is read from its end: only the last
   two thoughts are ever looked at, however long the thinking has run. */
export function finishedThought(text) {
  const s = String(text || '')
  let end = s.length
  while (end > 0) {
    // The end of the newest closed thought at or before `end`: a mark with
    // white space behind it, or a line break.
    let close = -1
    for (let i = end - 1; i >= 0; i--) {
      if (s[i] === '\n') {
        close = i
        break
      }
      if (isMark(s[i]) && i + 1 < s.length && isSpace(s[i + 1])) {
        close = i + 1
        break
      }
    }
    if (close < 0) return ''
    // The last thought in front of it: its start is the closest earlier
    // line break, or white space behind a mark.
    let last = close - 1
    while (last >= 0 && isSpace(s[last])) last--
    if (last >= 0) {
      let start = last
      while (start > 0 && s[start - 1] !== '\n' && !(isSpace(s[start - 1]) && start > 1 && isMark(s[start - 2]))) {
        start--
      }
      return s.slice(start, last + 1).trim()
    }
    end = close
  }
  return ''
}

/* Hands every offered value to `onShow`, but not sooner than `minMs` after
   the one before it; of several offered meanwhile only the newest is shown.
   An empty line, or the first value, is shown at once. `clock` is for tests. */
export function minimumDisplay(minMs, onShow, clock = { now: Date.now, set: setTimeout, clear: clearTimeout }) {
  let shown = ''
  let since = 0
  let timer = null
  const show = (value) => {
    timer = null
    shown = value
    since = clock.now()
    onShow(value)
  }
  return {
    offer(value) {
      if (timer !== null) {
        clock.clear(timer)
        timer = null
      }
      if (value === shown) return
      const wait = since + minMs - clock.now()
      if (shown === '' || value === '' || wait <= 0) show(value)
      else timer = clock.set(() => show(value), wait)
    },
    dispose() {
      if (timer !== null) clock.clear(timer)
      timer = null
    },
  }
}
