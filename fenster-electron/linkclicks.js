// The click catcher: the one way a link in a page reaches the default browser.
//
// A navigation never opens the browser by itself (adressregel.js,
// navigationVerdict) — a script that sets `location` in a loop would open one
// tab after another. What a person clicks is different: a click on a link to
// a foreign page is stopped here and the shell is asked to open it, and the
// shell checks the address with the same rule before anything starts.
//
// Loaded into every page of the program's session (`registerPreloadScript`, main.js),
// so the manual, a document and the developer tools carry it as well as the
// main window. A preload that is sandboxed may require nothing but electron,
// which is why this file stands alone and does not read adressregel.js: the
// shell decides, this file only reports.
//
// A click counts only when it is
//   * made by a person (`isTrusted`: a script's `click()` and `dispatchEvent`
//     are not),
//   * not handled by the page already (`defaultPrevented`: the page's own
//     handler has run by the time a listener on the window sees the event),
//   * on a link that goes to a foreign http(s) address.
// Everything else — a link of our own, a `javascript:` or `file:` address, a
// download — is left to the navigation rule, which stops what must not load.
//
// The file is listed in package.json under build.files.

const CHANNEL = 'open-link'

// The names a page of ours is reached by: the same two the address rule
// calls its own (adressregel.js, EIGENE_WIRTE).
const LOOPBACK = new Set(['127.0.0.1', 'localhost'])

// The first link on the path of the click, shadow trees included.
function linkOf(event) {
  const path = typeof event.composedPath === 'function' ? event.composedPath() : []
  for (const node of path) {
    const name = node && typeof node.tagName === 'string' ? node.tagName.toLowerCase() : ''
    if (name === 'a' && typeof node.href === 'string' && node.hasAttribute('href')) return node
  }
  return null
}

// Is `target` one of our own pages, seen from the page `here`? The same
// origin, or the other spelling of the same loopback service.
function isOwn(target, here) {
  if (target.origin === here.origin) return true
  return (
    LOOPBACK.has(target.hostname) && LOOPBACK.has(here.hostname) && target.port === here.port
  )
}

// Returns true when the click was taken over.
function handleClick(event, ipcRenderer, here) {
  if (!event.isTrusted || event.defaultPrevented) return false
  // The primary button (`click`) and the middle one (`auxclick`, button 1):
  // the middle click opens a link in a new tab, which the shell takes only
  // from the main window, so a person's middle click has to be told here.
  if (event.button !== 0 && event.button !== 1) return false
  const link = linkOf(event)
  if (!link || link.hasAttribute('download')) return false
  let target
  try {
    target = new URL(link.href)
  } catch (e) {
    return false
  }
  if (target.protocol !== 'http:' && target.protocol !== 'https:') return false
  if (isOwn(target, here)) return false
  event.preventDefault()
  ipcRenderer.send(CHANNEL, target.href)
  return true
}

function install(win, ipcRenderer) {
  // The window, in the bubbling phase: a listener on an element or on the
  // document has run before this one, so `defaultPrevented` tells what the
  // page did with the click.
  const take = (event) => {
    handleClick(event, ipcRenderer, win.location)
  }
  win.addEventListener('click', take)
  win.addEventListener('auxclick', take)
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { CHANNEL, handleClick, install, isOwn, linkOf }
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  install(window, require('electron').ipcRenderer)
}
