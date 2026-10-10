// The window around the service.
//
// Order of events: start the packaged service as a child process (unless one
// is already answering — a second window must not become a second service),
// wait for the port, then send the window to the interface. On exit the child
// goes with the window: whoever closes the program means all of it.
//
// Closing the main window ends the whole program, and ending the program
// stops the service GENTLY (SIGTERM), so the service runs its own shutdown
// and takes its model, embedding, guardian and image-turbo servers down with
// it. A hard SIGKILL would skip that shutdown and leave those servers
// running — orphans that the next launch cannot talk to (a fresh session key,
// an old server: "Invalid API-Key"). SIGTERM first, a few seconds to bow out,
// then the hard kill only as a backstop.
//
// Windows has no gentle signal: process.kill() there ends the process
// "forcefully and abruptly" (Node's child_process documentation), the
// service runs no shutdown, and what it started keeps running — measured in
// a Windows VM: the model server with 2.5 GB and its port still open. So on
// Windows the whole process tree goes at once (taskkill /T /F, the same call
// the service makes for its own children in app/prozessstopp.py), and the
// shell waits for the service's end before it ends itself.

const {
  app, BrowserWindow, Menu, clipboard, globalShortcut, ipcMain, nativeImage, nativeTheme, screen, shell,
} = require('electron')
const { execFile, spawn } = require('child_process')
const fs = require('fs')
const net = require('net')
const path = require('path')

// 8090 is what the shipped shell uses. Overridable so a trial run can sit
// on its own port beside the running program instead of fighting it for
// the same one — but an override that is not a real port number (unset,
// empty, `abc`, out of range) must not silently become NaN: `net.connect`
// throws on that immediately, `antwortet()` never resolves the way
// `warten()` expects, and the splash screen sits there for the full two
// minutes before failing for a reason nothing on screen names.
function portLesen() {
  const roh = process.env.EXE_AI_PORT
  if (!roh) return 8090
  const zahl = Number(roh)
  if (Number.isInteger(zahl) && zahl >= 1 && zahl <= 65535) return zahl
  console.warn(`EXE_AI_PORT=${roh} is not a valid port number, falling back to 8090`)
  return 8090
}
const PORT = portLesen()
const ZIEL = `http://127.0.0.1:${PORT}/app/`

// The window opens this big the very first time, centred, and never smaller
// than the minimum. Same numbers the Tauri shell used.
const BREITE = 1280
const HOEHE = 820
const MIN_BREITE = 720
const MIN_HOEHE = 480

function antwortet() {
  return new Promise((fertig) => {
    const dose = net.connect({ host: '127.0.0.1', port: PORT })
    let entschieden = false
    const schluss = (ja) => {
      if (entschieden) return
      entschieden = true
      dose.destroy()
      fertig(ja)
    }
    dose.setTimeout(400)
    dose.on('connect', () => schluss(true))
    dose.on('timeout', () => schluss(false))
    dose.on('error', () => schluss(false))
  })
}

// Packaged, electron-builder puts the service beside the interface in the
// resources folder (Contents/Resources on macOS, resources\ on Windows); from
// source it is the PyInstaller output in dist/. On macOS the service is ONE
// FILE, and that file is what sits there under the name exe-ai-terminal. On
// Windows it is a FOLDER — the exe with its files beside it
// (deploy/exe-ai-terminal.spec: a one-file build there unpacks itself into
// %TEMP% on every start) — so the path goes one level further, to the exe
// inside.
function dienstpfad() {
  if (process.env.EXE_AI_DIENST) return process.env.EXE_AI_DIENST
  const service = app.isPackaged
    ? path.join(process.resourcesPath, 'exe-ai-terminal')
    : path.join(__dirname, '..', 'dist', 'Exe AI')
  return process.platform === 'win32' ? path.join(service, 'Exe AI.exe') : service
}

// ---------------------------------------------------------------------------
// Remembering the window
//
// The Tauri shell always opened 1280x820 in the middle of the screen; keeping
// what the user had set is new. It lives beside the browser cache in the
// shell's own userData folder, NOT in the service's data folder — this is a
// property of the window, not of the chats.

const geometriedatei = () => path.join(app.getPath('userData'), 'fenster.json')

function geometrieLesen() {
  try {
    const gelesen = JSON.parse(fs.readFileSync(geometriedatei(), 'utf8'))
    const { x, y, width, height } = gelesen
    if (![x, y, width, height].every((n) => Number.isFinite(n))) return null
    if (width < MIN_BREITE || height < MIN_HOEHE) return null
    // A remembered position on a monitor that has since been unplugged would
    // open the window into nowhere. Only keep it if it still overlaps some
    // screen by a usable amount.
    const sichtbar = screen.getAllDisplays().some((bildschirm) => {
      const b = bildschirm.workArea
      const breit = Math.min(x + width, b.x + b.width) - Math.max(x, b.x)
      const hoch = Math.min(y + height, b.y + b.height) - Math.max(y, b.y)
      return breit > 100 && hoch > 60
    })
    return sichtbar ? { x, y, width, height } : null
  } catch (e) {
    return null // no file yet, or unreadable — the defaults apply
  }
}

function geometrieSchreiben(fenster) {
  try {
    // getNormalBounds, not getBounds: a window closed while maximised or in
    // full screen would otherwise come back stuck at screen size.
    // The frame colour and the frame's scheme share the file and stay in it.
    const colour = frameColourRead()
    const scheme = frameSchemeRead()
    fs.writeFileSync(geometriedatei(), JSON.stringify({
      ...fenster.getNormalBounds(), ...(colour ? { colour } : {}), ...(scheme ? { scheme } : {}),
    }))
  } catch (e) {
    /* not worth failing the shutdown over */
  }
}

