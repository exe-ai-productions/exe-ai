/* Thinking and tool calls between two pieces of text, drawn as one block.

   Everything an answer does between two stretches of visible text — its
   thinking and its calls — stands in one entry on the line: a head with the
   time it thought and the number of tools, one dot, and a window that opens
   on the calls. Visible text and an agent's row end the block; a blank piece
   of text or of thinking neither starts nor ends one. A running answer and
   a stored one go through the same function, so they draw the same blocks. */

/* A call that is drawn as a plain tool row; the start of an agent has a row
   of its own and is no part of a block. */
function istEinfacherAufruf(teil) {
  return teil.art === 'werkzeug' && !(teil.werkzeug?.name === 'start_job' && teil.werkzeug?.auftrag_id)
}

function istDenken(teil) {
  return teil.art === 'reasoning'
}

/* Text that draws nothing: it does not end a block. */
function isEmptyText(teil) {
  return teil.art === 'content' && !String(teil.text ?? '').trim()
}

/* How many of a block's entries are calls; its thinking does not count. */
export function aufrufZahl(eintraege) {
  return eintraege.filter(({ teil }) => istEinfacherAufruf(teil)).length
}

/* The parts of an answer, as a list of entries: `{ art: 'teil', teil, i }`
   for a part drawn on its own (text, an agent's row), `{ art: 'buendel',
   schluessel, eintraege }` for a block. `i` is the part's place in the
   answer; the block's key is a negative number, so it never meets the key
   of a part. */
export function buendeln(teile) {
  const aus = []
  let lauf = []
  const abschliessen = () => {
    if (lauf.length) {
      aus.push({ art: 'buendel', schluessel: -1 - lauf[0].i, eintraege: lauf })
    }
    lauf = []
  }
  teile.forEach((teil, i) => {
    if (istEinfacherAufruf(teil) || istDenken(teil)) {
      lauf.push({ teil, i })
      return
    }
    if (isEmptyText(teil)) return
    abschliessen()
    aus.push({ art: 'teil', teil, i })
  })
  abschliessen()
  return aus
}

/* The call a block's dot follows: the last one. */
export function lastCall(eintraege) {
  for (let k = eintraege.length - 1; k >= 0; k -= 1) {
    if (istEinfacherAufruf(eintraege[k].teil)) return eintraege[k].teil.werkzeug
  }
  return null
}

/* The block's dot, the way the terminal reads its last line: while the block
   goes it is blue, yellow where the last call waits for the reader; once it
   is over it is green or red after how the LAST call ended — a call that
   failed in the middle colours nothing. A block of thinking alone is blue.
   `dotOf` is asked for a call's own dot (`{ farbe, atmet }`); `atmet` is
   whether a dot that goes may breathe. */
export function blockDot(eintraege, running, dotOf, atmet = false) {
  const last = lastCall(eintraege)
  const stand = last ? dotOf(last) : null
  if (running) return stand?.farbe === 'gelb' ? stand : { farbe: 'blau', atmet }
  return stand ? { farbe: stand.farbe, atmet: false } : { farbe: 'blau', atmet: false }
}
