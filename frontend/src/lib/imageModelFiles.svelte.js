/* The picture server's model files with their state (GET
   /bild/model-files): kept once, because the table of the files and the
   block that converts one of them read the same list and a conversion has to
   show up in both. */
import { api } from './api.js'

export const imageFiles = $state({ list: [] })

export function loadImageFiles() {
  return api
    .imageModelFiles()
    .then((list) => {
      imageFiles.list = list
    })
    .catch(() => {})
}