// ---------------------------------------------------------------------------
// The colour the window opens on
//
// The window is there before any page is: first empty, then with the splash,
// then with the interface. Left alone it opens dark, whatever look the
// interface then shows — a light look started on a dark window and jumped.
// So the page says the solid tone of its frame (preload.js), the shell keeps
// it beside the geometry, and the next start builds the window on it. Only
// `#rrggbb` is taken: what is kept here ends as the window's ground and in
// the splash's address, and neither is a place for anything but a colour.

const FRAME_COLOUR = /^#[0-9a-f]{6}$/i

function windowFileRead() {
  try {
    const read = JSON.parse(fs.readFileSync(geometriedatei(), 'utf8'))
    return read && typeof read === 'object' && !Array.isArray(read) ? read : {}
  } catch {
    return {} // no file yet, or unreadable
  }
}

function frameColourRead() {
  const { colour } = windowFileRead()
  return typeof colour === 'string' && FRAME_COLOUR.test(colour) ? colour.toLowerCase() : null
}

function frameColourKeep(colour) {
  if (typeof colour !== 'string' || !FRAME_COLOUR.test(colour)) return
  const kept = windowFileRead()
  if (kept.colour === colour.toLowerCase()) return
  try {
    fs.writeFileSync(geometriedatei(), JSON.stringify({ ...kept, colour: colour.toLowerCase() }))
  } catch {
    /* the next start opens on the colour it had; nothing else depends on it */
  }
}

// Only the main window's page is heard: a colour is the look of the
// interface, and no other window of the program shows one.
ipcMain.on('frame-colour', (event, colour) => {
  if (!fenster || fenster.isDestroyed() || event.sender !== fenster.webContents) return
  frameColourKeep(colour)
})

// ---------------------------------------------------------------------------
// The title bar the system draws
//
// On Windows the system draws the window's title bar by its own setting: on
// a light Windows it stood white over a dark look. So the page says whether
// its look is dark or light (preload.js), and the shell hands that on as the
// theme of the window frame. A look that follows the device says `system`:
// the theme set here is also what the page is told the device prefers, and a
// forced one would hold such a look where it stands. Kept beside the colour,
// so the next start draws the bar right before any page is there. On every
// other system nothing is set and nothing is kept.

const FRAME_SCHEMES = ['dark', 'light', 'system']

function frameSchemeRead() {
  const { scheme } = windowFileRead()
  return FRAME_SCHEMES.includes(scheme) ? scheme : null
}

function frameSchemeKeep(scheme) {
  const kept = windowFileRead()
  if (kept.scheme === scheme) return
  try {
    fs.writeFileSync(geometriedatei(), JSON.stringify({ ...kept, scheme }))
  } catch {
    /* the next start leaves the bar to the system until the page speaks */
  }
}

// True where the frame was given the scheme.
function frameSchemeApply(scheme) {
  if (process.platform !== 'win32' || !FRAME_SCHEMES.includes(scheme)) return false
  if (nativeTheme.themeSource !== scheme) {
    nativeTheme.themeSource = scheme
    console.log(`Window frame: ${scheme}`)
  }
  return true
}

ipcMain.on('frame-scheme', (event, scheme) => {
  if (!fenster || fenster.isDestroyed() || event.sender !== fenster.webContents) return
  if (frameSchemeApply(scheme)) frameSchemeKeep(scheme)
})

// ---------------------------------------------------------------------------
// The menu bar
//
// It is NOT there to offer anything: the program is operated from its own
// toolbar and nothing about that changes. It exists because on macOS the
// standard shortcuts hang off menu items with the matching roles — no Edit
// menu, no Cmd+C, no matter what the page does. Electron builds no menu of
// its own once we set one, so every role we want has to be named here.
//
// On Windows the same menu would sit as a bar INSIDE every window of the
// program — a strip of "Edit · View · Window" above an interface that has
// its own toolbar. So there it is hidden in every window (menuBarOptions
// below): a single Alt key shows it, and the shortcuts of its items keep
// working while it is hidden, which is Electron's own rule for an auto-hidden
// bar. macOS has no bar in the window at all; the menu sits in the system's.

function menueSetzen() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      // About, Services, Hide, Quit (Cmd+Q) — the first submenu, which macOS
      // always labels with the program's name. Windows has no such menu, and
      // a role that exists only on macOS is not named anywhere else.
      ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : []),
      { role: 'editMenu' },  // Undo, Redo, Cut, Copy, Paste, Select All
      {
        label: 'View',
        submenu: [
          { role: 'reload' },          // Cmd+R
          { role: 'toggleDevTools' },  // Cmd+Alt+I — never be without a console again
          { type: 'separator' },
          // The whole program larger or smaller, in steps of about ten per
          // cent, and back to its own size.
          { role: 'zoomIn' },          // Cmd+Plus
          { role: 'zoomOut' },         // Cmd+Minus
          { role: 'resetZoom' },       // Cmd+0
        ],
      },
      {
        // The ready-made windowMenu role leaves Close out, and with it Cmd+W.
        // Measured on the first build: Minimize and Zoom were there, Cmd+W
        // did nothing. So the submenu is spelled out.
        role: 'windowMenu',
        submenu: [
          { role: 'minimize' }, // Cmd+M
          { role: 'zoom' },
          { type: 'separator' },
          { role: 'close' },    // Cmd+W
        ],
      },
    ])
  )
}

