/*
  A picture file for the studio's area, chosen on the phone: the file chooser
  of the system (photos, camera, files), the file uploaded to the pictures
  folder, then the start picture — unless another one was laid down while it
  was on its way. It lies in the pictures folder and belongs to no chat.
*/
import { api } from '../../lib/api.js'
import { pictureFromOutside } from '../../lib/studio.svelte.js'
import { melde } from '../../lib/zustand.svelte.js'

let laid = 0

async function lay(file) {
  if (!file?.type?.startsWith('image/')) return
  const mine = ++laid
  try {
    const result = await api.bildHochladen(file)
    if (mine === laid) pictureFromOutside(result.bild)
  } catch (error) {
    melde(String(error.message || error), 'fehler')
  }
}

/** Opens the chooser; call it from a tap. */
export function chooseFile() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = () => lay(input.files?.[0])
  input.click()
}
