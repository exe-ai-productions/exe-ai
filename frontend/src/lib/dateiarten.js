/*
  Which fenced block is a file, and what can be done with it — the catalogue.

  Its own module because three places ask the same question and must get the
  same answer: the renderer that turns a block into a file box, the preview
  window that has to decide how to show it, and the save button that needs a
  name and an extension.

  The dividing line is not "is this code" but "is this a document". A shell
  snippet in an answer is meant to be read in place; an HTML page is meant to
  be looked at, kept, or opened. Only the second kind becomes a file.

  `zeigen` says what the preview can do with it:

      gerendert   drawn — HTML and SVG by the browser, in a sealed frame;
                  Markdown by the renderer the chat itself uses
      tabelle     rows and columns, read from the text itself
      text        monospace, exactly as written

  Everything can be downloaded and saved, no matter how it is shown.
*/

/*
  The marks. One sheet with a folded corner carries all of them — the file
  the user hands in and the file the assistant hands back are the same kind
  of thing, so they wear the same body. Only what stands on the sheet
  changes: lines for prose, a grid for a table, brackets for markup, braces
  for data, a horizon for a picture.

  Drawn in the house measurements (64 grid, main stroke 5, secondary 4.5,
  round ends) and standing still — a mark that says what something IS does
  not animate; only a running tool call does.
*/
const BLATT = '<path d="M16 8 H38 L48 18 V56 H16 Z" stroke-width="5" />' +
  '<path d="M38 8 V18 H48" stroke-width="4.5" />'

const ZEICHEN = {
  zeilen: BLATT + '<path d="M24 32 H40 M24 42 H40" stroke-width="4.5" />',
  gitter: BLATT +
    '<path d="M23 30 H41 M23 40 H41 M32 26 V46" stroke-width="4.5" />',
  klammern: BLATT +
    '<path d="M29 32 L24 38 L29 44 M35 32 L40 38 L35 44" stroke-width="4.5" />',
  geschweift: BLATT +
    '<path d="M29 30 C26 30 27 37 24 37 C27 37 26 45 29 45" stroke-width="4.5" />' +
    '<path d="M35 30 C38 30 37 37 40 37 C37 37 38 45 35 45" stroke-width="4.5" />',
  bild: BLATT +
    '<path d="M23 45 L29 37 L34 43 L38 39 L41 45 Z" stroke-width="4.5" />',
}

const ARTEN = {
  html: { endung: 'html', typ: 'text/html', zeigen: 'gerendert', zeichen: 'klammern' },
  svg: { endung: 'svg', typ: 'image/svg+xml', zeigen: 'gerendert', zeichen: 'bild' },
  csv: { endung: 'csv', typ: 'text/csv', zeigen: 'tabelle', zeichen: 'gitter' },
  tsv: { endung: 'tsv', typ: 'text/tab-separated-values', zeigen: 'tabelle', zeichen: 'gitter' },
  markdown: { endung: 'md', typ: 'text/markdown', zeigen: 'gerendert', zeichen: 'zeilen' },
  md: { endung: 'md', typ: 'text/markdown', zeigen: 'gerendert', zeichen: 'zeilen' },
  json: { endung: 'json', typ: 'application/json', zeigen: 'text', zeichen: 'geschweift' },
  yaml: { endung: 'yaml', typ: 'application/yaml', zeigen: 'text', zeichen: 'geschweift' },
  yml: { endung: 'yaml', typ: 'application/yaml', zeigen: 'text', zeichen: 'geschweift' },
  xml: { endung: 'xml', typ: 'application/xml', zeigen: 'text', zeichen: 'klammern' },
}

