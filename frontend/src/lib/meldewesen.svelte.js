/*
  What the program does when something happens — decided in one place.

  It used to be decided by whoever was reporting. `melde()` played the
  failure sound and nothing else ("only failures make a sound"), the four
  places that stop and wait rang the waiting bell themselves, and every
  caller picked its own kind and its own duration. That is a policy spread
  across six files, and none of it could be switched off by the person
  hearing it.

  So a caller no longer says what should happen. It says WHAT HAPPENED —

      melden({ was: 'fertig', von: 'agent', text, auftragId })

  — and this module turns that into a notice, a sound and a moving dot, or
  into none of the three, according to the settings.

  WHAT IT DOES NOT BUILD. All four displays already existed and are used as
  they are: the toasts, the sounds (`klingen()` in klaenge.svelte.js, three
  files), the dots on the rail (agentenampel/cronjobampel/laufampel) and the
  dot per chat row (chatringe.svelte.js). This module wires them; it does
  not replace them.

  WHY THE NOTICES THEMSELVES SIT HERE. `melde()` and its list stood in
  zustand.svelte.js, and leaving them there meant a cycle: this module
  needed `melde`, and that module needed to ask whether a notice may also
  be heard. Two rune modules importing each other resolve — but which of
  the two is evaluated first is then the bundler's business rather than
  anybody's decision, and a module whose `$state` runs second is a bad
  thing to have to reason about.

  So the list is here, character for character as it was, and
  zustand.svelte.js hands it on: the forty callers that import `melde`
  from there still import it from there. What moved is where the code
  sits, not who may call it — and the dependency runs one way.

  WHERE THE SETTINGS LIVE. In two keys, not one. The sounds already had
  `klaenge` with values stored in it — switch, volume, and now the three
  per-sound switches and "only in the background" — and moving those would
  have meant carrying old values over for nothing. What did not exist
  before is under `meldewesen` (app/meldewahl.py): how long a notice
  stands, and which of the four dots may pulse. The settings page reads
  both and shows them as one block.

*/

import { api } from './api.js'
import { klingen } from './klaenge.svelte.js'
import { teile } from './texte.svelte.js'

export const SCHLUESSEL = 'meldewesen'

/* What happened, in the four words the rest of the program reports in.
   `warnung` has no sound of its own — there are three sound files, and a
   caution is the one that asks to be read rather than heard. */
export const VORFAELLE = ['fertig', 'wartet', 'fehler', 'warnung']

/* Which of the three sounds an occurrence rings, and which kind of toast
   it wears. The toast kinds are the ones Meldungen.svelte already draws. */
const TON = { fertig: 'fertig', wartet: 'wartet', fehler: 'fehler', warnung: '' }
const SORTE = { fertig: 'erfolg', wartet: 'hinweis', fehler: 'fehler', warnung: 'warnung' }

/* The stored names, once — the interface says `agenten`, the stored object
   says `punkt_agenten` (app/meldewahl.py). */
const FELDER = {
  agenten: 'punkt_agenten',
  cronjob: 'punkt_cronjob',
  terminal: 'punkt_terminal',
  chat: 'punkt_chat',
}

/* The same for the three occurrences that can be switched off entirely. */
const MELDERFELDER = { fertig: 'melde_fertig', wartet: 'melde_wartet', fehler: 'melde_fehler' }

export const meldewesen = $state({
  /* Seconds a notice stands. 0 is the field's `nullwort` — "Auto" — and
     means: a notice about a job stands until that job has been looked at,
     and everything else keeps the house duration for its kind. */
  popupSekunden: 0,
  /* Which of the three is reported at all. Off means the WHOLE notice
     stays away — no text, no sound. One meaning, one switch: a switch
     called "Failed" that silenced a knock while its message still appeared
     would be two answers to one question. */
  melder: { fertig: true, wartet: true, fehler: true },
  /* Which dots may pulse. Shipped switched on, like everything else that
     can announce itself. */
  punkte: { agenten: true, cronjob: true, terminal: true, chat: true },
  /* The stored state has arrived. Before that nothing is written back, or
     an early change would go out on top of the defaults. */
  geladen: false,
})

/* ——— The notices ——— */

export const meldungen = $state({ liste: [] })

let naechsteMeldung = 0

/* One notification system for all cases (3.8).

   Errors stay up longer than confirmations: a confirmation was expected,
   an error has to be read first.

   Kinds: hinweis, erfolg, fehler, werkzeug.

   `dauerhaft` means: stays up until someone changes or closes it. The
   tool call needs that — it reports once at the start and again when
   the result is in. */
