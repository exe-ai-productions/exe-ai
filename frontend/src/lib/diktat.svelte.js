/*
  What stands between the microphone and the input field — read from the
  service, written back to it.

  Twenty-seven answers: which language is spoken, the instruction the speech
  model gets, who tidies the dictation afterwards, which file that tidy-up
  model runs from, the instruction IT gets, whether a conversation reads its
  answers aloud, which voice does the reading, its voice sample, its
  language, its five generation values and its layers and threads, the
  instruction only a live conversation's message gets, whether a finished
  dictation is sent at once, which key works like a click on the microphone
  button, and the clean-up server's own seven — context, layers, threads and
  its five generation values. All of them live in one setting on the service
  (app/diktatsprachewahl.py), because the service is what uses them: the
  instruction goes into every request, and a copy kept in the browser would
  be read by nobody.

  The works texts are not repeated here. The panel gets them from the speech
  server's own answer (`diktat_vorgaben`), so its "restore" button puts back
  exactly what the service would use — a second copy in this file would agree
  with the first one only until somebody changed one of them.
*/

import { api } from './api.js'

const SCHLUESSEL = 'diktat'

/* Every number this setting carries. Stored one by one and absent until a
   hand sets them — each is read with `??` on the works answer, never `||`,
   because zero is a real value for every one of them. The clean-up
   server's five are works values its start always carries (a cleaner
   should write the same way everywhere); clearing one on purpose removes
   it from the start. */
const ZAHLFELDER = [
  'stimmtemperatur',
  'stimmtop_k', 'stimmtop_p', 'stimmmin_p', 'stimmstrafe',
  'stimmschichten', 'stimmfaeden',
  'putzkontext', 'putzschichten', 'putzfaeden',
  'putztemperatur', 'putztop_k', 'putztop_p', 'putzmin_p', 'putzstrafe',
]

export const diktat = $state({
  sprache: 'auto',
  anweisung: '',
  /* Empty, not 'aus'. These are placeholders for "nothing stored yet", and
     the panel reads them as `diktat.x || werk.x` — so a placeholder with a
     value in it is truthy and answers in place of the works answer the
     service actually goes by. With 'aus' here the panel said "off" while the
     service, whose own default is the tidy-up model, rewrote every dictation.
     A placeholder has to be falsy or it is not a placeholder. */
  bereinigung: '',
  putzmodell: '',
  bereinigung_anweisung: '',
  /* `null`, not `false`: a switch has no falsy placeholder of its own the
     way an empty string is for a text field — `false` IS a real, explicit
     "off". Read with `??`, never `||`, or a stored "off" would be
     overridden back to the works "on" the moment this reloads. */
  vorlesen: null,
  stimme: '',
  stimmprobe: '',
  stimmsprache: '',
  /* `null` for the same reason as `vorlesen`, and for the numbers below:
     zero is a real value, so the placeholder for "nobody set this" cannot
     be one. */
  stimmtemperatur: null,
  stimmtop_k: null,
  stimmtop_p: null,
  stimmmin_p: null,
  stimmstrafe: null,
  stimmschichten: null,
  stimmfaeden: null,
  putzkontext: null,
  putzschichten: null,
  putzfaeden: null,
  putztemperatur: null,
  putztop_k: null,
  putztop_p: null,
  putzmin_p: null,
  putzstrafe: null,
  gespraechsanweisung: '',
  /* `null` for the same reason as `vorlesen`: `false` is a real "off". */
  automatik: null,
  /* Empty until read: the key field and the listener then fall back to
     `DEFAULT_KEY` (lib/microphoneKey.js), which a test holds equal to the
     service's works key. */
  microphone_key: '',
  /* Nothing may be written before this is true, or a first pass would store
     its own placeholders over what was there. */
  geladen: false,
})

/* One write at a time. Several fields on one panel write themselves as they
   are changed, and two in flight would land in whichever order the network
   felt like. */
let schlange = Promise.resolve()

function nacheinander(arbeit) {
  const naechste = schlange.then(arbeit, arbeit)
  schlange = naechste.then(
    () => {},
    () => {},
  )
  return naechste
}

function alsObjekt() {
  const objekt = {
    sprache: diktat.sprache,
    anweisung: diktat.anweisung,
    bereinigung: diktat.bereinigung,
    putzmodell: diktat.putzmodell,
    bereinigung_anweisung: diktat.bereinigung_anweisung,
    vorlesen: diktat.vorlesen,
    stimme: diktat.stimme,
    stimmprobe: diktat.stimmprobe,
    stimmsprache: diktat.stimmsprache,
    gespraechsanweisung: diktat.gespraechsanweisung,
    automatik: diktat.automatik,
    microphone_key: diktat.microphone_key,
  }
  for (const name of ZAHLFELDER) objekt[name] = diktat[name]
  return objekt
}

let laden = null

export function standLaden(erneut = false) {
  if (diktat.geladen && !erneut) return Promise.resolve()
  if (erneut) return nacheinander(einlesen)
  if (!laden) laden = nacheinander(einlesen).finally(() => (laden = null))
  return laden
}

async function einlesen() {
  let stand = null
  try {
    stand = await api.einstellungAufgeloest(SCHLUESSEL)
  } catch {
    /* Nothing readable: the panel shows what it has and says nothing it
       cannot back up. */
    diktat.geladen = true
    return
  }
  const w = stand?.wert && typeof stand.wert === 'object' ? stand.wert : {}
  /* Only what was actually stored comes back here. A field nobody has
     touched is simply absent, and the panel fills it in from the works
     answers the speech server sends with its own status. */
  for (const name of [
    'sprache', 'anweisung', 'bereinigung', 'putzmodell', 'bereinigung_anweisung',
    'stimme', 'stimmprobe', 'stimmsprache', 'gespraechsanweisung', 'microphone_key',
  ]) {
    if (typeof w[name] === 'string') diktat[name] = w[name]
  }
  if (typeof w.vorlesen === 'boolean') diktat.vorlesen = w.vorlesen
  if (typeof w.automatik === 'boolean') diktat.automatik = w.automatik
  for (const name of ZAHLFELDER) {
    if (typeof w[name] === 'number') diktat[name] = w[name]
  }
  diktat.geladen = true
}

/** Stores what changed — and only what changed. Sending the whole object
    would send this window's copy of the fields it did NOT touch, and that
    copy is as old as the moment the panel opened. */
export function werteSetzen(werte) {
  return nacheinander(async () => {
    if (!diktat.geladen) await einlesen()
    const vorher = alsObjekt()
    Object.assign(diktat, werte)
    try {
      await api.einstellungMischen('global', SCHLUESSEL, werte)
    } catch {
      Object.assign(diktat, vorher)
      throw new Error('einstellung')
    }
  })
}
