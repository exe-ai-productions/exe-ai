/* The one table of model families, read from the service
   (GET /api/v1/bild/familien, app/image_families.py) — which families
   exist, their names, which files a kit reads and every start value. The
   window and the catalogue cards read it here; no family list lives in the
   interface itself. Fetched once, again only after a failed attempt. */
import { api } from './api.js'

export const imageFamilies = $state({ list: [] })

let loading = null

export function loadImageFamilies() {
  if (!loading) {
    loading = api
      .bildFamilien()
      .then((list) => {
        imageFamilies.list = Array.isArray(list) ? list : []
      })
      .catch(() => {
        loading = null
      })
  }
  return loading
}

export function familyOf(name) {
  return imageFamilies.list.find((family) => family.name === name) ?? null
}