/* A caution stands longer than a passing remark and shorter than a
   failure: it asks to be read, not answered. */
const DAUER = { fehler: 7000, warnung: 5000, erfolg: 2400, werkzeug: 3000, hinweis: 3200 }

/* The house duration of the tool notice's LAST state — the green tick at the
   end of a call, while the notice-duration field stands on "Auto". Shorter
   than `erfolg` above on purpose, and not by changing that entry: `erfolg` is
   also every confirmation of something a hand just did (an agent saved, a
   skill stored), and those were not asked to move. This one is the closing
   line of a running commentary that nobody stops to read, so it says its
   piece and goes. Named here, next to the other durations, and read by
   `werkzeugFertigDauer` below. */
export const WERKZEUG_FERTIG_MS = 1500

/* How long the tick at the end of a tool call stands: the seconds the user
   set in the notice-duration field (`meldewesen.popup`), and the house 1.5 s
   while that field stands on "Auto".

   The tick is written past `melden()` — the one path that reads that field —
   so it asks for the field here rather than keeping a clock of its own. It
   is not the only notice that does not go through `melden()`; it is the one
   whose duration used to be writable nowhere. */
export function werkzeugFertigDauer() {
  return meldewesen.popupSekunden > 0
    ? meldewesen.popupSekunden * 1000
    : WERKZEUG_FERTIG_MS
}

/* How long the notice of a FAILED tool call stands — always, whatever the
   notice-duration field says. A failure is not a remark somebody chose the
   length of; it is the one line of the commentary that has to be read, and
   the field below it runs from "Auto" to a minute (app/meldewahl.py), which
   would make the line missable at the low end and lingering at the high
   one. Named here, next to the other durations, because the call site needs
   a number and this one is a decision. */
export const WERKZEUG_FEHLER_MS = 5000

const uhren = new Map()

/* Which sound a plain notice owns. Only failure has one: a hint that
   something worked is what the screen is for. */
const TON_ZUR_SORTE = { fehler: 'fehler' }

/* `werkzeug` carries the tool name (e.g. web_search) so the notification
   can show the same icon as the line in the chat — one icon, one
   language. */
export function melde(
  text, art = 'hinweis',
  {
    dauerhaft = false, werkzeug = '', dauer = 0, auftragId = '', stumm = false,
    /* Which agent this notice is about, when it is about one. The name is
       already IN the text — this says which part of it is the name, so the
       notice can write it in that agent's own colour instead of leaving
       eight notices from eight agents looking alike. */
    agent = '',
    /* Which catalogue entry this sentence came from, and what was put into
       it. Kept beside the finished text rather than instead of it: the
       notice needs the words to show, and the two of these to know which of
       those words were put in a moment ago. Empty for a sentence that never
       came from the catalogue at all — an error message from a server, say
       — and such a notice reads exactly as it always did. */
    schluessel = '',
    werte = null,
  } = {},
) {
  /* A failure is one of the three the settings switch, and it is one
     wherever it comes from — through `melden()` or straight from whoever
     could not save. The other kinds have no switch of their own: a
     confirmation of something the hand just did is not a report about
     something that happened elsewhere. */
  if (art === 'fehler' && !gemeldetWird('fehler')) return 0
  /* `stumm` is `melden()` saying it has already rung. Without it a failure
     would be judged twice — once as an occurrence and once as a toast kind
     — and two tables would have to agree forever. */
  if (!stumm && TON_ZUR_SORTE[art]) klingen(TON_ZUR_SORTE[art])
  const id = ++naechsteMeldung
  /* `auftragId` is what lets a notice about a run be closed when that run
     is looked at, rather than by a clock. Empty for everything that is
     about no run in particular. */
  meldungen.liste.push({ id, text, art, werkzeug, auftragId, agent, schluessel, werte })
  if (meldungen.liste.length > 3) schliesseMeldung(meldungen.liste[0].id)
  if (!dauerhaft) _uhrStellen(id, dauer || DAUER[art] || 3200)
  return id
}

/** Closes every notice standing for one run — what "read" means for a
 *  notice that was told to wait for its run instead of for a clock. */
export function meldungenZuAuftragSchliessen(auftragId) {
  if (!auftragId) return
  for (const meldung of meldungen.liste.filter((m) => m.auftragId === auftragId)) {
    schliesseMeldung(meldung.id)
  }
}

