/*
  The kinds of tool, for the row that says what an agent may do.

  The row used to draw one mark per tool: thirty-four tools were thirty-four
  marks, several of them the same drawing twice, and a tool nobody had
  entered in the catalogue stood there as a loose grey chevron. What an agent
  may do is said in a handful of kinds — web, files, terminal and so on — so
  the row draws each kind once, with how many tools it covers.

  Everything the catalogue does not know ends in the last kind, `weitere`,
  which wears the grey chevron an unknown tool always wore.

  Which mark a kind draws is not decided here: each kind names one tool (or
  one server) whose mark it borrows from lib/werkzeugkatalog.js, so a mark
  that changes there changes here.
*/

/* In the order they are shown. `zeichen` is the tool and server whose mark the
   kind draws; `weitere` borrows nothing and gets the catalogue's fallback. */
export const ARTEN = [
  { art: 'web', zeichen: { name: 'web_search', server: '' } },
  { art: 'dateien', zeichen: { name: 'read_file', server: '' } },
  { art: 'terminal', zeichen: { name: 'run_command', server: '' } },
  { art: 'suche', zeichen: { name: 'search_files', server: '' } },
  { art: 'bilder', zeichen: { name: 'generate_image', server: '' } },
  { art: 'gedaechtnis', zeichen: { name: 'memory_save', server: '' } },
  { art: 'github', zeichen: { name: '', server: 'github' } },
  { art: 'gmail', zeichen: { name: '', server: 'gmail' } },
  { art: 'weitere', zeichen: { name: '', server: '' } },
]

/* By tool name — the tools the house itself ships. */
const NACH_WERKZEUG = {
  web_search: 'web',
  read_webpage: 'web',
  run_command: 'terminal',
  read_file: 'dateien',
  write_file: 'dateien',
  edit_file: 'dateien',
  list_dir: 'dateien',
  create_folder: 'dateien',
  deliver_file: 'dateien',
  search_files: 'suche',
  draw_image: 'bilder',
  generate_image: 'bilder',
  image_to_image: 'bilder',
  inpaint_image: 'bilder',
  remove_background: 'bilder',
  memory_save: 'gedaechtnis',
}

/* By the server a tool came from, the name from mcp_servers.json. */
const NACH_SERVER = {
  websuche: 'web',
  searxng: 'web',
  recraft: 'bilder',
  github: 'github',
  gmail: 'gmail',
}

/** The kind a tool belongs to; a tool nobody entered belongs to `weitere`. */
export function artFuer(name = '', server = '') {
  return NACH_WERKZEUG[name] ?? NACH_SERVER[server] ?? 'weitere'
}

/**
 * The tools grouped into kinds, in the order of ARTEN, empty kinds left out.
 * Each entry says the kind, how many tools it covers, their names (for the
 * pointer and for a screen reader) and the mark to draw.
 */
export function werkzeugarten(werkzeuge = []) {
  const gruppen = new Map()
  for (const werkzeug of werkzeuge) {
    const art = artFuer(werkzeug.name, werkzeug.server)
    if (!gruppen.has(art)) gruppen.set(art, [])
    gruppen.get(art).push(werkzeug.name)
  }
  return ARTEN.filter(({ art }) => gruppen.has(art)).map(({ art, zeichen }) => ({
    art,
    anzahl: gruppen.get(art).length,
    namen: gruppen.get(art),
    zeichen,
  }))
}
