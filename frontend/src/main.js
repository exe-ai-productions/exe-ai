import { mount } from 'svelte'
import App from './App.svelte'
import { bootMessage } from './lib/api.js'
import { texteLaden } from './lib/texte.svelte.js'
// DIAGNOSIS — see lib/geometriewache.js.
import { geometriewacheStarten } from './lib/geometriewache.js'
import './stil/global.css'
import './stil/codefarben.css'
import './stil/codeblock.css'
import './stil/tiles.css'
import './stil/berichttext.css'

/* Texts first, then the window.

   If we render first and the catalog arrives afterwards, the keys flash up
   for a moment ("chat.neu" instead of "Neuer Chat"). The catalogs are a few
   kilobytes and come from the same server as everything else — wait for
   them and you never see that state.

   Deliberately inside a function rather than a top-level `await`: the bundle
   is built for browsers that don't know top-level await, and the build
   breaks on it.

   If loading fails, the service isn't running — then the reason in plain
   text is more helpful than an empty window. The sentence around it comes
   with the page (app/main.py), in the language the service knows for the
   interface; this file writes none of its own. */
async function starten() {
  const wurzel = document.getElementById('wurzel')
  try {
    await texteLaden()
  } catch (fehler) {
    wurzel.textContent = bootMessage(fehler)
    throw fehler
  }
  const app = mount(App, { target: wurzel })
  /* Only where a config asked for it: the watch paints a report panel
     over the app and writes marker lines into the service log — a
     diagnosis tool for a test service, not something a shipped install
     runs. The flag travels in beside the session key (app/main.py). */
  if (window.__DIAGNOSE__) geometriewacheStarten()
  return app
}

export default starten()
