<script>
  import Klappwahl from './Klappwahl.svelte'
  /* The settings page — one page, grouped like a real settings app.

     The left column holds named groups of rows on the page ground:
     General, Assistant behaviour, Prompts & agents, Connections & keys,
     Files, and Help set apart at the foot. Every entry carries a drawn sign and a subtitle that says its
     current state — "2 connected · 28 tools", "On · stays with local
     models" — so the standing of a thing shows without clicking into it.
     The right column is the open section: appearance tiles, the prompt and
     agent editors, the memory switches, the connections gallery, the tools,
     the file editors. The Hugging Face token lives in the catalogue.

     It is ONE page (shown by zustand.promptOffen, routed by
     zustand.promptStart) in the frame every menu page stands in
     (Seitenrahmen, Menueseite); a section is a value of `art` plus a nav
     entry and a right-side branch.

     A broken file still gets saved — it is the user's file — but the page
     says so at once, in the red line under the field. Secrets never reach
     the interface: the editor shows only ${…} placeholders, a status dot
     says set or missing. */
  import { fade } from 'svelte/transition'
  import { tick, untrack } from 'svelte'
  import Seitenrahmen from './Seitenrahmen.svelte'
  import Menueseite from './Menueseite.svelte'
  import Updatezeile from './Updatezeile.svelte'
  import Werkzeuge from './Werkzeuge.svelte'
  import { handbuchOeffnen } from '../lib/handbuch.js'
  import { werkzeugeLaden, aktivStand } from '../lib/werkzeuge.svelte.js'
  import WachsendesFeld from './WachsendesFeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Menuezeile from './Menuezeile.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import SettingsCronjobs from './SettingsCronjobs.svelte'
  import SettingsAgents from './SettingsAgents.svelte'
  import Agentenmaske from './Agentenmaske.svelte'
  import Skriptordner from './Skriptordner.svelte'
  import Skillmaske from './Skillmaske.svelte'
  import Standpille from './Standpille.svelte'
  import Verbindungen from './Verbindungen.svelte'
  import Meldewahl from './Meldewahl.svelte'
  import Shortcuts from './Shortcuts.svelte'
  import { diktat, standLaden as diktatStandLaden } from '../lib/diktat.svelte.js'
  import { DEFAULT_KEY, showCombo } from '../lib/microphoneKey.js'
  import { layout } from '../lib/keyboardLayout.svelte.js'
  import { keyNames } from '../lib/keyNames.js'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import { klangwahl } from '../lib/klaenge.svelte.js'
  import Schalter from './Schalter.svelte'
  import { api } from '../lib/api.js'
  import { zustand, aktuellerChat, chatAendern, codefarbenSetzen, blasenfarbeSetzen, verlaufSetzen, lookFuer, vorgabenFuer, winkelVorgabeFuer, tonVorgabeFuer, EIGENER_VERLAUF, melde, frage, modelleLaden, seitenSchliessen, layoutModusOeffnen } from '../lib/zustand.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'

  function blasenStandard() {
    // The picker's "current default" swatch must match what an untouched
    // bubble actually shows — a theme may ship its own default (Dark Matter's
    // lavender), so prefer that over the plain house bubble.
    const stil = getComputedStyle(document.documentElement)
    const wert = (
      stil.getPropertyValue('--blase-eigen-standard').trim() ||
      stil.getPropertyValue('--blase').trim()
    )
    return /^#[0-9a-fA-F]{6}$/.test(wert) ? wert : '#232320'
  }
  import {
    t, texte, spracheWaehlen, spracheZuruecksetzen,
  } from '../lib/texte.svelte.js'
  import { begruessung, anredeSpeichern } from '../lib/begruessung.svelte.js'

  let { offen = $bindable(false), modus = $bindable('dunkel') } = $props()

  let art = $state('system') // sprache|darstellung|system|memory|skills|cronjobs|agent|tools|werkzeuge|tools_datei|konfiguration|zugangsdaten
  let agentName = $state('')
  /* The agent mask standing on the agents page: null, or { agent } with the
     agent's front matter (null for a new one). Agents are created and
     changed only here, with the mask; there is no raw text for them. */
  let maske = $state(null)
  /* Whether the standing mask holds anything not yet saved. */
  let maskeGeaendert = $state(false)
  let dateien = $state([]) // [{ name, kaputt }]
  let text = $state('')
  let geladen = $state('')
  let kaputt = $state(null)
  /* The sentence of a file the service would not hand over — the reason a
     LOAD was refused, with nothing written. Separate from ``kaputt``: that
     one's catalogue sentence ends with “the file is saved”, which is only
     true after a save and must not be said over a load. */
  let unlesbar = $state(null)
  let platzhalter = $state([]) // tools only
  let lese = $state(null) // GET /tools live readout
  let feld = $state(null)
  let laedt = $state(false)
  /* The cronjob page, so the head's "New cronjob" can open its form. */

  const chat = $derived(aktuellerChat())
  const ausgesetzt = $derived(Boolean(chat?.prompt_aus))
  const istSprache = $derived(art === 'sprache')
  const istDarstellung = $derived(art === 'darstellung')
  const istMeldungen = $derived(art === 'meldungen')
  const istShortcuts = $derived(art === 'shortcuts')
  const istSystem = $derived(art === 'system')
  const istGedaechtnis = $derived(art === 'memory')
  const istSkills = $derived(art === 'skills')
  const istCronjobs = $derived(art === 'cronjobs')
  const istGalerie = $derived(art === 'tools')
  const istTools = $derived(art === 'tools_datei')
  const istAgent = $derived(art === 'agent')
  const istWerkzeuge = $derived(art === 'werkzeuge')
  const istDatei = $derived(art === 'konfiguration' || art === 'zugangsdaten')
  /* The agent page has two faces: the list of agents, and the editor for
     one of them. A name means the editor is open. */
  const agentBearbeiten = $derived(istAgent && agentName !== '')
  const bearbeitet = $derived(istSystem || istGedaechtnis || istDatei || istTools || agentBearbeiten)

  const MODI = [
    ['auto', 'einstellungen.auto'],
    ['hell', 'einstellungen.hell'],
    ['dunkel', 'einstellungen.dunkel'],
    ['darkmatter', 'einstellungen.darkmatter'],
    ['heaven', 'einstellungen.heaven'],
    ['moune', 'einstellungen.moune'],
    ['eigen', 'einstellungen.eigen'],
  ]

  /* The frame's own gradient, edited where the look is chosen. "Auto"
     carries no choice of its own: its controls edit whatever the device
     resolves to — the one resolution rule lives in zustand, beside the
     device's report and the painter, so panel and frame can never edit
     and draw different looks. */
  const rahmenSchema = $derived(lookFuer(modus))

  let rahmenFarben = $state([])
  let rahmenVorgaben = $state([])
  let rahmenTon = $state(0)
  let rahmenTonVorgabe = $state(0)
  let rahmenWinkel = $state(135)
  let rahmenWinkelVorgabe = $state(135)
  /* Loaded from the look's sheet whenever the look (or the choice) changes
     — as many fields as the look brings. Read once the flush is through:
     the attribute the look's sheet hangs on is written by the window's own
     effect in the same flush — read before the flush ends and the previous
     look's defaults are what comes back (and the kept answers would keep
     them). */
  const gleichListe = (a, b) => a.length === b.length && a.every((x, i) => x === b[i])
  $effect(() => {
    const schema = rahmenSchema
    const wahl = zustand.verlauf[schema] || {}
    tick().then(() => {
      /* Only what differs is assigned: the store changes with every
         pointer event, and equal values must not re-render the tiles. */
      const vorgaben = vorgabenFuer(schema)
      if (!gleichListe(rahmenVorgaben, vorgaben)) rahmenVorgaben = vorgaben
      const farben = wahl.farben ? [...wahl.farben] : [...vorgaben]
      if (!gleichListe(rahmenFarben, farben)) rahmenFarben = farben
      const tonVorgabe = tonVorgabeFuer(schema)
      if (rahmenTonVorgabe !== tonVorgabe) rahmenTonVorgabe = tonVorgabe
      const ton = wahl.ton ?? tonVorgabe
      if (rahmenTon !== ton) rahmenTon = ton
      const winkelVorgabe = winkelVorgabeFuer(schema)
      if (rahmenWinkelVorgabe !== winkelVorgabe) rahmenWinkelVorgabe = winkelVorgabe
      const winkel = wahl.winkel ?? winkelVorgabe
      if (rahmenWinkel !== winkel) rahmenWinkel = winkel
    })
  })
  const rahmenGeaendert = $derived(Boolean(zustand.verlauf[rahmenSchema]))
  /* The bubble's default follows the look — and the own gradient turns
     light or dark with its colours — so it is read again after every
     change of either, once the frame has been redrawn. */
  let blasenVorgabe = $state(blasenStandard())
  $effect(() => {
    void rahmenSchema
    void zustand.verlauf[EIGENER_VERLAUF]
    tick().then(() => {
      const wert = blasenStandard()
      if (wert !== blasenVorgabe) blasenVorgabe = wert
    })
  })

  /* Only what was changed is kept: a field that equals the look's own
     colour, the look's own hue and the look's own angle fall away; a choice
     that holds nothing at all deletes its entry. */
  function rahmenSetzen(teil) {
    const schema = rahmenSchema
    const wahl = { ...(zustand.verlauf[schema] || {}), ...teil }
    if (
      wahl.farben &&
      wahl.farben.length === rahmenVorgaben.length &&
      wahl.farben.every((farbe, i) => farbe === rahmenVorgaben[i])
    ) {
      delete wahl.farben
    }
    if (wahl.ton === rahmenTonVorgabe) delete wahl.ton
    if (wahl.winkel === rahmenWinkelVorgabe) delete wahl.winkel
    if (!wahl.farben && wahl.ton == null && wahl.winkel == null) {
      verlaufSetzen(schema, null)
      return
    }
    verlaufSetzen(schema, wahl)
  }
  function rahmenFarbeSetzen(i, farbe) {
    const farben = [...rahmenFarben]
    farben[i] = farbe
    rahmenFarben = farben
    rahmenSetzen({ farben })
  }
  /* The code colour packs in the order the list offers them: the house
     pack first, then the eight editor packs (stil/codefarben.css). */
  const CODE_PACKS = [
    ['exe', 'einstellungen.codefarben_exe'],
    ['tokyo', 'einstellungen.codefarben_tokyo'],
    ['onelight', 'einstellungen.codefarben_onelight'],
    ['github', 'einstellungen.codefarben_github'],
    ['githubdark', 'einstellungen.codefarben_githubdark'],
    ['dracula', 'einstellungen.codefarben_dracula'],
    ['nord', 'einstellungen.codefarben_nord'],
    ['solarizedlight', 'einstellungen.codefarben_solarizedlight'],
    ['solarizeddark', 'einstellungen.codefarben_solarizeddark'],
  ]

  /* The switches that decide whether the memory travels. */
  let gedaechtnisSchalter = $state({ lokal: true, cloud: false })
  async function gedaechtnisStandLaden() {
    try {
      const stand = await api.einstellungAufgeloest('gedaechtnis')
      if (stand?.wert && typeof stand.wert === 'object') {
        gedaechtnisSchalter = { ...gedaechtnisSchalter, ...stand.wert }
      }
    } catch {
      /* Leaves the default standing — it is the careful one. */
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


  /* Which attempt is the current one: a click made while an earlier one is
     still on its way takes over, and the earlier one must not report a
     failure for a switch nobody is waiting for anymore. */
  let sprachversuch = 0
  /* The pill shows the stored choice: `texte.wahl` is reactive, and every
     switch writes it before its first await (`texte.svelte.js`), so the
     pill follows at once — the return to "auto" included. */
  const sprachwahl = $derived(texte.wahl)
  const sprachauswahl = $derived([
    { wert: 'auto', text: t('einstellungen.sprache_auto') },
    { wert: 'en', text: t('einstellungen.sprache_englisch') },
    { wert: 'de', text: t('einstellungen.sprache_deutsch') },
  ])
  async function spracheStellen(wert) {
    const meiner = ++sprachversuch
    try {
      if (wert === 'auto') await spracheZuruecksetzen()
      else await spracheWaehlen(wert)
      await modelleLaden()
    } catch {
      if (meiner === sprachversuch) melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* The live state behind the subtitles — fetched once when the window
     opens, so a glance at the list shows where everything stands. */
  let stand = $state({
    serverAnzahl: 0, werkzeugAnzahl: 0, skills: 0, skillsAuto: true,
    cronjobs: 0, cronjobsAktiv: 0,
  })
  async function standLaden() {
    api.werkzeuge().then((wz) => {
      stand.serverAnzahl = wz?.server?.length ?? 0
      stand.werkzeugAnzahl = wz?.werkzeuge?.length ?? 0
    }).catch(() => {})
    werkzeugeLaden()
    api.skillsVerwaltung().then((z) => (stand.skills = z.length)).catch(() => {})
    api.cronjobs().then((z) => {
      stand.cronjobs = z.length
      stand.cronjobsAktiv = z.filter((e) => e.aktiv).length
    }).catch(() => {})
    api.einstellungAufgeloest('skills_auto').then((s) => {
      if (s?.wert && typeof s.wert.an === 'boolean') stand.skillsAuto = s.wert.an
    }).catch(() => {})
    gedaechtnisStandLaden()
    bildschutzStandLaden()
    werkzeugRundenLaden()
    befehlZeitLaden()
    verdichtungSchwelleLaden()
    helperLimitsLoad()
  }

  /* The grouped nav: each box a group, each entry a sign, a title and a
     live-state subtitle. */
  const EINTRAEGE = {
    sprache: { zeichen: 'sprache', titel: 'editor.quelle_sprache' },
    darstellung: { zeichen: 'palette', titel: 'editor.quelle_darstellung' },
    meldungen: { zeichen: 'glocke', titel: 'meldewesen.quelle' },
    shortcuts: { zeichen: 'keyboard', titel: 'shortcuts.title' },
    memory: { zeichen: 'speicherriegel', titel: 'gedaechtnis.quelle' },
    skills: { zeichen: 'buch', titel: 'skills.quelle' },
    cronjobs: { zeichen: 'stopwatch', titel: 'cronjobs.quelle' },
    system: { zeichen: 'feder', titel: 'agenten.quelle_system' },
    agent: { zeichen: 'person', titel: 'editor.quelle_agenten' },
    tools: { zeichen: 'plug', titel: 'editor.quelle_tools' },
    werkzeuge: { zeichen: 'werkzeug', titel: 'werkzeuge.titel' },
    zugangsdaten: { zeichen: 'schluessel', titel: 'editor.quelle_zugangsdaten' },
    konfiguration: { zeichen: 'dokument', titel: 'editor.quelle_konfiguration' },
    tools_datei: { zeichen: 'dokument_pfeil', titel: 'editor.quelle_tools_datei' },
  }
  const GRUPPEN = [
    { name: 'general', titel: 'editor.gruppe_general', eintraege: ['sprache', 'darstellung', 'meldungen', 'shortcuts'] },
    { name: 'verhalten', titel: 'editor.gruppe_verhalten', eintraege: ['memory', 'skills', 'cronjobs'] },
    { name: 'prompts', titel: 'editor.gruppe_prompts', eintraege: ['system', 'agent'] },
    { name: 'verbindungen', titel: 'editor.gruppe_verbindungen', eintraege: ['tools', 'werkzeuge', 'zugangsdaten'] },
    { name: 'dateien', titel: 'editor.gruppe_dateien', eintraege: ['konfiguration', 'tools_datei'] },
  ]

  // The shortcuts entry names the microphone key under its title, so the
  // stored key is read as soon as the settings are open.
  $effect(() => {
    diktatStandLaden()
  })

  // The shortcut entry shows the key by the character the switched-on
  // layout writes on it ("⌘Ö" on a German layout) — the one holder the
  // Shortcuts page and the recogniser read as well, so both name the same
  // key (lib/keyboardLayout.svelte.js) — and, off the Mac, in the words
  // printed on the keys, as that page does (lib/keyNames.js).


  const spracheName = $derived(
    texte.sprache === 'de' ? t('einstellungen.sprache_deutsch') : t('einstellungen.sprache_englisch'),
  )

  function unterText(key) {
    switch (key) {
      case 'sprache':
        return spracheName
      case 'meldungen':
        return t(klangwahl.aus ? 'einstellungen.toene_aus' : 'einstellungen.toene_an')
      case 'darstellung':
        return t('einstellungen.' + modus)
      case 'shortcuts':
        return `${t('shortcuts.group_microphone')} ${showCombo(diktat.microphone_key || DEFAULT_KEY, layout.map, keyNames())}`
      // The row's dot already says on or off; a sentence beside it said it twice.
      case 'memory':
        return ''
      case 'skills':
        return t('editor.unter_skills', { n: stand.skills })
      case 'cronjobs':
        return `${stand.cronjobsAktiv}/${stand.cronjobs}`
      case 'system':
        return ''
      case 'agent':
        return t('editor.unter_agenten', { n: dateien.length })
      case 'tools':
        return t('editor.unter_server', { n: stand.serverAnzahl, w: stand.werkzeugAnzahl })
      case 'werkzeuge':
        return t('werkzeuge.aktiv_zahl', aktivStand())
      case 'zugangsdaten':
        return ''
      case 'konfiguration':
        return ''
      case 'tools_datei':
        return ''
      default:
        return ''
    }
  }
  /* An entry carries a status lamp only where there is a state worth one. */
  function ampelFarbe(key) {
    switch (key) {
      case 'memory':
        return gedaechtnisSchalter.lokal ? 'gruen' : 'still'
      case 'skills':
        return stand.skillsAuto ? 'gruen' : 'still'
      case 'cronjobs':
        return stand.cronjobsAktiv > 0 ? 'gruen' : 'still'
      case 'tools':
        return stand.serverAnzahl > 0 ? 'gruen' : 'still'
      default:
        return null
    }
  }
  function istAktiv(key) {
    return art === key
  }
  function navZiel(key) {
    // The agent entry always opens the list first, never the last file.
    if (key === 'agent') return wechseln('agent', '')
    return wechseln(key)
  }

  $effect(() => {
    if (!offen) return
    const start = zustand.promptStart
    const [ziel, name] = start === 'darstellung'
      ? [start, '']
      : start?.startsWith?.('agent:') ? ['agent', start.slice(6)] : ['system', '']
    untrack(() => {
      dateienLaden()
      standLaden()
      /* An edit left unsaved outlives the closed page. The settings button
         and ⌘, open it again where it was left; a way in that names a place
         of its own (an agent) asks before the edit goes, as every switch
         does. Without an edit the file is read fresh. */
      if (text === geladen) laden(ziel, name)
      else if (start !== 'darstellung') wechseln(ziel, name)
    })
  })

  async function dateienLaden() {
    try {
      dateien = await api.agentDateien()
    } catch {
      dateien = []
    }
  }
  async function leseanzeigeLaden() {
    try {
      lese = await api.werkzeuge()
    } catch {
      lese = null
    }
  }

  /* ``welche`` defaults to the current tile for the save path, where it is
     always the right one — but a failed LOAD must name the tile that was
     being switched to, not the one still showing while the request was in
     flight. So every caller names it (``melde(… meldeschluessel('…', art))``
     for the save path, the requested tile in ``laden``'s else branch):
     ``art`` is not a witness here, because the refusal of an agent file
     sets it too. */
  function meldeschluessel(fall, welche = art) {
    if (welche === 'system') return `systemprompt.${fall}`
    if (welche === 'memory') return `gedaechtnis.${fall}`
    if (welche === 'konfiguration' || welche === 'zugangsdaten') return `dateien.${fall}`
    if (welche === 'tools_datei') return `werkzeuge.${fall}`
    if (welche === 'cronjobs') return `cronjobs.${fall}`
    if (welche === 'agent') return `agenten.${fall}`
    return `editor.${fall}`
  }

  /* File-less pages carry no text to fetch or discard. The agent LIST is
     one of them; only an agent with a name loads a file. */
  const OHNE_DATEI = ['sprache', 'darstellung', 'meldungen', 'shortcuts', 'tools', 'werkzeuge', 'skills', 'cronjobs']

  async function laden(neueArt, name = '') {
    if (OHNE_DATEI.includes(neueArt) || (neueArt === 'agent' && !name)) {
      art = neueArt
      agentName = name
      text = ''
      geladen = ''
      kaputt = null
      unlesbar = null
      platzhalter = []
      return
    }
    laedt = true
    kaputt = null
    unlesbar = null
    platzhalter = []
    try {
      if (neueArt === 'system') {
        const daten = await api.systemPrompt()
        text = daten.text
      } else if (neueArt === 'memory') {
        const daten = await api.gedaechtnis()
        text = daten.text
        gedaechtnisStandLaden()
      } else if (neueArt === 'tools_datei') {
        const daten = await api.werkzeugKonfiguration()
        text = daten.content
        kaputt = daten.kaputt
        platzhalter = daten.platzhalter
        leseanzeigeLaden()
      } else if (neueArt === 'konfiguration' || neueArt === 'zugangsdaten') {
        const daten = await api.datei(neueArt)
        text = daten.inhalt
        kaputt = daten.kaputt
      } else {
        const daten = await api.agentDatei(name)
        text = daten.content
        kaputt = daten.kaputt
      }
      geladen = text
      art = neueArt
      agentName = name
      /* Read, so whatever an earlier refusal said about a file is answered
         here: without this line a late 422 could leave its sentence above
         the content of a file that arrived after it. */
      unlesbar = null
    } catch (fehler) {
      /* A file the service will not HAND OVER is still a file the user can
         act on: bytes that are no UTF-8 (a broken header does not come
         through here — it arrives as a body with a reason), a file nobody
         may read. The page opens with the service's own sentence in the
         warning box, and deleting and saving stay within reach — the save
         path writes without reading first, so it is the way out of exactly
         this state. A service that is not there is not this case and keeps
         the plain message. */
      /* ``name`` needs no second look: the guard at the top of this function
         already turns away an agent page without one. */
      if (neueArt === 'agent' && fehler?.status === 422) {
        art = neueArt
        agentName = name
        text = ''
        geladen = ''
        unlesbar = fehler.message
      } else {
        melde(t(meldeschluessel('nicht_geladen', neueArt)), 'fehler')
      }
    } finally {
      laedt = false
      setTimeout(() => feld?.fokus(), 60)
    }
  }

  /* Cancel lets the edit go: the text falls back to the file, and an agent
     that was never saved gives way to the list. */
  function abbrechen() {
    if (geladen === null) laden('agent', '')
    else text = geladen
    seitenSchliessen()
  }

  async function wechseln(neueArt, name = '') {
    if (neueArt === art && name === agentName) return
    if ((text !== geladen || (maske && maskeGeaendert)) && !(await frage(t('agenten.verwerfen_frage')))) return
    laden(neueArt, name)
  }

  function neuerAgent() {
    maske = { agent: null }
  }
  /* Saved: the list is read again, so the agent stands in it at once. */
  async function maskeFertig() {
    maske = null
    await dateienLaden()
  }
  /* Leaving the agents page takes the mask with it. */
  $effect(() => {
    if (!istAgent) maske = null
  })

  /* The server stores the text trimmed; after a save the field shows what
     was stored, so the edit no longer counts as unsaved — unless more was
     typed while the save was on its way, which stays and stays unsaved. */
  async function sichern() {
    const gesendet = text
    try {
      if (istSystem) {
        const daten = await api.systemPromptSichern(text)
        geladen = daten.text
        if (text === gesendet) text = geladen
        melde(daten.text ? t('systemprompt.gesichert') : t('systemprompt.geleert'), 'erfolg')
        seitenSchliessen()
      } else if (istGedaechtnis) {
        const daten = await api.gedaechtnisSichern(text)
        geladen = daten.text
        if (text === gesendet) text = geladen
        melde(daten.text ? t('gedaechtnis.gesichert') : t('gedaechtnis.geleert'), 'erfolg')
      } else if (istDatei) {
        const daten = await api.dateiSichern(art, text)
        geladen = daten.inhalt
        if (text === gesendet) text = geladen
        kaputt = daten.kaputt
        melde(t(kaputt ? 'dateien.gesichert_kaputt' : 'dateien.gesichert'), kaputt ? 'hinweis' : 'erfolg')
      } else if (istTools) {
        const daten = await api.werkzeugKonfigurationSichern(text)
        geladen = daten.content
        if (text === gesendet) text = geladen
        kaputt = daten.kaputt
        platzhalter = daten.platzhalter
        melde(kaputt ? t('werkzeuge.gesichert_kaputt') : t('werkzeuge.gesichert'), kaputt ? 'hinweis' : 'erfolg')
        if (!kaputt) {
          setTimeout(leseanzeigeLaden, 1500)
          setTimeout(leseanzeigeLaden, 5000)
        }
      } else {
        if (!/^[A-Za-z0-9_-]{1,100}$/.test(agentName)) {
          melde(t('fehler.agent_name_ungueltig'), 'fehler')
          return
        }
        const daten = await api.agentSichern(agentName, text)
        geladen = daten.content
        if (text === gesendet) text = geladen
        kaputt = daten.kaputt
        /* Written, so the file is a file again — what a refused LOAD said
           about it is settled. */
        unlesbar = null
        await dateienLaden()
        meldeText('agenten.gesichert', { name: agentName }, kaputt ? 'hinweis' : 'erfolg')
        if (!kaputt) wechseln('agent', '')
      }
    } catch {
      melde(t(meldeschluessel('nicht_gesichert')), 'fehler')
    }
  }

  /* ``name`` is the agent open in the editor, or one chosen on the list:
     an agent never saved (``geladen`` null) has no file to remove. */
  async function agentLoeschen(name = agentName) {
    if (!(await frage(t('agenten.loeschen_frage', { name })))) return
    try {
      if (name !== agentName || geladen !== null) await api.agentLoeschen(name)
      meldeText('agenten.geloescht', { name }, 'erfolg')
      await dateienLaden()
      laden('agent', '')
    } catch {
      melde(t('agenten.nicht_gesichert'), 'fehler')
    }
  }

  async function aussetzen(an) {
    if (!chat) {
      melde(t('chat.erst_oeffnen'))
      return
    }
    try {
      await chatAendern(chat.id, { prompt_aus: an })
    } catch {
      melde(t('systemprompt.schalter_fehler'), 'fehler')
    }
  }

  const kopfEintrag = $derived(agentBearbeiten ? EINTRAEGE.agent : EINTRAEGE[art] ?? EINTRAEGE.system)
</script>

<Seitenrahmen {offen} beschriftung={t('editor.titel')}>
  <!-- The parts are built fresh each time the page opens, as in the window
       the page replaces: a window one of them opened (the MCP mask) must not
       outlive the page. What was typed stays all the same — it lives in this
       file, not in the parts. -->
  {#if offen}
  <Menueseite beschriftung={t('editor.titel')} fuellen festeHoehe={istWerkzeuge || istCronjobs}>
    {#snippet liste()}
      {#each GRUPPEN as g (g.name)}
        <div class="menuegruppe">{t(g.titel)}</div>
        <div class="s2-box">
          {#each g.eintraege as key (key)}
            <Menuezeile
              titel={t(EINTRAEGE[key].titel)}
              wert={unterText(key)}
              punkt={ampelFarbe(key)}
              gewaehlt={istAktiv(key)}
              onclick={() => navZiel(key)}
            >
              {#snippet zeichen()}<Hauszeichen zeichen={EINTRAEGE[key].zeichen} groesse="gross" />{/snippet}
            </Menuezeile>
          {/each}
        </div>
      {/each}
      <!-- The manual, set apart at the foot of the list: not a setting, but
           the place a question about one leads to. -->
      <div class="abgesetzt">
        <Menuezeile titel={t('menue.hilfe')} onclick={handbuchOeffnen}>
          {#snippet zeichen()}
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M9.2 9a2.8 2.8 0 1 1 4 2.55c-.9.42-1.2 1.05-1.2 2.05v.4" /><path d="M12 17.6 V17.7" />
            </svg>
          {/snippet}
        </Menuezeile>
      </div>
      <!-- The program's version and the look for a newer one, at the very
           foot: about the program itself, not one of its settings. -->
      <Updatezeile />
    {/snippet}

    {#snippet kopf()}
      <div class="set-kopf">
        <span class="s2-zeichen gross"><Hauszeichen zeichen={kopfEintrag.zeichen} groesse="gross" /></span>
        <h3>{t(kopfEintrag.titel)}</h3>
        {#if istAgent && !agentBearbeiten && !maske}
          <button class="neu" onclick={() => neuerAgent()}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            {t('agenten.neu_kurz')}
          </button>
        {/if}
      </div>
    {/snippet}

    {#snippet inhalt()}
      {#if istSprache}
        <div class="kachelliste">
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.sprache')}
              <span class="hinweis">{t('einstellungen.sprache_hinweis')}</span>
            </div>
            <div class="auswahl">
              <Auswahlfeld
                wert={sprachwahl}
                eintraege={sprachauswahl}
                beschriftung={t('einstellungen.sprache')}
                gewaehlt={spracheStellen}
              />
            </div>
          </div>
        </div>
      {:else if istMeldungen}
        <!-- The sounds sat under the language for a while, on the grounds
             that how loud the program is is not a question of how it
             looks. It is not a question of which words it uses either:
             it belongs with everything else the program does to get
             attention, which is what this page is. -->
        <Meldewahl />
      {:else if istShortcuts}
        <Shortcuts />
      {:else if istDarstellung}
        <div class="kachelliste">
          <!-- The chat layout is not set here but over the real chat,
               where every change can be seen: the button closes the
               settings and opens the layout mode. -->
          <div class="einstellkachel">
            <button class="layoutknopf" onclick={layoutModusOeffnen}>
              <Hauszeichen zeichen="ecken" groesse={24} />
              {t('einstellungen.layout_modus')}
            </button>
          </div>
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.erscheinungsbild')}
              <span class="hinweis">{t('einstellungen.auto_hinweis')}</span>
            </div>
            <Klappwahl
              optionen={MODI.map(([wert, schluessel]) => [wert, t(schluessel)])}
              bind:wert={modus}
              beschriftung={t('einstellungen.erscheinungsbild')}
            />
          </div>
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.codefarben')}
              <span class="hinweis">{t('einstellungen.codefarben_hinweis')}</span>
            </div>
            <Klappwahl
              optionen={CODE_PACKS.map(([wert, schluessel]) => [wert, t(schluessel)])}
              wert={zustand.codefarben}
              aufWahl={(neu) => codefarbenSetzen(neu)}
              beschriftung={t('einstellungen.codefarben')}
            />
          </div>
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.blase')}
              <span class="hinweis">{t('einstellungen.blase_hinweis')}</span>
            </div>
            <div class="farbwahl">
              {#if zustand.blasenfarbe}
                <button class="ruecksetzer" onclick={() => blasenfarbeSetzen('')}>{t('einstellungen.blase_standard')}</button>
              {/if}
              <input type="color" aria-label={t('einstellungen.blase')}
                     value={zustand.blasenfarbe || blasenVorgabe} oninput={(e) => blasenfarbeSetzen(e.currentTarget.value)} />
            </div>
          </div>
          <!-- Only the own gradient is the user's to paint: every other
               look keeps the gradient its design gave it, so the colour,
               hue and angle rows stand only while it is chosen. -->
          {#if rahmenSchema === EIGENER_VERLAUF}
          {#each rahmenFarben as farbe, i (rahmenSchema + ':' + i)}
            <div class="einstellkachel">
              <div class="zeilentext">{t('einstellungen.hintergrundfarbe', { nummer: i + 1 })}</div>
              <div class="farbwahl">
                <input type="color"
                       aria-label={t('einstellungen.hintergrundfarbe', { nummer: i + 1 })}
                       value={farbe} oninput={(e) => rahmenFarbeSetzen(i, e.currentTarget.value)} />
              </div>
            </div>
          {/each}
          <!-- The two slider tiles: the name and the number on one line,
               the slider over the whole width under them. -->
          <div class="einstellkachel regel">
            <div class="kopfzeile">
              <div class="zeilentext">{t('einstellungen.farbton')}</div>
              <span class="rahmenwert">{rahmenTon}°</span>
            </div>
            <input type="range" min="-180" max="180" step="1"
                   aria-label={t('einstellungen.farbton')} value={rahmenTon}
                   oninput={(e) => { rahmenTon = Number(e.currentTarget.value); rahmenSetzen({ ton: rahmenTon }) }} />
          </div>
          <div class="einstellkachel regel">
            <div class="kopfzeile">
              <div class="zeilentext">{t('einstellungen.winkel')}</div>
              <button class="ruecksetzer standardplatz" class:an={rahmenGeaendert}
                      onclick={() => verlaufSetzen(rahmenSchema, null)}>{t('einstellungen.blase_standard')}</button>
              <span class="rahmenwert">{rahmenWinkel}°</span>
            </div>
            <input type="range" min="0" max="360" step="1"
                   aria-label={t('einstellungen.winkel')} value={rahmenWinkel}
                   oninput={(e) => { rahmenWinkel = Number(e.currentTarget.value); rahmenSetzen({ winkel: rahmenWinkel }) }} />
          </div>
          {/if}
        </div>
      {:else if istSkills}
        <Skillmaske />
      {:else if istCronjobs}
        <!-- The page itself stands still: the schedules scroll in their own
             room and the scripts stay at the foot. -->
        <div class="cronjobseite">
          <SettingsCronjobs onzahlen={(aktiv, gesamt) => { stand.cronjobsAktiv = aktiv; stand.cronjobs = gesamt }} />
          <!-- Where the scripts a schedule may start live, under the
               schedules; a script clicked opens the form above with it. -->
          <div class="skriptteil">
            <h4 class="tafelkopf">{t('cronjobs.abschnitt_skripte')}</h4>
            <Skriptordner />
          </div>
        </div>
      {:else if istGalerie}
        <Verbindungen
          zuWerkzeugen={() => navZiel('werkzeuge')}
        />
      {:else if istWerkzeuge}
        <!-- The tools, once a window of their own, right under the servers
             they come from. Their one way out leads next door. -->
        <Werkzeuge zuVerbindungen={() => navZiel('tools')} />
      {:else if istAgent && maske}
        <Agentenmaske agent={maske.agent} bind:geaendert={maskeGeaendert}
                      onfertig={maskeFertig} onabbrechen={() => (maske = null)} />
      {:else if istAgent && !agentBearbeiten}
        <SettingsAgents {dateien} {helpersAtOnce} {helperSteps}
                        onbearbeiten={(agent) => (maske = { agent })}
                        onloeschen={(name) => agentLoeschen(name)} />
      {:else}
        <!-- A floor of about six lines around the editor: where the page
             gives no height to share out (a narrow window stacks everything
             into one column), the field would otherwise shrink to its single
             row. -->
        <div class="editorboden">
        <WachsendesFeld
          bind:this={feld}
          bind:wert={text}
          gesperrt={laedt}
          gedimmt={istSystem && ausgesetzt}
          quelle={istDatei || istTools || agentBearbeiten}
          platzhalter={istSystem ? t('systemprompt.platzhalter') : ''}
          beschriftung={t('editor.titel')}
          volleHoehe
        />
        </div>
      {/if}

      {#if kaputt || unlesbar}
        <div class="warnung" transition:fade={{ duration: 120 }}>
          {unlesbar ?? t(istTools ? 'werkzeuge.kaputt' : 'agenten.kaputt', { grund: kaputt })}
        </div>
      {/if}

      {#if istTools && platzhalter.length}
        <div class="ampeln">
          {#each platzhalter as eintrag (eintrag.name)}
            <span class="ampelzeile" class:fehlt={!eintrag.gesetzt}>
              <Leuchtpunkt farbe={eintrag.gesetzt ? 'gruen' : 'still'} groesse={11} />
              {eintrag.name} — {t(eintrag.gesetzt ? 'werkzeuge.platzhalter_gesetzt' : 'werkzeuge.platzhalter_fehlt')}
            </span>
          {/each}
        </div>
      {/if}

      {#if istTools}
        <div class="lese">
          <div class="lesetitel tafelkopf">{t('werkzeuge.live')}</div>
          {#if !lese}
            <span class="leseleer">{t('werkzeuge.keine')}</span>
          {:else if !lese.aktiv}
            <span class="leseleer">{t('werkzeuge.abgeschaltet')}</span>
          {:else}
            {#each lese.server as server (server)}
              <span class="server"><Leuchtpunkt farbe="gruen" groesse={11} />{server}</span>
            {/each}
            {#if lese.werkzeuge.length}
              <div class="werkzeugpillen">
                {#each lese.werkzeuge as werkzeug (werkzeug.name)}
                  <Standpille farbe="werkzeug">{werkzeug.name}</Standpille>
                {/each}
              </div>
            {:else}
              <span class="leseleer">{t('werkzeuge.keine')}</span>
            {/if}
          {/if}
        </div>
      {/if}

      {#if istGedaechtnis}
        <div class="schalterzeile">
          <div class="beschriftung">
            {t('gedaechtnis.an_lokal')}
            <span class="hinweis">{t('gedaechtnis.an_lokal_hinweis')}</span>
          </div>
          <Schalter an={gedaechtnisSchalter.lokal} beschriftung={t('gedaechtnis.an_lokal')} onschalten={(an) => gedaechtnisSchalten('lokal', an)} />
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">
            {t('gedaechtnis.an_cloud')}
            <span class="hinweis">{t('gedaechtnis.an_cloud_hinweis')}</span>
          </div>
          <Schalter an={gedaechtnisSchalter.cloud} beschriftung={t('gedaechtnis.an_cloud')} onschalten={(an) => gedaechtnisSchalten('cloud', an)} />
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">
            {t('bildschutz.titel')}
            <span class="hinweis">{t('bildschutz.hinweis')}</span>
          </div>
          <Schalter an={bildschutzSchalter.an} beschriftung={t('bildschutz.titel')} onschalten={(an) => bildschutzSchalten(an)} />
        </div>
      {/if}

      {#if istSystem}
        <div class="schalterzeile">
          <div class="beschriftung">{t('editor.werkzeugrunden_titel')}
            <span class="hinweis">{t('editor.werkzeugrunden_unter')}</span>
          </div>
          <div class="zahlfeld">
            <Zahlenfeld bind:wert={werkzeugRunden} min={0} ganzzahlig
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">{t('editor.befehlszeit_titel')}
            <span class="hinweis">{t('editor.befehlszeit_unter')}</span>
          </div>
          <div class="zahlfeld">
            <Zahlenfeld bind:wert={befehlZeit} min={0} ganzzahlig
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">{t('editor.kontextkomprimierung_titel')}
            <span class="hinweis">{t('editor.kontextkomprimierung_unter')}</span>
          </div>
          <div class="zahlfeld">
            <!-- `max` matters here in a way it does not for the two
                 fields above: those have no ceiling on the service side,
                 this one is refused above 85 (app/verdichtungswahl.py),
                 and a refused value is filed as "nothing set" with a
                 plain 200. Typing 90 therefore left the field showing 90,
                 nothing complaining, and the threshold quietly still at
                 its default. Clamped here, the field shows at once what
                 was actually stored.
                 The floor needs no clamp: the service takes anything from
                 1 up, which is exactly what this field can offer once 0
                 is spoken for by "default". -->
            <Zahlenfeld bind:wert={verdichtungSchwelle} min={0} max={85} ganzzahlig
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">{t('editor.anrede_titel')}
            <span class="hinweis">{t('editor.anrede_unter')}</span>
          </div>
          <input class="anredefeld" value={begruessung.name} placeholder={begruessung.vorschlag}
                 aria-label={t('editor.anrede_titel')}
                 onchange={(e) => anredeSpeichern(e.currentTarget.value, begruessung.an)} />
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">{t('editor.anrede_schalter')}
            <span class="hinweis">{t('editor.anrede_schalter_unter')}</span>
          </div>
          <Schalter an={begruessung.an} beschriftung={t('editor.anrede_schalter')}
                    onschalten={(an) => anredeSpeichern(begruessung.name, an)} />
        </div>
        <div class="schalterzeile">
          <div class="beschriftung">{t('systemprompt.aussetzen')}</div>
          <Schalter an={ausgesetzt} art="eingriff" beschriftung={t('systemprompt.aussetzen')} onschalten={(an) => aussetzen(an)} />
        </div>
      {/if}

      <div class="fuss">
        {#if istSystem || istGedaechtnis}
          <button class="textknopf" onclick={() => { text = ''; feld?.fokus() }}>{t('app.leeren')}</button>
        {:else if agentBearbeiten}
          <button class="textknopf gefahr" onclick={() => agentLoeschen()}>{t('agenten.loeschen')}</button>
        {:else}
          <span></span>
        {/if}
        <div class="rechts">
          {#if bearbeitet}
            <button class="button" onclick={abbrechen}>{t('app.abbrechen')}</button>
            <button class="button primary" onclick={sichern}>{t('app.sichern')}</button>
          {/if}
        </div>
      </div>
    {/snippet}
  </Menueseite>
  {/if}
</Seitenrahmen>

<style>
  .s2-box {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .s2-zeichen.gross {
    width: 24px;
    height: 24px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
  }
  /* The manual, apart from the groups: air above it, no line. */
  .abgesetzt {
    margin-top: 24px;
  }
  .set-kopf {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .set-kopf h3 {
    font-size: var(--schrift-seitentitel);
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 0;
  }

  /* "New agent" / "New cronjob" at the far end of the head. */
  .neu {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 36px;
    padding: 0 18px;
    border: none;
    border-radius: 9px;
    /* A main button, so button glass with its fine edge; only Send is filled. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
    transition: background 0.12s;
  }
  .neu:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }

  .warnung {
    margin-top: 10px;
    border-radius: 9px;
    /* A state surface mixes its colour over the card glass. */
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-card));
    color: var(--rot-text);
    font-size: 12.5px;
    line-height: 1.5;
    padding: 8px 12px;
  }

  .ampeln {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin-top: 10px;
  }
  .ampelzeile {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-leise);
  }
  .ampelzeile.fehlt {
    color: var(--text-still);
  }

  .lese {
    margin-top: 12px;
    padding-top: 12px;
  }
  /* Text itself: global.css, .tafelkopf. */
  .lesetitel {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .lesetitel::after {
    content: '';
    flex: 1;
    border-top: 1px solid var(--linie);
  }
  .server {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    margin-right: 14px;
  }
  .werkzeugpillen {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 6px;
  }
  .leseleer {
    font-size: 12px;
    color: var(--text-still);
  }

  /* The switches under an editor: one card, a hairline between its rows —
     the first row after anything else opens the card, the last before the
     foot closes it. */
  .schalterzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 16px;
    background: var(--glass-card);
    border-top: 1px solid var(--linie);
  }
  :global(*:not(.schalterzeile)) + .schalterzeile {
    margin-top: 14px;
    border-top-color: transparent;
    border-radius: 9px 9px 0 0;
  }
  .schalterzeile:has(+ .fuss) {
    border-bottom-left-radius: 9px;
    border-bottom-right-radius: 9px;
  }
  .beschriftung {
    flex: 1;
    min-width: 0;
    font-size: 13px;
  }

  /* A page's settings as one card, a hairline between its rows. */
  .kachelliste {
    display: flex;
    flex-direction: column;
    padding: 0 16px;
    border-radius: 9px;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .einstellkachel {
    padding: 12px 0;
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .einstellkachel + .einstellkachel {
    border-top: 1px solid var(--linie);
  }
  .zeilentext {
    flex: 1;
    min-width: 0;
    font-size: 13px;
  }
  .hinweis {
    display: block;
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
    margin-top: 2px;
  }
  /* The picker brings its own measure; the row only says how wide it may be
     so the label keeps the rest. */
  .auswahl {
    flex: none;
    width: 190px;
  }
  .farbwahl {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  /* The gradient's sliders and the figure beside them: the house's own
     colours — the track takes the text colour through accent-color, no
     invented shade. */
  .einstellkachel.regel {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }
  .kopfzeile {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .einstellkachel.regel input[type='range'] {
    margin: 0;
    accent-color: var(--text);
  }
  .rahmenwert {
    min-width: 40px;
    text-align: right;
    font-family: var(--schrift-fest);
    font-size: 12px;
    color: var(--text-leise);
  }
  .farbwahl input[type='color'] {
    width: 44px;
    height: 32px;
    padding: 2px;
    /* A field on glass: glass with the house's field outline. */
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    cursor: pointer;
  }
  .ruecksetzer {
    font: inherit;
    font-size: 12.5px;
    color: var(--text);
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    border: none;
    border-radius: 9px;
    padding: 6px 11px;
    cursor: pointer;
  }
  .ruecksetzer:hover {
    color: var(--text);
  }
  .layoutknopf {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font: inherit;
    font-size: 13px;
    color: var(--text);
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    border: none;
    border-radius: 9px;
    padding: 8px 12px;
    cursor: pointer;
  }
  /* The reset's place is held from the start: the entry it clears is made
     mid-drag, and a button inserted in that moment would shift the track
     under the pointer. */
  .standardplatz {
    visibility: hidden;
  }
  .standardplatz.an {
    visibility: visible;
  }

  .editorboden {
    flex: 1;
    min-height: 10rem;
    display: flex;
    flex-direction: column;
  }
  .fuss {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: auto;
    padding-top: 14px;
    flex: none;
  }
  .rechts {
    display: flex;
    gap: 8px;
  }
  /* The foot's buttons are the house button (`.button`, stil/global.css);
     only the press is this page's own. */
  .button:active:not(:disabled) {
    transform: scale(0.975);
  }
  .textknopf {
    border: none;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 9px;
  }
  .textknopf:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .textknopf.gefahr:hover {
    background: color-mix(in srgb, var(--rot) 12%, var(--glass-card));
  }

  .anredefeld {
    height: 32px;
    box-sizing: border-box;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 13px var(--schrift);
    padding: 6px 11px;
    width: 150px;
    flex: none;
  }
  /* A round count is a short number, not a name — a narrow field says so.
     Wide enough for the word standing in for its zero. */
  .zahlfeld {
    width: 108px;
    flex: none;
  }
  /* Reaches down into the frame's foot room, so the scripts sit lower
     without touching the edge. */
  .cronjobseite {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin-bottom: -32px;
  }
  /* The scripts' part under the schedules, set off like a part of a view;
     it keeps its own height and never scrolls out. */
  .skriptteil {
    flex: none;
    margin-top: 22px;
  }
  .skriptteil h4 {
    margin: 0 0 10px;
  }
</style>
