/*
  The one bridge between the shell and the page.

  The interface is a web page. It knows nothing about the window it sits in,
  and that is deliberate: `contextIsolation` is on and `nodeIntegration` is
  off, so nothing in the page can reach the machine. This file is the single,
  named exception, and it carries exactly one thing across.

  Two things cross it, both about the page's own voice and microphone. The
  dictation shortcut: it is registered by the shell, because a key pressed
  while another program is in front never reaches a web page at all; the
  page is what owns the microphone button, so the shell has to be able to
  say "that key was pressed" and nothing more. And "Read aloud" in the
  right-click menu: the menu belongs to the shell, the voice to the page —
  the page names the entry in its own language, the shell hands back the
  marked text.

  And one question the page may ask: the preview of a file in the doc
  folder. It names the address the service hands the file out at, never a
  path, and the shell answers only for its own service (thumbnail.js).

  And the program's own newer version (updater.js): the page asks what the
  shell found, and says when to look again, to fetch it and to install it.
  The shell shows nothing of an update itself, so the page is where it is
  offered — and installing ends the program, which only the shell can do.

  And the colour of the page's frame: the page says it, the shell keeps it
  and opens its window on that colour the next time, before any page is
  there to paint one.

  And one fact the shell tells the page, once: whether the window buttons
  stand in the page (`topBar`, true on the Mac, where the system's bar is left
  out of the window; topbar.js). The shell passes it as an argument of this
  process, since a sandboxed bridge cannot read the shell's files. And one
  word the page tells the shell: whether the narrow bar of signs stands
  (`sidebarFolded`), which moves the window buttons.

  And the terminal in the window (terminal.js): the page asks the shell for
  the terminal client running against the shell's own service, sends what
  was typed and every new size, and hears the output and the end. The
  process is the shell's; the page only draws it.

  Nothing else goes over this bridge: every other function only hears from
  the shell, or tells it a word for its menu or a colour for its window.
*/

