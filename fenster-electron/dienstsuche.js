/*
  The service that is already running on this shell's folder and port —
  found before the shell starts one of its own.

  When the service starts it writes a note about itself into its data
  folder (app/main.py: `.dienst-<port>.json`, its process id and its port)
  and takes the note back on a clean stop. A note under THIS shell's port in
  THIS shell's data folder is a service of ours: same folder, same port,
  started by `exe` without a window, or still running from an earlier
  window. Whether it is alive is asked of the service itself, at the one
  address every client of it loads first — the interface page. A port that
  merely accepts a connection could be anything; a page that answers is the
  service.

  The folder is the one the service itself resolves (app/paketierung.py):
  EXE_AI_DATEN where that names one, the system's place for the packaged
  program, the source tree otherwise — and the service's `data_dir` under
  it, which ships as `./data` (config.example.yaml). A service that was
  given another data folder in its own configuration file leaves no note
  here, and the shell then probes the port the way it always did.

  Plain node, no electron: tests run it, and so does main.js.
*/

const fs = require('fs')
const http = require('http')
const os = require('os')
const path = require('path')

// The service's name for its note, and its data folder under the root.
const NOTE_PREFIX = '.dienst'
const DATA_FOLDER = 'data'

// How long the interface page gets to answer. Local, so short — but longer
// than the port probe's 400 ms: a page is more than a socket.
const PAGE_TIMEOUT_MS = 1500

/**
 * The root the service keeps its data under, resolved the way the service
 * does it (app/paketierung.py, `daten()`).
 */
function dataRoot({
  env = process.env,
  packaged = false,
  platform = process.platform,
  home = os.homedir(),
  repoRoot = '',
} = {}) {
  const own = String(env.EXE_AI_DATEN || '').trim()
  if (own) return own
  if (!packaged) return repoRoot
  if (platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'Exe AI Terminal')
  if (platform === 'win32') return path.join(home, 'AppData', 'Roaming', 'Exe AI Terminal')
  return path.join(home, '.local', 'share', 'exe-ai-terminal')
}

/** Where the service's note for `port` lies under `root`. */
function noteFile(root, port) {
  return path.join(root, DATA_FOLDER, `${NOTE_PREFIX}-${port}.json`)
}

/**
 * The note's content — `{ pid, port }` — or null where there is no readable
 * note. Half a file, a folder, a stranger's format: all null; the note is
 * a hint to ask the service, never the proof that it is there.
 */
function readNote(file) {
  let text
  try {
    text = fs.readFileSync(file, 'utf8')
  } catch {
    return null
  }
  try {
    const data = JSON.parse(text)
    const pid = Number(data.pid)
    const port = Number(data.port)
    if (!Number.isInteger(pid) || !Number.isInteger(port)) return null
    return { pid, port }
  } catch {
    return null
  }
}

/**
 * Is the process behind `pid` possibly alive? Only a clear "no such
 * process" says no; a process this user may not signal exists all the
 * same, and so does one the system cannot be asked about.
 */
function processAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (failure) {
    return !(failure && failure.code === 'ESRCH')
  }
}

/**
 * Does the interface page answer at that port? Resolves true only for a
 * complete 200 — a refused connection, a timeout, any other status is a
 * silent service.
 */
function pageAnswers(port, { host = '127.0.0.1', timeout = PAGE_TIMEOUT_MS } = {}) {
  return new Promise((done) => {
    let decided = false
    const settle = (answer) => {
      if (decided) return
      decided = true
      done(answer)
    }
    const request = http.get({ host, port, path: '/app/', timeout }, (answer) => {
      answer.resume()
      settle(answer.statusCode === 200)
    })
    request.on('timeout', () => {
      request.destroy()
      settle(false)
    })
    request.on('error', () => settle(false))
  })
}

/**
 * The service of ours already running on `port` with its data under
 * `root`: `{ pid, port }` — or null, where there is no note for the port,
 * the note names another port, its process is certainly gone, or the page
 * does not answer. `answers` and `alive` stand in for the two probes in
 * tests.
 */
async function runningService({ port, root, answers = pageAnswers, alive = processAlive }) {
  const note = readNote(noteFile(root, port))
  if (!note || note.port !== port) return null
  // A note whose writer is certainly gone names nobody, whatever answers
  // on the port now: a crashed service leaves its note behind, and the
  // port may since have gone to another program.
  if (!alive(note.pid)) return null
  if (!(await answers(port))) return null
  return { pid: note.pid, port }
}

module.exports = {
  dataRoot, noteFile, readNote, pageAnswers, processAlive, runningService,
}
