/*
  Word, Excel and PowerPoint files, read in the page. Each library is loaded
  the first time a file of its kind opens (a dynamic import), so a person who
  never opens one never pays for them.

  What a file holds is never handed to the page as markup: a spreadsheet's
  cells come out as text values, a Word document is drawn by docx-preview with
  the embedded HTML of the file switched off, and what its links lead to is
  checked after the drawing (`plainLinks`).
*/

/** The bytes of a file from its address. */
export async function readBytes(address) {
  const answer = await fetch(address)
  if (!answer.ok) throw new Error(`The file could not be read (${answer.status}).`)
  return answer.arrayBuffer()
}

/* Where a link of a file may lead: a web page or a mail address, written out
   in full. Everything else is not a way out of the page: a script, a local
   file, a bookmark of the document itself, an address with no scheme. */
const OPEN_LINK = /^\s*(https?:\/\/|mailto:)/i

/** Turn every link under `root` that does not lead to a web page or a mail
 *  address into plain text; the others open in a new window and tell it
 *  nothing about where they came from. */
export function plainLinks(root) {
  for (const link of Array.from(root.querySelectorAll('a'))) {
    if (OPEN_LINK.test(link.getAttribute('href') || '')) {
      link.setAttribute('target', '_blank')
      link.setAttribute('rel', 'noopener noreferrer')
    } else {
      link.replaceWith(...Array.from(link.childNodes))
    }
  }
}

/** A Word document drawn into `body`; its styles go into `styles`. */
export async function drawWord(bytes, body, styles) {
  const { renderAsync } = await import('docx-preview')
  await renderAsync(bytes, body, styles, {
    className: 'docx',
    inWrapper: true,
    breakPages: true,
    renderHeaders: true,
    renderFooters: true,
    renderFootnotes: true,
    renderEndnotes: true,
    renderAltChunks: false,
  })
  plainLinks(body)
}

/** The sheets of a workbook: `{ name, rows }` each, the rows as the text a
 *  cell shows (a date as a date, a number as it is formatted). */
export async function readSheets(bytes) {
  const XLSX = await import('xlsx')
  const book = XLSX.read(bytes, { type: 'array' })
  return book.SheetNames.map((name) => ({
    name,
    rows: XLSX.utils
      .sheet_to_json(book.Sheets[name], { header: 1, raw: false, defval: '' })
      .map((row) => row.map((cell) => String(cell ?? '')))
      .filter((row) => row.some((cell) => cell !== '')),
  }))
}

/* The slide library sets the text of every run into the page as markup. Text
   written with entities (`&lt;`) arrives as it is and stays text, but a run
   written as a CDATA section arrives raw, and one that reads
   `<img src=x onerror=…>` would be a tag of the page. Before the file goes to
   the library, every CDATA section inside a run is written with entities. */
const RUN_TEXT = /(<a:t(?:\s[^>]*)?>)([\s\S]*?)(<\/a:t>)/g
const CDATA = /<!\[CDATA\[([\s\S]*?)\]\]>/g

const withEntities = (raw) => raw.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')

/** The presentation with the text of its slides, layouts, masters and notes
 *  made safe to be set as markup. */
export async function escapeSlideText(bytes) {
  const { default: JSZip } = await import('jszip')
  const archive = await JSZip.loadAsync(bytes)
  const parts = archive.file(/^ppt\/.+\.xml$/)
  await Promise.all(
    parts.map(async (part) => {
      const xml = await part.async('string')
      const safe = xml.replace(RUN_TEXT, (_, open, text, close) => open + text.replace(CDATA, (__, raw) => withEntities(raw)) + close)
      if (safe !== xml) archive.file(part.name, safe)
    }),
  )
  return archive.generateAsync({ type: 'arraybuffer' })
}

/** A presentation drawn into `host`, its slides one under the other, each
 *  `width` wide. Returns what takes it down again. */
export async function drawSlides(bytes, host, width) {
  const { init } = await import('pptx-preview')
  const previewer = init(host, { width, height: Math.round((width * 9) / 16), mode: 'list' })
  await previewer.preview(await escapeSlideText(bytes))
  return () => {
    try {
      previewer.destroy()
    } catch {
      host.replaceChildren()
    }
  }
}
