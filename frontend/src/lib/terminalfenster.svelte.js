/*
  The terminal module's state: which commands ran in this chat, and what
  they wrote while they ran.

  Its own module for the same reason the tools have one — the window draws,
  it does not decide. What it shows comes from one stream per chat
  (`/laeufe/{chat}/stream`), and that stream is deliberately NOT the answer
  stream: a background command outlives the answer that started it, and its
  lines have to keep arriving after the model has stopped talking.

  Two habits are worth naming, because both were decided against something:

    * The rail does not come forward by itself when a command starts: the
      list fills, and the sign of the terminal carries the colour of the
      state; whoever wants it clicks the sign. A panel that takes the column
      from the tool the reader chose is a panel people learn to hate.
    * The view sticks to the end while nobody scrolls. The moment somebody
      scrolls up, it stops following: reading beats watching.
*/

import { api } from './api.js'
import { chatOeffnen, zustand, nachrichtenAnzeige } from './zustand.svelte.js'
import { historie } from './werkzeughistorie.js'

export const terminal = $state({
  /* The runs of the open chat, oldest first. */
  laeufe: [],
  /* Follow the last line, or stay where the reader put us. */
  klebt: true,
  /* The highest run number of THIS chat that somebody has had in front of
     them — reset on every chat switch, because run numbers start again at 1
     in each. What ended above this line has not been looked at, and the dot
     may say so.

     The other three dots get this for free: their green and red mean
     "nobody has looked" already, so the colour IS the answer. A run's
     colour is only its state and stays green forever, so without a mark
     the dot would pulse for the rest of the session over one finished
     command. Memory only, like the marks on the two rail dots — after a
     restart there is no output to walk over to. */
  gesehen: 0,
  /* The same mark for calls that never became a run — refused before they
     started, or failed as a line. Named rather than counted: the key of
     the last such line when the panel was open. A count only ever rose,
     and after "regenerate" took a failed call away it stood above the
     truth and silenced the next one. */
  gesehenerAufruf: null,
})

/** The panel is open, so everything in it has been seen. */
export function terminalGesehen() {
  const hoechste = terminal.laeufe.reduce((h, l) => Math.max(h, l.lauf ?? 0), 0)
  if (hoechste > terminal.gesehen) terminal.gesehen = hoechste
  const aufrufe = historie(nachrichtenAnzeige(), terminal.laeufe).filter(
    (e) => e.art === 'aufruf',
  )
  terminal.gesehenerAufruf = aufrufe.length ? aufrufe[aufrufe.length - 1].schluessel : null
}

/** Is this run still worth a moving dot? Running, or ended above the mark. */
export function laufWach(eintrag) {
  if (!eintrag) return false
  if (eintrag.zustand === 'laeuft') return true
  return (eintrag.lauf ?? 0) > terminal.gesehen
}

function lauf(nummer) {
  return terminal.laeufe.find((l) => l.lauf === nummer) ?? null
}

/* The tool-log entry of the call that started run `nummer`, wherever the
   chat holds it: on the live placeholder (`werkzeuge`) or on a stored row
   (`stats.werkzeuge`). The report row's own entry carries the number too
   and is skipped by its kind — it is the model's copy, not the card. */
function aufrufkarte(nummer) {
  const sichtbar = nachrichtenAnzeige()
  for (let i = sichtbar.length - 1; i >= 0; i--) {
    const nachricht = sichtbar[i]
    if ((nachricht.art ?? 'nachricht') === 'werkzeugmeldung') continue
    const liste = nachricht.werkzeuge?.length
      ? nachricht.werkzeuge
      : (nachricht.stats?.werkzeuge ?? [])
    const treffer = liste.find((w) => w.lauf_nummer === nummer)
    if (treffer) return treffer
  }
  return null
}

/* ——— The stream ——— */

let quelle = null
let verbundenerChat = null
/* The highest event number already applied on the current connection. Kept
   outside `verbinden()` because it must survive a reconnect the browser does
   on its own — `EventSource` retries the very same URL, `ab` and all, so
   without this a resent stretch would be drawn a second time. */
let hoechsteNummer = -1