/* Rewrite a running notification instead of putting a second one next to it. */
export function aktualisiereMeldung(
  id, { text, art, dauerhaft = false, dauer = 0, schluessel, werte, werkzeug } = {},
) {
  const meldung = meldungen.liste.find((m) => m.id === id)
  /* Says whether it found one. A notice can be gone — three is the most
     that stand at once, and a fourth pushes the oldest out — and a caller
     that means to rewrite ITS notice has to be able to tell "changed" from
     "there was nothing left to change", or its notice silently stops
     appearing for the rest of the run. */
  if (!meldung) return false
  /* Off means the whole notice stays away, the same rule `melde()` applies
     to a brand-new one — applied here too, because a rewrite into a
     failure is a failure just the same. Closing it rather than leaving the
     running text standing: the switch says nothing about this call is
     reported, not that its last known state should linger. */
  if (art === 'fehler' && !gemeldetWird('fehler')) {
    schliesseMeldung(id)
    return true
  }
  if (text !== undefined) meldung.text = text
  if (art !== undefined) meldung.art = art
  /* Which tool's mark it shows. A notice that follows a whole answer moves
     from one tool to the next, and the mark has to move with it. */
  if (werkzeug !== undefined) meldung.werkzeug = werkzeug
  /* Rewritten together with the text, never left behind: a notice carrying
     the seams of the sentence it USED to hold would set the wrong words
     apart in the new one. Cleared when a rewrite names no key. */
  if (text !== undefined) {
    meldung.schluessel = schluessel ?? ''
    meldung.werte = werte ?? null
  }
  /* A clock already running has to be STOPPED, not merely left unset: a
     notice rewritten from a finished call back into a running one would
     otherwise close itself two seconds later, in the middle of the call it
     had just started reporting. */
  if (dauerhaft) {
    clearTimeout(uhren.get(id))
    uhren.delete(id)
  } else {
    /* `dauer` beats the kind's own, the same way it does in `melde` — one
       option, one meaning, so a caller that needs its own clock does not
       need a second way to ask for it. Zero means "the kind decides". */
    _uhrStellen(id, dauer || DAUER[meldung.art] || 3200)
  }
  return true
}

function _uhrStellen(id, dauer) {
  clearTimeout(uhren.get(id))
  uhren.set(id, setTimeout(() => schliesseMeldung(id), dauer))
}

export function schliesseMeldung(id) {
  clearTimeout(uhren.get(id))
  uhren.delete(id)
  const stelle = meldungen.liste.findIndex((m) => m.id === id)
  if (stelle !== -1) meldungen.liste.splice(stelle, 1)
}

/* ——— The one way in ——— */

/**
 * The one way in. `was` is what happened, `von` who it happened to, `text`
 * the sentence to show, `auftragId` the run it belongs to if there is one.
 *
 * Returns the notice's id, so a caller that wants to rewrite its own
 * notice later can — the same id `melde()` has always returned.
 */
export function melden({
  was = 'fertig', von = '', text = '', auftragId = '', agent = '',
} = {}) {
  /* Switched off means nothing happens at all — not a quieter version of
     it. This is the only place that asks, and it asks before anything is
     drawn or played. */
  if (!gemeldetWird(was)) return 0
  if (TON[was]) klingen(TON[was])
  if (!text) return 0
  return melde(text, SORTE[was] ?? 'hinweis', {
    /* The sound is already out; the notice must not ring a second time. */
    stumm: true,
    /* "Auto" with a job behind it means the notice waits for that job to
       be looked at — it is closed from the outside, by whoever marks the
       job seen (agentenampel.svelte.js). Without a job there is nothing to
       wait for, so the kind's own duration applies. */
    dauerhaft: meldewesen.popupSekunden === 0 && Boolean(auftragId),
    dauer: meldewesen.popupSekunden > 0 ? meldewesen.popupSekunden * 1000 : 0,
    auftragId,
    agent,
    werkzeug: von === 'werkzeug' ? text : '',
  })
}

/**
 * A notice built FROM THE CATALOGUE, so it knows its own seams.
 *
 * `melde(t('agenten.gesichert', { name }), 'erfolg')` hands over a finished
 * sentence, and with it the answer to "which of these words is the agent's
 * name" is gone — a display cannot work that out afterwards without
 * guessing, and a name can be a common word, a single digit, or a path that
 * repeats the sentence's own wording.
 *
 * This says the key and the values instead. The text is built the same way
 * it always was; what is new is that the notice can still take it apart.
 *
 *     meldeText('agenten.gesichert', { name }, 'erfolg')
 *
 * Everything else that reports keeps calling `melde()` and is unaffected.
 */
