/* Tool calls that follow one another, bundled into one row of the answer.

   A single call stays a row of its own. Two or more in a row become one
   bundle that stands closed: the number of calls — or, while one is
   running, its name and "running" — and one dot that carries
   the worst state of them all.

   Thinking does not end a run: a model that thinks before every call would
   otherwise never show a bundle, only a ladder of single rows. Thinking
   before or between the calls goes into the bundle; thinking after the
   last call stays a row of its own, because it may be the stretch running
   right now, and its clock has to stay in view. Text and an agent's row end
   the run. */

/* A call that is drawn as a plain tool row; the start of an agent has a row
   of its own and is no part of a bundle. */
function istEinfacherAufruf(teil) {
  return teil.art === 'werkzeug' && !(teil.werkzeug?.name === 'start_job' && teil.werkzeug?.auftrag_id)
}

function istDenken(teil) {
  return teil.art === 'reasoning'
}

/* How many of a bundle's entries are calls; its thinking does not count. */
export function aufrufZahl(eintraege) {
  return eintraege.filter(({ teil }) => istEinfacherAufruf(teil)).length
}

/* The parts of an answer, as a list of entries: `{ art: 'teil', teil, i }`
   for a part drawn as before, `{ art: 'buendel', schluessel, eintraege }`
   for a run of calls and the thinking among them. `i` is the part's place in
   the answer; the bundle's key is a negative number, so it never meets the
   key of a part. */
export function buendeln(teile) {
  const aus = []
  let lauf = []
  const abschliessen = () => {
    let ende = lauf.length
    while (ende > 0 && !istEinfacherAufruf(lauf[ende - 1].teil)) ende -= 1
    const buendel = lauf.slice(0, ende)
    if (aufrufZahl(buendel) > 1) {
      aus.push({ art: 'buendel', schluessel: -1 - buendel[0].i, eintraege: buendel })
      for (const eintrag of lauf.slice(ende)) aus.push({ art: 'teil', ...eintrag })
    } else {
      for (const eintrag of lauf) aus.push({ art: 'teil', ...eintrag })
    }
    lauf = []
  }
  teile.forEach((teil, i) => {
    if (istEinfacherAufruf(teil) || istDenken(teil)) {
      lauf.push({ teil, i })
      return
    }
    abschliessen()
    aus.push({ art: 'teil', teil, i })
  })
  abschliessen()
  return aus
}

/* Red before yellow (waits for the reader) before blue (runs) before green. */
const RANG = { rot: 4, gelb: 3, blau: 2, gruen: 1, still: 0 }

/* The dot of a bundle: the worst of its calls' dots; the first of equals. */
export function schlechtesterPunkt(punkte) {
  let bester = punkte[0]
  for (const punkt of punkte) {
    if ((RANG[punkt.farbe] ?? 0) > (RANG[bester.farbe] ?? 0)) bester = punkt
  }
  return bester
}

/* What a bundle's closed row says about the newest call without a result:
   its name, and whether it goes. A call that waits for the reader (a
   permission, a question, a job to confirm — `waits` is asked with its id)
   has no result either, but nothing runs: the row names it and leaves
   "running" out, and the dot says the waiting. Where no call is open, a
   command that runs in the background is named instead and goes for as
   long as its run does (`inBackground` is asked with the call and says
   whether its run still goes); `background` tells the row which word to say.
   Null where nothing is open and nothing runs. */
export function openCall(eintraege, waits, inBackground = () => false) {
  const werkzeug = laufenderAufruf(eintraege)
  if (werkzeug) return { name: werkzeug.name, going: !waits(werkzeug.aufruf_id), background: false }
  const lauf = runningBackgroundCall(eintraege, inBackground)
  if (lauf) return { name: lauf.name, going: true, background: true }
  return null
}

/* The newest call whose background run still goes. */
function runningBackgroundCall(eintraege, inBackground) {
  for (let k = eintraege.length - 1; k >= 0; k -= 1) {
    const werkzeug = eintraege[k].teil.werkzeug
    if (werkzeug && inBackground(werkzeug)) return werkzeug
  }
  return null
}

/* The call that is running now — the newest one still without a result. */
export function laufenderAufruf(eintraege) {
  for (let k = eintraege.length - 1; k >= 0; k -= 1) {
    const werkzeug = eintraege[k].teil.werkzeug
    if (!werkzeug) continue
    if (werkzeug.ergebnis === null && !werkzeug.fehlgeschlagen) return werkzeug
  }
  return null
}
