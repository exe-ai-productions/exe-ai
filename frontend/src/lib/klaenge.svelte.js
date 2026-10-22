/*
  The four sounds: answer done, the program is waiting, something failed,
  and an agent's or a cronjob's run that ended well.

  Soft tones the program makes itself (static/klaenge/HERKUNFT.md). They
  live in static/klaenge/ and not under static/app/, which is emptied on
  every frontend build.

  Four rules, and each of them is the whole reason this module exists:

    * **Only when the window is in the background** — unless that is
      switched off. Whoever is looking at the screen has usually seen it
      already, so a sound for something visible is noise, and noise is what
      makes people switch sounds off. It was wired in until it became the
      setting it is now, shipped the way it always behaved.
    * **Shipped switched on.** A sound nobody finds is a sound nobody has —
      the switch, the volume and the background rule live in the settings.
    * **Never twice at once.** A running sound is stopped before the next
      one starts, so a burst of errors is one knock, not a rattle.
    * **Each sound has its own switch.** A sound is played when the main
      switch is on, the volume is above zero and the switch of that sound is
      on. The service asks the same three for the sound of a schedule's
      notification (app/cronmeldung.py).

  The preview button in the settings is the one exception to the first
  rule: pressing it means asking to hear it now.

  WHO CALLS THIS. Only frontend/src/lib/meldewesen.svelte.js. Deciding that
  something is worth hearing is that module's job now, not the job of
  whoever happened to notice the thing — this file only knows how to play.

  Whether the NOTICE of an occurrence is drawn is not asked here: that is
  the popup switch of the same occurrence (meldewesen.svelte.js). The two
  switches of one row are two questions — may it be heard, may it be seen.
*/

import { api } from './api.js'

const ORT = '/klaenge/'

/* The file name of the bundle this module came in: it carries a checksum, so
   it changes with every build. Put behind a sound's address it makes an
   address that no earlier version has been stored under — a browser that
   kept the old sound under the same file name, from before the service
   told it to check back, asks for the new one. */
const BUILD = new URL(import.meta.url).pathname.split('/').pop()
export const KLAENGE = ['fertig', 'wartet', 'fehler', 'agent_cronjob']

/* The file of each sound, named where the underscore of the occurrence
   would not be wanted in a file name. */
const FILES = {
  fertig: 'fertig',
  wartet: 'wartet',
  fehler: 'fehler',
  agent_cronjob: 'agent-cronjob',
}

/* The stored names of the four switches (app/klangwahl.py). */
const SOUND_FIELDS = {
  fertig: 'ton_fertig',
  wartet: 'ton_wartet',
  fehler: 'ton_fehler',
  agent_cronjob: 'ton_agent_cronjob',
}

/* One key in the settings cascade, checked on the service side by
   app/klangwahl.py. Both values live in one object on purpose: the route
   reads a falsy value as "nothing set", so a bare `false` could never
   switch the sounds off and a volume of 0 would spring back. */
export const SCHLUESSEL = 'klaenge'

export const klangwahl = $state({
  aus: false,
  /* 0 to 100 — the value the slider carries. */
  pegel: 70,
  /* Was the standing rule above, now a switch: with it off, a sound is
     played whatever the window is doing. */
  nurHintergrund: true,
  /* Which of the four sounds may be played at all. */
  ton: { fertig: true, wartet: true, fehler: true, agent_cronjob: true },
  /* The stored state has arrived; before that the slider must not adopt
     anything, or it would jump once while being dragged. */
  geladen: false,
})

const gepuffert = new Map()
let laufend = null

function datei(name) {
  if (!gepuffert.has(name)) {
    const ton = new Audio(`${ORT}${FILES[name]}.wav?v=${BUILD}`)
    ton.preload = 'auto'
    gepuffert.set(name, ton)
  }
  return gepuffert.get(name)
}

/* The window is "away" when it has no focus or is not visible at all —
   another program in front, another tab, a minimised window. */
function imVordergrund() {
  return document.hasFocus() && document.visibilityState === 'visible'
}

function abspielen(name) {
  const ton = datei(name)
  if (laufend && laufend !== ton) {
    laufend.pause()
    laufend.currentTime = 0
  }
  ton.volume = Math.min(1, Math.max(0, klangwahl.pegel / 100))
  ton.currentTime = 0
  laufend = ton
  /* A browser that refuses to play (no user gesture yet) is not an error
     worth a red message — the sound is a courtesy, not a result. */
  return ton.play().catch(() => {})
}

/** The ordinary way in: plays only if this sound is wanted, and — unless
 *  that was switched off — only while the window is in the background. */
export function klingen(name) {
  if (klangwahl.aus || !KLAENGE.includes(name)) return
  /* Volume zero is silence, however the switches stand — the service
     reads it the same way. */
  if (klangwahl.pegel <= 0 || klangwahl.ton[name] === false) return
  if (klangwahl.nurHintergrund && imVordergrund()) return
  abspielen(name)
}

/** The preview button: plays no matter where the window is. */
export function probehoeren(name) {
  if (!KLAENGE.includes(name)) return
  abspielen(name)
}

/* ——— The switch and the volume, stored in the settings cascade ——— */

export async function klangwahlLaden() {
  const stand = await api.einstellungAufgeloest(SCHLUESSEL).catch(() => null)
  const wert = stand?.wert
  if (!wert || typeof wert !== 'object') return
  if (typeof wert.an === 'boolean') klangwahl.aus = !wert.an
  if (typeof wert.pegel === 'number') klangwahl.pegel = wert.pegel
  if (typeof wert.nur_hintergrund === 'boolean') klangwahl.nurHintergrund = wert.nur_hintergrund
  for (const [name, schluessel] of Object.entries(SOUND_FIELDS)) {
    if (typeof wert[schluessel] === 'boolean') klangwahl.ton[name] = wert[schluessel]
  }
  klangwahl.geladen = true
}

function sichern() {
  return api
    .einstellungSetzen('global', SCHLUESSEL, {
      an: !klangwahl.aus,
      pegel: klangwahl.pegel,
      nur_hintergrund: klangwahl.nurHintergrund,
      ...Object.fromEntries(
        Object.entries(SOUND_FIELDS).map(([name, schluessel]) => [schluessel, klangwahl.ton[name]]),
      ),
    })
    .catch(() => {})
}

export async function klaengeSchalten(an) {
  klangwahl.aus = !an
  await sichern()
}

/** The sound of one occurrence on its own. */
export async function setSound(name, an) {
  if (!(name in SOUND_FIELDS)) return
  klangwahl.ton[name] = an
  await sichern()
}

export async function nurHintergrundSchalten(an) {
  klangwahl.nurHintergrund = an
  await sichern()
}

/* Dragging fires an event per pixel. Storing each one meant a dozen
   requests in flight at once, and whichever answered last wrote its value
   back into the slider — the knob jumped around under the finger.

   So: the state follows the hand immediately, and only the last position
   is stored, once the hand has come to rest. A failed write is not undone
   either; snapping the knob back mid-drag is exactly the jump this fixes. */
const SPEICHER_RUHE_MS = 300
let speicherUhr = 0

export function pegelSetzen(wert) {
  klangwahl.pegel = Math.min(100, Math.max(0, Math.round(wert)))
  clearTimeout(speicherUhr)
  speicherUhr = setTimeout(sichern, SPEICHER_RUHE_MS)
}
