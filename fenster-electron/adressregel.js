// Where an address is allowed to open.
//
// A program window has no address line. A foreign page shown in one therefore
// looks like a part of this program, which is exactly how a page that asks
// for a password gets believed. So only our own pages are allowed into one;
// everything else is handed to the default browser, which shows where the
// page really comes from.
//
// Its own file, and not a block inside main.js, for one reason: main.js
// requires electron, so nothing in it can be run outside a packaged window,
// and this guard could break without a single test going red. Here it is
// plain JavaScript over the standard URL parser — node runs it, and
// tests/test_adressregel.py does exactly that. Whoever adds a function here
// keeps it that way: no electron, no window, no state.
//
// The file is listed in package.json under build.files. Left out, the
// packaged program starts and dies on the first require.

// Our own pages are the ones the interface itself is served from: plain http
// on loopback, on the port the shell loads. `localhost` counts as well as
// `127.0.0.1`, because either spelling reaches the same service.
const EIGENE_WIRTE = new Set(['127.0.0.1', 'localhost'])

// The port is compared the way the URL parser writes it, on both sides: it
// drops a port that is the scheme's default (`:80` on http reads back as
// ''), so a raw `String(port)` would have a shell on port 80 take its own
// page for a foreign one.
function istEigeneSeite(adresse, port) {
  try {
    const ziel = new URL(adresse)
    return (
      ziel.protocol === 'http:' &&
      EIGENE_WIRTE.has(ziel.hostname) &&
      ziel.port === new URL(`http://127.0.0.1:${port}/`).port
    )
  } catch (e) {
    return false // not an address we can take apart, so not one of ours
  }
}

// Only http and https ever leave. `file:`, `javascript:`, `data:` and
// anything unknown are refused outright and never reach openExternal: the
// system hands those to whatever program claims the scheme, which would turn
// this guard into a way of starting arbitrary programs from a page.
//
// The answer, not the act: opening belongs to the window, so that the rule
// can be asked without a browser being started.
function darfNachDraussen(adresse) {
  let ziel
  try {
    ziel = new URL(adresse)
  } catch (e) {
    return false // not an address at all: nothing to open
  }
  return ziel.protocol === 'http:' || ziel.protocol === 'https:'
}

// What one navigation inside a window may do: 'allow' (stay), 'outside'
// (stopped here and handed to the default browser) or 'block' (stopped,
// nothing opens). One answer for every frame and for a server's redirect, so
// no route into a window can answer differently from another.
//
// A page never opens the browser by itself: a script that sets `location` in
// a loop would otherwise open one tab after another, and a form posting to a
// foreign address would arrive there as an empty GET. A page's navigation
// always has a frame that started it (the page itself), and that is stopped.
// What goes outside is
//   * a CLICK on a link in a page (linkclicks.js asks for it, `linkVerdict`
//     answers), and
//   * a navigation no frame started — the person did, through Chromium's PDF
//     viewer, which navigates for a link inside a PDF and sets no initiating
//     frame — or one the viewer's own frames started.
// A redirect is the server's choice and is only ever stopped. What a
// subframe may still load besides our own pages: the two inert documents it
// is born with — the preview's `srcdoc` and an empty `about:blank` — and the
// PDF viewer itself, which shows a PDF of ours inside frames of its own
// extension (its id is fixed in Chromium; measured in a document window
// showing one of our PDFs).
const EMPTY_FRAMES = new Set(['srcdoc', 'blank'])
const PDF_VIEWER = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/'

// Is this address a page of Chromium's PDF viewer? Its frames and its own
// page both live under the extension's address; asked of a web contents'
// address, it tells the viewer from the window and from the developer tools.
function isPdfViewer(address) {
  return String(address || '').startsWith(PDF_VIEWER)
}

// `about:blank#x` is the same empty document as `about:blank`: compared by
// scheme and path, not by the raw text.
function isEmptyFrame(address) {
  try {
    const parsed = new URL(address)
    return parsed.protocol === 'about:' && EMPTY_FRAMES.has(parsed.pathname)
  } catch (e) {
    return false
  }
}

