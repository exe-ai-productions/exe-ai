// The window around the service.
//
// Order of events: start the packaged service as a process of its own
// (unless one is already answering — a second window must not become a
// second service), wait for the port, then send the window to the interface.
//
// Closing the main window does not end the program: it runs on with its sign
// in the menu bar (menueleiste.js), and the sign opens the window again. The
// program ends from the sign's menu, with Cmd+Q, or for an update. Either
// way the service is not ended with it. The service outlives the window,
// whether this window started it or only found it running: the terminal
// client talks to the same service, and a client in the middle of an answer
// must not lose it because the window went; the next window, and the next
// client, attach to the service that is still there, with its model server
// and its running chats. So the service is
// started cut loose from the shell (a session of its own, no shared
// streams), on every platform, and before-quit ends only what belongs to
// the window: the terminals inside it. The service ends through `exe service stop`,
// or through its own shutdown — and, the one time this shell ends it, before
// an update is installed (endServiceForUpdate).

const {
  app, BrowserWindow, ClipboardItem, Menu, Tray, clipboard, globalShortcut, ipcMain, nativeImage, nativeTheme, screen,
  session, shell,
} = require('electron')
const { spawn } = require('child_process')
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
// source it is the PyInstaller output in dist/. The service is a FOLDER on
// every system — the program with its files beside it
// (deploy/exe-ai-terminal.spec: a one-file build unpacks itself into the
// system's temporary folder on every start) — so the path goes one level
// further, to the program inside.
function dienstpfad() {
  if (process.env.EXE_AI_DIENST) return process.env.EXE_AI_DIENST
  const service = app.isPackaged
    ? path.join(process.resourcesPath, 'exe-ai-terminal')
    : path.join(__dirname, '..', 'dist', 'Exe AI')
  return path.join(service, process.platform === 'win32' ? 'Exe AI.exe' : 'Exe AI')
}

// ---------------------------------------------------------------------------
// The command on the path
//
// After the first start of the app there is a command exe in every terminal
// of the machine: a link in /usr/local/bin to the command inside this app
// (Contents/Resources/bin/exe). Placed without asking where the folder is
// ours to write; where it is not — on most Macs it belongs to the system —
// the system's own password window asks once. Declined, it asks once more
// on the next start, and then never again: the count lives beside the
// window's geometry. A link that already points here is left alone; one
// that points elsewhere (an older copy of the app, a move) is replaced; a
// file that is no link is somebody else's and stays. `exe install` in a
// terminal does the same by hand (cli/install.py). Windows needs nothing
// here: its installer and the Store place the command.
//
// One case places nothing at all. An app started from a disk image, or
// from the read-only copy the system runs a freshly downloaded app from,
// sits where nothing stays: a link into it would point nowhere as soon as
// the app ends.

const CLI_LINK = '/usr/local/bin/exe'
// How often the password window may be declined before the app stops asking.
const CLI_LINK_DECLINES = 2
// What the password window says it is for.
const CLI_LINK_PROMPT = 'Exe AI places the command exe at /usr/local/bin.'

function cliLinkTarget() {
  return path.join(process.resourcesPath, 'bin', 'exe')
}

const cliLinkMemoryFile = () => path.join(app.getPath('userData'), 'cli-link.json')

// Where a link points, or null where there is none.
function cliLinkRead(link) {
  try {
    return fs.readlinkSync(link)
  } catch {
    return null
  }
}

// Does the command stay where it is? Not on a read-only volume — a disk
// image, the system's copy of a downloaded app. A folder that merely is not
// this user's to write is a different answer, and an installed app's.
function cliLinkTargetStays(target) {
  try {
    fs.accessSync(path.dirname(target), fs.constants.W_OK)
  } catch (error) {
    return error.code !== 'EROFS'
  }
  return true
}

function cliLinkDeclinesRead(file) {
  try {
    const { declined } = JSON.parse(fs.readFileSync(file, 'utf8'))
    return Number.isInteger(declined) && declined > 0 ? declined : 0
  } catch {
    return 0 // no file yet, or unreadable
  }
}

function cliLinkDeclineKeep(file, declined) {
  try {
    fs.writeFileSync(file, JSON.stringify({ declined }))
  } catch {
    /* asked again next time, which is the smaller of two faults */
  }
}

// A word for the shell, in single quotes; and a word for AppleScript, in
// double quotes — each escaping what its reader would otherwise read.
const shellWord = (text) => `'${text.replace(/'/g, "'\\''")}'`
const appleScriptWord = (text) => `"${text.replace(/[\\"]/g, '\\$&')}"`

