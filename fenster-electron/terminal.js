/*
  The terminal inside the window: one pseudoterminal per page, running the
  terminal client `exe` against this shell's own service.

  The page draws the terminal (xterm.js, frontend/src/teile/Terminal.svelte)
  and knows nothing about processes; this module owns the process. Over the
  bridge (preload.js) the page asks for a terminal with its size, the look
  and the language it shows and the chat it has open; it sends what was
  typed and every new size, and hears the output and the end. The client is
  told that it runs in the window (EXE_AI_WINDOW_TERMINAL=1): there it
  leaves the ground to the page instead of painting it, so the page's own
  ground shows through.

  The address the client is given is always the shell's own service — the
  page does not get to name one. What the page names (chat, look, language,
  size) is checked here before it becomes an argument.

  node-pty is the one native piece, and it is handed in by main.js: the
  rest of this file is plain node, so tests run it with a stand-in.
*/

const fs = require('fs')
const os = require('os')
const path = require('path')

// The client's mark that it runs inside the window.
const WINDOW_MARK = 'EXE_AI_WINDOW_TERMINAL'

// The terminal type the client sees. xterm.js speaks it, with true colour.
const TERMINAL_NAME = 'xterm-256color'

// What the page may name. A look or a language is a short word; a chat id
// is the service's hex id (app/db). Anything else is dropped, not passed.
const WORD = /^[a-z]{2,16}$/
const CHAT_ID = /^[0-9a-f]{32}$/
const SIZE_MIN = 2
const SIZE_MAX = 1000
const DEFAULT_COLS = 80
const DEFAULT_ROWS = 24

/**
 * The program to run and how: packaged, the command the package carries;
 * from source the virtual environment's Python with the client as a
 * module, in the source tree. EXE_AI_CLI names another program for a trial
 * run, as EXE_AI_DIENST does for the service.
 *
 * Where the package carries the command, counted from its resources folder:
 * on macOS the small script the link on the path points at, in a bin folder
 * beside the service's folder (package.json, mac.extraResources); on Windows
 * the console program inside the service's folder (the folder from
 * package.json, extraResources; the program from deploy/exe-ai-terminal.spec
 * — the installer's exe.cmd and the Store's alias name the same place).
 */
function clientCommand({
  env = process.env,
  packaged = false,
  resourcesPath = '',
  repoRoot = '',
  platform = process.platform,
} = {}) {
  const own = String(env.EXE_AI_CLI || '').trim()
  if (own) return { file: own, args: [], cwd: os.homedir() }
  if (packaged) {
    const file = platform === 'win32'
      ? path.join(resourcesPath, 'exe-ai-terminal', 'exe.exe')
      : path.join(resourcesPath, 'bin', 'exe')
    return { file, args: [], cwd: os.homedir() }
  }
  const python = platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python')
  return { file: python, args: ['-m', 'cli'], cwd: repoRoot }
}

function size(value, fallback) {
  const n = Math.round(Number(value))
  return Number.isInteger(n) && n >= SIZE_MIN && n <= SIZE_MAX ? n : fallback
}

function word(value, pattern) {
  return typeof value === 'string' && pattern.test(value) ? value : ''
}

/** What the page asked for, with only the shapes this module passes on. */
function cleanRequest(raw) {
  const request = raw && typeof raw === 'object' ? raw : {}
  return {
    chat: word(request.chat, CHAT_ID),
    look: word(request.look, WORD),
    lang: word(request.lang, WORD),
    cols: size(request.cols, DEFAULT_COLS),
    rows: size(request.rows, DEFAULT_ROWS),
  }
}

/** The client's arguments: the service's address, then what the page named. */
function clientArguments({ address, chat = '', look = '', lang = '' }) {
  const args = ['--url', address]
  if (chat) args.push('--chat', chat)
  if (look) args.push('--theme', look)
  if (lang) args.push('--lang', lang)
  return args
}