// The window option that hides the bar, set on every window the program
// makes — except on macOS, where a window has no bar to hide and an option
// it does not need is not set on it.
function menuBarOptions() {
  return process.platform === 'darwin' ? {} : { autoHideMenuBar: true }
}

// ---------------------------------------------------------------------------
// The context menu
//
// Electron ships none. Unlike a browser, a right click does nothing at all
// until the shell catches the event itself — which is why Paste was reachable
// by Cmd+V and through the menu bar, but never by right-clicking.
//
// Everything the menu needs arrives with the event in `params`: what was hit,
// what is selected, and what the page allows at that spot (`editFlags`).
//
// The text entries are `role`s, like the menu bar above: nothing to wire up by
// hand, and each one carries its own shortcut and its own wording. The image
// and link entries CANNOT be — measured on Electron 33.4.11: there is no
// `saveImageAs`, `copyImage` or `copyLinkAddress` role (see the role list in
// electron.d.ts). Those are Chromium's own context-menu commands, not Electron
// menu roles, and a template asking for them builds a menu item with an empty
// label that does nothing at all — a narrow blank box beside the picture. So
// those three are spelled out with the documented webContents/clipboard calls
// and carry their own labels, in the same English the roles above render in.
//
// The listener sits on every webContents the program ever creates, not on the
// main window's alone: the manual opens as a SECOND window with its own
// webContents, and a listener on the first one would never reach it. Frames
// inside a window — the sandboxed preview frame in the module panel — belong
// to their window's webContents and are covered by the same listener; the
// entries act on the frame the click came from, so a copy in the preview
// copies the preview, not the chat around it.
//
// The spelling suggestions ride along in the same event. They cost nothing to
// take: the spellchecker is on by default and takes its language from the
// system (measured: `spellCheckerEnabled` true, languages ['de']) — no setting
// to add, nothing to install. And they need no wording of our own either, the
// entries ARE the words. What is deliberately NOT here is "Add to dictionary":
// that one would need a label, and a label needs a language, and the shell has
// no translations. That is a product decision, not this file's.

// ---------------------------------------------------------------------------
// What must never reach the clipboard
//
// Every /api/v1 address the interface writes into an href or an <img src>
// carries this run's session key IN THE ADDRESS: a browser cannot attach a
// header to those two, so `mitSchluessel()` (frontend/src/lib/api.js:20)
// appends `?schluessel=…` instead — the query fallback the guard itself
// documents (app/sitzungsschluessel.py:40-41: HEADER for fetch,
// ABFRAGEPARAMETER for the rest). The download arrow under every picture is
// exactly such an href (frontend/src/teile/Nachricht.svelte:536 and :628,
// frontend/src/teile/ModulAgenten.svelte:300).
//
// "Copy Link Address" hands what it finds to the clipboard word for word, and
// this menu is the first way of operating the program that turns that address
// into TEXT at all. Right-clicking a download arrow therefore used to put the
// key into the clipboard, and from there into a message to the model, a mail,
// a note. That key is the only thing between this API and every other program
// on the machine (app/sitzungsschluessel.py:7-12). It does not travel.
//
// The filter goes by the SHAPE of a parameter name, not by that one name: a
// list that knows only `schluessel` is blind again the day the next secret
// rides along in a URL. Query and fragment both — `#access_token=…` is the
// OAuth implicit flow's own habit, and a fragment never reaches a server but
// reaches the clipboard just fine.
//
// Names that ARE the secret, spelled out or as one word of a longer name
// (`api_key`, `access-token`, `X-Auth`). Whole words only, so `keyword`,
// `codec` or `authority` are not swept up with them — `pin`, `otp` and
// `passcode` belong here rather than below for the same reason: a substring
// match on `pin` would also catch `shipping` and `spinner`.
const GEHEIME_WOERTER = new Set([
  'schluessel', 'schlussel', 'key', 'apikey', 'token', 'secret', 'geheim',
  'auth', 'authorization', 'password', 'passwort', 'pass', 'pwd',
  'credential', 'credentials', 'signature', 'sig', 'session', 'sid',
  'pin', 'otp', 'passcode',
])

// The few that are unmistakable even inside a longer word, so a future
// `sitzungsschluessel=` or `refresh_token_v2` is caught as well —
// `sessionid` and `authkey` join them measured against real logins
// (`SESSIONID`, `jsessionid`, `authkey`, none of which the whole-word list
// above catches on their own; `jsessionid` needs no entry of its own, since
// `sessionid` already matches inside it).
const GEHEIME_TEILE = [
  'schluessel', 'schlüssel', 'token', 'secret', 'passw', 'sessionid', 'authkey',
]

function istGeheimerParameter(name) {
  const klein = name.toLowerCase()
  if (GEHEIME_TEILE.some((teil) => klein.includes(teil))) return true
  return klein.split(/[^a-z0-9äöüß]+/).some((wort) => GEHEIME_WOERTER.has(wort))
}

function parameterSaeubern(suchparameter) {
  let entfernt = false
  // A copy of the names first: deleting while iterating the live list skips
  // entries.
  for (const name of [...suchparameter.keys()]) {
    if (!istGeheimerParameter(name)) continue
    suchparameter.delete(name)
    entfernt = true
  }
  return entfernt
}

