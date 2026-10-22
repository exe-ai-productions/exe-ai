/*
  The list of the settings, in the order it stands in the sidebar.

  Five groups, each a heading over its rows. A row names its sign, the title
  (a catalogue key) and where it leads:

    art     a page of the settings window itself (SystemPrompt.svelte)
    menu    one of the other menu pages — the local models, the cloud
            providers, the catalogue — and, where it has one, the part of
            it to show: `server` (one of the names below) for a server's
            page on the local models, none for the local models
            themselves, `seite` for the catalogue
    hilfe   the manual
    update  the look for a newer version of the program

  A row marked `desktopOnly` has no counterpart on the phone's settings page.

  The `server` names are the ones ModelleLokal.svelte names its server
  windows by; a test holds the two lists together.
*/

/* The six servers, in the order the local page has always listed them. */
export const SERVER = [
  { name: 'server', titel: 'modell.server', zeichen: 'server' },
  { name: 'agent', titel: 'agentserver.titel', zeichen: 'agent' },
  { name: 'einbettung', titel: 'einbettungsserver.titel', zeichen: 'einbettung' },
  { name: 'sprache', titel: 'sprachserver.titel', zeichen: 'sprache_welle' },
  { name: 'bereinigung', titel: 'bereinigungsserver.titel', zeichen: 'besen' },
  { name: 'bild', titel: 'bildserver.titel', zeichen: 'bild' },
]

/* `zeichen` is a drawn sign of the house (Hauszeichen.svelte), `fenster` a
   window sign (Fensterzeichen.svelte); a row has one of the two. */
export const GRUPPEN = [
  {
    name: 'oberflaeche',
    titel: 'einstellungen.gruppe_oberflaeche',
    zeilen: [
      { id: 'darstellung', zeichen: 'palette', titel: 'editor.quelle_darstellung', ziel: { art: 'darstellung' } },
      { id: 'sprache', zeichen: 'sprache', titel: 'editor.quelle_sprache', ziel: { art: 'sprache' } },
      { id: 'meldungen', zeichen: 'glocke', titel: 'meldewesen.quelle', ziel: { art: 'meldungen' } },
      { id: 'shortcuts', zeichen: 'keyboard', titel: 'shortcuts.title', ziel: { art: 'shortcuts' } },
    ],
  },
  {
    name: 'verhalten',
    titel: 'einstellungen.gruppe_verhalten',
    zeilen: [
      { id: 'system', zeichen: 'feder', titel: 'agenten.quelle_system', ziel: { art: 'system' } },
      { id: 'memory', zeichen: 'speicherriegel', titel: 'gedaechtnis.quelle', ziel: { art: 'memory' } },
      { id: 'skills', zeichen: 'buch', titel: 'skills.quelle', ziel: { art: 'skills' } },
      { id: 'cronjobs', zeichen: 'stopwatch', titel: 'cronjobs.quelle', ziel: { art: 'cronjobs' } },
      { id: 'agent', zeichen: 'person', titel: 'editor.quelle_agenten', ziel: { art: 'agent' } },
    ],
  },
  {
    name: 'modelle',
    titel: 'einstellungen.gruppe_modelle',
    zeilen: [
      { id: 'lokal', zeichen: 'raster', titel: 'einstellungen.lokale_modelle', ziel: { menu: 'lokal' } },
      { id: 'cloud', fenster: 'cloud', titel: 'einstellungen.cloud_anbieter', ziel: { menu: 'cloud' } },
      { id: 'katalog', fenster: 'katalog', titel: 'menue.katalog', ziel: { menu: 'katalog', seite: 'chat' } },
      { id: 'downloads', zeichen: 'download', titel: 'downloads.titel', ziel: { menu: 'katalog', seite: 'downloads' } },
    ],
  },
  {
    name: 'server',
    titel: 'einstellungen.gruppe_server',
    zeilen: [
      { id: 'overview', zeichen: 'ranking_bars', titel: 'server_overview.row', ziel: { menu: 'lokal', server: 'overview' } },
      ...SERVER.map((s) => ({
        id: `server:${s.name}`,
        zeichen: s.zeichen,
        titel: s.titel,
        ziel: { menu: 'lokal', server: s.name },
      })),
      { id: 'tools', zeichen: 'plug', titel: 'editor.quelle_tools', ziel: { art: 'tools' } },
      { id: 'werkzeuge', zeichen: 'werkzeug', titel: 'werkzeuge.titel', ziel: { art: 'werkzeuge' } },
      { id: 'web_app', zeichen: 'handy', titel: 'webapp.title', ziel: { art: 'web_app' }, desktopOnly: true },
    ],
  },
  {
    name: 'system',
    titel: 'einstellungen.gruppe_system',
    zeilen: [
      { id: 'zugangsdaten', zeichen: 'schluessel', titel: 'editor.quelle_zugangsdaten', ziel: { art: 'zugangsdaten' } },
      { id: 'konfiguration', zeichen: 'dokument', titel: 'editor.quelle_konfiguration', ziel: { art: 'konfiguration' } },
      { id: 'tools_datei', zeichen: 'dokument_pfeil', titel: 'editor.quelle_tools_datei', ziel: { art: 'tools_datei' } },
      { id: 'hilfe', zeichen: 'hilfe', titel: 'menue.hilfe', ziel: { hilfe: true } },
      { id: 'updates', zeichen: 'update_available', titel: 'einstellungen.updates', ziel: { update: true } },
    ],
  },
]

