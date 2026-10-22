/*
  The numbers and switches of the settings that are plain values: whether the
  memory travels, the picture protection, how many tool rounds one answer may
  run, how long one shell command may run, at what share of the context a chat
  is folded, and the two limits of the helpers. Each one is read from the
  service when asked and written back once the hand has come to rest.

  Called while a page is made, by the settings window of the desktop and by
  the settings page of the phone, so both show and change the same values.
*/

import { api } from './api.js'
import { t } from './texte.svelte.js'
import { melde } from './zustand.svelte.js'

export function useSettingsValues() {
  /* The switches that decide whether the memory travels. */
  let gedaechtnisSchalter = $state({ lokal: true, cloud: true })
  async function gedaechtnisStandLaden() {
    try {
      const stand = await api.einstellungAufgeloest('gedaechtnis')
      if (stand?.wert && typeof stand.wert === 'object') {
        gedaechtnisSchalter = { ...gedaechtnisSchalter, ...stand.wert }
      }
    } catch {
      /* Leaves the default standing: the memory travels. */
    }
  }
  async function gedaechtnisSchalten(seite, an) {
    const vorher = gedaechtnisSchalter
    gedaechtnisSchalter = { ...vorher, [seite]: an }
    try {
      await api.einstellungSetzen('global', 'gedaechtnis', gedaechtnisSchalter)
    } catch {
      gedaechtnisSchalter = vorher
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* The switch that strips a picture of everything but its pixels — uploaded
     and generated alike. Shipped on: a picture leaves no trail unless this is
     turned off on purpose. Stored as a set of one, like the memory switches,
     so "off" is a truthy value the settings route keeps rather than discards. */
  let bildschutzSchalter = $state({ an: true })
  async function bildschutzStandLaden() {
    try {
      const stand = await api.einstellungAufgeloest('bildmetadaten')
      if (stand?.wert && typeof stand.wert === 'object') {
        bildschutzSchalter = { ...bildschutzSchalter, ...stand.wert }
      }
    } catch {
      /* Leaves the default standing — it is the careful one. */
    }
  }
  async function bildschutzSchalten(an) {
    const vorher = bildschutzSchalter
    bildschutzSchalter = { an }
    try {
      await api.einstellungSetzen('global', 'bildmetadaten', bildschutzSchalter)
    } catch {
      bildschutzSchalter = vorher
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* Two settings that are plain numbers, and both of them have a state
     that is not a number: nothing set here, the shipped default applies.
     That used to be reached by emptying the field, which nothing on
     screen said and nothing on screen showed afterwards — an unset
     setting and one deliberately set to the default looked the same.

     So both are number fields with the house's own steppers, and their
     zero is a word rather than a count. Setting it clears the override;
     an unset setting comes back as that word instead of as a number
     somebody might think they chose.

     Writing goes out once the hand has come to rest. The steppers fire on
     every click and typing fires per digit, which against the service
     would be a request each. */
  const ZAHL_RUHE_MS = 400
  const zahlUhren = new Map()

  function zahlSpeichern(schluessel, wert, zuruecknehmen) {
    clearTimeout(zahlUhren.get(schluessel))
    zahlUhren.set(
      schluessel,
      setTimeout(async () => {
        try {
          await api.einstellungSetzen(
            'global', schluessel, wert >= 1 ? Math.floor(wert) : null,
          )
        } catch {
          zuruecknehmen()
          melde(t('fehler.allgemein'), 'fehler')
        }
      }, ZAHL_RUHE_MS),
    )
  }

  /* How many tool rounds one answer may run. A setting now, not a number
     baked into the code: a task across many files needs more than the old
     ten, where it was cut off after three. Shipped at 50; the field takes
     any whole number from one up, with no ceiling — a long run is meant by
     whoever types it.

     What that shipped number IS lives on the service (VORGABE,
     app/werkzeugrundenwahl.py) and in the sentence under the field. It is
     deliberately not repeated here as a constant: this window no longer
     falls back to it — the field shows the word instead — and a third copy
     would be a third place to forget. */
  /* Empty = nothing set, the shipped default applies — the field says
     "Auto" for it. The companion `…Stand` starts as `undefined` for "not
     loaded yet", because `null` is now a value the field itself can hold. */
  let werkzeugRunden = $state(null)
  let rundenStand = $state(undefined)
  async function werkzeugRundenLaden() {
    let wert = null
    try {
      const stand = await api.einstellungAufgeloest('werkzeug_runden')
      if (Number.isInteger(stand?.wert) && stand.wert >= 1) wert = stand.wert
    } catch {
      /* Leaves the field on "Auto". */
    }
    werkzeugRunden = wert
    rundenStand = wert
  }
  $effect(() => {
    const wert = werkzeugRunden
    if (rundenStand === undefined || wert === rundenStand) return
    const vorher = rundenStand
    rundenStand = wert
    zahlSpeichern('werkzeug_runden', wert, () => {
      werkzeugRunden = vorher
      rundenStand = vorher
    })
  })

  /* The helpers' two limits (app/helper.py): how many may run at the same
     time, and how many tool rounds one of them may take. They stand once,
     here beside the agents, and hold for every helper. Empty is the shipped
     value, and the field says "Auto" for it, as the fields above do; a
     count starts at 1, so a typed zero cannot stand there meaning Auto. One
     small field object per limit, so the load, the save and its rollback
     are written once for both. */
  function countSetting(key) {
    const field = $state({ value: null, stored: undefined })
    $effect(() => {
      const value = field.value
      if (field.stored === undefined || value === field.stored) return
      const before = field.stored
      field.stored = value
      zahlSpeichern(key, value, () => {
        field.value = before
        field.stored = before
      })
    })
    return field
  }
  const helpersAtOnce = countSetting('helpers_at_once')
  const helperSteps = countSetting('helper_steps')
  async function helperLimitsLoad() {
    let read = {}
    try {
      read = await api.einstellungAufgeloestViele(['helpers_at_once', 'helper_steps'])
    } catch {
      /* Leaves both fields on "Auto". */
    }
    for (const [field, key] of [[helpersAtOnce, 'helpers_at_once'], [helperSteps, 'helper_steps']]) {
      const value = read[key]?.wert
      field.value = Number.isInteger(value) && value >= 1 ? value : null
      field.stored = field.value
    }
  }

  /* How many seconds one shell command may run before it is stopped. The
     same story as the tool rounds right above: a number that used to be
     baked into the code (120), which a model download simply dies against.
     Shipped at 120 — whoever sets nothing keeps exactly the old behaviour.
     Any whole number from one up, no ceiling. The number itself lives on
     the service (VORGABE, app/befehlszeitwahl.py), for the same reason as
     above. */
  let befehlZeit = $state(null)
  let zeitStand = $state(undefined)
  async function befehlZeitLaden() {
    let wert = null
    try {
      const stand = await api.einstellungAufgeloest('befehl_zeitgrenze')
      if (Number.isInteger(stand?.wert) && stand.wert >= 1) wert = stand.wert
    } catch {
      /* Leaves the field on "Auto". */
    }
    befehlZeit = wert
    zeitStand = wert
  }
  $effect(() => {
    const wert = befehlZeit
    if (zeitStand === undefined || wert === zeitStand) return
    const vorher = zeitStand
    zeitStand = wert
    zahlSpeichern('befehl_zeitgrenze', wert, () => {
      befehlZeit = vorher
      zeitStand = vorher
    })
  })

  /* At what share of the context a chat folds its settled middle into one
     summary. The same story as the two above: a number that was baked into
     the code (50), and that has to be wrong for somebody — a chat of short
     questions can run most of the way full before a summary is worth the
     request it costs, one that reads large files wants the room long
     before. The band and the shipped value live on the service
     (app/verdichtungswahl.py), not here, so there is one place to change
     them. An empty field means "Auto", exactly like the fields above. */
  let verdichtungSchwelle = $state(null)
  let schwelleStand = $state(undefined)
  async function verdichtungSchwelleLaden() {
    let wert = null
    try {
      const stand = await api.einstellungAufgeloest('verdichtung_schwelle')
      if (Number.isInteger(stand?.wert) && stand.wert >= 1) wert = stand.wert
    } catch {
      /* Leaves the field on "Auto". */
    }
    verdichtungSchwelle = wert
    schwelleStand = wert
  }
  $effect(() => {
    const wert = verdichtungSchwelle
    if (schwelleStand === undefined || wert === schwelleStand) return
    const vorher = schwelleStand
    schwelleStand = wert
    zahlSpeichern('verdichtung_schwelle', wert, () => {
      verdichtungSchwelle = vorher
      schwelleStand = vorher
    })
  })

  function loadAll() {
    gedaechtnisStandLaden()
    bildschutzStandLaden()
    werkzeugRundenLaden()
    befehlZeitLaden()
    verdichtungSchwelleLaden()
    helperLimitsLoad()
  }

  return {
    loadAll,
    gedaechtnisStandLaden,
    gedaechtnisSchalten,
    bildschutzStandLaden,
    bildschutzSchalten,
    werkzeugRundenLaden,
    befehlZeitLaden,
    verdichtungSchwelleLaden,
    helperLimitsLoad,
    helpersAtOnce,
    helperSteps,
    get gedaechtnisSchalter() {
      return gedaechtnisSchalter
    },
    get bildschutzSchalter() {
      return bildschutzSchalter
    },
    get werkzeugRunden() {
      return werkzeugRunden
    },
    set werkzeugRunden(wert) {
      werkzeugRunden = wert
    },
    get befehlZeit() {
      return befehlZeit
    },
    set befehlZeit(wert) {
      befehlZeit = wert
    },
    get verdichtungSchwelle() {
      return verdichtungSchwelle
    },
    set verdichtungSchwelle(wert) {
      verdichtungSchwelle = wert
    },
  }
}
