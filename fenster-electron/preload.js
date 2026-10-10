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

  Nothing else goes over this bridge: every other function only hears from
  the shell, or tells it a word for its menu or a colour for its window.
*/

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('exeHuelle', {
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
  /* The entry's word in the page's language; until it is sent — or while
     it is sent empty — the menu has no entry for it. */
  vorlesenBeschriftung(wort) {
    ipcRenderer.send('vorlesen-beschriftung', String(wort ?? ''))
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
})