/** The client's environment: the window's mark and a true-colour terminal. */
function clientEnvironment(env = process.env) {
  return { ...env, [WINDOW_MARK]: '1', TERM: TERMINAL_NAME, COLORTERM: 'truecolor' }
}

/**
 * The terminals of this shell, one per page. `pty` is node-pty (or a
 * stand-in with `spawn`); null where it could not be loaded, and then
 * every start answers with an error instead of a process id. `exists` says
 * whether the program is there: where it is not, nothing is started and the
 * answer names the file.
 *
 * Wired to `ipcMain` under five names: `terminal-start` (invoke, answers
 * `{ pid }` or `{ error }`), `terminal-write`, `terminal-resize`,
 * `terminal-stop`; the page hears `terminal-data` and `terminal-exit`.
 */
function createTerminals({ ipcMain, pty, address, command, log = console.log, exists = fs.existsSync }) {
  const sessions = new Map()
  // The pages whose end is already listened for: one listener per page,
  // however often it asks for a client.
  const watched = new Set()

  function start(contents, request) {
    stop(contents.id)
    // The one failure named here rather than by the system: `reason` lets
    // the page say it in the language it shows.
    if (!pty) return { error: 'node-pty is unavailable.', reason: 'no-pty' }
    /* A missing program does not make node-pty throw on every system: the
       child ends at once and the page would only see that it ended. So the
       file is looked for first, and nothing is started where it is not. */
    if (!exists(command.file)) {
      log(`Terminal: ${command.file} was not found, nothing was started`)
      return { error: `${command.file} was not found.`, reason: 'no-file', path: command.file }
    }
    const wish = cleanRequest(request)
    let term
    try {
      term = pty.spawn(command.file, [...command.args, ...clientArguments({ address, ...wish })], {
        name: TERMINAL_NAME,
        cols: wish.cols,
        rows: wish.rows,
        cwd: command.cwd,
        env: clientEnvironment(),
      })
    } catch (failure) {
      log(`Terminal: ${command.file} could not be started: ${failure && failure.message}`)
      return { error: String((failure && failure.message) || failure) }
    }
    sessions.set(contents.id, term)
    // Only the page's CURRENT client speaks to it: one that was replaced
    // (a reload, a restart) still drains and exits after its successor
    // started, and its end must not be taken for the successor's.
    const current = () => sessions.get(contents.id) === term
    term.onData((data) => {
      if (current() && !contents.isDestroyed()) contents.send('terminal-data', data)
    })
    term.onExit(({ exitCode }) => {
      if (!current()) return
      sessions.delete(contents.id)
      if (!contents.isDestroyed()) contents.send('terminal-exit', exitCode)
    })
    log(`Terminal: ${command.file} started in the window against ${address} (pid ${term.pid})`)
    return { pid: term.pid }
  }

  function stop(id) {
    const term = sessions.get(id)
    if (!term) return
    sessions.delete(id)
    try {
      term.kill()
    } catch {
      /* already gone */
    }
  }

  function stopAll() {
    for (const id of [...sessions.keys()]) stop(id)
  }

  ipcMain.handle('terminal-start', (event, request) => {
    const contents = event.sender
    if (!watched.has(contents.id)) {
      watched.add(contents.id)
      contents.once('destroyed', () => {
        watched.delete(contents.id)
        stop(contents.id)
      })
    }
    return start(contents, request)
  })
  ipcMain.on('terminal-write', (event, data) => {
    const term = sessions.get(event.sender.id)
    if (term) term.write(String(data ?? ''))
  })
  ipcMain.on('terminal-resize', (event, cols, rows) => {
    const term = sessions.get(event.sender.id)
    if (term) term.resize(size(cols, DEFAULT_COLS), size(rows, DEFAULT_ROWS))
  })
  ipcMain.on('terminal-stop', (event) => stop(event.sender.id))

  return { start, stop, stopAll, running: (id) => sessions.has(id) }
}

module.exports = {
  WINDOW_MARK,
  TERMINAL_NAME,
  clientCommand,
  cleanRequest,
  clientArguments,
  clientEnvironment,
  createTerminals,
}
