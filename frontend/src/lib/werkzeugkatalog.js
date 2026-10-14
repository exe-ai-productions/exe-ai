/*
  Which mark belongs to which tool — the catalogue.

  Its own module, because the answer must be the same everywhere it is asked
  (chat row, job log, tool overview) and because the rule is data, not markup.

  Three steps, from certain to uncertain:

  1. THE TOOL BY NAME. An exact entry always wins. This is where a tool goes
     that deserves its own mark regardless of where it comes from.

  2. THE SERVER. Every tool the registry offers knows which server it came
     from, and that name is fixed in mcp_servers.json — it cannot be guessed
     wrong. A tool of the Notion server gets the Notion mark, whatever it is
     called. This is the step that makes the catalogue reliable instead of
     clever: a new server tool that nobody has seen yet still lands right.

  3. THE NAME PATTERN. Only for what arrives without a known server — a tool
     from a server someone registered by hand. Order matters here, because
     `search_repositories` and `model_search` both contain "search".

  Whatever survives all three keeps the gray chevron. That is the honest
  answer, not a placeholder to be forgotten: an unknown tool should look
  unknown.
*/

import { ownName } from './mcpWerkzeuge.js'

/* Step 1 — by tool name. */
const NACH_WERKZEUG = {
  web_search: 'globus',
  read_webpage: 'globus',
  run_command: 'eingabe',
  read_file: 'seite',
  search_files: 'lupe',
  write_file: 'stift',
  edit_file: 'stiftlinie',
  list_dir: 'ordner',
  create_folder: 'ordner',
  ask_user: 'question',
  draw_image: 'bild',
  draw_video: 'clapperboard',
  generate_image: 'bild',
  image_to_image: 'bild',
  inpaint_image: 'bild',
  remove_background: 'freistellen',
  memory_save: 'wolke',
  deliver_file: 'seite',
}

/* Step 2 — by server, the name from mcp_servers.json. The one entry a new
   server needs; without it its tools fall through to the patterns. A server
   may name one of the house's standing signs instead of a drawn tool mark:
   the row draws that sign in the tool colour, and no server needs a drawing
   made for it alone. */
const NACH_SERVER = {
  websuche: 'globus',
  searxng: 'globus',
  notion: 'seite',
  recraft: 'bild',
  github: 'verzweigung',
  gmail: 'brief',
  figma: 'flaechen',
  huggingface: 'paket',
  slack: 'sprechblase',
  calendar: 'stoppuhr',
  drive: 'ordner',
  canva: 'palette',
  spotify: 'sprache_welle',
  todoist: 'haken',
  trello: 'raster',
  asana: 'haken',
  linear: 'ordner',
  clickup: 'haken',
  airtable: 'raster',
  vercel: 'wolke',
  sentry: 'glocke',
}

/* Step 2 for a BUILT-IN source — the three names whose mark belongs to the
   house and not to a server: the shell, the memory, the skills. They stand
   apart from NACH_SERVER because a server of one's own may carry the same
   name: a foreign server called "shell" wears the built-in shell's mark the
   moment both are read from one table, and the two rows then look alike
   although one of them is not even switchable. Which of the two is meant is
   not a question for the name but for the source's kind, so the caller hands
   it over (`eingebaut`). */
const NACH_EINGEBAUT = {
  shell: 'eingabe',
  memory: 'wolke',
  skills: 'buch',
}

/* Step 3 — by name pattern, for tools whose server we do not know. */
const NACH_MUSTER = [
  [/^(API-|notion-)/, 'seite'],
  [/^(gmail|.*_(email|draft))|(^|_)(send_message|messages?_(send|list|get)|threads?_)/, 'brief'],
  [/(repo|issue|pull_request|commit|branch|gist|workflow|fork)/, 'verzweigung'],
  [/(figma|design_context|node|frame)/, 'flaechen'],
  [/(model|dataset|paper|space)_?(search|detail|info|list)/, 'paket'],
]

export const RUECKFALL = 'winkel'

/**
 * The mark for a tool — or for a source that draws one of its own.
 *
 * `server` is what makes this dependable — pass it whenever it is known.
 * Without it the catalogue still answers, just with less certainty.
 *
 * `eingebaut` says the server is one of the house's own sources rather than
 * a server somebody registered. It decides which name table step 2 reads:
 * the two carry the same names, and only the kind tells them apart.
 *
 * `null` — the caller does not know, as the tool rows of a chat cannot —
 * reads the house's table first. For the three names in both that is the
 * answer the one table gave before, so nothing loses its mark for not
 * knowing; what the kind adds is the DIFFERENCE, and only the caller who
 * knows it can draw it.
 */
export function zeichenFuer(rohname = '', server = '', eingebaut = null) {
  /* A server's tool reaches the chat under the server's own word (the
     program shows that), the lists and the window under
     `mcp__<server>__<tool>` — the mark is the same for both. */
  const name = ownName(rohname, server)
  if (NACH_WERKZEUG[name]) return NACH_WERKZEUG[name]
  const nachServer =
    eingebaut === true
      ? NACH_EINGEBAUT[server]
      : eingebaut === false
        ? NACH_SERVER[server]
        : NACH_EINGEBAUT[server] ?? NACH_SERVER[server]
  if (server && nachServer) return nachServer
  for (const [muster, zeichen] of NACH_MUSTER) {
    if (muster.test(name)) return zeichen
  }
  return RUECKFALL
}

/** Which servers the catalogue answers for — the registered ones and the
    house's own, for the preview page and for tests. The two tables carry
    names, not kinds: which of them a name is is the caller's to say. */
export function bekannteServer() {
  return [...new Set([...Object.keys(NACH_EINGEBAUT), ...Object.keys(NACH_SERVER)])]
}
