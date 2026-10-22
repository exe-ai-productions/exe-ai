/*
  What the rows of the settings list show at their right edge: the short quiet
  value (the language, "6/6" skills, the microphone key) and, where a state is
  worth one, the colour of the dot.

  The list stands on more than one page — the settings, the local models and
  the server pages — and every one of them must show the same figures, so the
  figures live here once. The settings window keeps them current while it is
  open (the look, the memory switch, the agents and the schedules are its own
  state and are written in as they change); a page without them asks for them
  when its list appears.
*/
import { api } from './api.js'
import { t, texte } from './texte.svelte.js'
import { klangwahl } from './klaenge.svelte.js'
import { diktat, standLaden as diktatStandLaden } from './diktat.svelte.js'
import { DEFAULT_KEY, showCombo } from './microphoneKey.js'
import { layout } from './keyboardLayout.svelte.js'
import { keyNames } from './keyNames.js'
import { werkzeugeLaden, anzahlAlle, anzahlAn, serverStand } from './werkzeuge.svelte.js'
import { SERVER } from './einstellungsliste.js'
import { serverActive } from './serverstand.svelte.js'
import { WEB_APP_VERSION } from './webAppVersion.js'

export const settingsState = $state({
  skills: 0,
  skillsAngeboten: 0,
  skillsAuto: true,
  cronjobs: 0,
  cronjobsAktiv: 0,
  agents: 0,
  /* Whether the memory travels to the local models. */
  memoryLocal: true,
  /* The look the program wears, as the settings window names it. */
  look: 'auto',
})

/** Asks for the figures the list shows; a figure that cannot be read stays as it
 *  was. `own`: the caller keeps the memory switch and the agents current as they
 *  change, so a read that may land after such a change is left out. */
export function loadSettingsState({ own = false } = {}) {
  werkzeugeLaden()
  diktatStandLaden()
  api.skillsVerwaltung().then((list) => {
    settingsState.skills = list.length
    settingsState.skillsAngeboten = list.filter((e) => e.auto).length
  }).catch(() => {})
  api.cronjobs().then((list) => {
    settingsState.cronjobs = list.length
    settingsState.cronjobsAktiv = list.filter((e) => e.aktiv).length
  }).catch(() => {})
  api.einstellungAufgeloest('skills_auto').then((s) => {
    if (s?.wert && typeof s.wert.an === 'boolean') settingsState.skillsAuto = s.wert.an
  }).catch(() => {})
  if (own) return
  api.einstellungAufgeloest('gedaechtnis').then((s) => {
    if (typeof s?.wert?.lokal === 'boolean') settingsState.memoryLocal = s.wert.lokal
  }).catch(() => {})
  api.agentDateien().then((list) => {
    settingsState.agents = list.length
  }).catch(() => {})
}

/** The quiet value at the right of the row with this id. */
export function rowValue(id) {
  switch (id) {
    case 'sprache':
      return t(texte.sprache === 'de' ? 'einstellungen.sprache_deutsch' : 'einstellungen.sprache_englisch')
    case 'meldungen':
      return t(klangwahl.aus ? 'einstellungen.toene_aus' : 'einstellungen.toene_an')
    case 'darstellung':
      return t('einstellungen.' + settingsState.look)
    case 'shortcuts':
      return `${t('shortcuts.group_microphone')} ${showCombo(diktat.microphone_key || DEFAULT_KEY, layout.map, keyNames())}`
    case 'skills':
      // The skills the model is offered by itself, of all there are.
      return `${settingsState.skillsAuto ? settingsState.skillsAngeboten : 0}/${settingsState.skills}`
    case 'cronjobs':
      return `${settingsState.cronjobsAktiv}/${settingsState.cronjobs}`
    case 'agent':
      return t('agenten.created_count', { n: settingsState.agents })
    case 'overview':
      // The local servers that run, of the six.
      return `${SERVER.filter((server) => serverActive(server.name)).length}/${SERVER.length}`
    case 'tools':
      return `${serverStand().aktiv}/${serverStand().alle}`
    case 'werkzeuge':
      return `${anzahlAn()}/${anzahlAlle()}`
    case 'web_app':
      return WEB_APP_VERSION
    // The dot of the memory row already says on or off; a sentence beside it said it twice.
    default:
      return ''
  }
}

/** The dot of the row with this id: a colour, or null where there is no state worth one. */
export function rowDot(id) {
  switch (id) {
    case 'memory':
      return settingsState.memoryLocal ? 'gruen' : 'still'
    case 'skills':
      return settingsState.skillsAuto ? 'gruen' : 'still'
    case 'cronjobs':
      return settingsState.cronjobsAktiv > 0 ? 'gruen' : 'still'
    case 'tools':
      return serverStand().aktiv > 0 ? 'gruen' : 'still'
    default:
      return null
  }
}