function ohneGeheimnis(adresse) {
  let url
  try {
    url = new URL(adresse)
  } catch (e) {
    return { adresse, entfernt: false } // not an address we can take apart
  }
  let entfernt = parameterSaeubern(url.searchParams)
  // Only the part of the fragment AFTER its own "?" is a query string — the
  // part before it is the route (`#/page/1?token=abc`, a client-side router's
  // own address). Handing the WHOLE fragment to URLSearchParams treated the
  // route as if it were itself a parameter name, and stripping "a secret
  // parameter" deleted the route along with it.
  const bruchIndex = url.hash.indexOf('?')
  if (bruchIndex !== -1) {
    const route = url.hash.slice(0, bruchIndex)
    const bruchstueck = new URLSearchParams(url.hash.slice(bruchIndex + 1))
    if (parameterSaeubern(bruchstueck)) {
      const rest = bruchstueck.toString()
      url.hash = rest ? `${route}?${rest}` : route
      entfernt = true
    }
  } else if (url.hash.includes('=')) {
    // No "?" but an "=" is the OAuth implicit-flow shape itself
    // (`#access_token=…&token_type=…`), not a route: the whole fragment IS
    // the query string. The "=" check keeps a plain same-page anchor
    // (`#auth`, `#key-features`) out of this branch — istGeheimerParameter
    // splits on punctuation, so treating a bare anchor slug as a parameter
    // name would falsely match one of its hyphenated words.
    const ganzesFragment = new URLSearchParams(url.hash.slice(1))
    if (parameterSaeubern(ganzesFragment)) {
      url.hash = ganzesFragment.toString()
      entfernt = true
    }
  }
  // A username and password embedded in the address itself
  // (`https://user:hunter2@host/`) are exactly the shape a secret takes,
  // whatever name they arrived under.
  if (url.username || url.password) {
    url.username = ''
    url.password = ''
    entfernt = true
  }
  // Only an address we actually changed gets serialised again. An untouched
  // one is handed on byte for byte the way the page wrote it — re-serialising
  // would quietly re-encode a perfectly ordinary web link.
  return entfernt
    ? { adresse: url.toString(), entfernt: true }
    : { adresse, entfernt: false }
}

// ---------------------------------------------------------------------------
// Where an address is allowed to open
//
// The rules themselves live in adressregel.js — plain JavaScript without
// electron, so node can run them and tests/test_adressregel.py does. What is
// left here is the pair of things that need a window: the port this shell
// loaded, and the act of handing an address to the browser.

const regel = require('./adressregel')
const kontextmenue = require('./kontextmenue')
const { thumbnail } = require('./thumbnail')
const { istHandbuch } = regel

function istEigeneSeite(adresse) {
  return regel.istEigeneSeite(adresse, PORT)
}

function nachDraussen(adresse) {
  if (regel.darfNachDraussen(adresse)) shell.openExternal(adresse)
}

// The rule itself, kept in one place because it is set on every window the
// program makes, not only on the first one.
//
// THREE ANSWERS, AND THE MIDDLE ONE WAS MISSING. A foreign page goes to the
// browser. The manual gets the one window it is allowed, raised rather than
// stacked. Everything else of ours — a file from the agents' shelf, a
// document, a script — is neither: it got the manual's title, was remembered
// AS the manual, and from then on every click on a shelf file raised that
// window instead of opening the file. Clicking a document opened the manual,
// and the file could not be saved at all, because the open was denied before
// the download could begin.
function fensterweiche({ url }) {
  if (!istEigeneSeite(url)) {
    nachDraussen(url)
    return { action: 'deny' }
  }
  if (!istHandbuch(url)) {
    // Our own, but not the manual: a document or a script shown in its own
    // window. A plain window, no borrowed title, and not remembered as
    // anything. (Downloads open no window at all — the page saves them
    // through the link's own download attribute.)
    return {
      action: 'allow',
      overrideBrowserWindowOptions: { width: 900, height: 720, ...menuBarOptions() },
    }
  }
  if (hilfefenster && !hilfefenster.isDestroyed()) {
    hilfefenster.focus()
    return { action: 'deny' }
  }
  return {
    action: 'allow',
    overrideBrowserWindowOptions: {
      width: 880, height: 720, title: 'Exe AI — Help', ...menuBarOptions(),
    },
  }
}

// "Copy Image" used to take the spot on screen (`copyImageAt(x, y)`), the
// same coordinates the right click carried. Between that right click and the
// click on "Copy Image" the menu stays open while the chat underneath is
// free to scroll — the coordinates are what was under the pointer at the
// FIRST click, and by the second one they can belong to a different message
// entirely. The picture's own address (`params.srcURL`) names
// the SAME picture regardless of where the page has since scrolled to, the
// way "Save Image As" already works one line above.
//
// This also sidesteps a second, unrelated problem `copyImageAt` had: it
// writes TWO clipboard flavours, `image/png` and a `text/html` one that
// spells the address out in full, session key and all —
//
//   <meta charset='utf-8'><img src="http://127.0.0.1:8096/api/v1/images/
//   1307d26….png?schluessel=olY1JlcrKOL3RQIGn7fjZgXjTRJTgEQwBaZdJYTSpng"/>
//
// — which anything preferring rich text over pixels (Mail, Notes, Word, a
// chat box) picks up instead of the picture. Fetching the bytes ourselves
// and writing only `{ image }` never produces that second flavour, so there
// is nothing here to work around.
async function bildKopieren(adresse) {
  const bild = adresse.startsWith('data:')
    ? nativeImage.createFromDataURL(adresse)
    : nativeImage.createFromBuffer(
        Buffer.from(await (await fetch(adresse)).arrayBuffer())
      )
  // Nothing landed (a picture that never loaded, an address that no longer
  // answers): then the clipboard is none of our business — whatever the
  // user had in it stays.
  if (bild.isEmpty()) return
  clipboard.write({ image: bild })
}