export function meldeText(pfad, werte, art = 'hinweis', optionen = {}) {
  const stuecke = teile(pfad, werte)
  /* The sentence is put together FROM the pieces rather than asked of `t()`
     a second time, so the two can never say different things. They can: `t()`
     substitutes value after value into the growing string, so a value that
     itself contains another key's brace gets walked into on the next pass —
     a path with `{name}` in it, say, next to a `name` of its own. The pieces
     never look at what was put in, which is the behaviour that belongs on
     screen; this makes it the only one. */
  const text = stuecke.map((stueck) => stueck.wert ?? stueck.fest).join('')
  return melde(text, art, { ...optionen, schluessel: pfad, werte })
}

/** Is this kind of occurrence reported at all? A `was` with no switch of
 *  its own — a caution — is always reported. */
export function gemeldetWird(was) {
  return meldewesen.melder[was] !== false
}

/** Is this dot allowed to move at all? Read where the dot is drawn, so a
 *  switch takes effect without anything having to be told about it. */
export function punktPulsiert(welcher) {
  return meldewesen.punkte[welcher] !== false
}

/* What does not move.
   
   Two of them are not a state at all: a grey disc holding a row's geometry,
   and a fact rather than a state. Neither has anything to say.
   
   Blue is the third, and it is the deliberate one. Blue means a run is
   going, which is the one state that needs no hand — and a run can go for
   an hour, so a mark that pulsed for it would pulse in the corner of the
   eye for an hour. What the eye is wanted for is the other three: green
   says the work is done, yellow that it is waiting on you, red that it
   broke. Those three move; the one that only says "busy" holds still. */
const RUHIG = ['still', 'leer', 'blau']

/**
 * Does this dot pulse right now?
 *
 * A dot moves while it has something that has not been dealt with — a run
 * going, a question standing, a report or a failure nobody has opened. For
 * three of the four the colour already carries that: their green and red
 * exist only while nobody has looked. The terminal's does not, so its
 * caller adds the missing half itself.
 *
 * Standing still under `prefers-reduced-motion` is not decided here.
 * Leuchtpunkt.svelte does that in CSS, which is the only place that can
 * see the setting at all — so a switch left on does the right thing on a
 * machine that asks for calm.
 */
export function punktAtmet(welcher, farbe) {
  if (!farbe || RUHIG.includes(farbe)) return false
  return punktPulsiert(welcher)
}

/* ——— The settings, stored in the cascade ——— */

export async function meldewesenLaden() {
  const stand = await api.einstellungAufgeloest(SCHLUESSEL).catch(() => null)
  const wert = stand?.wert
  if (wert && typeof wert === 'object') {
    if (typeof wert.popup_sekunden === 'number') meldewesen.popupSekunden = wert.popup_sekunden
    for (const [name, schluessel] of Object.entries(FELDER)) {
      if (typeof wert[schluessel] === 'boolean') meldewesen.punkte[name] = wert[schluessel]
    }
    for (const [name, schluessel] of Object.entries(MELDERFELDER)) {
      if (typeof wert[schluessel] === 'boolean') meldewesen.melder[name] = wert[schluessel]
    }
  }
  meldewesen.geladen = true
}

function sichern() {
  return api
    .einstellungSetzen('global', SCHLUESSEL, {
      popup_sekunden: meldewesen.popupSekunden,
      ...Object.fromEntries(
        Object.entries(FELDER).map(([name, schluessel]) => [schluessel, meldewesen.punkte[name]]),
      ),
      ...Object.fromEntries(
        Object.entries(MELDERFELDER).map(([n, k]) => [k, meldewesen.melder[n]]),
      ),
    })
    .catch(() => {})
}

export async function punktSchalten(welcher, an) {
  meldewesen.punkte[welcher] = an
  await sichern()
}

/** One of the three occurrences on its own — notice and sound together. */
export async function melderSchalten(was, an) {
  if (!(was in MELDERFELDER)) return
  meldewesen.melder[was] = an
  await sichern()
}

/* The number field fires on every chevron click and on every typed digit.
   Storing each one meant a request per keystroke, the same fight the
   volume slider had — so the state follows the hand and only the last
   value is written, once the hand has come to rest. */
const SPEICHER_RUHE_MS = 300
let speicherUhr = 0

export function popupSekundenSetzen(wert) {
  meldewesen.popupSekunden = Math.max(0, Math.min(60, Math.round(wert)))
  clearTimeout(speicherUhr)
  speicherUhr = setTimeout(sichern, SPEICHER_RUHE_MS)
}
