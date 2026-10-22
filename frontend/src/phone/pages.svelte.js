/*
  The pages of the phone page that open over the chat — settings, the model
  menus, the studio and the rest.

  A page is a file in `pages/`: a Svelte component whose module script
  exports `meta`. Nothing here has to be told about it — the folder is read
  when the page is built, so a page appears in the chat list the moment its
  file exists, and a page that does not exist is not offered.

    meta = {
      name:  the page's key, unique,
      title: catalogue key of its name,
      sign:  the house sign drawn before the name (Hauszeichen),
      place: 'list' for the rows above the foot, 'foot' for the foot,
      order: the number the rows are sorted by,
      action: optional — a row that does something instead of opening a
              page (the manual opens in a window of its own); the page it
              names has nothing to draw,
    }
*/

const files = import.meta.glob('./pages/*.svelte', { eager: true })

export const PAGES = Object.values(files)
  .filter((file) => file.meta?.name)
  .map((file) => ({ ...file.meta, view: file.default }))
  .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

/* The page standing over the chat, by name; null while the chat shows. */
export const pageState = $state({ open: null })

/* A page that holds something not yet saved puts a question here: leaving
   the page — by its back button or from the drawer — asks it first and
   stays when the answer is no. */
export const pageLeave = { guard: null }

/* Runs `go` when leaving is allowed. With nothing unsaved that is at once
   (some pages must act inside the tap that opened them); otherwise after
   the answer. Gives true when the page was left, as a value or a promise. */
function leave(go) {
  if (!pageLeave.guard) return go()
  return pageLeave.guard().then((ok) => (ok ? go() : false))
}

export function pageOpen(name) {
  return leave(() => {
    const page = PAGES.find((entry) => entry.name === name)
    if (page?.action) {
      page.action()
      return true
    }
    pageState.open = page ? name : null
    return true
  })
}

export function pageClose() {
  return leave(() => {
    pageState.open = null
    return true
  })
}

export function openPage() {
  return PAGES.find((page) => page.name === pageState.open) ?? null
}
