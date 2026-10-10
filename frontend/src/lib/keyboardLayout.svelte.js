/* The switched-on keyboard layout, held once for the whole page.

   The key field, the settings overview and the recogniser all read this one
   map, so a key is shown and judged by the same character everywhere and
   two places of the same window cannot disagree about it
   (lib/microphoneKey.js, readLayout).

   Read when the module loads and again at every focus of the window: the
   layout can be switched while the page stands open, and a key that was
   free can then write a character the program has a shortcut on. A reading
   that brings nothing — no Keyboard API, a page not served securely, a
   refused promise — leaves the last one standing: dropping it would put
   every key back to its code name and unmark a key that is still taken. */
import { readLayout } from './microphoneKey.js'

export const layout = $state({ map: null })

/** Read the layout again, keeping the last map where the reading brings
    none. */
export function refreshLayout() {
  readLayout().then((map) => {
    if (map) layout.map = map
  })
}

refreshLayout()
window.addEventListener('focus', refreshLayout)