/* The doc folder's previews (thumbnail.js): only of what the service this
   shell opened hands out. A preview that fails is simply none. */
ipcMain.handle('thumbnail', async (event, address, name, size) => {
  try {
    return await thumbnail(new URL(ZIEL).origin, address, name, size)
  } catch {
    return ''
  }
})

/* The word for "Read aloud", per page that asked for the entry — the page
   sends it from its own catalogue (preload.js), because the shell has no
   translations. A page that never sent it gets no entry. */
const vorlesenWorte = new Map()
const vorlesenBeobachtet = new WeakSet()

ipcMain.on('vorlesen-beschriftung', (ereignis, wort) => {
  const inhalt = ereignis.sender
  // Forgotten with the page, whichever way it goes.
  if (!vorlesenBeobachtet.has(inhalt)) {
    vorlesenBeobachtet.add(inhalt)
    inhalt.once('destroyed', () => vorlesenWorte.delete(inhalt.id))
  }
  // Empty: the page cannot read right now (its microphone is open), so the
  // entry goes until it sends the word again.
  if (typeof wort !== 'string' || !wort.trim()) {
    vorlesenWorte.delete(inhalt.id)
    return
  }
  vorlesenWorte.set(inhalt.id, wort.trim())
})

/* The list of entries comes from kontextmenue.js (plain JavaScript, checked
   by tests/test_kontextmenue.py); this is the half that needs a window: each
   description is turned into a menu item, and the ones that act on a window,
   a clipboard or a download get their action hung on here. */
function kontextmenueBauen(inhalt, params) {
  const kann = params.editFlags || {}
  const link = params.linkURL ? ohneGeheimnis(params.linkURL) : null
  return kontextmenue
    .baue(params, kann, {
      vorlesenLabel: vorlesenWorte.get(inhalt.id),
      // The label carries the difference, and that is the whole point. A
      // silently shortened address would leave the user holding something
      // he believes is a working link — it is not: /api/v1 answers 401
      // without the key, so a picture address without it opens nothing,
      // here or anywhere else. The label names that consequence rather than
      // its cause: "without key" said why the key was dropped and left the
      // user to work out that the address is dead, "not available" says it
      // outright. He has to be able to read that off the menu before he
      // copies, not find it out afterwards. And leaving the entry out
      // entirely would be just as mute: a right click that offers nothing
      // looks like the broken right click this menu was built for.
      //
      // "not available" only says something true about OUR OWN addresses,
      // where the missing part really is what makes the link dead — a
      // foreign link that happened to carry a `token=` or a `user:pass@`
      // still works perfectly well without it, it is simply a link this
      // program will not hand over whole.
      linkLabel: link && link.entfernt && istEigeneSeite(params.linkURL)
        ? 'Copy Link Address — not available'
        : 'Copy Link Address',
      linkAdresse: link ? link.adresse : '',
    })
    .map((eintrag) => {
      if (eintrag.art === 'trenner') return { type: 'separator' }
      if (eintrag.art === 'rolle') {
        return eintrag.enabled === undefined
          ? { role: eintrag.role }
          : { role: eintrag.role, enabled: eintrag.enabled }
      }
      if (eintrag.art === 'wort') {
        return {
          label: eintrag.label,
          click: () => inhalt.replaceMisspelling(eintrag.label),
        }
      }
      if (eintrag.art === 'vorlesen') {
        // To the page, which owns the voice: it reads the text the same way
        // it reads an answer in a conversation.
        return { label: eintrag.label, click: () => inhalt.send('vorlesen', eintrag.text) }
      }
      if (eintrag.art === 'bild_speichern') {
        // downloadURL runs the normal download path, which asks where to put
        // the file — the same dialog the interface's own download button gets.
        return { label: 'Save Image As…', click: () => inhalt.downloadURL(params.srcURL) }
      }
      if (eintrag.art === 'bild_kopieren') {
        // The picture's own address, not the spot it was clicked at — see
        // bildKopieren above.
        // Caught here: the menu takes no promise back, so a rejection on the
        // way (a window closed mid-copy, a dead address) would be an
        // unhandled one in the main process, where nothing is watching for it.
        return {
          label: 'Copy Image',
          click: () => {
            bildKopieren(params.srcURL).catch((fehler) => {
              console.error('Copy Image failed:', fehler)
            })
          },
        }
      }
      return { label: eintrag.label, click: () => clipboard.writeText(eintrag.adresse) }
    })
}

function kontextmenueSetzen(inhalt) {
  inhalt.on('context-menu', (ereignis, params) => {
    const eintraege = kontextmenueBauen(inhalt, params)
    if (!eintraege.length) return

    Menu.buildFromTemplate(eintraege).popup({
      window: BrowserWindow.fromWebContents(inhalt),
    })
  })
}

app.on('web-contents-created', (ereignis, inhalt) => {
  kontextmenueSetzen(inhalt)
  // Both rules for every page the program creates, at any depth: which
  // addresses may open a window, and where a page may navigate — for the
  // developer tools (View menu) in their own form, see navigationVerdict.
  inhalt.setWindowOpenHandler(fensterweiche)
  navigationSperren(inhalt)
  inhalt.on('devtools-opened', () => {
    if (inhalt.devToolsWebContents) toolsPages.add(inhalt.devToolsWebContents)
  })
})