export async function verbinden(chatId) {
  if (chatId === verbundenerChat) return
  trennen()
  verbundenerChat = chatId ?? null
  terminal.laeufe = []
  /* The mark goes with the runs it was about. Run numbers start at 1 in
     every chat (`nummer=len(liste) + 1` per chat, app/tools/hintergrund.py),
     so a mark carried over from a chat with twelve commands would sit above
     everything the next chat can produce and quietly silence its dot. */
  terminal.gesehen = 0
  terminal.gesehenerAufruf = null
  if (!chatId) return

  /* What already ran comes through the ordinary route — the stream only
     carries what happens from now on. This is what makes a chat switch
     harmless: coming back fetches the chat's runs again, output included,
     instead of showing only what happens from the moment of reconnecting.

     The honest limit: those runs live in the service's memory, not in the
     database. They survive switching chats, closing the panel and reloading
     the window; they do not survive a restart of the service. A chat opened
     the next morning shows its tool calls (those are on the messages) but
     not the output of yesterday's commands. */
  let geladen, ab
  try {
    ;({ laeufe: geladen, ab } = await api.laeufe(chatId))
  } catch {
    geladen = []
    ab = 0
  }
  /* Whoever switches chats twice before the first fetch lands must not have
     the first call win: it would attach this chat's view to the other one's
     stream, and nothing afterwards notices — the guard on entry above only
     catches a repeated call for the SAME chat. */
  if (chatId !== verbundenerChat) return
  terminal.laeufe = geladen

  /* `ab` is the event count this fetch already covers — the stream resumes
     from there instead of repeating `lauf_start` for a run already in
     `terminal.laeufe` (which would draw it twice). */
  hoechsteNummer = ab - 1
  quelle = new EventSource(api.laeufeStrom(chatId, ab))
  quelle.onmessage = (nachricht) => {
    let ereignis
    try {
      ereignis = JSON.parse(nachricht.data)
    } catch {
      return
    }
    if (typeof ereignis.n === 'number') {
      if (ereignis.n <= hoechsteNummer) return
      hoechsteNummer = ereignis.n
    }
    aufnehmen(ereignis)
  }
  /* A dropped stream is not worth a red message: the browser reconnects by
     itself, resending everything from the original `ab` — the `n` check
     above throws away what is already on screen and keeps only what is new. */
  quelle.onerror = () => {}
}

/* Stop pressed on a run: the service asks the command to end and then
   insists (app/prozessstopp.py); its ending arrives on the stream like any
   other. Until then the button stays held, so a second click cannot send a
   second stop. A refused stop frees the button again and is the caller's
   to report. */
export async function stopRun(nummer) {
  const eintrag = lauf(nummer)
  if (!eintrag || !verbundenerChat) return
  eintrag.stopping = true
  let answer
  try {
    answer = await api.stopRun(verbundenerChat, nummer)
  } catch (error) {
    eintrag.stopping = false
    throw error
  }
  /* The service has waited its grace period and insisted. A run still
     going after that — one that had not quite started, or a child that
     slipped out of the group — gets its button back for another try. */
  if (answer?.zustand === 'laeuft') eintrag.stopping = false
}

export function trennen() {
  quelle?.close()
  quelle = null
  verbundenerChat = null
}

function aufnehmen(ereignis) {
  if (ereignis.typ === 'lauf_start') {
    terminal.laeufe = [
      ...terminal.laeufe,
      {
        lauf: ereignis.lauf,
        befehl: ereignis.befehl,
        hintergrund: Boolean(ereignis.hintergrund),
        // The folder the command runs in, shown under it.
        folder: ereignis.folder ?? null,
        /* What kind of work this was. Older entries and anything the server
           does not label are commands — that is what the list held before
           pictures joined it. */
        art: ereignis.art || 'befehl',
        zustand: 'laeuft',
        code: null,
        dauer_sekunden: null,
        ausgabe: '',
        /* The dials a picture was made with — arrives a moment later, its
           own event (below), because bildlauf.beginnen() only knows them
           once the run itself already exists. null for a command; still
           null for a picture until that event lands. */
        regler: null,
        /* Whether an answer has read this run's report yet (server event
           `lauf_gelesen`, and the snapshot's own field). The card of the
           call pulses until it is true. */
        gelesen: false,
      },
    ]
    /* Shipped switched on: a command that runs is a thing to watch — for
       whoever opens the list. The rail is left as it stands. */
    terminal.klebt = true
    return
  }
  const eintrag = lauf(ereignis.lauf)
  if (!eintrag) return
  if (ereignis.typ === 'lauf_regler') {
    eintrag.regler = ereignis.regler
    return
  }
  if (ereignis.typ === 'lauf_zeile') {
    eintrag.ausgabe = eintrag.ausgabe ? `${eintrag.ausgabe}\n${ereignis.text}` : ereignis.text
    return
  }
  if (ereignis.typ === 'lauf_gelesen') {
    eintrag.gelesen = true
    return
  }
  if (ereignis.typ === 'lauf_ende') {
    eintrag.zustand = ereignis.zustand
    eintrag.code = ereignis.code
    eintrag.dauer_sekunden = ereignis.dauer_sekunden ?? null
    /* The ending goes onto the card of the call that started the run —
       output, exit code, duration — the same fields the server writes into
       the stored log. Nothing is drawn under the answer for it: the report
       row the server adds is the model's, and the chat skips it. */
    if (ereignis.hintergrund) {
      const karte = aufrufkarte(ereignis.lauf)
      if (karte) {
        karte.exit_code = ereignis.code ?? null
        /* Failed is what the STATE says, the same word the stored entry
           carries: a run stopped by hand or at the time limit ends with
           no code at all, and "code is not zero" called both a failure. */
        karte.lauf_zustand = ereignis.zustand
        karte.fehlgeschlagen = ereignis.zustand === 'fehler'
        karte.dauer_sekunden = ereignis.dauer_sekunden ?? null
        karte.ergebnis = eintrag.ausgabe.trim() ? eintrag.ausgabe : ''
      }
    }
    /* A background run leaves a message behind. Fetch the chat again so it
       appears without anybody having to click. */
    if (ereignis.hintergrund && zustand.aktiverChat === verbundenerChat) {
      chatOeffnen(verbundenerChat)
    }
  }
}
