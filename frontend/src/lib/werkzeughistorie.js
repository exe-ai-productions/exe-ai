/*
  Everything this chat has had done for it, in one list.

  The terminal module started as a window on shell commands, and it kept
  that view long after the program had grown five file tools, a question
  tool, a memory and a whole shelf of MCP servers. A conversation spent
  reading and writing files reported "no command has run yet" — empty and
  wrong, because the module was looking into one drawer of a cupboard.

  So the list is built from both places a call can be:

    * the RUNS — commands with live output, which have their own stream and
      keep writing after the answer is over. They stay the big entries.
    * the calls recorded on the messages — every tool, whatever its source,
      built in or from a server. They become one quiet line each.

  A shell command is both by nature: a run AND a recorded call. It appears
  once, as its run — the big entry says everything the quiet line would and
  carries the output besides.

  The ORDER is taken from the messages, and the runs are threaded into it
  at the calls that started them. Sorting by a timestamp was not possible:
  a run knows its number, a call knows only its place in the conversation,
  and there is no clock both of them read.

  Its one import is a pure helper (paths.js), so this stays readable in one
  piece and runnable in a test without the interface standing up around it.
*/

import { displayPath } from './paths.js'

/* Tools whose story a run already tells. */
const ALS_LAUF = new Set(['run_command'])

/* How much of an argument stands in the line. Enough to recognise WHICH
   call it was, not enough to wrap: the line is a record, not a transcript. */
const ARGUMENT_LAENGE = 60

/* How much of an argument or result the line KEEPS, for when it is opened.

   The short text alone turned a refused download into what looked like a
   crash: the address was cut at sixty characters and the error was not
   there at all — not hidden, gone. So the full argument and the result
   travel with the line, and a click can show them.

   The lid is the same 20,000 characters the shell already cuts its output
   at — a `find /` must not sit whole in every line of the history. */
const VOLL_DECKEL = 20_000

function gedeckelt(text) {
  if (typeof text !== 'string' || text.length <= VOLL_DECKEL) return text
  return text.slice(0, VOLL_DECKEL) + '…'
}

/* The arguments that say what a call touches, in the order they are looked
   for. A file tool lists its text before its path (`content` comes first
   for a write), so the first text of the call would be the file's body.
   The first three name a place and are shown the way every path is. */
const PATH_KEYS = ['path', 'file_path', 'pfad']
const MAIN_KEYS = [...PATH_KEYS, 'command', 'query', 'url', 'name']

/* The one argument a call is about, as a line of text: the first of the
   keys above that carries something, otherwise the first argument that does.
   A path is shown with slashes. A tool whose arguments say nothing gets an
   empty string rather than an invented one. */
export function mainArgument(argumente) {
  if (!argumente || typeof argumente !== 'object') return ''
  for (const key of MAIN_KEYS) {
    const value = argumente[key]
    if (typeof value === 'string' && value.trim()) {
      return PATH_KEYS.includes(key) ? displayPath(value.trim()) : value.trim()
    }
  }
  for (const value of Object.values(argumente)) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  }
  return ''
}

/* One readable word for what a call was about: the main argument, cut to
   one short line. */
export function kurzargument(argumente) {
  const knapp = mainArgument(argumente).replace(/\s+/g, ' ')
  return knapp.length > ARGUMENT_LAENGE ? knapp.slice(0, ARGUMENT_LAENGE) + '…' : knapp
}

/* The calls one message recorded.

   While an answer streams, they hang on the message object itself; once it
   is stored they live in its stats. Both are read, the live one wins —
   during a run it is the more complete of the two. */
function aufrufeVon(nachricht) {
  return nachricht.werkzeuge?.length ? nachricht.werkzeuge : nachricht.stats?.werkzeuge || []
}

function alsZeile(aufruf, schluessel) {
  /* The full arguments, each value under the lid. Kept as an object so the
     opened line can show them field by field, the way the chat's own tool
     rows do (Nachricht.svelte). */
  let argumente = null
  if (aufruf.argumente && typeof aufruf.argumente === 'object') {
    argumente = {}
    for (const [schluessel, wert] of Object.entries(aufruf.argumente)) {
      argumente[schluessel] = typeof wert === 'string' ? gedeckelt(wert) : wert
    }
  }
  return {
    art: 'aufruf',
    /* Which call this is — the message's id and the call's place in it.
       Stable across rebuilds of this list (the objects are made afresh
       each time) and gone with its message, so the rail can remember the
       one call somebody looked at by name rather than by counting. */
    schluessel,
    /* The number of the run this call started, kept so that the chat's name
       for a shell call (`l` and the number, teile/Nachricht.svelte) still
       finds its line after the service was restarted and the run is gone. */
    lauf_nummer: aufruf.lauf_nummer ?? null,
    name: aufruf.name,
    server: aufruf.server || '',
    kurz: kurzargument(aufruf.argumente),
    argumente,
    /* Passed through, not normalised: null means "still running", a missing
       field means an old message that never stored one — the chat's tool
       rows read it the same way (Nachricht.svelte), and the opened line
       says the right sentence for each. */
    ergebnis:
      typeof aufruf.ergebnis === 'string' ? gedeckelt(aufruf.ergebnis) : aufruf.ergebnis,
    fehlgeschlagen: Boolean(aufruf.fehlgeschlagen),
    /* Same pass-through as ergebnis above: missing on an older call that was
       never timed, and that absence must stay visible rather than read as
       an invented zero. */
    dauer_sekunden: aufruf.dauer_sekunden,
  }
}