// ---------------------------------------------------------------------------

let kind = null
let fenster = null
let hilfefenster = null
let beendet = false
// The service is being stopped: every further quit pass waits for that.
let stopping = false

// Shown the moment the service is known to be unreachable, whether that
// verdict comes early (spawn itself failed, or the service died before it
// ever answered) or only after the two-minute wait below gives up — one
// place for the one state, not two copies of the string that could drift
// apart.
//
// Not into a page that is still loading: an early verdict can arrive while
// the splash is loading, and a mark set on the document about to be
// replaced is lost with it — the splash would then sit there without its
// failure, waiting for something that never comes. The splash's own
// 'did-finish-load' (fensterBauen) writes the mark then.
function alsFehlgeschlagenZeigen() {
  if (!fenster || fenster.isDestroyed()) return
  if (fenster.webContents.isLoading()) return
  fehlstartSchreiben()
}

// The mark itself. Called directly from 'did-finish-load': the page is
// complete then, while isLoading() still answers true inside that event.
function fehlstartSchreiben() {
  if (!fenster || fenster.isDestroyed()) return
  fenster.webContents
    .executeJavaScript("document.body.dataset.zustand = 'fehlgeschlagen'")
    .catch((fehler) => {
      if (fenster && !fenster.isDestroyed()) console.error('Marking the start failure failed:', fehler)
    })
}

let dienstFehlgeschlagen = false
// Set once the service has answered: an exit after that is a service that
// stopped, not one that never started.
let dienstAntwortete = false

function fehlstartMelden(grund) {
  if (dienstFehlgeschlagen) return
  dienstFehlgeschlagen = true
  console.error('Service did not start:', grund)
  alsFehlgeschlagenZeigen()
}

async function dienstStarten() {
  if (await antwortet()) return
  // Quit while the probe above was still out: nothing is left to serve, and
  // a service started now would outlive the program.
  if (beendet) return
  kind = spawn(dienstpfad(), [], {
    // PORT is portLesen()'s already-validated fallback, not the raw
    // environment — passing an invalid EXE_AI_PORT (e.g. "abc") through
    // unchanged crashes the service's own startup (app/config.py: int(port)),
    // which fires 'exit' rather than 'error' below and defeats the port
    // fallback's fix for that exact value.
    env: { ...process.env, EXE_AI_TERMINAL_HEADLESS: '1', EXE_AI_PORT: String(PORT) },
    stdio: 'ignore',
  })
  // A service that starts and dies a second later — a missing library, a
  // port already taken, a broken database — fires 'exit', not 'error'.
  // Before it ever answered, that is a failed start just the same, and the
  // wait below stops at once instead of polling for two minutes.
  kind.on('exit', (code, signal) => {
    kind = null
    if (!dienstAntwortete && !beendet) {
      fehlstartMelden(`exited before it answered (code ${code}, signal ${signal})`)
    }
  })
  // Node treats an 'error' event with no listener as an uncaught exception —
  // spawning a service whose file is missing fired exactly that and took the
  // whole main process down with it, before `warten()` below ever got to say
  // why the window was still on its splash screen. With a
  // listener here, that failure shows up on screen immediately instead of
  // silently spending the next two minutes waiting on a port nothing will
  // ever answer.
  kind.on('error', (fehler) => {
    kind = null
    fehlstartMelden(fehler)
  })
}

// A window of this program never navigates away from our own pages — a
// dropped file or a foreign link stays out. Set once for every page the
// program creates (the 'web-contents-created' hook), so a manual or a shelf
// window, and any window those open, obey the same rule as the main one.
//
// Dropping a file on a window must never navigate away from the program —
// Chromium would happily replace the interface with the file. The frontend
// handles its own drops in the page; everything else stays put. (This is
// what dragDropEnabled:false bought us under Tauri.)
//
// The SAME module the window-open handler uses (adressregel.js), so the two
// can never answer the same address differently.
//
// One listener decides a navigation, in every frame: 'will-frame-navigate'
// fires for the main frame too, and before 'will-navigate', which a prevented
// navigation never reaches. A foreign link in the main frame of a manual or
// document window used to be swallowed without a trace; it now opens in the
// browser. A server's redirect is asked the same rule and is only ever
// stopped — 'will-frame-navigate' never sees it.
function navigationSperren(inhalt) {
  inhalt.on('will-frame-navigate', (details) => navigationDecide(inhalt, details, false))
  inhalt.on('will-redirect', (details) => navigationDecide(inhalt, details, true))
}

// The developer tools are known by what they are — the tools page some page
// of ours opened — and not by their type: the PDF viewer's page is of type
// 'remote' as well (measured), and must get the rule of a program window.
// Each tools page is noted when its owner opens it ('devtools-opened', in the
// 'web-contents-created' hook) and stays noted until it is gone.
const toolsPages = new WeakSet()

// One decision for both events. The log names the place, never the whole
// address (adressregel.js, addressForLog).
function navigationDecide(contents, details, redirect) {
  const verdict = regel.navigationVerdict(details.url, PORT, {
    mainFrame: details.isMainFrame, redirect, tools: toolsPages.has(contents),
  })
  if (verdict === 'allow') return
  details.preventDefault()
  console.log(`Navigation ${verdict}${redirect ? ' (redirect)' : ''}: ${regel.addressForLog(details.url)}`)
  if (verdict === 'outside') nachDraussen(details.url)
}

