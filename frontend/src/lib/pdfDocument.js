/*
  The one place for pdf.js: its worker, its data folders and the way a file
  is opened. The rail beside the chat, the view over the window and the tiles
  of the doc folder all draw a PDF through here, so they ask the library for
  the same things.

  The page's policy allows no `eval` and no WebAssembly, and pdf.js needs
  neither: the decoders it would run as WebAssembly come as plain JavaScript
  from the wasm folder, and `useWasm` is off so the browser is never asked
  to compile what it would refuse. The worker is the package's own, shipped
  as a file of the build; the folders of the package (cmaps, standard fonts,
  decoders, ICC profiles) are copied beside the build (vite.config.js) and
  found by the library through the addresses below.
*/
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist'
import workerAddress from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerAddress

/* Where the data folders stand. A page that is not served from the build's
   own address (a measuring page) sets another one. */
export const pdfData = { base: `${import.meta.env.BASE_URL}pdfjs/` }

/** Opens a PDF by its address; resolves to the document, which the caller
 *  hands back with `closePdf` when it is done with it. */
export function openPdf(address) {
  const task = getDocument({
    url: address,
    cMapUrl: `${pdfData.base}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${pdfData.base}standard_fonts/`,
    wasmUrl: `${pdfData.base}wasm/`,
    iccUrl: `${pdfData.base}iccs/`,
    useWasm: false,
  })
  return task.promise
}

/** Gives a document back: its requests end and its worker is let go. */
export function closePdf(document) {
  return document.loadingTask.destroy()
}

/** The size of a page at scale 1, in CSS pixels. */
export function pageSize(page) {
  const { width, height } = page.getViewport({ scale: 1 })
  return { width, height }
}

/**
 * Draws a page into a canvas so that it is `width` CSS pixels wide, sharp on
 * a dense screen. Returns the viewport it used (for the text layer) and the
 * task, which can be cancelled.
 */
export function drawPage(page, canvas, width) {
  const scale = width / page.getViewport({ scale: 1 }).width
  const viewport = page.getViewport({ scale })
  const density = window.devicePixelRatio || 1
  canvas.width = Math.floor(viewport.width * density)
  canvas.height = Math.floor(viewport.height * density)
  canvas.style.width = `${Math.floor(viewport.width)}px`
  canvas.style.height = `${Math.floor(viewport.height)}px`
  const task = page.render({
    canvas,
    viewport,
    transform: density === 1 ? undefined : [density, 0, 0, density, 0, 0],
  })
  return { viewport, task }
}

/** Sets the selectable text of a page over its canvas. */
export async function drawText(page, viewport, container) {
  container.replaceChildren()
  const layer = new TextLayer({ textContentSource: page.streamTextContent(), container, viewport })
  await layer.render()
  return layer
}

/* The first page as a picture, for a tile: a few at a time, kept for the
   session, the way the app shell's previews are (lib/thumbnails.js). */
const AT_ONCE = 2
const cache = new Map()
const waiting = []
let running = 0

function next() {
  while (running < AT_ONCE && waiting.length) {
    const job = waiting.shift()
    running += 1
    job().finally(() => {
      running -= 1
      next()
    })
  }
}

async function firstPage(address, width) {
  const document = await openPdf(address)
  try {
    const page = await document.getPage(1)
    const canvas = window.document.createElement('canvas')
    const { task } = drawPage(page, canvas, width)
    await task.promise
    return canvas.toDataURL('image/jpeg', 0.85)
  } finally {
    closePdf(document)
  }
}

/**
 * A data URL of the first page of the PDF at `address`, `width` pixels wide,
 * or '' when it cannot be drawn. `key` names the file and the size.
 */
export function pdfFirstPage(key, address, width) {
  if (!cache.has(key)) {
    cache.set(
      key,
      new Promise((resolve) => {
        waiting.push(() => firstPage(address, width).then(resolve, () => resolve('')))
        next()
      }),
    )
  }
  return cache.get(key)
}
