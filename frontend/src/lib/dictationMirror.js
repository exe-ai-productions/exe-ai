/*
  The mirror laid over the field while somebody is still dictating.

  The speech model reads a finished recording, so what it heard is shown
  while it is still being spoken: the words settled so far in the field's
  own colour, the unsettled end grey behind them. The field underneath keeps
  its own text and waits for the last pass after the stop — nothing
  half-heard ever lands in a draft.

  What is computed here is the text and its measure: what the mirror shows,
  where the words belong when they arrive, and how tall the field has to
  grow for both. The field itself, its lettering and its scrolling stay in
  the component.

  Pure functions, no state of their own: the input bar keeps the state and
  node runs these in the tests, the way lib/diktatabgleich.js does it.
*/

/* One word gap, where something stands in front of it that does not already
  end in one. The same rule for the mirror and for the text that lands in
  the field: the mirror is the preview of exactly that text. Not behind »,
  which opens a German quotation: the quoted word follows it directly. */
function gapOf(text) {
  return text && !/[\s»]$/.test(text) ? ' ' : ''
}

/* And one behind, where a word follows: dictated in front of a draft, the
  words would otherwise run straight into it. Not where the text behind
  already begins with a gap, and not in front of a mark that closes what
  stands before it — a word dictated over the last one of a sentence keeps
  its full stop right behind it. German quotation marks close with «; » opens
  a quotation there and stands apart from the word in front of it like any
  other word. */
function gapBehind(text) {
  return text && !/^[\s.,;:!?)\]}…«]/.test(text) ? ' ' : ''
}

/*
  A dictation begins: the mirror takes the field's text around the spot the
  words will go, with nothing settled yet. `from` and `to` are that spot —
  the selection, or the end of the field when it was not in hand.

  Returns the mirror and the range the words belong to: the field's text as
  it stood at that moment, and the spot it replaces. The range goes stale
  the moment the field's text changes under the dictation.
*/
export function startMirror(fieldText, from, to) {
  return {
    mirror: {
      davor: fieldText.slice(0, from),
      danach: fieldText.slice(to),
      fest: '',
      unsicher: '',
    },
    range: { basis: fieldText, von: from, bis: to },
  }
}

/* One more reading: the words it settled and the end it is still unsure
  about, both as the reading answered them. */
export function mirrorReading(mirror, settled, unsure) {
  return { ...mirror, fest: settled, unsicher: unsure }
}

/*
  The field's text can still change under a dictation: another chat opened
  and its draft moved in. The words then belong where they would have
  belonged before this mirror existed — at the end of what now stands
  there — and the mirror shows exactly that instead of the old chat's text
  over the new chat's field.

  Null while there is nothing to move: no mirror, no range, or the field
  still holding what it held.
*/
export function mirrorAfterFieldChange(mirror, range, fieldText) {
  if (!mirror || !range || fieldText === range.basis) return null
  return {
    mirror: { ...mirror, davor: fieldText, danach: '' },
    range: { basis: fieldText, von: fieldText.length, bis: fieldText.length },
  }
}

/*
  What the mirror lays over the field, ready to be shown: the field's own
  text, the settled words, the grey rest. The word gaps belong here and not
  in the markup.

  Written to be total: no mirror at all, a `null` mirror or one that has not
  been filled in shows empty text rather than the word "undefined" or "null"
  over the draft — `null` is what the field's own state holds whenever nobody
  dictates.
*/
export function mirrorParts(mirror) {
  const { davor, danach, fest, unsicher } = mirror ?? {}
  const before = davor ?? ''
  const settled = fest ?? ''
  const unsure = unsicher ?? ''
  const gapBefore = settled || unsure ? gapOf(before) : ''
  const gapBetween = settled && unsure ? ' ' : ''
  const after = danach ?? ''
  const gapAfter = settled || unsure ? gapBehind(after) : ''
  return {
    davor: before + gapBefore,
    fest: settled + gapBetween,
    unsicher: unsure,
    danach: gapAfter + after,
  }
}

/*
  Where the spoken words go, and where the cursor lands afterwards.

  The spot the dictation started at counts as long as the field still holds
  what it held then — it stood still while the words came in, so the spot
  the interim text was shown at is the spot the text belongs. Only when the
  field changed under it does the cursor decide, and the end of the field
  when it is not in hand at all.

  `range` is what `startMirror` handed back; `cursor` is `{ start, end }`
  read off the field. `spoken` comes as it should land — trimmed and not
  empty, which the caller has to know anyway.

  The cursor lands BEHIND what was inserted: dictating twice in a row should
  read as one thought, not as two texts fighting over one spot.
*/
export function placeWords(fieldText, options) {
  const { range = null, cursor = null, spoken = '' } = options ?? {}
  const [from, to] = spotOf(fieldText, range, cursor)
  const before = fieldText.slice(0, from)
  const after = fieldText.slice(to)
  const gap = spoken ? gapOf(before) : ''
  const gapAfter = spoken ? gapBehind(after) : ''
  const placed = before + gap + spoken
  return { text: placed + gapAfter + after, caret: placed.length }
}

/* The spot the words belong to as [from, to]; the end of the field when none
  is named. A spot counts only with both of its two positions, each a whole
  number or a number written as a string — `slice` took the latter happily,
  and a caller that read its positions back somewhere must not lose the spot
  over their spelling. Half a spot — or a bare number where an object
  belongs — would copy the whole field's text behind the words instead of
  replacing a piece of it. */
function spotOf(fieldText, range, cursor) {
  const spot = (value, first, second) => {
    const from = value ? position(value[first]) : null
    const to = value ? position(value[second]) : null
    return from === null || to === null ? null : [from, to]
  }
  const held = range && range.basis === fieldText ? spot(range, 'von', 'bis') : null
  return held ?? spot(cursor, 'start', 'end') ?? [fieldText.length, fieldText.length]
}

function position(value) {
  if (Number.isInteger(value)) return value
  return typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : null
}

/*
  How tall the field has to be: as tall as the taller of the two — its own
  text, or the mirror laid over it — and never taller than 40 percent of the
  window. Past that it scrolls instead of pushing the rest of the page
  away; scrolling only starts there, so before that there is no bar in the
  middle of the text. No mirror at all measures as nothing.

  Named arguments and not three numbers in a row: the heights of the field
  and of the window are both pixels, and swapping them would not fail —
  it would just measure the wrong thing.
*/
export function fieldSize({ fieldHeight, mirrorHeight = 0, windowHeight }) {
  const cap = Math.round(windowHeight * 0.4)
  const wanted = Math.max(fieldHeight, mirrorHeight)
  return {
    height: Math.min(wanted, cap) + 'px',
    overflowY: wanted > cap ? 'auto' : 'hidden',
  }
}
