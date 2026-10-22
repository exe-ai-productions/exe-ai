/*
  The logo a server of one's own sent along when it connected.

  The service checks it (app/tools/mcp_logo.py) and hands it over as a data
  URL in the server list; this is the one place the tool rows and the
  notices ask for it. A shipped server keeps its maker's own vector, so a
  name the catalogue knows never takes a logo from here; a server without
  one, or with one that did not pass, answers null and the house's mark
  stands.

  The list is loaded once for whoever asks first, and once more for a name
  it did not hold: a server connected after the list was read.
*/
import { SERVERKATALOG } from './serverkatalog.js'
import { ownerLogo } from './logos.js'
import { werkzeugeLaden, werkzeugwahl } from './werkzeuge.svelte.js'

const KATALOGNAMEN = new Set(SERVERKATALOG.map((k) => k.name))
let geladen = false
let laedt = false
const nachgefragt = new Set()

function laden() {
  laedt = true
  werkzeugeLaden().finally(() => { laedt = false })
}

export function serverLogo(name) {
  if (!name || KATALOGNAMEN.has(name)) return null
  const eintrag = werkzeugwahl.server.find((s) => s.name === name)
  if (!geladen) {
    geladen = true
    laden()
  } else if (!eintrag && !laedt && !nachgefragt.has(name)) {
    /* Not while a load is on its way: the answer may hold the name, and the
       rows draw again once it has arrived. */
    nachgefragt.add(name)
    laden()
  }
  return eintrag?.logo ?? null
}

/* The house's own sources: a call of a built-in tool reaches the chat with
   the name of its source (`shell`, `memory`, …) — the same word a server of
   one's own may be called, and such a server never lends its logo to them. */
const BUILT_IN_SOURCES = new Set(['clock', 'cronjob', 'dock', 'goal', 'image', 'memory', 'shell', 'skills'])

/* The mark a call row wears for the server that ran it: the maker's vector
   for a name the catalogue knows, the checked image for a server of one's
   own, nothing for a built-in tool and for a server without a logo. */
export function serverMark(name) {
  if (!name || BUILT_IN_SOURCES.has(name)) return null
  const vector = KATALOGNAMEN.has(name) ? ownerLogo(name) : null
  if (vector) return { vector }
  const image = serverLogo(name)
  return image ? { image } : null
}
