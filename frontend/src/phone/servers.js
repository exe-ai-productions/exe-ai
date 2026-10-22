/*
  The servers of the machine, as the phone page lists them.

  Six of them hold a model or draw a picture: the model server, the agent
  server, the embedding server, the speech server with its clean-up beside
  it, and the picture server. Each reports itself in its own words; this
  turns a report into what a list row says — a dot, a state, the model and
  the port — so the list and the page of one server read the same thing.

  No imports on purpose: a report in, a row out, so a test can run it
  without a window around it.
*/

/* The servers in the order the list shows them: the model server first, the
   agent server right under it because it is the other one that holds a chat
   model, then embedding, speech with its clean-up, and pictures. `title` is
   the catalogue key of the name, `sign` the house sign. */
export const SERVERS = [
  { kind: 'model', title: 'modell.server', sign: 'server' },
  { kind: 'agent', title: 'agentserver.titel', sign: 'agent' },
  { kind: 'embedding', title: 'einbettungsserver.titel', sign: 'einbettung' },
  { kind: 'speech', title: 'sprachserver.titel', sign: 'sprache_welle' },
  { kind: 'cleanup', title: 'bereinigungsserver.titel', sign: 'besen' },
  { kind: 'image', title: 'bildserver.titel', sign: 'bild' },
]

/* The picture server's own four states and the colour each one wears. */
const IMAGE_DOT = { bereit: 'gruen', zeichnet: 'blau', fehler: 'rot' }
const IMAGE_WORD = {
  aus: 'studio.bildserver_aus',
  bereit: 'studio.bildserver_bereit',
  zeichnet: 'studio.bildserver_zeichnet',
  fehler: 'studio.bildserver_fehler',
}

/** What a list row says about one server, from the report it gave.

    `dot` is the colour of its dot, or `null` — only a server that runs (or
    failed) has one: six grey dots for six stopped servers say nothing the
    missing green does not. `word` is the catalogue key of the state's name
    and `running` whether it holds a model right now. `model` and `port` are
    what it holds and where, or `null`. A report that has not come yet is a
    server whose state is not known: no dot, no word. */
export function serverRow(kind, report) {
  if (!report) return { dot: null, word: null, running: false, model: null, port: null }
  if (kind === 'image') {
    const state = report.zustand ?? 'aus'
    return {
      dot: IMAGE_DOT[state] ?? null,
      word: IMAGE_WORD[state] ?? IMAGE_WORD.aus,
      running: state === 'bereit' || state === 'zeichnet',
      model: report.modell ?? null,
      port: null,
    }
  }
  const running = Boolean(report.laeuft)
  return {
    dot: running ? 'gruen' : null,
    word: running ? 'status.aktiv' : 'status.inaktiv',
    running,
    model: running ? (report.modell ?? null) : null,
    port: report.port ?? null,
  }
}

/** The files a server can start from, as the pick list wants them: the name,
    its size and a ready-made line. A report without a list has no files. */
export function modelOptions(report) {
  return (report?.modelle ?? []).map((file) => ({
    value: file.name,
    label: file.name,
    gb: file.groesse_gb ?? null,
  }))
}

/** The file a start would use: the one picked, else the one the report
    names, else the one remembered from the last start, else the first of the
    list — and `''` where there is none, never a guess at a name that is not
    in the folder. */
export function startModel(report, picked, remembered = null) {
  const names = (report?.modelle ?? []).map((file) => file.name)
  if (picked && names.includes(picked)) return picked
  if (report?.modell && names.includes(report.modell)) return report.modell
  if (remembered && names.includes(remembered)) return remembered
  return names[0] ?? ''
}

/** A whole number from what was typed, or `null` for nothing or nonsense —
    `null` is what the service takes as "the server's own". */
export function wholeNumber(text) {
  const value = String(text ?? '').trim()
  if (!/^\d+$/.test(value)) return null
  const number = Number(value)
  return Number.isSafeInteger(number) ? number : null
}

/** A size in gigabytes the way the lists say it, one decimal. */
export function gbLabel(gb) {
  return gb == null ? '' : `${(Math.round(gb * 10) / 10).toLocaleString('en-US', { minimumFractionDigits: 1 })} GB`
}

/** What a number field holds before anyone typed. A running server's own
    number is what it was started with; otherwise what was chosen before
    (`stored`, the store of a server that keeps a choice) comes ahead of what
    a start would use, because a start sends only what the hand changed
    against that choice. A server with no stored choice has its own report,
    then what the service says a start would use. */
export function seedValue(report, name, stored) {
  const own = report?.[name]
  if (report?.laeuft && own !== null && own !== undefined) return String(own)
  if (stored) {
    const chosen = stored[name]
    if (chosen !== null && chosen !== undefined) return String(chosen)
  } else if (own !== null && own !== undefined) {
    return String(own)
  }
  const fallback = report?.vorgaben?.[name] ?? (stored ? own : null)
  return fallback === null || fallback === undefined ? '' : String(fallback)
}