const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('exeHuelle', {
  /* Whether the window buttons stand in the page (the Mac, where the system's
     bar is left out of the window): the sidebar then makes room for them in
     its first row, and has no such room where this is false. */
  topBar: process.argv.includes('--exe-top-bar'),
  /* The page says whether the narrow bar of signs stands instead of the open
     sidebar, every time that changes; the shell moves the window buttons to
     the place that fits. Only heard on the Mac. */
  sidebarFolded(folded) {
    ipcRenderer.send('sidebar-folded', folded === true)
  },
  /* Calls back every time the shortcut fires. The page decides what that
     means — start recording, or stop and fetch the text — exactly as a click
     on its own button would. */
  aufDiktat(rueckruf) {
    if (typeof rueckruf !== 'function') return
    ipcRenderer.on('diktat', () => rueckruf())
  },
  /* Calls back with the marked text whenever "Read aloud" is chosen, and
     hands back the way to stop listening — a page part built anew must not
     leave its old listener reading along. */
  aufVorlesen(rueckruf) {
    if (typeof rueckruf !== 'function') return undefined
    const hoerer = (ereignis, text) => rueckruf(String(text ?? ''))
    ipcRenderer.on('vorlesen', hoerer)
    return () => ipcRenderer.removeListener('vorlesen', hoerer)
  },
  /* Calls back whenever Escape is pressed while the focus is inside the PDF
     viewer: that key arrives at the viewer and never at the page. The page
     closes the reader with it, as it does for Escape anywhere else. Hands
     back the way to stop listening. */
  aufBetrachterEscape(rueckruf) {
    if (typeof rueckruf !== 'function') return undefined
    const hoerer = () => rueckruf()
    ipcRenderer.on('betrachter-escape', hoerer)
    return () => ipcRenderer.removeListener('betrachter-escape', hoerer)
  },
  /* The entry's word in the page's language; until it is sent — or while
     it is sent empty — the menu has no entry for it. */
  vorlesenBeschriftung(wort) {
    ipcRenderer.send('vorlesen-beschriftung', String(wort ?? ''))
  },
  /* The words of the menu entries the shell names by itself — for a link,
     for a picture — in the page's language. Until they are sent, and for
     every word left out, the shell shows its English ones. */
  menuWords(words) {
    const sent = {}
    for (const [name, word] of Object.entries(words ?? {})) sent[name] = String(word ?? '')
    ipcRenderer.send('menu-words', sent)
  },
  /* Calls back when the shell has something to tell the user in the page's
     words — today `service-stop-failed`, when ending the service from the
     sign's menu did not work. Hands back the way to stop listening. */
  onShellNotice(callback) {
    if (typeof callback !== 'function') return undefined
    const listener = (event, kind) => callback(String(kind ?? ''))
    ipcRenderer.on('shell-notice', listener)
    return () => ipcRenderer.removeListener('shell-notice', listener)
  },
  /* The solid tone of the frame of the look the page shows, as `#rrggbb`.
     The shell keeps it for the ground of its next start. */
  frameColour(colour) {
    ipcRenderer.send('frame-colour', String(colour ?? ''))
  },
  /* Whether the look the page shows is dark or light, or follows the device:
     `dark`, `light` or `system`. On Windows the shell has the system draw
     the window's title bar by it. */
  frameScheme(scheme) {
    ipcRenderer.send('frame-scheme', String(scheme ?? ''))
  },
  /* A data URL of the file's preview, or '' where the system has none. */
  thumbnail(address, name, size) {
    return ipcRenderer.invoke(
      'thumbnail', String(address ?? ''), String(name ?? ''),
      { width: Number(size?.width) || 0, height: Number(size?.height) || 0 },
    )
  },
  /* The program's own newer version (updater.js). `status()` answers with
     the running version, the newer one a look found (`found`, with its
     `notes` and `date`), the `state` — none, checking, available,
     downloading with `progress`, downloaded, error with `reason`. `check()`
     looks again, `download()` fetches what was found, `install()` ends the
     program and installs it; each answers with the state it left behind.
     `on` calls back with the state on every change and hands back the way
     to stop listening. */
  updates: {
    status: () => ipcRenderer.invoke('updates-status'),
    check: () => ipcRenderer.invoke('updates-check'),
    download: () => ipcRenderer.invoke('updates-download'),
    install: () => ipcRenderer.invoke('updates-install'),
    on(callback) {
      if (typeof callback !== 'function') return undefined
      const listener = (event, state) => callback(state)
      ipcRenderer.on('updates-state', listener)
      return () => ipcRenderer.removeListener('updates-state', listener)
    },
  },
  /* The terminal in the window (terminal.js). `start` asks for the client
     with the drawing's size (`cols`, `rows`), the look and the language the
     page shows and the chat it has open, and answers with the process id —
     with `foreign: true` where the program is not the client — or with an
     `error` where no client could start. `write` sends what was
     typed, `resize` the new size, `stop` ends the client. `pathOf` names
     where a file dropped on the page lies on the disk — empty for one that
     does not lie there; the page cannot read it off the file itself since
     Electron 32. `onData` and
     `onExit` call back with the output and with the end, and hand back the
     way to stop listening. */
  terminal: {
    start: (request) => ipcRenderer.invoke('terminal-start', request ?? {}),
    write: (data) => ipcRenderer.send('terminal-write', String(data ?? '')),
    resize: (cols, rows) => ipcRenderer.send('terminal-resize', Number(cols) || 0, Number(rows) || 0),
    stop: () => ipcRenderer.send('terminal-stop'),
    pathOf(file) {
      try {
        return String(webUtils.getPathForFile(file) || '')
      } catch {
        return ''
      }
    },
    onData(callback) {
      if (typeof callback !== 'function') return undefined
      const listener = (event, data) => callback(String(data ?? ''))
      ipcRenderer.on('terminal-data', listener)
      return () => ipcRenderer.removeListener('terminal-data', listener)
    },
    onExit(callback) {
      if (typeof callback !== 'function') return undefined
      const listener = (event, code) => callback(Number(code))
      ipcRenderer.on('terminal-exit', listener)
      return () => ipcRenderer.removeListener('terminal-exit', listener)
    },
  },
})
