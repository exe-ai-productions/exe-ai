/*
  The state that only the phone page has: whether the chat list stands open.

  Everything else — the chats, the model, the notices, the questions — is the
  desktop's own state in lib/zustand.svelte.js and is read from there.
*/

export const phone = $state({
  /* The chat list, drawn as a drawer from the left. */
  drawer: false,
})

/* The look the page wears, as the person last chose it here: the settings
   page puts the choice in, the phone page (which holds the look and saves it)
   takes it out and says which look it stands on, and which look it draws
   (`drawn`: what the choice and the device's light or dark make of it). */
export const lookPick = $state({ mode: 'auto', drawn: null, value: null, count: 0 })

export function pickLook(value) {
  lookPick.value = value
  lookPick.count += 1
}

export function drawerSet(open = !phone.drawer) {
  phone.drawer = open
}