// The developer tools the View menu opens (`tools`) are a page of their own:
// their frames may hold pages of the frontend shipped with the program,
// `data:` and `blob:` previews, an empty `about:blank` and an `about:srcdoc`
// document (inline HTML of its parent), nothing else — neither a stranger's
// page, nor one of ours, nor the PDF viewer. Their main frame stays on that
// frontend (measured: devtools://devtools/bundled/devtools_app.html) and goes
// nowhere else — not to one of our pages, not to the browser. In any other
// page a `devtools:` address is as foreign as any other.
const TOOLS_FRAMES = new Set(['data:', 'blob:'])

// The shipped frontend, matched on the address as Chromium hands it over:
// plain path characters only and no `..` step, so no spelling (an escape, a
// backslash, a name and password) can lead out of `/bundled/`.
const BUNDLED_TOOLS = /^devtools:\/\/devtools\/bundled\/([\w\-./]*)([?#].*)?$/

function isBundledTools(text) {
  const match = BUNDLED_TOOLS.exec(text)
  return match !== null && !match[1].split('/').includes('..')
}

function toolsVerdict(text, mainFrame) {
  if (isBundledTools(text)) return 'allow'
  if (mainFrame) return 'block'
  let parsed
  try {
    parsed = new URL(text)
  } catch (e) {
    return 'block'
  }
  return TOOLS_FRAMES.has(parsed.protocol) || isEmptyFrame(text) ? 'allow' : 'block'
}

// `initiator` is the address of the frame that started the navigation;
// `byBrowser` says that no frame did (the person, through the PDF viewer).
// Both are only ever a reason to send a foreign http(s) address outside,
// never to let anything load in the window.
function navigationVerdict(
  address, port,
  { mainFrame = false, redirect = false, tools = false, initiator = '', byBrowser = false } = {},
) {
  const text = String(address)
  if (tools) return toolsVerdict(text, mainFrame)
  if (istEigeneSeite(text, port)) return 'allow'
  if (!mainFrame && (isEmptyFrame(text) || text.startsWith(PDF_VIEWER))) return 'allow'
  const fromViewer = byBrowser || String(initiator).startsWith(PDF_VIEWER)
  if (!redirect && fromViewer && darfNachDraussen(text)) return 'outside'
  return 'block'
}

// What the shell does with a link a person clicked in a page, as linkclicks.js
// reported it: 'outside' (the default browser opens it), 'allow' (one of our
// own pages: the shell does nothing, the page goes there itself) or 'block'
// (nothing opens). Only a foreign http(s) address leaves, and never at the
// request of the developer tools (`tools`): they are not a page that shows
// links of ours.
function linkVerdict(address, port, { tools = false } = {}) {
  const text = String(address)
  if (tools) return 'block'
  if (istEigeneSeite(text, port)) return 'allow'
  return darfNachDraussen(text) ? 'outside' : 'block'
}

// How a stopped navigation is named in the log: the place only, never the
// path or the query — either can carry a token (a reset link, an invite).
function addressForLog(address) {
  try {
    const parsed = new URL(address)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
      ? parsed.origin
      : parsed.protocol
  } catch (e) {
    return '(not an address)'
  }
}

// The manual, told apart from everything else this program serves. It is one
// fixed path, so recognising it needs no bookkeeping — which is the whole
// point: the rule in the window used to treat EVERY own page as the manual.
const HANDBUCH_PFAD = '/help/'

function istHandbuch(adresse) {
  try {
    return new URL(adresse).pathname.startsWith(HANDBUCH_PFAD)
  } catch (e) {
    return false
  }
}

module.exports = {
  EIGENE_WIRTE,
  addressForLog,
  HANDBUCH_PFAD,
  darfNachDraussen,
  istEigeneSeite,
  isPdfViewer,
  istHandbuch,
  linkVerdict,
  navigationVerdict,
}