/*
  What a FILE is, apart from what a fence is. A fence becomes a file box only
  when it is a document (`ARTEN` above); a file that lies somewhere — handed
  over by the model, kept in a chat's folder — is shown by its ending, and
  there are more kinds of it than there are documents:

      doc     one of `ARTEN`: drawn, tabled or set as its source (above)
      pdf     the pages, drawn by pdf.js from the file's address
      code    the text with colours and line numbers; `language` names the
              grammar where highlight.js has one, and is empty where it has
              none (the lines are numbered all the same)
      text    the text, as written
      image   a picture, drawn from the file's address
      video   a player with its own controls, from the file's address
      audio   a player with its own controls, from the file's address
      word    a Word document (docx), its pages drawn from the file's address
      sheet   a spreadsheet (xlsx, xls), a tab per sheet and its values as a table
      slides  a presentation (pptx), its slides one under the other

  The old binary formats of Word and PowerPoint (doc, ppt) have no kind: they
  stay a card with name, size and the download.

  The endings of text files are the ones the service accepts as text
  (app/api/v1/dokumente.py, `TEXT_ENDUNGEN`); everything it accepts that is
  neither a document nor plain text is code.
*/
const CODE_LANGUAGES = {
  py: 'python', pyi: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
  ts: 'typescript', tsx: 'typescript', sh: 'bash', bash: 'bash', zsh: 'bash', fish: 'bash', ps1: '', bat: '',
  c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', hpp: 'cpp', cs: 'csharp', java: 'java', kt: 'kotlin', go: 'go',
  rs: 'rust', rb: 'ruby', php: 'php', pl: '', lua: 'lua', r: '', jl: '', swift: 'swift', m: '', scala: '',
  clj: '', ex: '', exs: '', erl: '', sql: 'sql', graphql: '', proto: '', tf: '', hcl: '',
  dockerfile: 'dockerfile', makefile: 'makefile', cmake: '', gradle: '', rst: '', tex: '',
  diff: 'diff', patch: 'diff', css: 'css', scss: 'scss', sass: 'scss', less: '',
  toml: 'toml', ini: 'ini', cfg: 'ini', conf: 'ini', properties: 'ini', jsonl: 'json', ndjson: 'json',
}
const TEXT_ENDINGS = ['txt', 'log', 'srt', 'vtt']
const IMAGE_ENDINGS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'bmp', 'ico']
const VIDEO_ENDINGS = ['mp4', 'webm', 'mov', 'm4v']
const AUDIO_ENDINGS = ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'oga', 'flac', 'opus']
const WORD_ENDINGS = ['docx']
const SHEET_ENDINGS = ['xlsx', 'xls']
const SLIDE_ENDINGS = ['pptx']
const MARK_OF_KIND = {
  code: 'klammern', text: 'zeilen', image: 'bild', video: 'bild', audio: 'zeilen',
  word: 'zeilen', sheet: 'gitter', slides: 'bild',
}

/** The kinds that have no text to hand over: the page draws or plays them
 *  from the file's own address. */
export const ADDRESS_KINDS = ['image', 'video', 'audio', 'word', 'sheet', 'slides']
/** The kinds of an Office file, which the reader shows as a page. */
export const OFFICE_KINDS = ['word', 'sheet', 'slides']

/** What a file is, from its ending (with or without the dot): `{ kind,
 *  language }`, or null for an ending the program shows nothing of. `htm`
 *  is html. */
export function fileKind(ending) {
  const raw = String(ending || '').toLowerCase().trim().replace(/^\./, '')
  const name = raw === 'htm' ? 'html' : raw
  if (!name) return null
  if (name === 'pdf') return { kind: 'pdf', language: '' }
  if (ARTEN[name]) return { kind: 'doc', language: name }
  if (Object.hasOwn(CODE_LANGUAGES, name)) return { kind: 'code', language: CODE_LANGUAGES[name] }
  if (TEXT_ENDINGS.includes(name)) return { kind: 'text', language: '' }
  if (IMAGE_ENDINGS.includes(name)) return { kind: 'image', language: '' }
  if (VIDEO_ENDINGS.includes(name)) return { kind: 'video', language: '' }
  if (AUDIO_ENDINGS.includes(name)) return { kind: 'audio', language: '' }
  if (WORD_ENDINGS.includes(name)) return { kind: 'word', language: '' }
  if (SHEET_ENDINGS.includes(name)) return { kind: 'sheet', language: '' }
  if (SLIDE_ENDINGS.includes(name)) return { kind: 'slides', language: '' }
  return null
}

/** A drawing from its text as an address an image element can load. The
 *  element runs no script in it, whatever the file holds. */
export function svgAddress(text) {
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(String(text ?? ''))
}

/** The finished mark for a fence language or a file's ending, ready to drop
 *  into markup. */
export function dateizeichen(sprache, groesse = 22) {
  const art = dateiart(sprache)
  const zeichen = art ? art.zeichen : MARK_OF_KIND[fileKind(sprache)?.kind]
  if (!zeichen) return ''
  return `<svg class="datei-zeichen" width="${groesse}" height="${groesse}" ` +
    'viewBox="0 0 64 64" fill="none" stroke="currentColor" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    ZEICHEN[zeichen] + '</svg>'
}

