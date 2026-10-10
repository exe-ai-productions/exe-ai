/*
  The program's own newer version, as the page knows it.

  The shell looks for it, fetches it and installs it; the page is where it
  is offered. What the shell found comes over its bridge
  (`window.exeHuelle.updates`): once when the page asks, and again with
  every change. This module keeps the loaded copy and passes the three
  requests on — look again, fetch, install. Nothing is fetched and nothing
  installed without a click.

  In a browser there is no shell and no bridge: `present` stays false, and
  nothing of an update is shown anywhere.
*/

const STATES = ['none', 'checking', 'available', 'downloading', 'downloaded', 'error']

export const updates = $state({
  // Whether the page runs in the shell at all.
  present: false,
  // The running version, and the newer one the last look found.
  version: '',
  found: '',
  // The notes of that release as the shell hands them over, and its date.
  notes: '',
  date: '',
  state: 'none',
  // How far a running download is, in per cent.
  percent: 0,
  // Why the last step failed, while the state is error.
  reason: '',
  /* A look came back with nothing newer. Until one has, "none" only says
     that nothing is known yet — the page must not call that up to date. */
  looked: false,
  // "Later" was chosen: the card stays away until the next start.
  later: false,
})

function bridge() {
  return typeof window !== 'undefined' ? window.exeHuelle?.updates : undefined
}

function take(status) {
  if (!status || typeof status !== 'object') return
  const state = STATES.includes(status.state) ? status.state : 'none'
  if (state === 'none') updates.looked = updates.looked || updates.state === 'checking'
  else if (state !== 'checking') updates.looked = false
  updates.version = String(status.version ?? '')
  updates.found = String(status.found ?? '')
  updates.notes = typeof status.notes === 'string' ? status.notes : ''
  updates.date = String(status.date ?? '')
  updates.state = state
  updates.percent = Math.max(0, Math.min(100, Math.round(Number(status.progress?.percent) || 0)))
  updates.reason = String(status.reason ?? '')
}

let listening = false

/** Asks the shell what it found and listens for every change from then on.
    Without a shell it does nothing. */
export function updatesStart() {
  const shell = bridge()
  if (!shell || listening) return
  listening = true
  updates.present = true
  shell.on?.(take)
  Promise.resolve(shell.status?.()).then(take, () => {})
}

/* Each request answers with the state it left behind. The shell tells a
   failure as a state of its own; a request that does not come back at all
   is told the same way, so no button ever ends in silence. */
async function request(name) {
  const shell = bridge()
  if (!shell?.[name]) return
  try {
    take(await shell[name]())
  } catch (error) {
    updates.state = 'error'
    updates.reason = String(error?.message ?? error)
  }
}

/** Looks for a newer version again. */
export function checkForUpdates() {
  return request('check')
}

/** Fetches the version the last look found. */
export function downloadUpdate() {
  return request('download')
}

/** Ends the program and installs the fetched version — only once it lies
    ready. */
export function installUpdate() {
  if (updates.state !== 'downloaded') return undefined
  return request('install')
}

/** Closes the card for this start, with no word to the shell: the next
    start finds the version again. */
export function chooseLater() {
  updates.later = true
}

/** Whether the card stands: a newer version was found, is being fetched or
    lies ready, and "Later" was not chosen. */
export function cardShown() {
  return (
    updates.present &&
    !updates.later &&
    (updates.state === 'available' || updates.state === 'downloading' || updates.state === 'downloaded')
  )
}

/** The release's date in the language of the interface, or '' where the
    shell named none that can be read. */
export function releaseDate(locale) {
  const day = updates.date ? new Date(updates.date) : null
  if (!day || Number.isNaN(day.getTime())) return ''
  return day.toLocaleDateString(locale, { day: 'numeric', month: 'long', year: 'numeric' })
}
