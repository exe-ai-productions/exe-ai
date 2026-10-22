/*
  What the chat list does to a chat or a project once the person has chosen
  it from a menu: rename, delete, create — each with its question — and the
  one place a failure of any of them is said.

  Both sidebars call these, so the question, the wording and the reaction
  are the same wherever the menu was opened. What a menu does to itself
  (closing, remembering which project stands open) stays with the menu.
*/
import { t } from './texte.svelte.js'
import {
  zustand, melde, frage, chatAendern, chatLoeschen,
  projectCreate, projectUpdate, projectDelete,
} from './zustand.svelte.js'

/* Runs what was chosen; what fails is said. The chat or project an action
   works on is handed in as an argument, read at the click: read later from
   the menu, it would be gone with it. */
export async function runAction(action) {
  try {
    await action()
  } catch (error) {
    melde(error.message || t('fehler.allgemein'), 'fehler')
  }
}

export async function renameChat(chat) {
  const title = await frage(t('chat.neuer_titel'), { eingabe: chat.title, okSchluessel: 'app.sichern' })
  if (title === null) return
  await runAction(() => chatAendern(chat.id, { title }))
}

export async function removeChat(chat) {
  /* An agent this chat started stops with it; the question says which. */
  const agent = zustand.auftraege.find(
    (job) => job.chat_id === chat.id && (job.state === 'laeuft' || job.state === 'wartet'),
  )?.agent
  const question = agent
    ? t('chat.delete_with_agent_question', { agent })
    : t('chat.loeschen_frage')
  if (!(await frage(question))) return
  await runAction(async () => {
    await chatLoeschen(chat.id)
    melde(t('chat.geloescht'), 'erfolg')
  })
}

/* Asks for a name and makes the project; resolves with it, or with null when
   nothing was made. */
export async function createProject() {
  const name = await frage(t('project.name_question'), { eingabe: '', okSchluessel: 'app.sichern' })
  if (!name?.trim()) return null
  let project = null
  await runAction(async () => {
    project = await projectCreate(name.trim())
  })
  return project
}

export async function renameProject(project) {
  const name = await frage(t('project.name_question'), {
    eingabe: project.name, okSchluessel: 'app.sichern',
  })
  if (!name?.trim()) return
  await runAction(() => projectUpdate(project.id, { name: name.trim() }))
}

/* Deleting a project deletes its chats: the question says how many. */
export async function removeProject(project) {
  const question = t('archive.delete_project_question', {
    name: project.name, count: project.chat_count,
  })
  if (!(await frage(question))) return
  await runAction(() => projectDelete(project.id))
}
