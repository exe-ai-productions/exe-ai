/*
  The chat list as the sidebars draw it: pinned chats, the projects with the
  chats inside them, and the rest cut into days.

  Pinned chats stand under "Pinned" wherever they lie; a chat in a project
  otherwise stands under its project and not in the days. While searching,
  every hit stands in the days: one inside a folded project would stay out of
  sight. So does a chat whose project is not known (yet) — it has no row to
  stand under.

  A pure function of the lists and a moment, so both sidebars — the
  desktop's and the phone's — read the same answer and a test can run it
  without a window around it.
*/
import { chatgruppen } from './chatgruppen.js'

const PINNED = 'chat.angeheftet'

/** `{ pinned, days, byProject }` for the chats, the projects and the search state. */
export function chatListe(chats, projects, searching, now = Date.now()) {
  const projectIds = new Set(projects.map((project) => project.id))
  const listed = searching
    ? chats
    : chats.filter((chat) => chat.pinned || !projectIds.has(chat.project_id))
  const groups = chatgruppen(listed, now)

  /* Each project's chats in the order they were made. */
  const byProject = {}
  for (const chat of chats) {
    if (chat.project_id && !chat.pinned) (byProject[chat.project_id] ??= []).push(chat)
  }
  for (const list of Object.values(byProject)) {
    list.sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0))
  }

  return {
    pinned: groups.filter((group) => group.schluessel === PINNED),
    days: groups.filter((group) => group.schluessel !== PINNED),
    byProject,
  }
}
