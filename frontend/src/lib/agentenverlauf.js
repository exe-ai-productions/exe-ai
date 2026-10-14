/* The history of a running agent, cut into what stands in view and what
   stands behind a click.

   In view: the agent's sentences, and for each stretch between two
   sentences one row that names the tools it used. Behind that row: every
   line the run wrote — thinking, the half-written call, the context
   reading, the call and its result as the raw data.

   A step is `{ nummer, typ, inhalt }`. The types the run writes: `text` (a
   sentence of the agent), `reasoning`, `werkzeug` (one line per call that is
   still being written, rewritten as it grows), `tool_call` and `tool_result`
   (JSON), `kontext`, `status`, `ende`. */

function lesen(inhalt) {
  try {
    const wert = JSON.parse(inhalt)
    return wert && typeof wert === 'object' ? wert : null
  } catch {
    return null
  }
}

/* The entries of the history, in order: `{ art: 'satz', schluessel, text }`
   or `{ art: 'runde', schluessel, schritte, aufrufe, anzahl, laufend, zustand }`.
   `laeuft` says the run itself is still going; only then can the last
   stretch have a call that is running. */
export function verlaufBauen(schritte, laeuft) {
  const eintraege = []
  let runde = null
  const abschliessen = () => {
    if (runde) eintraege.push(runde)
    runde = null
  }
  for (const schritt of schritte) {
    /* A `text` step with nothing to read — empty, or only line breaks and
       spaces — is no sentence: the run writes one for any text piece, also
       a lone line break before a call. It draws no ring, and it does not
       end the stretch; it stays among that stretch's steps, behind the
       click. */
    if (schritt.typ === 'text' && String(schritt.inhalt ?? '').trim() !== '') {
      abschliessen()
      eintraege.push({ art: 'satz', schluessel: schritt.nummer, text: schritt.inhalt })
      continue
    }
    if (!runde) {
      runde = { art: 'runde', schluessel: schritt.nummer, schritte: [], aufrufe: [], geschrieben: 0, letzterName: '' }
    }
    runde.schritte.push(schritt)
    if (schritt.typ === 'tool_call') {
      runde.aufrufe.push({ name: lesen(schritt.inhalt)?.name ?? '?', ergebnis: null })
    } else if (schritt.typ === 'tool_result') {
      const daten = lesen(schritt.inhalt)
      const offen = runde.aufrufe.find((a) => a.ergebnis === null && a.name === daten?.name)
      if (offen) offen.ergebnis = { fehlgeschlagen: Boolean(daten?.fehlgeschlagen) }
    } else if (schritt.typ === 'werkzeug') {
      runde.geschrieben += 1
      runde.letzterName = String(schritt.inhalt).split(' ')[0]
    }
  }
  abschliessen()

  const letzte = eintraege.at(-1)
  for (const e of eintraege) {
    if (e.art !== 'runde') continue
    /* A call still being written has a line of its own before its
       `tool_call` exists, and a call that wrote one has both: the larger of
       the two counts is the number of calls. */
    e.anzahl = Math.max(e.aufrufe.length, e.geschrieben)
    const ohneErgebnis = e.aufrufe.filter((a) => a.ergebnis === null)
    const noch = laeuft && e === letzte
    e.laufend = noch
      ? ohneErgebnis.length
        ? ohneErgebnis.at(-1).name
        : e.geschrieben > e.aufrufe.length
          ? e.letzterName
          : ''
      : ''
    e.zustand = e.aufrufe.some((a) => a.ergebnis?.fehlgeschlagen)
      ? 'rot'
      : e.laufend
        ? 'blau'
        : e.anzahl
          ? 'gruen'
          : 'still'
  }
  return eintraege
}

/* A step's content for the raw view: JSON in its readable form, anything
   else as it stands. */
export function rohText(inhalt) {
  const wert = lesen(inhalt)
  return wert ? JSON.stringify(wert, null, 2) : String(inhalt ?? '')
}
