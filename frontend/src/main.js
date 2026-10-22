import { mount, unmount } from 'svelte'
import App from './App.svelte'
import Anmeldung from './teile/Anmeldung.svelte'
import Phone from './phone/Phone.svelte'
import PhoneSignIn from './phone/SignIn.svelte'
import { isPhoneNow, watchDevice } from './phone/device.js'
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
/* A service beyond the loopback address hands its key out only against
   the password (app/anmeldung.py): its page comes without a key, and the
   sign-in stands alone on it until it has one. Before the catalogue, which
   is itself behind the key — so the sign-in's words come with the page
   (`window.__TEXTE__`). Resolves once the key is kept (lib/api.js). The
   phone page has a sign-in of its own, as a page and not as a card. */
function signIn(wurzel, phone) {
  return new Promise((resolve) => {
    const mask = mount(phone ? PhoneSignIn : Anmeldung, {
      target: wurzel,
      props: {
        texts: window.__TEXTE__ ?? {},
        done: () => {
          unmount(mask)
          resolve()
        },
      },
    })
  })
}

async function starten() {
  const wurzel = document.getElementById('wurzel')
  if (window.__ANMELDUNG__ && !window.__SITZUNGSSCHLUESSEL__) await signIn(wurzel, isPhoneNow())
  try {
    await texteLaden()
  } catch (fehler) {
    wurzel.textContent = bootMessage(fehler)
    throw fehler
  }
  /* Two faces of the one interface: the desktop page, and the phone page
     on any device whose main input is a finger (a phone, a tablet, upright
     or sideways) and in a window without touch that is narrow. Both read
     the same state; a window dragged across the narrow line, or a change of
     the main input, swaps the page. */
  let app = mount(isPhoneNow() ? Phone : App, { target: wurzel })
  watchDevice((phone) => {
    unmount(app)
    app = mount(phone ? Phone : App, { target: wurzel })
  })
  /* Only where a config asked for it: the watch paints a report panel
     over the app and writes marker lines into the service log — a
     diagnosis tool for a test service, not something a shipped install
     runs. The flag travels in beside the session key (app/main.py). */
  if (window.__DIAGNOSE__) geometriewacheStarten()
  return app
}

export default starten()
