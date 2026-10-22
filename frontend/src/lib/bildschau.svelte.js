/*
  What the reader shows: one picture, one page or one report, alone in the
  middle of the window.

  Its own module for the same reason the file preview has one: an overlay
  that covers the whole program cannot live inside a message. Fixed
  positioning reaches the whole window only when no ancestor holds it, and
  the message list holds it — the enlargement was drawn underneath the
  sidebar, which is exactly as useful as not opening at all.

  Every place that shows, reads or opens a picture or a document comes
  here: the tiles of the doc folder and the pictures, pictures and file
  cards in the chat, the image window, the input bar, the agents' reports.
  There is no second way.
*/

export const bildschau = $state({
  offen: false,
  /* 'picture' a picture or a video, 'page' a document, 'report' a report. */
  kind: 'picture',
  adresse: '',
  name: '',
  /* Who a file is from and its project, in a short line beside the name. */
  origin: '',
  /* The named storage location the file lives in; empty, and the reader
     offers no folder button. */
  folder: '',
  /* A clip or a sound handed in as a file: 'video' or 'audio', and its
     player is drawn instead of a picture. Empty for a picture. */
  mediaKind: '',
  /* A page: the text when it is at hand, or a way to fetch it, and the
     language it is written in (for colour and the download's type). */
  language: '',
  text: null,
  loadText: null,
  /* A page the browser cannot set as text (a PDF): a picture of it, or a
     way to ask the app shell for one. */
  preview: '',
  loadPreview: null,
  /* A page the browser's own viewer draws (a PDF): `adresse` is the file,
     shown in a frame instead of as text. */
  framed: false,
  /* A download of the caller's own — a card hands out exactly the text it
     holds; without one the reader saves what `adresse` points at. */
  download: null,
  report: null,
})

function clear() {
  Object.assign(bildschau, {
    kind: 'picture',
    adresse: '',
    name: '',
    origin: '',
    folder: '',
    mediaKind: '',
    language: '',
    text: null,
    loadText: null,
    preview: '',
    loadPreview: null,
    framed: false,
    download: null,
    report: null,
  })
}

/* The last piece of an address, without its query: the name a picture is
   saved under when the caller has none to give. */
function nameOf(adresse) {
  const path = String(adresse || '').split(/[?#]/)[0]
  const last = path.split('/').pop() || ''
  try {
    return decodeURIComponent(last)
  } catch {
    return last
  }
}

/** A picture or a video. `more` may name it, say where it came from and
 *  which storage location holds it. */
export function bildZeigen(adresse, more = {}) {
  clear()
  Object.assign(bildschau, {
    kind: 'picture',
    adresse,
    name: more.name || nameOf(adresse),
    origin: more.origin || '',
    folder: more.folder || '',
    mediaKind: more.mediaKind || '',
  })
  bildschau.offen = true
}

/** A document as a page: its text, or a way to fetch it, or — for what the
 *  browser cannot set as text — a picture of it. `mediaKind` names an Office
 *  file ('word', 'sheet', 'slides') that the page draws from its address. */
export function showPage(file) {
  clear()
  Object.assign(bildschau, {
    kind: 'page',
    adresse: file.adresse || '',
    name: file.name || nameOf(file.adresse),
    origin: file.origin || '',
    folder: file.folder || '',
    language: file.language || '',
    text: file.text ?? null,
    loadText: file.loadText || null,
    preview: file.preview || '',
    loadPreview: file.loadPreview || null,
    framed: Boolean(file.framed && file.adresse),
    mediaKind: file.mediaKind || '',
    download: file.download || null,
  })
  bildschau.offen = true
}

/** An agent's report as a page: who, what, how it ended, and its text with
 *  the files it wrote. */
export function showReport(report) {
  clear()
  Object.assign(bildschau, { kind: 'report', name: report.name || '', report })
  bildschau.offen = true
}

export function closeReader() {
  bildschau.offen = false
}