function fensterBauen() {
  const gemerkt = geometrieLesen()
  // The frame colour of the look shown last: the ground of the window until
  // a page paints over it, and the ground of the splash. Without one kept,
  // window and splash are what they always were.
  const ground = frameColourRead()
  if (ground) console.log(`Window ground: ${ground}`)
  // The scheme of that look, before the window is there to be drawn.
  frameSchemeApply(frameSchemeRead())
  fenster = new BrowserWindow({
    ...(gemerkt || { width: BREITE, height: HOEHE, center: true }),
    ...menuBarOptions(),
    ...(ground ? { backgroundColor: ground } : {}),
    minWidth: MIN_BREITE, minHeight: MIN_HOEHE,
    title: 'Exe AI',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      /* The one bridge to the page, and it carries one thing: the dictation
         shortcut (see preload.js). Everything else about the interface is
         still a plain web page that knows nothing about this shell. */
      preload: path.join(__dirname, 'preload.js'),
      /* The viewer that draws a PDF's pages is a built-in plugin, and the
         window loads none unless told to. The page shows a PDF document in
         a frame; without this the frame stays empty. */
      plugins: true,
    },
  })
  fenster.loadFile(
    path.join(__dirname, 'anzeige', 'index.html'), ground ? { query: { ground } } : undefined,
  )
  // The splash shows a failed start every time it has just loaded: the
  // first time when the verdict came while it was still loading, and again
  // after a reload, which would otherwise bring it back without its failure.
  fenster.webContents.on('did-finish-load', () => {
    if (dienstFehlgeschlagen) fehlstartSchreiben()
  })

  // The program is called Exe AI, and the title bar says so. Left alone,
  // Chromium replaces the window title with the page's own <title> the
  // moment a page loads — the loading page first, then the interface,
  // whatever each calls itself. The title bar is the window's, so the
  // window keeps it, and no page has to carry the program's name for it to
  // stand there.
  //
  // The listener belongs on the WINDOW, not on its webContents: both emit
  // this event, but only the window's preventDefault actually stops the
  // native title from changing. Measured — on webContents it does nothing.
  fenster.on('page-title-updated', (ereignis) => ereignis.preventDefault())

  // The manual, second window — and every other address the page asks for.
  //
  // The interface asks for the manual with a plain window.open('/hilfe/')
  // whenever the Tauri bridge is absent — which it is here — so nothing in
  // the frontend has to know about this shell. Like the Tauri command it
  // replaces, a second click raises the window that is already open instead
  // of stacking another one on top.
  //
  // The callback is handed the address, and only our own pages get that
  // window. Everything else — a link in an answer, the sign-in page an
  // account connection opens — goes to the default browser instead, where
  // its address is visible. See istEigeneSeite/nachDraussen above.
  //
  // The raise-instead-of-stack rule deliberately applies to our own pages
  // only: it used to swallow every second address whatever it was, so a
  // sign-in page opened while the manual stood open simply never appeared.
  // The handler itself is set for every page in the 'web-contents-created'
  // hook; here only the manual is picked out of the windows it lets open.
  fenster.webContents.on('did-create-window', (neues, angaben) => {
    // Only the manual is remembered as the manual. This line used to greet
    // every window the program made, so a file opened from the agents' shelf
    // became "the help window" — and the next click on anything raised it.
    if (!istHandbuch(angaben && angaben.url)) return
    hilfefenster = neues
    // /hilfe/ carries its own <title> and would overwrite "Exe AI — Help"
    // as soon as it loads.
    neues.on('page-title-updated', (ereignis) => ereignis.preventDefault())
    neues.on('closed', () => { hilfefenster = null })
  })

  // Size and position are kept as they were when the program was closed.
  // Closing the window this way is only one of two exits — Cmd+Q never gets
  // here, so before-quit saves as well.
  fenster.on('close', () => geometrieSchreiben(fenster))

  // Closing the main window means closing the program — on macOS a window
  // otherwise just hides and the service would keep running.
  fenster.on('closed', () => app.quit())
}