// What the password window runs: the folder, then the link — replacing a
// link that is there (-n: a link to a folder is replaced, not entered).
function cliLinkScript(link, target) {
  const commands = `mkdir -p ${shellWord(path.dirname(link))} && ln -sfn ${shellWord(target)} ${shellWord(link)}`
  return `do shell script ${appleScriptWord(commands)} with prompt ${appleScriptWord(CLI_LINK_PROMPT)} with administrator privileges`
}

// The system's password window, once: the same two steps, run with the
// right the folder needs. Resolves to whether they went through.
function cliLinkElevate(link, target) {
  return new Promise((resolve) => {
    const ask = spawn('osascript', ['-e', cliLinkScript(link, target)], { stdio: 'ignore' })
    ask.on('error', () => resolve(false))
    ask.on('exit', (code) => resolve(code === 0))
  })
}

async function cliLinkPlace({
  link = CLI_LINK, target = cliLinkTarget(), memoryFile = cliLinkMemoryFile(), elevate = cliLinkElevate,
} = {}) {
  if (!cliLinkTargetStays(target)) return 'skipped'
  const pointsAt = cliLinkRead(link)
  if (pointsAt === target) return 'kept'
  try {
    fs.mkdirSync(path.dirname(link), { recursive: true })
    if (pointsAt !== null) fs.unlinkSync(link)
    fs.symlinkSync(target, link)
    console.log(`CLI: link placed at ${link}`)
    return 'placed'
  } catch (error) {
    if (error.code !== 'EACCES' && error.code !== 'EPERM') {
      console.error(`CLI: link not placed at ${link}:`, error.message)
      return 'failed'
    }
  }
  const declined = cliLinkDeclinesRead(memoryFile)
  if (declined >= CLI_LINK_DECLINES) return 'declined'
  if (await elevate(link, target)) {
    console.log(`CLI: link placed at ${link} with administrator rights`)
    return 'placed'
  }
  cliLinkDeclineKeep(memoryFile, declined + 1)
  console.log(`CLI: password window declined (${declined + 1} of ${CLI_LINK_DECLINES})`)
  return 'declined'
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
    const folded = sidebarFoldedRead()
    fs.writeFileSync(geometriedatei(), JSON.stringify({
      ...fenster.getNormalBounds(), ...(colour ? { colour } : {}), ...(scheme ? { scheme } : {}),
      ...(folded ? { folded } : {}),
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

// Where no colour is kept yet (the very first start), the page will show the
// look Auto: Exe where the system is dark, Snow where it is light. These are
// the solid frame tones (--bg-seite) of those two looks in stil/global.css, so
// window, splash and interface open on one colour and nothing changes on the
// way up. A test keeps them equal to the stylesheet.
const AUTO_GROUND_DARK = '#151514'
const AUTO_GROUND_LIGHT = '#e2e2e2'

function autoGround() {
  return nativeTheme.shouldUseDarkColors ? AUTO_GROUND_DARK : AUTO_GROUND_LIGHT
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
// The window buttons over the sidebar
//
// On the Mac the three window buttons stand in the first row of the sidebar
// (topbar.js): in front of the mark while the sidebar is open, centred over
// the signs of the narrow bar while it is folded. Only the page knows which
// of the two stands, so it says so (preload.js) every time it changes, and the
// shell moves the buttons there. Kept beside the colour, so the next start
// builds the window with the buttons where they stood. Nowhere else is
// anything set or kept.

function sidebarFoldedRead() {
  return windowFileRead().folded === true
}

function sidebarFoldedKeep(folded) {
  const kept = windowFileRead()
  if ((kept.folded === true) === folded) return
  try {
    fs.writeFileSync(geometriedatei(), JSON.stringify({ ...kept, folded }))
  } catch {
    /* the next start puts the buttons where the open sidebar wants them */
  }
}

ipcMain.on('sidebar-folded', (event, folded) => {
  if (process.platform !== 'darwin') return
  if (!fenster || fenster.isDestroyed() || event.sender !== fenster.webContents) return
  const is = folded === true
  fenster.setWindowButtonPosition(topbar.buttonsAt(is))
  sidebarFoldedKeep(is)
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
const dienstsuche = require('./dienstsuche')
const menueleiste = require('./menueleiste')
const topbar = require('./topbar')
const terminal = require('./terminal')
const { istHandbuch } = regel

function istEigeneSeite(adresse) {
  return regel.istEigeneSeite(adresse, PORT)
}

function nachDraussen(adresse) {
  if (regel.darfNachDraussen(adresse)) shell.openExternal(adresse)
}

// Whether this content is the main window's page.
function istHauptfenster(inhalt) {
  return Boolean(inhalt && fenster && !fenster.isDestroyed() && fenster.webContents === inhalt)
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
function fensterweiche({ url }, inhalt) {
  if (!istEigeneSeite(url)) {
    // A page may hand a foreign address to the browser by itself only from
    // the main window, whose page is the program's own code (the buttons to
    // a model's page and to an MCP server's page). Any other content — a
    // document, the manual, the developer tools — has no person's click
    // behind this call: a script in a loop would open one tab after another.
    // What a person clicks there goes out through the click catcher
    // (linkclicks.js), with or without `target="_blank"`.
    const haupt = istHauptfenster(inhalt)
    console.log(`Window open ${haupt ? 'outside' : 'block'}: ${regel.addressForLog(url)}`)
    if (haupt) nachDraussen(url)
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
// and writing only `image/png` never produces that second flavour, so there
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
  await clipboard.write([
    new ClipboardItem({ 'image/png': new Blob([bild.toPNG()], { type: 'image/png' }) }),
  ])
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

/* The words of the entries this program names by itself, in the language of
   the interface: the main window's page sends them from its catalogue
   (preload.js). Until it has, and for every word it left out, the English
   ones stand (kontextmenue.js). Every window's menu reads them — the
   language is the interface's, not one window's. */
let menuWords = kontextmenue.wordsFrom(null)

ipcMain.on('menu-words', (event, sent) => {
  if (!fenster || fenster.isDestroyed() || event.sender !== fenster.webContents) return
  menuWords = kontextmenue.wordsFrom(sent)
  // The page sends its words once it stands (and listens for the notice
  // before it does), so this is also the moment a notice that waited for it
  // can be handed over.
  pageTold = true
  noticeDeliver()
  // The sign's menu speaks the same language, and is set anew with it. After
  // the notice: a menu that cannot be set must not hold the notice back.
  try {
    if (sign) sign.setWords(sent)
  } catch (failure) {
    console.error('Menu bar: setting the words failed:', failure && failure.message)
  }
})

/* A notice for the page, from the shell: today only that ending the service
   from the sign's menu failed. It is handed over once — at once where the
   page stands, else as soon as it does (the window was closed, or is still
   loading) — and the page shows it in its own words. */
let pageTold = false
let noticePending = false

function noticeDeliver() {
  if (!noticePending || !pageTold || !fenster || fenster.isDestroyed()) return
  noticePending = false
  fenster.webContents.send('shell-notice', 'service-stop-failed')
}

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
      // user to work out that the address is dead, "unavailable" says it
      // outright. He has to be able to read that off the menu before he
      // copies, not find it out afterwards. And leaving the entry out
      // entirely would be just as mute: a right click that offers nothing
      // looks like the broken right click this menu was built for.
      //
      // "unavailable" only says something true about OUR OWN addresses,
      // where the missing part really is what makes the link dead — a
      // foreign link that happened to carry a `token=` or a `user:pass@`
      // still works perfectly well without it, it is simply a link this
      // program will not hand over whole.
      linkLabel: link && link.entfernt && istEigeneSeite(params.linkURL)
        ? menuWords.copyLinkUnavailable
        : menuWords.copyLink,
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
        return { label: menuWords.saveImage, click: () => inhalt.downloadURL(params.srcURL) }
      }
      if (eintrag.art === 'bild_kopieren') {
        // The picture's own address, not the spot it was clicked at — see
        // bildKopieren above.
        // Caught here: the menu takes no promise back, so a rejection on the
        // way (a window closed mid-copy, a dead address) would be an
        // unhandled one in the main process, where nothing is watching for it.
        //
        // A picture without an address has none to name: it is copied from
        // the spot it was clicked at, the only handle it has.
        return {
          label: menuWords.copyImage,
          click: () => {
            if (!params.srcURL) {
              inhalt.copyImageAt(params.x, params.y)
              return
            }
            bildKopieren(params.srcURL).catch((fehler) => {
              console.error('Copy Image failed:', fehler)
            })
          },
        }
      }
      return {
        label: eintrag.label,
        click: () => {
          clipboard.writeText(eintrag.adresse).catch((fehler) => {
            console.error('Copy failed:', fehler)
          })
        },
      }
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

// The manual is noted as the manual whichever window of the program opened
// it. `did-create-window` comes to the page that called `window.open`, so a
// listener on the main window alone never heard of a manual that a second
// window opened: that one stood there unnoticed, and the next call opened
// another beside it. Only the manual is remembered; a document or a script
// in its own window is not (see fensterweiche).
function rememberManual(inhalt) {
  inhalt.on('did-create-window', (neues, angaben) => {
    if (!istHandbuch(angaben && angaben.url)) return
    hilfefenster = neues
    // /help/ carries its own <title> and would overwrite "Exe AI — Help"
    // as soon as it loads.
    neues.on('page-title-updated', (ereignis) => ereignis.preventDefault())
    neues.on('closed', () => {
      if (hilfefenster === neues) hilfefenster = null
    })
  })
}

// Escape pressed while the focus is inside Chromium's PDF viewer. The viewer
// is a content of its own (the type `remote`, an address under the
// extension's); the key arrives there and not at the page, so the reader the
// page shows over the window would stay open under a key that closes it
// everywhere else. The shell hears the key at the viewer and says so to the
// page (preload.js, `aufBetrachterEscape`); the page closes the reader if it
// has one open. Only Escape, only a key going down, only while the window
// that shows the reader is the one with the focus — a PDF in a window of its
// own does not close a reader in this one. The key itself goes on into the
// viewer, untouched.
function betrachterTaste(inhalt, eingabe) {
  if (!eingabe || eingabe.type !== 'keyDown' || eingabe.key !== 'Escape') return
  if (!regel.isPdfViewer(inhalt.getURL())) return
  if (!fenster || fenster.isDestroyed() || !fenster.isFocused()) return
  fenster.webContents.send('betrachter-escape')
}

app.on('web-contents-created', (ereignis, inhalt) => {
  kontextmenueSetzen(inhalt)
  // Both rules for every page the program creates, at any depth: which
  // addresses may open a window, and where a page may navigate — for the
  // developer tools (View menu) in their own form, see navigationVerdict.
  inhalt.setWindowOpenHandler((angaben) => fensterweiche(angaben, inhalt))
  inhalt.on('before-input-event', (ereignis, eingabe) => betrachterTaste(inhalt, eingabe))
  rememberManual(inhalt)
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
// The sign in the menu bar (menueleiste.js), once the program is ready.
let sign = null

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
// The service of ours that was already running when this window started —
// its process id and port — and that this window uses instead of one of
// its own. It is not `kind`: nobody here started it, nobody here stops it.
let dienstVorgefunden = null
// Said once on the way out; before-quit runs more than once.
let bleibenGesagt = false

// Before a service is started: one of ours may already be running on this
// folder and port — started by the terminal client without a window, left
// running on purpose, or left behind by the installation of this program.
// Its note in the data folder names it, and its page answering says it is
// alive (dienstsuche.js). It is always ended and this window starts its own:
// whatever version it says it is, it was built before this program, and a
// build with the same number is not the same build. Where the client's stop
// does not end it, its process id does (endFoundService). Only a service
// that dienstsuche proves to be ours is ended; whatever else answers on the
// port is never touched.
//
// A service that cannot be ended at all (the system refuses the signal)
// stays in use, and the log says why — the one case left where this window
// attaches to a service it did not start.
async function dienstAnbinden() {
  const root = dienstsuche.dataRoot({
    packaged: app.isPackaged, repoRoot: path.join(__dirname, '..'),
  })
  const gefunden = await dienstsuche.runningService({ port: PORT, root })
  if (!gefunden) return false
  console.log(`Service: a service of ours is running on port ${gefunden.port} (pid ${gefunden.pid}); ending it, this program starts its own`)
  try {
    const words = await endFoundService(gefunden)
    console.log(`Service: ended (pid ${gefunden.pid}; ${words}); this program starts its own`)
    return false
  } catch (failure) {
    console.error(`Service: the running service did not end, it is used as it is: ${failure.message}`)
  }
  dienstVorgefunden = gefunden
  console.log(`Service: using the running service on port ${gefunden.port} (pid ${gefunden.pid}); none started`)
  return true
}

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
    // Cut loose from the shell, so that the service outlives the window
    // (the header of this file): a session of its own on macOS, its own
    // process group without a console on Windows — the same way the
    // terminal client starts it. No shared streams either: the service
    // writes its own log file.
    detached: true,
  })
  // The two listeners below speak for this one process, and only while it
  // is the shell's service. One that was ended before an update fires its
  // 'exit' when its shutdown is through, and by then `kind` is nothing, or
  // the service started after it.
  const started = kind
  // The shell does not wait for the service to end before it ends itself.
  kind.unref()
  // A service that starts and dies a second later — a missing library, a
  // port already taken, a broken database — fires 'exit', not 'error'.
  // Before it ever answered, that is a failed start just the same, and the
  // wait below stops at once instead of polling for two minutes.
  kind.on('exit', (code, signal) => {
    if (kind !== started) return
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
    if (kind !== started) return
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

// Who started a navigation. A page's own navigation names the frame that
// started it (`initiator`); one nobody started — the person's click on a link
// inside a PDF, which Chromium's viewer turns into a navigation of the
// window — has none. A frame that is already gone answers with an error
// instead of an address: that is "unknown", and unknown goes nowhere.
function starterOf(details) {
  try {
    const frame = details.initiator
    if (!frame) return { initiator: '', byBrowser: true }
    return { initiator: String(frame.url || ''), byBrowser: false }
  } catch (e) {
    return { initiator: '', byBrowser: false }
  }
}

// A link a person clicked in one of the program's pages: linkclicks.js
// reports it, the same rule as for a navigation decides, and only a foreign
// http(s) address opens the browser. The developer tools ask in vain.
ipcMain.on('open-link', (event, address) => {
  if (typeof address !== 'string') return
  const verdict = regel.linkVerdict(address, PORT, { tools: toolsPages.has(event.sender) })
  console.log(`Link click ${verdict}: ${regel.addressForLog(address)}`)
  if (verdict === 'outside') nachDraussen(address)
})

// One decision for both events. The log names the place, never the whole
// address (adressregel.js, addressForLog).
function navigationDecide(contents, details, redirect) {
  const verdict = regel.navigationVerdict(details.url, PORT, {
    mainFrame: details.isMainFrame, redirect, tools: toolsPages.has(contents),
    ...starterOf(details),
  })
  if (verdict === 'allow') return
  details.preventDefault()
  console.log(`Navigation ${verdict}${redirect ? ' (redirect)' : ''}: ${regel.addressForLog(details.url)}`)
  if (verdict === 'outside') nachDraussen(details.url)
}

function fensterBauen() {
  const gemerkt = geometrieLesen()
  // The scheme of that look, before the window is there to be drawn (and
  // before the system's own scheme is asked below: a forced one counts).
  frameSchemeApply(frameSchemeRead())
  // The frame colour of the look shown last: the ground of the window until
  // a page paints over it, and the ground of the splash. Without one kept,
  // the first start, it is the colour of the look Auto on this system.
  const ground = frameColourRead() || autoGround()
  console.log(`Window ground: ${ground}`)
  // The top bar: on the Mac the page draws it (topbar.js).
  const topBarOptions = topbar.topBarOptions(process.platform, sidebarFoldedRead())
  console.log(`Window top bar: ${JSON.stringify(topBarOptions)}`)
  fenster = new BrowserWindow({
    ...(gemerkt || { width: BREITE, height: HOEHE, center: true }),
    ...menuBarOptions(),
    ...topBarOptions,
    backgroundColor: ground,
    minWidth: MIN_BREITE, minHeight: MIN_HOEHE,
    title: 'Exe AI',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      /* The one bridge to the page, and it carries one thing: the dictation
         shortcut (see preload.js). Everything else about the interface is
         still a plain web page that knows nothing about this shell. */
      preload: path.join(__dirname, 'preload.js'),
      /* Tells the bridge whether the page draws the top bar. */
      additionalArguments: topbar.topBarArguments(process.platform),
      /* The viewer that draws a PDF's pages is a built-in plugin, and the
         window loads none unless told to. The page shows a PDF document in
         a frame; without this the frame stays empty. */
      plugins: true,
    },
  })
  fenster.loadFile(
    path.join(__dirname, 'anzeige', 'index.html'), { query: { ground } },
  )
  // The splash shows a failed start every time it has just loaded: the
  // first time when the verdict came while it was still loading, and again
  // after a reload, which would otherwise bring it back without its failure.
  fenster.webContents.on('did-finish-load', () => {
    if (dienstFehlgeschlagen) fehlstartSchreiben()
  })
  // A page that loads has not sent its words yet. The window's own page only:
  // a frame inside it (a document, a preview) loading changes nothing.
  pageTold = false
  fenster.webContents.on('did-navigate', () => { pageTold = false })

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
  // The interface asks for the manual with a plain window.open('/help/')
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
  // hook, and so is the noting of the manual (rememberManual): the manual
  // may be opened from any window, not only from this one.

  // Size and position are kept as they were when the program was closed.
  // Closing the window this way is only one of two exits — Cmd+Q never gets
  // here, so before-quit saves as well.
  fenster.on('close', () => geometrieSchreiben(fenster))

  // Closing the main window leaves the program running with its sign in the
  // menu bar; the terminals in the window end with its page (terminal.js).
}

// The window, whenever the sign, the dock or a second start asks for it: the
// one there is, in front — or, where it was closed, a new one. The interface
// loads as soon as the service answers, and the service is started again
// where it does not (it was ended from the sign's menu). A service that
// runs is never ended for a window, a service that is coming up is waited
// for and not started twice, and one asking while another is still under
// way is let go.
let opening = false

async function openWindow() {
  if (beendet || opening) return
  opening = true
  try {
    // A service that is just being ended is waited for, not started over.
    if (endingService) await endingService.catch(() => {})
    if (fenster && !fenster.isDestroyed()) {
      bringWindowForward()
      // On the interface, with the service answering: nothing left to do.
      if (fenster.webContents.getURL().startsWith(ADDRESS) && (await antwortet())) return
      // A failed start that stands on the page is over with this new try.
      fenster.webContents
        .executeJavaScript('delete document.body.dataset.zustand')
        .catch(() => {})
    } else {
      fensterBauen()
    }
    dienstFehlgeschlagen = false
    dienstAntwortete = false
    // A service found running whose process has since gone is no service.
    if (dienstVorgefunden && !dienstsuche.processAlive(dienstVorgefunden.pid)) dienstVorgefunden = null
    // A service of ours that is coming up is waited for, never started twice.
    if (!kind && !dienstVorgefunden) await dienstStarten()
    await warten()
  } finally {
    opening = false
  }
}

// The splash page is showing; switch over as soon as the service answers.
// Two minutes, not thirty seconds: the limit comes from the one-file build,
// whose first start was measured at around 55 seconds — it had to unpack
// before it even began setting up its database. The folder build unpacks
// nothing and answers within about a second; the limit stays generous, since
// the wait ends the moment the service answers or fails.
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

/* Pressed where the program runs on in the menu bar without a window: the
   window is opened, and the page is told once its microphone button stands
   (`button.mikro`, the button of Mikrofonknopf.svelte) — the page only
   listens after it has been built, so a message sent any earlier goes
   nowhere. An open already under way is waited for, as long as it takes;
   a start of the service that failed ends the wait. A press while this is
   under way changes nothing; it would stop the recording the first one is
   about to start. */
let dictationPending = false

async function startDictationInNewWindow() {
  if (dictationPending) return
  dictationPending = true
  try {
    await openWindow()
    const deadline = Date.now() + 30000
    while (opening || Date.now() < deadline) {
      if (beendet || dienstFehlgeschlagen || !fenster || fenster.isDestroyed()) return
      const ready =
        fenster.webContents.getURL().startsWith(ADDRESS) &&
        (await fenster.webContents
          .executeJavaScript("!!document.querySelector('button.mikro')")
          .catch(() => false))
      if (ready) {
        bringWindowForward()
        fenster.webContents.send('diktat')
        return
      }
      await new Promise((r) => setTimeout(r, 200))
    }
  } finally {
    dictationPending = false
  }
}

function kuerzelSetzen() {
  /* A shortcut another program already holds cannot be taken, and that is
     not a reason to refuse to start: everything else about the program works
     without it, and the button is still there to be clicked. */
  const genommen = globalShortcut.register(DIKTAT_KUERZEL, () => {
    if (dictationPending) return
    if (!fenster || fenster.isDestroyed()) {
      // The program runs on without a window, in the menu bar: the shortcut
      // brings one, and the dictation begins in it.
      if (sign) startDictationInNewWindow()
      return
    }
    bringWindowForward()
    fenster.webContents.send('diktat')
  })
  if (!genommen) console.warn('Shortcut already taken:', DIKTAT_KUERZEL)
}

// ---------------------------------------------------------------------------
// The terminal in the window
//
// The way to it is terminal.js: the page asks for it over the bridge and
// gets the terminal client against this shell's own service, in a
// pseudoterminal this shell owns. node-pty is the one native piece, built
// for this Electron; where it cannot be loaded the page is told so when it
// asks, and nothing else of the program is affected.
let pty = null
try {
  pty = require('node-pty')
} catch (fehler) {
  console.error('node-pty could not be loaded; the terminal in the window is unavailable:', fehler && fehler.message)
}
// The one spelling of the own address, without the page's path.
const ADDRESS = new URL(ZIEL).origin
// The terminal client of this installation: the terminals in the window run
// it, and an update ends the service with it.
const clientProgram = terminal.clientCommand({
  packaged: app.isPackaged,
  resourcesPath: process.resourcesPath,
  repoRoot: path.join(__dirname, '..'),
})
const terminals = terminal.createTerminals({
  ipcMain,
  pty,
  address: ADDRESS,
  command: clientProgram,
})

// ---------------------------------------------------------------------------
// The sign in the menu bar
//
// The way to it is menueleiste.js. Its entries open the window, end the
// service, and end the program; ending the service is the client's stop, the
// one an update takes, and it takes the model server along.

// The end that is under way, while there is one: a window asked for in the
// meantime waits for it, and starts the service afterwards.
let endingService = null

function endServiceFromMenu() {
  endingService = endServiceNow().finally(() => { endingService = null })
  return endingService
}

async function endServiceNow() {
  const root = dienstsuche.dataRoot({
    packaged: app.isPackaged, repoRoot: path.join(__dirname, '..'),
  })
  const running = await dienstsuche.runningService({ port: PORT, root })
  const mine = kind
  const found = dienstVorgefunden
  // Whatever it was doing, its end is the one asked for: no failed start.
  dienstAntwortete = true
  // The client's stop, and then the process itself, as before an update: the
  // service closes its port before its model server is gone, and a window
  // opened in between would start a second service on the same folder.
  const words = await endRunningService(running)
  const whose = running ? `pid ${running.pid}; ` : ''
  console.log(`Service: ended from the menu bar (${whose}${words})`)
  // Nothing of ours runs any more — unless another start began while this
  // one ended, which is its own.
  if (kind === mine) kind = null
  if (dienstVorgefunden === found) dienstVorgefunden = null
}

// Ending the service from the menu failed: the window comes up (a new one
// where it was closed) and the page shows a message.
async function tellStopFailed() {
  noticePending = true
  try {
    await openWindow()
  } finally {
    // No window came up (the program is ending): nothing waits for a page
    // that is not there, and the notice does not wait for a later one.
    if (!fenster || fenster.isDestroyed()) noticePending = false
  }
  bringWindowForward()
  noticeDeliver()
}

function setUpSign() {
  try {
    sign = menueleiste.start({
      Tray, Menu, nativeImage,
      folder: path.join(__dirname, 'anzeige'),
      platform: process.platform,
      answers: antwortet,
      openWindow,
      endService: endServiceFromMenu,
      endProgram: () => app.quit(),
      endFailed: tellStopFailed,
      log: (line) => console.error(line),
    })
  } catch (failure) {
    // Without its sign the program ends with its window, as it always did.
    sign = null
    console.error('Menu bar: the sign could not be set up:', failure && failure.message)
  }
}

// ---------------------------------------------------------------------------
// A newer version
//
// The way to it is updater.js. It answers the page of the main window and
// nobody else, and the one look it takes by itself comes after the service's
// start, below.
//
// Installing one is the single case in which this shell ends the service.
// The release replaces the service's own files; a service left running
// would carry on as the old program on top of them, and the new window
// would attach to it after the restart. So the service of this installation
// goes before the package takes over, and the new version starts it afresh.
// An answer that is being written ends with it.

// Ends the service on the one way there is: the terminal client's
// `service stop`, the command a user types as `exe service stop`
// (cli/service.py). It reads the
// service's note, asks the process that wrote it to end and waits until the
// port is free; the service's own shutdown takes its model server along.
// Asked for this shell's own address, so it is the service of this
// installation whoever started it — this window, an earlier one, the
// terminal client. In English, like every other reason an update gives.
//
// Resolves with the client's words once it reports that no service is left;
// rejects with them where the service did not end, and with the system's
// where the client could not be run at all.
function clientStop() {
  return new Promise((done, failed) => {
    const said = []
    const client = spawn(
      clientProgram.file,
      [...clientProgram.args, 'service', 'stop', '--url', ADDRESS, '--lang', 'en'],
      { cwd: clientProgram.cwd, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true },
    )
    client.stdout.on('data', (piece) => said.push(piece))
    client.stderr.on('data', (piece) => said.push(piece))
    client.on('error', failed)
    client.on('close', (code) => {
      const words = Buffer.concat(said).toString('utf8').trim()
      if (code === 0) done(words)
      else failed(new Error(words || `exe service stop: ${code}`))
    })
  })
}

// The pause between two looks at a process that is ending — the one the
// wait for the service's start takes between two looks at its port.
const LOOK_PAUSE_MS = 300

// The end of a service of ours that is running (`running`: its note's
// `{ pid, port }`, or null where none is known): the client's stop, and then
// the end of the process itself, waited for with no time of its own — the
// way before an update, where the service may be writing an answer to its
// end. The start has its own, bounded one (endFoundService).
async function endRunningService(running) {
  const words = await clientStop()
  while (running && dienstsuche.processAlive(running.pid)) {
    await new Promise((next) => setTimeout(next, LOOK_PAUSE_MS))
  }
  return words
}

// How long a process that was asked to end may live before it is made to.
const KILL_AFTER_MS = 5000

// A signal to the process of a service that was proved to be ours. A process
// that is already gone is the end that was wanted, not a failure.
function signalProcess(pid, signal) {
  try {
    process.kill(pid, signal)
  } catch (failure) {
    if (!failure || failure.code !== 'ESRCH') throw failure
  }
}

// The end of the service found at the start (`running`: its note's
// `{ pid, port }`, proved to be ours by dienstsuche.runningService): the
// client's stop first, the way an update ends it; where that fails the
// process is asked to end by its id (SIGTERM). A process that still lives
// after KILL_AFTER_MS is made to end (SIGKILL). Resolves with the words of
// how it ended; rejects where the process cannot be ended.
async function endFoundService(running) {
  let words
  try {
    words = await clientStop()
  } catch (failure) {
    words = `the client's stop failed (${failure.message}); the process was asked to end`
    signalProcess(running.pid, 'SIGTERM')
  }
  const waitFor = async () => {
    const until = Date.now() + KILL_AFTER_MS
    while (dienstsuche.processAlive(running.pid) && Date.now() < until) {
      await new Promise((next) => setTimeout(next, LOOK_PAUSE_MS))
    }
    return !dienstsuche.processAlive(running.pid)
  }
  if (await waitFor()) return words
  signalProcess(running.pid, 'SIGKILL')
  if (await waitFor()) return `${words}; it lived ${KILL_AFTER_MS / 1000} s on and was ended by force`
  throw new Error(`pid ${running.pid} is still alive after SIGKILL`)
}

// The service's end before an update: the client's stop, and then the end
// of the process itself. The stop is through when the port is free, and the
// service closes its port before it shuts down — its model server and
// whatever else it runs end after that. The program is handed over only
// once that process is gone. Which process: the service of ours that is
// running here before the stop, found the way the start finds it — a note
// alone would not do, a crashed service leaves its note behind and the
// system may have handed its number to a stranger since. Waited for as long
// as it lives, with no time of its own, the way the client waits for a
// service it started.
async function endServiceForUpdate() {
  const root = dienstsuche.dataRoot({
    packaged: app.isPackaged, repoRoot: path.join(__dirname, '..'),
  })
  const running = await dienstsuche.runningService({ port: PORT, root })
  const words = await endRunningService(running)
  const whose = running ? `pid ${running.pid}; ` : ''
  console.log(`Service: ended before the update is installed (${whose}${words})`)
  // Gone, whoever started it: the way out has no service left to speak of.
  dienstVorgefunden = null
  kind = null
}

// An installation that failed after the service had ended for it. The
// program runs on, so its service comes back; and the window loads the
// interface anew, because the page it shows belonged to the service that is
// gone. A service that does not come up is a failed start like any other.
function restartServiceAfterUpdate() {
  console.log('Service: starting again, the update was not installed')
  dienstAntwortete = false
  dienstStarten().then(warten)
}

const updater = require('./updater')
updater.start(() => fenster, {
  endService: endServiceForUpdate,
  restartService: restartServiceAfterUpdate,
})

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
    // A program that runs on in the menu bar without a window opens one.
    if (sign && (!fenster || fenster.isDestroyed())) {
      console.log('Second start: opening the window')
      openWindow()
      return
    }
    console.log('Second start: bringing the window forward')
    bringWindowForward()
  })
  app.whenReady().then(async () => {
    // The click catcher goes into every page of the session, before any
    // window loads one.
    session.defaultSession.registerPreloadScript({
      type: 'frame', id: 'linkclicks', filePath: path.join(__dirname, 'linkclicks.js'),
    })
    menueSetzen()
    fensterBauen()
    kuerzelSetzen()
    setUpSign()
    // The sign's entries wait while the start is under way.
    opening = true
    try {
      if (!(await dienstAnbinden())) await dienstStarten()
    } finally {
      opening = false
    }
    // One quiet look for a newer version, once the service is on its way.
    // Whatever it finds is the page's to show; the shell shows nothing.
    updater.check()
    // The command on the path — only the installed app has one to point at.
    if (process.platform === 'darwin' && app.isPackaged) cliLinkPlace().catch((error) => {
      console.error('CLI: link not placed:', error.message)
    })
    warten()
  })
} else {
  // The program is already running, and that instance has just been told.
  console.log('Already running: handing this start to the first instance')
  app.quit()
}

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  if (sign) sign.remove()
})

// The dock icon on macOS asks for a window as well.
app.on('activate', () => {
  if (sign && (!fenster || fenster.isDestroyed())) openWindow()
})

// The last window closing does not end the program; the sign keeps it. Where
// the sign could not be set up, nothing would keep it, and it ends.
app.on('window-all-closed', () => {
  if (!sign) app.quit()
})

// The way out. The service is not ended here, on no platform: it was started
// cut loose from the shell (dienstStarten) and runs on for the terminal
// client and the next window (the header of this file). Nothing is waited
// for, so the quit goes through as it came — a quit from the sign in the
// menu bar, Cmd+Q and an update's restart can each run through more than
// once, and every pass simply runs through.
app.on('before-quit', () => {
  // Cmd+Q ends the program without ever closing the window — so the
  // geometry has to be written here too, before anything else, or a quit by
  // keystroke forgets where the window stood.
  if (fenster && !fenster.isDestroyed()) geometrieSchreiben(fenster)
  // Remembered on every pass, with or without a service: a start still on
  // its way (dienstStarten) must not spawn one after this.
  beendet = true
  // The terminal client in the window ends with its window: a client
  // outliving its page would hang on a closed pipe. The service it talked
  // to stays.
  terminals.stopAll()
  // Said once, whoever started the service: the one this window found was
  // meant to run on by whoever started it — the terminal client, an earlier
  // window; the one this window started runs on for the same reason.
  if (bleibenGesagt) return
  bleibenGesagt = true
  if (dienstVorgefunden) {
    console.log(`Service: the running service on port ${dienstVorgefunden.port} stays; this window did not start it`)
  } else if (kind) {
    console.log(`Service: the service on port ${PORT} started by this window stays, for the terminal client and the next window`)
  }
})
