/*
  The maker's logo for a model file, by the file's name.

  One place for the question "whose file is this": a file the catalogue
  carries — a model, or an accessory such as a vision projector or a speed
  module, in any of its lists — wears the logo its card names; any other file
  wears the logo of the family its name says (`modellMarke`); a file nothing
  knows has none, and the caller shows what stands in for a logo.

  The logo is the house's own original vector (lib/logos.js), never a picture
  fetched from anywhere.
*/
import { ARTEN, katalogFuer } from './modellempfehlungen.js'
import { modellMarke } from './anbieterzeichen.js'
import { LOGOS } from './logos.js'

/* File name (lower case) -> the logo key of the card that carries the file.
   Built on first use: the catalogue is data that does not change while the
   program runs. */
let byFile = null

function index() {
  if (byFile) return byFile
  byFile = new Map()
  for (const art of ARTEN) {
    for (const card of katalogFuer(art)) {
      if (!card.marke) continue
      for (const build of card.fassungen ?? []) {
        // The names a build brings to the folder: the model and each
        // companion under the name it is saved as (the name in the repository
        // only where no other is given — several repositories call their
        // projector plainly the same, so that name alone says nothing).
        const names = [build.ziel ?? build.datei, build.mmproj_ziel ?? build.mmproj, build.drafter_ziel ?? build.drafter]
        for (const name of names) {
          if (name && !byFile.has(name.toLowerCase())) byFile.set(name.toLowerCase(), card.marke)
        }
      }
    }
  }
  return byFile
}

/** The logo (`{ vb, html }`) of the file with this name, or null. */
export function fileMark(fileName) {
  const name = String(fileName || '')
  if (!name) return null
  const key = index().get(name.toLowerCase())
  if (key && Object.hasOwn(LOGOS, key)) return LOGOS[key]
  return modellMarke(name, '')
}
