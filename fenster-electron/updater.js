// The shell's way to a newer version of itself.
//
// The published versions are the project's releases. electron-updater reads
// their feed (latest-mac.yml on macOS, latest.yml on Windows), compares the
// version by semver and fetches the package. A release still in draft is in
// no feed, so nobody is offered it before it is published.
//
// Nothing here acts on its own beyond one quiet look after the start: no
// download and no installation without a word from the page, and never a
// step back to an older version. The shell shows nothing of this itself —
// no window, no menu entry. It keeps one state, tells the page every change
// of it over the bridge (preload.js) and writes the same change as a line
// into its own log. A failure is one more state, with its reason, and
// nothing else: the program runs on.

const { app, ipcMain } = require('electron')
const { autoUpdater } = require('electron-updater')

autoUpdater.autoDownload = false
autoUpdater.autoInstallOnAppQuit = false
autoUpdater.allowDowngrade = false
// One voice in the log: the lines written below. The library's own lines
// and its stack traces stay out.
autoUpdater.logger = null

// A copy from the Microsoft Store is the Store's to keep current: it
// installs every new version itself, and a look of our own would find a
// feed that copy cannot install from. Electron says which copy runs
// (process.windowsStore); such a copy never looks, fetches or installs, and
// tells the page so in one state of its own.
const storeManaged = Boolean(process.windowsStore)

// A run from the source folder is not packaged and has no feed description,
// so it never looks for anything. A trial run can name one of its own — a
// file like the app-update.yml a packaged shell carries — and then checks
// like a packaged one, against whatever feed that file points at. A packaged
// shell does not read the variable.
const trialConfig = app.isPackaged ? '' : process.env.EXE_AI_UPDATE_CONFIG
if (trialConfig) {
  autoUpdater.forceDevUpdateConfig = true
  autoUpdater.updateConfigPath = trialConfig
}

// What the page is told. `state` is one of none, checking, available,
// downloading, downloaded, error — or store, from the first moment on, in a
// copy the Store keeps current. `found`, `notes` and `date` describe the
// newer release of the last look that found one — the notes as the release
// carries them, which from a GitHub release is HTML. `progress` is set while
// a download runs, `reason` and `step` while the state is error: `step` says
// which of the three steps failed — check, download or install.
const status = {
  version: app.getVersion(),
  found: '',
  notes: '',
  date: '',
  state: storeManaged ? 'store' : 'none',
  progress: null,
  reason: '',
  step: '',
}

let mainWindow = () => null
let installing = false
// The step under way. The library's error event carries a failure and its
// text but no step, so the call that starts one writes it down here.
let step = 'check'

// What an installation asks of the service, handed in by the shell (start).
// The release about to be installed replaces the service's own files, and a
// service left running would go on as the old program on top of them — with
// the new window attaching to it after the restart. So `endService` ends the
// service of this installation, with its model server, before the package
// takes over, and rejects with the reason where it cannot. `restartService`
// brings it back where the installation fails after that: the program runs
// on then, and so must its service.
const service = { endService: async () => {}, restartService: () => {} }
// Set from the service's end until the program's: an installation that
// fails in that stretch has taken the service down and owes it back.
let serviceEnded = false

function snapshot() {
  return { ...status, progress: status.progress && { ...status.progress } }
}

function change(next, line) {
  Object.assign(status, next)
  console.log(`Update: ${line}`)
  const window = mainWindow()
  if (window && !window.isDestroyed()) window.webContents.send('updates-state', snapshot())
}

// What went wrong, in one line: the library's messages run on with response
// headers and a stack trace after the first. The library's own code for the
// failure leads, unless the message begins with it already.
function reasonOf(error) {
  const line = String(error?.message ?? error).split('\n')[0].trim()
  const code = error?.code
  return code && !line.startsWith(code) ? `${code}: ${line}` : line
}

function fail(error) {
  // An installation that failed is over; the next try starts from a new look.
  installing = false
  const reason = reasonOf(error)
  change({ state: 'error', reason, step, progress: null }, `error: ${reason}`)
  if (serviceEnded) {
    serviceEnded = false
    service.restartService()
  }
}

autoUpdater.on('checking-for-update', () => {
  change({ state: 'checking', reason: '' }, 'checking')
})

autoUpdater.on('update-available', (info) => {
  change({
    state: 'available',
    found: info.version,
    notes: typeof info.releaseNotes === 'string' ? info.releaseNotes : '',
    date: info.releaseDate || '',
    progress: null,
  }, `available ${info.version}`)
})

autoUpdater.on('update-not-available', (info) => {
  change(
    { state: 'none', found: '', notes: '', date: '', progress: null },
    `not available (running ${status.version}, published ${info.version})`,
  )
})

autoUpdater.on('download-progress', (progress) => {
  change({
    state: 'downloading',
    progress: {
      percent: progress.percent,
      transferred: progress.transferred,
      total: progress.total,
      bytesPerSecond: progress.bytesPerSecond,
    },
  }, `downloading ${Math.round(progress.percent)} %`)
})

autoUpdater.on('update-downloaded', () => {
  change({ state: 'downloaded', progress: null }, `downloaded ${status.found}`)
})

autoUpdater.on('error', fail)

// Each of the three calls below answers with the state it left behind. The
// library tells a failure as the 'error' event and then repeats it as its
// promise's rejection, so the rejection normally finds the state at error
// already. One that comes without the event — or a call that throws at once
// — must not leave the state waiting for an end that never comes.
async function settle(call) {
  try {
    await call()
  } catch (error) {
    if (status.state !== 'error') fail(error)
  }
  return snapshot()
}

// Looks at the feed. Not while a download runs or lies ready: the look would
// put the state back to "available" underneath it.
function check() {
  if (storeManaged) return snapshot()
  if (status.state === 'downloading' || status.state === 'downloaded') return snapshot()
  step = 'check'
  return settle(() => autoUpdater.checkForUpdates())
}

// Fetches the release the last look found, and nothing without one.
function download() {
  if (status.state !== 'available') return snapshot()
  step = 'download'
  change({ state: 'downloading', progress: null }, `downloading ${status.found}`)
  return settle(() => autoUpdater.downloadUpdate())
}

// Ends the service, then the program, installs the fetched release and
// starts it again. The service goes first, and nothing is handed over before
// it is gone: where it cannot be ended, nothing is installed, and the state
// is the error with its reason. On macOS the system's updater first takes
// the package over, so the program ends a moment after the call, not with
// it; a second call in between — or while the service is still ending —
// must not start that a second time.
async function install() {
  if (status.state !== 'downloaded' || installing) return snapshot()
  installing = true
  step = 'install'
  console.log(`Update: installing ${status.found}`)
  try {
    await service.endService()
    serviceEnded = true
    autoUpdater.quitAndInstall()
  } catch (error) {
    fail(error)
  }
  return snapshot()
}

// Wires the bridge's four calls. `window` hands back the main window, or
// nothing while there is none: only that page hears of a change.
// `installation` carries the two things an installation asks of the service
// (above); a shell that hands in none installs without them.
function start(window, installation = {}) {
  mainWindow = window
  Object.assign(service, installation)
  ipcMain.handle('updates-status', () => snapshot())
  ipcMain.handle('updates-check', () => check())
  ipcMain.handle('updates-download', () => download())
  ipcMain.handle('updates-install', () => install())
}

module.exports = { start, check }
