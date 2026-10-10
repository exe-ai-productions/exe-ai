/* The table of sd.cpp's further switches, read from the service
   (GET /api/v1/bild/switches, app/image_switches.py): which switches exist,
   their kind, their window block, and the files each file switch picks
   from. Read again whenever the window reads its model lists, since the
   files in the folders change. */
import { api } from './api.js'

export const imageSwitches = $state({ list: [], files: {}, weightTypes: [] })

export function loadImageSwitches() {
  return api
    .imageSwitches()
    .then((table) => {
      imageSwitches.list = Array.isArray(table?.switches) ? table.switches : []
      imageSwitches.files = table?.files ?? {}
      imageSwitches.weightTypes = Array.isArray(table?.weight_types) ? table.weight_types : []
    })
    .catch(() => {})
}