// The splash page is showing; switch over as soon as the service answers.
// Two minutes, not thirty seconds: a first start has the PyInstaller bundle
// to unpack before it even begins setting up its database, and that alone was
// measured at around 55 seconds.
async function warten() {
  const ende = Date.now() + 120000
  while (Date.now() < ende) {
    // dienstStarten()'s own listeners already showed the failure the moment
    // spawn() failed or the service died before answering — polling a port
    // nothing will ever answer for the rest of the two minutes would only
    // waste cycles on a verdict already reached.
    if (dienstFehlgeschlagen || beendet) return
    // Closed during the splash screen: there is nothing left to load into,
    // the same check the dictation shortcut makes.
    if (!fenster || fenster.isDestroyed()) return
    if (await antwortet()) {
      dienstAntwortete = true
      if (!fenster || fenster.isDestroyed() || beendet) return
      // A window closed while the page is still loading rejects the load;
      // that is the close, not a failure. Any other rejection is written
      // down — the splash is already gone then (Chromium shows its own error
      // page), so there is nothing left on screen to mark.
      return fenster.loadURL(ZIEL).catch((fehler) => {
        if (fenster && !fenster.isDestroyed()) console.error('Loading the interface failed:', fehler)
      })
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  fehlstartMelden('no answer within two minutes')
}

/* The dictation shortcut, as a constant rather than a setting. A settable
   one would need a second way over the bridge and a place to keep it; fixed,
   it is one line here and one line in the page.

   Pressed while another program is in front, this brings the window forward
   and tells the page — which does exactly what a click on its microphone
   button does: start recording, or stop and fetch the text. */
const DIKTAT_KUERZEL = 'CommandOrControl+Shift+M'

function kuerzelSetzen() {
  /* A shortcut another program already holds cannot be taken, and that is
     not a reason to refuse to start: everything else about the program works
     without it, and the button is still there to be clicked. */
  const genommen = globalShortcut.register(DIKTAT_KUERZEL, () => {
    if (!fenster || fenster.isDestroyed()) return
    bringWindowForward()
    fenster.webContents.send('diktat')
  })
  if (!genommen) console.warn('Shortcut already taken:', DIKTAT_KUERZEL)
}

// ---------------------------------------------------------------------------
// A newer version
//
// The way to it is updater.js. It answers the page of the main window and
// nobody else, and the one look it takes by itself comes after the service's
// start, below.
const updater = require('./updater')
updater.start(() => fenster)

// ---------------------------------------------------------------------------
// One program at a time
//
// A second start — a second double click on Windows, `open -n` on macOS —
// used to build a second shell with a second window; and while the first
// service had not answered its port yet, a second service on the same data
// folder, whose start tidies up every runner (app/main.py) and so took the
// first instance's model servers down, or died at the taken port and
// reported a failed start. So the lock comes first, before a window or a
// service exists: Electron keys it on the userData folder, the second
// process is told at once and quits, and the first gets 'second-instance'
// and brings its window forward.

// The first instance's answer to a second start: the one window, in front —
// restored if it was minimised. Before the window exists there is nothing to
// raise; the start under way shows it.
function bringWindowForward() {
  if (!fenster || fenster.isDestroyed()) return
  if (fenster.isMinimized()) fenster.restore()
  fenster.show()
  fenster.focus()
}

if (app.requestSingleInstanceLock()) {
  app.on('second-instance', () => {
    console.log('Second start: bringing the window forward')
    bringWindowForward()
  })
  app.whenReady().then(async () => {
    menueSetzen()
    fensterBauen()
    kuerzelSetzen()
    await dienstStarten()
    // One quiet look for a newer version, once the service is on its way.
    // Whatever it finds is the page's to show; the shell shows nothing.
    updater.check()
    warten()
  })
} else {
  // The program is already running, and that instance has just been told.
  console.log('Already running: handing this start to the first instance')
  app.quit()
}

app.on('will-quit', () => globalShortcut.unregisterAll())

app.on('window-all-closed', () => app.quit())

// How long the shell waits for the service to end before it ends itself —
// the ten-second ceiling before-quit below explains.
const STOP_DEADLINE_MS = 10000

// Ending the service: the gentle way where there is one. macOS: SIGTERM, and
// the service runs its own shutdown (the header of this file). Windows: there
// is no gentle signal, process.kill() ends the process at once and leaves its
// children running — so the WHOLE TREE goes, the service and every server it
// started, with the same call the service makes for its own children
// (app/prozessstopp.py). The wait in before-quit ends on the service's own
// 'exit', not on taskkill's answer.
function stopService(service) {
  if (process.platform === 'win32') {
    execFile('taskkill', ['/PID', String(service.pid), '/T', '/F'], (failure) => {
      // taskkill could not run (not on the path, denied) or found nothing
      // left to end. In the first case the service is still there: end it
      // alone, hard — the one way left. In the second there is nothing to
      // end, and kill() on a process that is gone does nothing.
      if (failure) service.kill()
    })
    return
  }
  try { process.kill(service.pid, 'SIGTERM') } catch { /* already gone */ }
}

// The backstop after the deadline. On Windows taskkill /F has already killed;
// there is no harder step to take.
function killService(service) {
  if (process.platform === 'win32') return
  try { process.kill(service.pid, 'SIGKILL') } catch { /* already gone */ }
}

app.on('before-quit', async (ereignis) => {
  // Cmd+Q ends the program without ever closing the window, and app.exit()
  // below is a hard stop — so the geometry has to be written here too, before
  // anything else, or a quit by keystroke forgets where the window stood.
  if (fenster && !fenster.isDestroyed()) geometrieSchreiben(fenster)
  // Remembered on every pass, with or without a service: a start still on
  // its way (dienstStarten) must not spawn one after this.
  beendet = true
  // A shutdown is already under way: closing the window calls app.quit()
  // twice (the window's 'closed' and 'window-all-closed'), and a second pass
  // that simply returned let the program end in the middle of the wait
  // below — the service was never stopped hard. Every further pass is held
  // until that wait is over; app.exit() is the only way out. Without a
  // service there is no wait, and a further pass simply goes through.
  if (stopping) {
    ereignis.preventDefault()
    return
  }
  if (!kind) return
  ereignis.preventDefault()
  stopping = true
  const dienst = kind
  // Waited for is the END OF THE PROCESS, not a silent port: the service
  // closes its port first and then still tidies up, and a hard kill the
  // moment the port went quiet cut that short. The ten-second ceiling stays.
  const zuEnde = new Promise((r) => dienst.once('exit', r))
  stopService(dienst)
  const vorbei = await Promise.race([
    zuEnde.then(() => true),
    new Promise((r) => setTimeout(() => r(false), STOP_DEADLINE_MS)),
  ])
  if (!vorbei) killService(dienst)
  app.exit(0)
})