/* What a text weighs as a file: its bytes, not its characters. */
function byteCount(inhalt) {
  return new Blob([inhalt ?? '']).size
}

/**
 * How much a file weighs, in the shortest honest form: bytes up to 1 KB,
 * whole kilobytes up to 1 MB, megabytes with one decimal after that.
 *
 * A fact, not a state — so it is told in plain text and carries no colour.
 * The one place that turns a byte count into words: the card in the chat and
 * the tab beside it both ask here.
 */
export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** What a text weighs as a file. */
export function dateigroesse(inhalt) {
  return formatSize(byteCount(inhalt))
}

/** The catalogue entry for a fence language, or null if it is not a document. */
export function dateiart(sprache) {
  return ARTEN[String(sprache || '').toLowerCase().trim()] || null
}

/** The line under a written file's name: what kind it is, and how big. */
export function dateiFakten(datei) {
  const art = dateiart(datei?.art)
  const ending = art ? art.endung : fileKind(datei?.art) ? String(datei.art).toLowerCase() : ''
  return [ending.toUpperCase(), dateigroesse(datei?.inhalt)].filter(Boolean).join(' · ')
}

/**
 * How much a file weighs while it is still being written.
 *
 * One decimal from the first kilobyte on, written the way the window's
 * language writes a number: a size rounded to whole kilobytes stands still
 * for seconds at a time, and a line that says "being written" has to move.
 */
export function growingSize(inhalt, language) {
  const bytes = byteCount(inhalt)
  if (bytes < 1024) return `${bytes} B`
  const mega = bytes >= 1024 * 1024
  const amount = mega ? bytes / 1024 / 1024 : bytes / 1024
  const digits = { minimumFractionDigits: 1, maximumFractionDigits: 1 }
  return `${amount.toLocaleString(language, digits)} ${mega ? 'MB' : 'KB'}`
}

/** The line under the name of a file that is being written: what kind it
 *  is, the word that says so, and how big it has become so far. */
export function writingFacts(datei, word, language) {
  const art = dateiart(datei?.art)
  return [art?.endung.toUpperCase(), word, growingSize(datei?.inhalt, language)]
    .filter(Boolean).join(' · ')
}

/** Saves what an address hands out, under a name: the one link every save
 *  in the window clicks — for a text made into a blob below, and for a file
 *  the service hands out as it is. */
export function saveFromAddress(name, address) {
  const link = document.createElement('a')
  link.href = address
  link.download = name
  link.click()
}

/** Hands a text out as a browser download — the one blob-and-anchor dance,
 *  shared so the card and the preview cannot drift apart on it again. */
export function dateiHerunterladen(name, inhalt, typ) {
  const blob = new Blob([inhalt], { type: typ || 'text/plain' })
  const adresse = URL.createObjectURL(blob)
  saveFromAddress(name, adresse)
  URL.revokeObjectURL(adresse)
}

/**
 * A file name for a block.
 *
 * The model rarely gives one, so one is made up — and it has to be stable
 * within a message, otherwise the same file is called something else after
 * every keystroke while the answer is still streaming in.
 */
export function dateiname(sprache, nummer) {
  const art = dateiart(sprache)
  if (!art) return null
  return `${sprache.toLowerCase()}-${nummer}.${art.endung}`
}

/** Rows and columns out of a separated text, quoted fields included. */
export function tabelleLesen(text, trenner = ',') {
  const zeilen = []
  let feld = '', reihe = [], inAnfuehrung = false

  for (let i = 0; i < text.length; i++) {
    const z = text[i]
    if (inAnfuehrung) {
      if (z === '"' && text[i + 1] === '"') { feld += '"'; i++ }
      else if (z === '"') inAnfuehrung = false
      else feld += z
    } else if (z === '"') {
      inAnfuehrung = true
    } else if (z === trenner) {
      reihe.push(feld); feld = ''
    } else if (z === '\n') {
      reihe.push(feld); zeilen.push(reihe); reihe = []; feld = ''
    } else if (z !== '\r') {
      feld += z
    }
  }
  if (feld || reihe.length) { reihe.push(feld); zeilen.push(reihe) }

  return zeilen.filter((r) => r.some((f) => f !== ''))
}
