/*
  The rows of the settings page of the phone: the groups and, in each, the
  entries in the order the desktop's settings window lists them, every entry
  with its sign and the catalogue key of its name.

  No imports on purpose: the table is plain data, so a test can run it and
  hold it against the desktop's own list, and no entry can go missing
  without one of them noticing.
*/

export const ENTRIES = {
  sprache: { sign: 'sprache', title: 'editor.quelle_sprache' },
  darstellung: { sign: 'palette', title: 'editor.quelle_darstellung' },
  meldungen: { sign: 'glocke', title: 'meldewesen.quelle' },
  shortcuts: { sign: 'keyboard', title: 'shortcuts.title' },
  memory: { sign: 'speicherriegel', title: 'gedaechtnis.quelle' },
  skills: { sign: 'buch', title: 'skills.quelle' },
  cronjobs: { sign: 'stopwatch', title: 'cronjobs.quelle' },
  system: { sign: 'feder', title: 'agenten.quelle_system' },
  agent: { sign: 'person', title: 'editor.quelle_agenten' },
  tools: { sign: 'plug', title: 'editor.quelle_tools' },
  werkzeuge: { sign: 'werkzeug', title: 'werkzeuge.titel' },
  zugangsdaten: { sign: 'schluessel', title: 'editor.quelle_zugangsdaten' },
  konfiguration: { sign: 'dokument', title: 'editor.quelle_konfiguration' },
  tools_datei: { sign: 'dokument_pfeil', title: 'editor.quelle_tools_datei' },
}

/* The groups of the desktop's list that lead to a page of the settings, with
   those pages in its order. The models and the six servers have pages of
   their own on the phone, so that group and those rows are not here. */
export const GROUPS = [
  { name: 'oberflaeche', title: 'einstellungen.gruppe_oberflaeche', entries: ['darstellung', 'sprache', 'meldungen', 'shortcuts'] },
  { name: 'verhalten', title: 'einstellungen.gruppe_verhalten', entries: ['system', 'memory', 'skills', 'cronjobs', 'agent'] },
  { name: 'server', title: 'einstellungen.gruppe_server', entries: ['tools', 'werkzeuge'] },
  { name: 'system', title: 'einstellungen.gruppe_system', entries: ['zugangsdaten', 'konfiguration', 'tools_datei'] },
]

/* The entries that are a file the person edits as text. */
export const TEXT_KINDS = ['system', 'memory', 'konfiguration', 'zugangsdaten', 'tools_datei']

/* The look the phone page shows for what the desktop stands on: Exe, Pearl
   and Snow are the three it draws, whatever else the desktop holds reads as
   Exe. */
export function shownLook(mode) {
  return ['auto', 'hell', 'snow'].includes(mode) ? mode : 'dunkel'
}