/* The pages of the settings window itself — the rows that lead to one — by the
   name of the page: its sign and the catalogue key of its title. The page head
   and the phone's list read their signs and titles from here. */
export const SEITEN = Object.fromEntries(
  GRUPPEN.flatMap((gruppe) => gruppe.zeilen)
    .filter((z) => z.ziel.art)
    .map((z) => [z.ziel.art, { zeichen: z.zeichen, titel: z.titel }]),
)

/* The switches the search finds by name: each names the row whose page holds
   it (an id of GRUPPEN) and the catalogue key of the switch's label. Only the
   switches that stand on their page for good are here — a switch a list makes
   for every entry (one per schedule, one per tool) has no name of its own.
   A test holds this list to the pages' own markup. */
export const FELDER = [
  { zeile: 'meldungen', titel: 'meldewesen.toene' },
  { zeile: 'meldungen', titel: 'meldewesen.nur_hintergrund' },
  { zeile: 'meldungen', titel: 'meldewesen.fertig' },
  { zeile: 'meldungen', titel: 'meldewesen.wartet' },
  { zeile: 'meldungen', titel: 'meldewesen.fehler' },
  { zeile: 'meldungen', titel: 'meldewesen.punkt_agenten' },
  { zeile: 'meldungen', titel: 'meldewesen.punkt_cronjob' },
  { zeile: 'meldungen', titel: 'meldewesen.punkt_terminal' },
  { zeile: 'meldungen', titel: 'meldewesen.punkt_chat' },
  { zeile: 'meldungen', titel: 'meldewesen.popups_aus' },
  { zeile: 'system', titel: 'editor.anrede_schalter' },
  { zeile: 'memory', titel: 'gedaechtnis.an_lokal' },
  { zeile: 'memory', titel: 'gedaechtnis.an_cloud' },
  { zeile: 'memory', titel: 'bildschutz.titel' },
  { zeile: 'skills', titel: 'skills.selbst' },
  { zeile: 'server:server', titel: 'modell.feld_kv' },
  { zeile: 'server:server', titel: 'modell.feld_mlock' },
  { zeile: 'server:server', titel: 'modell.laeuft_gerade' },
  { zeile: 'server:server', titel: 'modell.fuer_agenten' },
  { zeile: 'server:server', titel: 'modell.feld_kv_unified' },
  { zeile: 'server:sprache', titel: 'sprachserver.feld_automatik' },
  { zeile: 'server:sprache', titel: 'sprachserver.feld_vorlesen' },
  { zeile: 'server:sprache', titel: 'sprachserver.keep_model_loaded' },
]

/* The row an id names, or null. */
export function zeile(id) {
  for (const gruppe of GRUPPEN) {
    const treffer = gruppe.zeilen.find((z) => z.id === id)
    if (treffer) return treffer
  }
  return null
}
