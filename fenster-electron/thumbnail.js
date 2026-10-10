/*
  The doc folder's previews: the system's own picture of a file — a PDF's
  first page, a text's lines — drawn by `nativeImage.createThumbnailFromPath`
  (macOS and Windows). The page cannot draw these itself, and a browser
  without this shell shows the file sign instead.

  The page does not name a path on this machine. It names the ADDRESS the
  service hands the file out at, and only one on the service this shell
  opened; the shell fetches the bytes from there into a file of its own in
  the temporary folder, asks the system for the picture, and removes the
  file again. So the page can see a preview of exactly what the service
  would hand it anyway, and of nothing else on the disk.
*/

const { nativeImage } = require('electron')
const crypto = require('crypto')
const fs = require('fs/promises')
const os = require('os')
const path = require('path')

// A file bigger than this is not fetched for a preview: the preview of a
// huge file is not worth reading it whole into memory.
const MAX_BYTES = 50 * 1024 * 1024
// The largest picture asked for (the big view's); anything past it is a
// request nobody on the page makes.
const MAX_SIDE = 2000

function extension(name) {
  const ext = path.extname(String(name || '')).toLowerCase()
  return /^\.[a-z0-9]{1,10}$/.test(ext) ? ext : ''
}

function side(value) {
  const n = Math.round(Number(value))
  return Number.isFinite(n) && n > 0 ? Math.min(n, MAX_SIDE) : 0
}

/**
 * A data URL of the file's preview, or '' where there is none.
 * `origin` is the service's own origin; any other address is refused.
 */
async function thumbnail(origin, address, name, size) {
  if (process.platform !== 'darwin' && process.platform !== 'win32') return ''
  let url
  try {
    url = new URL(String(address))
  } catch {
    return ''
  }
  if (url.origin !== origin) return ''
  const width = side(size?.width)
  const height = side(size?.height)
  if (!width || !height) return ''

  const answer = await fetch(url)
  if (!answer.ok) return ''
  const length = Number(answer.headers.get('content-length') || 0)
  if (length > MAX_BYTES) return ''
  const bytes = Buffer.from(await answer.arrayBuffer())
  if (bytes.length > MAX_BYTES) return ''

  // The system reads the kind of a file off its extension, so the copy
  // carries the file's own.
  const file = path.join(os.tmpdir(), `exe-preview-${crypto.randomUUID()}${extension(name)}`)
  try {
    await fs.writeFile(file, bytes)
    const image = await nativeImage.createThumbnailFromPath(file, { width, height })
    return image.isEmpty() ? '' : image.toDataURL()
  } catch {
    return ''
  } finally {
    await fs.rm(file, { force: true })
  }
}

module.exports = { thumbnail }