/* Runs and calls in the order they happened.

   The messages carry the order; the runs are handed out in theirs, one per
   shell call, as those calls come along. A run left over at the end —
   started from the CLI module, or belonging to a message that is no longer
   loaded — is appended rather than dropped: it happened, so it is shown.

   A shell call with no run left to claim falls back to a quiet line. That
   is the honest picture of a service that was restarted: the call is in
   the conversation, its output is not in memory anymore. */
export function historie(nachrichten, laeufe) {
  const alle = [...(laeufe || [])]
  /* Only command runs are handed to a shell call. A drawing job has no tool
     call behind it at all — it comes from the picture window — so letting a
     shell call claim one would file the picture under a command that never
     drew it, and leave the command that really ran without its output. */
  const offen = alle.filter((lauf) => (lauf.art || 'befehl') === 'befehl')
  const vergeben = new Set()
  const eintraege = []
  /* Chat-wide, not per row: a refused call sits in an EARLIER row than the
     call that really ran, and a row-by-row reading let it take the run
     from a row it never belonged to. Runs live in memory only, so every
     run on the list belongs to a call made since the service started —
     and those all carry numbers. */
  const nummeriert = (nachrichten || []).some((n) =>
    aufrufeVon(n).some((a) => ALS_LAUF.has(a.name) && a.lauf_nummer != null),
  )
  for (const [nummer, nachricht] of (nachrichten || []).entries()) {
    /* A finished background run's report row carries the call a second
       time — for the model, which reads it there. The run itself is in the
       list already, claimed by the call that started it; listing the
       report's copy as well showed the command twice. */
    if ((nachricht.art ?? 'nachricht') === 'werkzeugmeldung') continue
    /* A divider between two messages' calls — but only once this message
       actually has one, and only if something already stands above it. A
       message with no calls of its own must not leave an empty gap. */
    let grenzeGesetzt = false
    /* Where the chat's shell calls carry run numbers, call and run are
       paired by NUMBER, and a shell call without one never ran — refused
       before it started, for want of a shared folder — and gets a bare
       line. By position, that refused call took the next real run's
       output, the real call fell to a line under it, and the rail read the
       wrong state off the end. Chats from before the numbers keep the
       positional pairing. */
    for (const [stelle, aufruf] of aufrufeVon(nachricht).entries()) {
      /* A message without an id (none should reach here, but a stream
         start without one would make one) falls back to its place in the
         list, so two such messages cannot share a key. */
      const schluessel = `${nachricht.id ?? `o${nummer}`}#${stelle}`
      if (!grenzeGesetzt) {
        if (eintraege.length) eintraege.push({ art: 'trennung' })
        grenzeGesetzt = true
      }
      if (!ALS_LAUF.has(aufruf.name)) {
        eintraege.push(alsZeile(aufruf, schluessel))
        continue
      }
      let lauf = null
      if (nummeriert) {
        lauf = aufruf.lauf_nummer == null
          ? null
          : offen.find((l) => l.lauf === aufruf.lauf_nummer) ?? null
        if (lauf) offen.splice(offen.indexOf(lauf), 1)
      } else {
        lauf = offen.shift() ?? null
      }
      if (lauf) vergeben.add(lauf)
      eintraege.push(lauf ? { art: 'lauf', lauf } : alsZeile(aufruf, schluessel))
    }
  }
  /* Everything nobody claimed, in the order it happened: runs started from
     the CLI module, drawing jobs, and runs whose message is no longer
     loaded. Walked over the original list rather than the filtered one, so
     the order between the two kinds is the order they really came in. */
  for (const lauf of alle) {
    if (!vergeben.has(lauf)) eintraege.push({ art: 'lauf', lauf })
  }
  return eintraege
}

/* Is there anything at all to show?

   Asked before the empty notice: "no command has run yet" is only true
   when nothing of either kind is there. That sentence over a chat full of
   file work was the whole reason for this module. */
export function leer(nachrichten, laeufe) {
  return historie(nachrichten, laeufe).length === 0
}
