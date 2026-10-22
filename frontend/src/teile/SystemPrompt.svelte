<script>
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
  import Werkzeuge from './Werkzeuge.svelte'
  import { aktivStand } from '../lib/werkzeuge.svelte.js'
  import { chooseRow } from '../lib/settingsrow.js'
  import { settingsState } from '../lib/settingsState.svelte.js'
  import WachsendesFeld from './WachsendesFeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import InfoMark from './InfoMark.svelte'
  import SettingsNav from './SettingsNav.svelte'
  import { SEITEN, zeile as listenZeile } from '../lib/einstellungsliste.js'
  import { schalterAnspringen } from '../lib/einstellungssuche.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Looktafel from './Looktafel.svelte'
  import { eigenVorschau } from '../lib/looksvorschau.js'
  import { farbtonDrehen } from '../lib/agentenfarbe.svelte.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import SettingsCronjobs from './SettingsCronjobs.svelte'
  import SettingsWebApp from './SettingsWebApp.svelte'
  import SettingsAgents from './SettingsAgents.svelte'
  import Agentenmaske from './Agentenmaske.svelte'
  import Skriptordner from './Skriptordner.svelte'
  import Skillmaske from './Skillmaske.svelte'
  import Standpille from './Standpille.svelte'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import { serverLogo } from '../lib/serverlogo.svelte.js'
  import Verbindungen from './Verbindungen.svelte'
  import Meldewahl from './Meldewahl.svelte'
  import { useSettingsValues } from '../lib/settingsvalues.svelte.js'
  import { spracheStellen } from '../lib/sprachwahl.svelte.js'
  import { CODE_PACKS, blasenStandard } from '../lib/darstellungswerte.js'
  import Shortcuts from './Shortcuts.svelte'
  import { standLaden as diktatStandLaden } from '../lib/diktat.svelte.js'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import Schalter from './Schalter.svelte'
  import { api } from '../lib/api.js'
  import { zustand, aktuellerChat, promptAusgesetzt, codefarbenSetzen, blasenfarbeSetzen, verlaufSetzen, lookFuer, vorgabenFuer, winkelVorgabeFuer, tonVorgabeFuer, EIGENER_VERLAUF, melde, frage, seitenSchliessen, layoutModusOeffnen } from '../lib/zustand.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'

  import {
    t, texte,
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
  /* What a save of a file page (credentials, configuration, tools file)
     answers with: the catalogue key of its sentence, whether it is the
     caution that the file was saved but not applied, and the text that was
     saved. It stands left in the foot, in the line of the two signs, while
     the field holds that text, and goes when another page opens — nothing is
     said above the chat for these pages. */
  let saveNote = $state(null)
  let lese = $state(null) // GET /tools live readout
  let feld = $state(null)
  let laedt = $state(false)
  /* The cronjob page, so the head's "New cronjob" can open its form. */

  const chat = $derived(aktuellerChat())
  const ausgesetzt = $derived(promptAusgesetzt())
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
  const isWebApp = $derived(art === 'web_app')
  const istDatei = $derived(art === 'konfiguration' || art === 'zugangsdaten')
  /* The two pages of a file the service checks, the configuration and the
     tools file: their warning stands over the field, under the head. */
  const filePage = $derived(istDatei || istTools)
  /* The agent page has two faces: the list of agents, and the editor for
     one of them. A name means the editor is open. */
  const agentBearbeiten = $derived(istAgent && agentName !== '')
  /* The agents' list with the chosen agent beside it: it stands as tall as
     the page and scrolls inside itself, like the tools list. */
  const agentList = $derived(istAgent && !maske && !agentBearbeiten)
  const bearbeitet = $derived(istSystem || istGedaechtnis || istDatei || istTools || agentBearbeiten)
  /* The note stands only over a field that still holds what was saved. */
  const shownNote = $derived(saveNote && saveNote.saved === text ? saveNote : null)

  /* The sample under the settings of the look: a function of 23 lines, each
     line a list of pieces, a plain string or `[class, word]` with the class
     the highlighter would give the word, so the chosen colour pack paints it
     the way it paints a code block in the chat. */
  const kw = (word) => ['hljs-keyword', word]
  const fn = (word) => ['hljs-title function_', word]
  const str = (word) => ['hljs-string', word]
  const num = (word) => ['hljs-number', word]
  const lit = (word) => ['hljs-literal', word]
  const CODE_SAMPLE_LINES = [
    [['hljs-comment', '// Ask every server for its models and keep the fastest one.']],
    [kw('async'), ' ', kw('function'), ' ', fn('pickServer'), '(servers, timeoutMs = ', num('3000'), ') {'],
    ['  ', kw('const'), ' results = [];'],
    [],
    ['  ', kw('for'), ' (', kw('const'), ' server ', kw('of'), ' servers) {'],
    ['    ', kw('const'), ' started = performance.', fn('now'), '();'],
    [],
    ['    ', kw('try'), ' {'],
    ['      ', kw('const'), ' reply = ', kw('await'), ' ', fn('fetch'), '(', str('`${server.url}/v1/models`'), ', {'],
    ['        signal: AbortSignal.', fn('timeout'), '(timeoutMs),'],
    ['      });'],
    ['      ', kw('if'), ' (!reply.ok) ', kw('continue'), ';'],
    [],
    ['      ', kw('const'), ' { data } = ', kw('await'), ' reply.', fn('json'), '();'],
    ['      results.', fn('push'), '({ server, models: data.length, ms: performance.', fn('now'), '() - started });'],
    ['    } ', kw('catch'), ' (error) {'],
    ['      console.', fn('warn'), '(', str('`${server.name} did not answer:`'), ', error.message);'],
    ['    }'],
    ['  }'],
    [],
    ['  results.', fn('sort'), '((a, b) => a.ms - b.ms);'],
    ['  ', kw('return'), ' results[', num('0'), '] ?? ', lit('null'), ';'],
    ['}'],
  ]
  /* One flat run of pieces with the line breaks between them. */
  const CODE_SAMPLE = CODE_SAMPLE_LINES.flatMap((line, i) => [
    ...line.map((piece) => (typeof piece === 'string' ? ['', piece] : piece)),
    ['', i < CODE_SAMPLE_LINES.length - 1 ? '\n' : ''],
  ])

  const MODI = [
    ['auto', 'einstellungen.auto'],
    ['hell', 'einstellungen.hell'],
    ['dunkel', 'einstellungen.dunkel'],
    ['darkmatter', 'einstellungen.darkmatter'],
    ['heaven', 'einstellungen.heaven'],
    ['moune', 'einstellungen.moune'],
    ['snow', 'einstellungen.snow'],
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
  /* The card of the own gradient draws what the user has set, or the
     gradient's start. */
  const eigenBild = $derived(eigenVorschau(zustand.verlauf[EIGENER_VERLAUF], farbtonDrehen))
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
  /* The plain values of the settings (the memory switches, the picture
     protection, the numbers) are the shared module's: the phone page reads
     the same ones. */
  const values = useSettingsValues()
  const {
    gedaechtnisSchalten, bildschutzSchalten, helpersAtOnce, helperSteps,
  } = values
  const gedaechtnisSchalter = $derived(values.gedaechtnisSchalter)
  const bildschutzSchalter = $derived(values.bildschutzSchalter)

  /* The pill shows the stored choice: `texte.wahl` is reactive, and a
     switch writes it once its catalogue has arrived (`texte.svelte.js`), so
     the pill follows the texts — the return to "auto" included. The field is
     bound to that value for reading only: left to itself it would keep the
     entry that was clicked, whether or not the switch ever happened. */
  const sprachwahl = $derived(texte.wahl)
  const sprachauswahl = $derived([
    { wert: 'auto', text: t('einstellungen.sprache_auto') },
    { wert: 'en', text: t('einstellungen.sprache_englisch') },
    { wert: 'de', text: t('einstellungen.sprache_deutsch') },
  ])
  /* The figures behind the subtitles of the list live in one place the
     other pages that carry the list read as well (lib/settingsState.svelte.js).
     What this window holds as its own state is written in as it changes. */
  $effect(() => {
    settingsState.look = modus
  })
  $effect(() => {
    settingsState.memoryLocal = gedaechtnisSchalter.lokal
  })
  $effect(() => {
    settingsState.agents = dateien.length
  })
  function standLaden() {
    values.loadAll()
  }

  /* The pages of this window: each a sign and a title, as the list that
     leads to them names them (lib/einstellungsliste.js). */
  const EINTRAEGE = SEITEN

  // The shortcuts entry names the microphone key under its title, so the
  // stored key is read as soon as the settings are open.
  $effect(() => {
    diktatStandLaden()
  })

  function navZiel(key) {
    // The agent entry always opens the list first, never the last file.
    if (key === 'agent') return wechseln('agent', '')
    return wechseln(key)
  }
  /* The list of the settings (SettingsNav.svelte): its row "Updates" asks for
     a newer version and shows what came of it. */
  let nav = $state(null)
  /* What a row of the list does (lib/settingsrow.js). A page of this window is
     switched to, and asks first if an edit stands unsaved; the other menus
     open with the part the row names, which the page there reads once; the
     manual and the row of the updates do what their names say. */
  function zeileGewaehlt(zeile) {
    return chooseRow(zeile, { page: navZiel, look: () => nav?.look() })
  }

  /* A switch found by the search: its page opens like its row would open it,
     then the page scrolls to the switch. */
  let anspringenStopp = null
  async function schalterGewaehlt(feld) {
    const zeile = listenZeile(feld.zeile)
    anspringenStopp?.()
    await zeileGewaehlt(zeile)
    // A page the question "discard?" kept in place is not the page of the switch.
    if (zeile.ziel.art && art !== zeile.ziel.art) return
    anspringenStopp = schalterAnspringen(t(feld.titel))
  }

  $effect(() => {
    if (!offen) return
    const start = zustand.promptStart
    const [ziel, name] = Object.hasOwn(EINTRAEGE, start)
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
  const OHNE_DATEI = ['sprache', 'darstellung', 'meldungen', 'shortcuts', 'tools', 'werkzeuge', 'web_app', 'skills', 'cronjobs']

  async function laden(neueArt, name = '') {
    if (OHNE_DATEI.includes(neueArt) || (neueArt === 'agent' && !name)) {
      art = neueArt
      agentName = name
      text = ''
      geladen = ''
      kaputt = null
      unlesbar = null
      saveNote = null
      platzhalter = []
      return
    }
    laedt = true
    kaputt = null
    unlesbar = null
    saveNote = null
    platzhalter = []
    try {
      if (neueArt === 'system') {
        const daten = await api.systemPrompt()
        text = daten.text
      } else if (neueArt === 'memory') {
        const daten = await api.gedaechtnis()
        text = daten.text
        values.gedaechtnisStandLaden()
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
    const savedPage = art
    /* A save in flight takes the last answer down: a failure must not stand
       beside "saved", and a second save shows its answer anew. */
    saveNote = null
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
        if (art === savedPage) {
          saveNote = { key: kaputt ? 'dateien.gesichert_kaputt' : 'dateien.gesichert', caution: Boolean(kaputt), saved: geladen }
        }
      } else if (istTools) {
        const daten = await api.werkzeugKonfigurationSichern(text)
        geladen = daten.content
        if (text === gesendet) text = geladen
        kaputt = daten.kaputt
        platzhalter = daten.platzhalter
        if (art === savedPage) {
          saveNote = { key: kaputt ? 'werkzeuge.gesichert_kaputt' : 'werkzeuge.gesichert', caution: Boolean(kaputt), saved: geladen }
        }
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
    if (!(await frage(t('agenten.loeschen_frage', { name }), { danger: true, okSchluessel: 'agenten.delete_button' }))) return
    try {
      if (name !== agentName || geladen !== null) await api.agentLoeschen(name)
      meldeText('agenten.geloescht', { name }, 'erfolg')
      await dateienLaden()
      laden('agent', '')
    } catch {
      melde(t('agenten.nicht_gesichert'), 'fehler')
    }
  }

  const kopfEintrag = $derived(agentBearbeiten ? EINTRAEGE.agent : EINTRAEGE[art] ?? EINTRAEGE.system)
</script>

{#snippet warningBox()}
  <div class="warnung" class:above={filePage} transition:fade={{ duration: 120 }}>
    {#if filePage}<Leuchtpunkt farbe="rot" groesse={10} />{/if}
    <span>{unlesbar ?? t(filePage ? 'werkzeuge.kaputt' : 'agenten.kaputt', { grund: kaputt })}</span>
  </div>
{/snippet}

<Seitenrahmen {offen} beschriftung={t('editor.titel')}>
  <!-- The parts are built fresh each time the page opens, as in the window
       the page replaces: a window one of them opened (the MCP mask) must not
       outlive the page. What was typed stays all the same — it lives in this
       file, not in the parts. -->
  {#if offen}
  <Menueseite beschriftung={t('editor.titel')} fuellen festeHoehe={istWerkzeuge || istCronjobs || agentList || istDatei} fillsFoot={istCronjobs || agentList}>
    {#snippet liste()}
      <SettingsNav bind:this={nav} current={art} pick={zeileGewaehlt} jump={schalterGewaehlt} own />
    {/snippet}

    {#snippet kopf()}
      <div class="set-kopf">
        <span class="s2-zeichen gross"><Hauszeichen zeichen={kopfEintrag.zeichen} groesse={22} /></span>
        {#if istCronjobs}
          <!-- Only this page has a sentence at its title: the mark stands 6 px
               after the name and its sentence opens under the title. -->
          <div class="titelzelle"><h3>{t(kopfEintrag.titel)}</h3><InfoMark text={t('cronjobs.info_page')} /></div>
        {:else}
          <h3>{t(kopfEintrag.titel)}</h3>
        {/if}
        {#if istWerkzeuge}
          <!-- How many tools reach the model, from how many sources: a figure
               in words at the title, not a line above the list. -->
          <span class="zahlpille"><Standpille farbe="count">{t('werkzeuge.aktiv_zahl', aktivStand())}</Standpille></span>
        {/if}
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
      {#if filePage && (kaputt || unlesbar)}
        {@render warningBox()}
      {/if}
      {#if istSprache}
        <div class="kachelliste">
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.sprache')}
            </div>
            <div class="auswahl">
              <Auswahlfeld
                bind:wert={() => sprachwahl, () => {}}
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
        <h4 class="tafelkopf abschnitt">{t('einstellungen.erscheinungsbild')}</h4>
        <!-- The looks are always in sight, never behind a list: one card
             each, the chosen one marked. -->
        <Looktafel
          optionen={MODI.map(([wert, schluessel]) => [wert, t(schluessel)])}
          bind:wert={modus}
          beschriftung={t('einstellungen.erscheinungsbild')}
          eigen={eigenBild}
        />
        <div class="kachelliste unterteil">
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.blase')}
            </div>
            <div class="farbwahl">
              {#if zustand.blasenfarbe}
                <button class="ruecksetzer" onclick={() => blasenfarbeSetzen('')}>{t('einstellungen.blase_standard')}</button>
              {/if}
              <input type="color" aria-label={t('einstellungen.blase')}
                     value={zustand.blasenfarbe || blasenVorgabe} oninput={(e) => blasenfarbeSetzen(e.currentTarget.value)} />
            </div>
          </div>
          <div class="einstellkachel">
            <div class="zeilentext">{t('einstellungen.codefarben')}</div>
            <div class="auswahl">
              <Auswahlfeld
                bind:wert={() => zustand.codefarben, () => {}}
                eintraege={CODE_PACKS.map(([wert, schluessel]) => ({ wert, text: t(schluessel) }))}
                beschriftung={t('einstellungen.codefarben')}
                gewaehlt={(neu) => codefarbenSetzen(neu)}
              />
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
          <!-- The chat layout is not set here but over the real chat,
               where every change can be seen: the button closes the
               settings and opens the layout mode. It stands last. -->
          <div class="einstellkachel">
            <div class="zeilentext">
              {t('einstellungen.layout_modus')}
            </div>
            <button class="symbolknopf" onclick={layoutModusOeffnen}
                    aria-label={t('einstellungen.layout_modus')}
                    title={t('einstellungen.layout_modus')}>
              <Hauszeichen zeichen="ecken" groesse={22} />
            </button>
          </div>
        </div>
        <!-- A function in the chosen colours, set the way a code block in the
             chat is set, over the whole width under the settings. -->
        <pre class="code-sample hljs" aria-hidden="true"><code>{#each CODE_SAMPLE as [klasse, wort], i (i)}<span class={klasse}>{wort}</span>{/each}</code></pre>
      {:else if istSkills}
        <Skillmaske />
      {:else if istCronjobs}
        <!-- The page itself stands still: the schedules scroll in their own
             room and the scripts stay at the foot. -->
        <div class="cronjobseite">
          <SettingsCronjobs onzahlen={(aktiv, gesamt) => { settingsState.cronjobsAktiv = aktiv; settingsState.cronjobs = gesamt }} />
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
      {:else if isWebApp}
        <SettingsWebApp />
      {:else if istWerkzeuge}
        <!-- The tools, once a window of their own, right under the servers
             they come from. Their one way out leads next door. -->
        <Werkzeuge zuVerbindungen={() => navZiel('tools')} />
      {:else if istAgent && maske}
        <!-- A file that cannot be read gives the mask's place back and the
             list is read again: the page stands on what the service says
             of the file now, with its warning box, not on the list that was
             loaded while the file was still sound. -->
        <Agentenmaske agent={maske.agent} bind:geaendert={maskeGeaendert}
                      onfertig={maskeFertig} onabbrechen={() => (maske = null)}
                      onunlesbar={() => { maske = null; dateienLaden() }} />
      {:else if istAgent && !agentBearbeiten}
        <SettingsAgents {dateien} {helpersAtOnce} {helperSteps}
                        onbearbeiten={(agent) => (maske = { agent })}
                        onloeschen={(name) => agentLoeschen(name)} />
      {:else}
        <!-- The field carries its own floor of about six lines
             (WachsendesFeld): where the page gives no height to share out (a
             narrow window stacks everything into one column), it would
             otherwise shrink to its single row. -->
        <div class="editorboden" class:file={istDatei} class:tools={istTools}>
        <WachsendesFeld
          bind:this={feld}
          bind:wert={text}
          gesperrt={laedt}
          gedimmt={istSystem && ausgesetzt}
          quelle={istDatei || istTools || agentBearbeiten}
          platzhalter={istSystem ? t('systemprompt.platzhalter') : ''}
          beschriftung={t('editor.titel')}
          block={istTools}
          volleHoehe={!istTools}
        />
        </div>
      {/if}

      {#if !filePage && (kaputt || unlesbar)}
        {@render warningBox()}
      {/if}

      {#if istTools && platzhalter.length}
        <div class="keys">
          <div class="keys-title tafelkopf">{t('werkzeuge.keys_heading')}</div>
          <div class="keys-card">
            {#each platzhalter as eintrag (eintrag.name)}
              <div class="key-row">
                <Leuchtpunkt farbe={eintrag.gesetzt ? 'gruen' : 'rot'} groesse={10} />
                <span class="key-name">{'${' + eintrag.name + '}'}</span>
                <span class="key-state" class:set={eintrag.gesetzt} class:missing={!eintrag.gesetzt}>
                  {t(eintrag.gesetzt ? 'werkzeuge.platzhalter_gesetzt' : 'werkzeuge.platzhalter_fehlt')}
                  <!-- The sign says the state for a reader that cannot see it. -->
                  <span class="key-sign" role="img" aria-label={t(eintrag.gesetzt ? 'modell.schluessel_gesetzt' : 'modell.schluessel_fehlt')}>
                    <Hauszeichen zeichen={eintrag.gesetzt ? 'haken' : 'kreuz'} groesse={14} />
                  </span>
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      {#if istTools}
        <div class="lese">
          <div class="lesetitel tafelkopf">{t('werkzeuge.live')}</div>
          {#if lese && !lese.aktiv}
            <span class="leseleer">{t('werkzeuge.abgeschaltet')}</span>
          {:else if lese}
            {#if lese.server.length}
            <div class="live-card">
              {#each lese.server as server (server)}
                <div class="live-row">
                  <span class="server"><Leuchtpunkt farbe="gruen" groesse={10} />{server}</span>
                  <div class="werkzeugpillen">
                    {#each lese.werkzeuge.filter((w) => !w.builtin && w.server === server) as werkzeug (werkzeug.name)}
                      <span class="werkzeugpille">
                        <span class="pillenzeichen">
                          <Werkzeugzeichen name={werkzeug.name} server={werkzeug.server} eingebaut={false}
                                           logo={serverLogo(werkzeug.server)} />
                        </span>
                        <span class="pillenname">{werkzeug.anzeige ?? werkzeug.name}</span>
                      </span>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
            {/if}
          {/if}
        </div>
      {/if}

      {#if istGedaechtnis}
        <div class="row-tiles">
          <div class="schalterzeile">
            <div class="beschriftung mitmarke">{t('gedaechtnis.an_lokal')}<InfoMark text={t('gedaechtnis.info_an_lokal')} /></div>
            <Schalter an={gedaechtnisSchalter.lokal} beschriftung={t('gedaechtnis.an_lokal')} onschalten={(an) => gedaechtnisSchalten('lokal', an)} />
          </div>
          <div class="schalterzeile">
            <div class="beschriftung mitmarke">{t('gedaechtnis.an_cloud')}<InfoMark text={t('gedaechtnis.info_an_cloud')} /></div>
            <Schalter an={gedaechtnisSchalter.cloud} beschriftung={t('gedaechtnis.an_cloud')} onschalten={(an) => gedaechtnisSchalten('cloud', an)} />
          </div>
          <div class="schalterzeile">
            <div class="beschriftung mitmarke">{t('bildschutz.titel')}<InfoMark text={t('bildschutz.info_titel')} /></div>
            <Schalter an={bildschutzSchalter.an} beschriftung={t('bildschutz.titel')} onschalten={(an) => bildschutzSchalten(an)} />
          </div>
        </div>
      {/if}

      {#if istSystem}
        <div class="row-tiles">
          <div class="schalterzeile">
            <div class="beschriftung">{t('editor.anrede_titel')}
            </div>
            <input class="anredefeld" value={begruessung.name} placeholder={begruessung.vorschlag}
                   aria-label={t('editor.anrede_titel')}
                   onchange={(e) => anredeSpeichern(e.currentTarget.value, begruessung.an)} />
          </div>
          <div class="schalterzeile">
            <div class="beschriftung mitmarke">{t('editor.anrede_schalter')}<InfoMark text={t('editor.info_anrede_schalter')} /></div>
            <Schalter an={begruessung.an} beschriftung={t('editor.anrede_schalter')}
                      onschalten={(an) => anredeSpeichern(begruessung.name, an)} />
          </div>
          <div class="schalterzeile">
            <div class="beschriftung">{t('editor.werkzeugrunden_titel')}
            </div>
            <div class="zahlfeld">
              <Zahlenfeld bind:wert={values.werkzeugRunden} min={0} ganzzahlig
                          nullwort={t('parameter.auto')} />
            </div>
          </div>
          <div class="schalterzeile">
            <div class="beschriftung">{t('editor.befehlszeit_titel')}
            </div>
            <div class="zahlfeld">
              <Zahlenfeld bind:wert={values.befehlZeit} min={0} ganzzahlig
                          nullwort={t('parameter.auto')} />
            </div>
          </div>
          <div class="schalterzeile">
            <div class="beschriftung">{t('editor.kontextkomprimierung_titel')}
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
              <Zahlenfeld bind:wert={values.verdichtungSchwelle} min={0} max={85} ganzzahlig
                          nullwort={t('parameter.auto')} />
            </div>
          </div>
        </div>
      {/if}

      <div class="fuss">
        {#if istSystem || istGedaechtnis}
          <button class="textknopf" onclick={() => { text = ''; feld?.fokus() }}>{t('app.leeren')}</button>
        {:else if agentBearbeiten}
          <button class="textknopf gefahr" onclick={() => agentLoeschen()}>{t('agenten.loeschen')}</button>
        {:else}
          <!-- The answer of a save, where the signs stand: it may take two
               lines, the signs stay at the right. The live region is always
               there, so a screen reader announces what comes into it. -->
          <span class="save-note" class:caution={shownNote?.caution} role="status">{#if shownNote}{t(shownNote.key)}{/if}</span>
        {/if}
        <div class="rechts">
          {#if bearbeitet}
            <button class="symbolknopf" onclick={abbrechen}
                    aria-label={t('app.abbrechen')} title={t('app.abbrechen')}>
              <Hauszeichen zeichen="kreuz" groesse={18} />
            </button>
            <button class="symbolknopf" onclick={sichern}
                    aria-label={t('app.sichern')} title={t('app.sichern')}>
              <Hauszeichen zeichen="save" groesse={18} />
            </button>
          {/if}
        </div>
      </div>
    {/snippet}
  </Menueseite>
  {/if}
</Seitenrahmen>

<style>
  /* The page's mark: the sign in a 40 px box of button glass. */
  .s2-zeichen.gross {
    width: 40px;
    height: 40px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    /* The glass of a button with its fine line, drawn inside the box. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .set-kopf {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .titelzelle {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .titelzelle :global(.mark) {
    margin-left: 0;
  }
  .set-kopf h3 {
    font-size: var(--schrift-seitentitel);
    font-weight: 400;
    line-height: 1.3;
    color: var(--text);
    margin: 0;
  }
  /* 12 px from the title: the head's gap less two. */
  .zahlpille {
    display: inline-flex;
    margin-left: -2px;
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
  /* On the pages of a file the box stands under the head, over the field: no
     ground, a red edge, the red dot at the start of the sentence, the
     sentence in the quiet ink. */
  .warnung.above {
    flex: none;
    box-sizing: border-box;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin: 0 0 32px;
    padding: 12px 16px;
    border: 1px solid var(--rot);
    background: none;
    color: var(--text-leise);
    font-size: var(--schrift-hinweis);
    line-height: 1.2;
  }
  /* A long word in the service's reason breaks inside the box, not through its edge. */
  .warnung.above > span {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  /* The keys the tools file names: a heading over one field of button glass, a
     row for each, its name in the `${NAME}` notation (a key named by
     `api_key_env` is read the same way) on the left and on the right
     the file that holds the value, green with a check where it is there and red
     with a cross where it is not. The sign says it as well, so the colour is
     never the only mark. */
  .keys {
    margin-top: 32px;
  }
  /* Text itself: global.css, .tafelkopf. A heading is a band of 34 with its
     line in the middle, and the next block stands 32 below it. */
  .keys-title,
  .lesetitel {
    display: flex;
    align-items: center;
    height: 34px;
    margin-bottom: 32px;
    line-height: 1.35;
  }
  .keys-card,
  .live-card {
    padding: 0 16px;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-card);
  }
  .key-row {
    display: flex;
    align-items: center;
    gap: 10px;
    /* 16 px of content between two paddings of 12: the row is 40 high, and the
       line between two rows comes on top of that. */
    box-sizing: content-box;
    padding: 12px 0;
    min-height: 16px;
  }
  .key-row + .key-row {
    border-top: 1px solid var(--feldstrich);
  }
  .key-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--schrift-fest);
    font-size: 12px;
    color: var(--text-leise);
  }
  .key-state {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
  }
  .key-sign {
    display: inline-flex;
  }
  .key-state.set {
    color: var(--gruen-text);
  }
  .key-state.missing {
    color: var(--rot-text);
  }
  /* The tick and the cross are signs, not words: the colour of the shape. */
  .key-state.set .key-sign {
    color: var(--gruen);
  }
  .key-state.missing .key-sign {
    color: var(--rot);
  }

  /* What is live: a field like the key list, a row for each connected
     server with its dot, its name and, at the right, its tools as pills. */
  .lese {
    margin-top: 32px;
  }
  .live-row {
    display: flex;
    align-items: center;
    gap: 8px;
    /* The pill is 28 high between two paddings of 12: the row is 52 high. */
    box-sizing: content-box;
    padding: 12px 0;
    min-height: 28px;
  }
  .live-row + .live-row {
    border-top: 1px solid var(--feldstrich);
  }
  .server {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    flex: 0 0 auto;
    max-width: 40%;
    overflow-wrap: anywhere;
    font-family: var(--schrift-fest);
    font-size: 12px;
    color: var(--text-leise);
  }
  .werkzeugpillen {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
    margin-left: auto;
    min-width: 0;
  }
  /* A tool of the server: its mark and the name the server gives it, in the
     tool face; 1 px rim, so the pill is 28 high with a line of 16. */
  .werkzeugpille {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 5px 11px 5px 10px;
    border: 1px solid var(--linie);
    border-radius: 9px;
    background: var(--glass-button);
    font-family: var(--schrift-fest);
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    color: var(--text);
    white-space: nowrap;
    max-width: 100%;
  }
  /* A name longer than the room of the row is cut with dots, so the pill
     never leaves the field. */
  .pillenname {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pillenzeichen {
    --wz-groesse: 14px;
    display: inline-flex;
    flex: none;
    width: 14px;
    height: 14px;
  }
  .leseleer {
    font-size: 12px;
    color: var(--text-still);
  }

  /* The settings under an editor as a row of tiles, each a card of glass
     with its fine line: equally wide, as high as the tallest of them, 12 px
     apart; where the room runs out they wrap into a second row. */
  .row-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
    margin-top: 14px;
  }
  .schalterzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 16px;
    background: var(--glass-card);
    border-radius: 9px;
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .beschriftung {
    flex: 1;
    min-width: 0;
    font-size: 13px;
  }
  /* The mark right after the name, 6 px away, and its sentence on a line of
     its own below the name when it is open. */
  .mitmarke {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .mitmarke :global(.mark) {
    margin-left: 0;
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
  /* The heading over the row of looks. */
  .abschnitt {
    margin: 0 0 10px;
  }
  .unterteil {
    margin-top: 20px;
  }
  /* The sample under the settings of the look: a block of code on the
     ground the chosen colour pack gives it, over the whole width. */
  .code-sample {
    box-sizing: border-box;
    margin: 16px 0 0;
    padding: 20px 24px;
    border-radius: 9px;
    background: var(--code-grund);
    font: 13px/1.65 var(--schrift-fest);
    overflow: auto;
  }
  .code-sample code {
    white-space: pre;
  }
  /* A button with a sign and no word: the layout mode's way in and the foot
     of the text pages (cancel, save). */
  .symbolknopf {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    color: var(--text);
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    border: none;
    border-radius: 9px;
    cursor: pointer;
  }
  .symbolknopf:hover {
    background: var(--glass-hover);
  }
  .symbolknopf:active {
    transform: scale(0.95);
  }
  .symbolknopf:focus-visible {
    outline: 2px solid var(--text);
    outline-offset: 2px;
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
    display: flex;
    flex-direction: column;
  }
  /* The configuration and the credentials fill the page down to the foot,
     and the field ends this far above it. */
  .editorboden.file {
    margin-bottom: 18px;
  }
  /* The tools file: a field of 420 that scrolls in itself (4 of padding and
     1 of rim on each side of the text area), and the room that is left stands
     at the foot, where more keys will come. */
  .editorboden.tools {
    flex: none;
  }
  .editorboden.tools :global(.feld.block textarea) {
    height: 410px;
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
    flex: none;
  }
  /* The answer of a save in the foot: quiet text, brightness only; the
     caution (saved but not applied) takes the quiet yellow of the house. */
  .save-note {
    flex: 1;
    min-width: 0;
    padding-right: 16px;
    font-size: 12.5px;
    line-height: 1.4;
    color: var(--text-leise);
  }
  .save-note.caution {
    color: var(--gelb-text);
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
  /* Fills the frame down to its foot (`fillsFoot` on the frame), so the
     scripts sit low without touching the edge. */
  .cronjobseite {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  /* The scripts' part under the schedules, set off like a part of a view.
     It takes the room its scripts need up to a third of the page, and
     scrolls inside beyond that: the schedules above it keep the rest. */
  .skriptteil {
    flex: 0 1 auto;
    max-height: 33%;
    overflow-y: auto;
    margin-top: 22px;
  }
  .skriptteil h4 {
    margin: 0 0 10px;
  }
</style>
