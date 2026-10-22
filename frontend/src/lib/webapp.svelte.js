/* The state of the web app page: what the service tells about itself and the
   four things the page can do — set the password, start and stop the service,
   start Tailscale.

   The service answers every one of them with the same snapshot, so there is
   one place that takes an answer in (`take`) and one place that turns a
   refusal into something to show (`fail`). A refusal reads "<reason>" or
   "<reason>: <what Tailscale itself said>"; the reason is a short word the
   page has a sentence for, the rest is shown as it came. */

import { api } from './api.js'

export const webapp = $state({
  /* Whether the service has answered once; the page shows its rows only then. */
  loaded: false,
  password: false,
  /* The fewest characters a password may have, as the service says it. */
  passwordMin: 0,
  running: false,
  address: '',
  /* The address as a drawing (SVG), empty where there is no address. */
  qr: '',
  tailscale: { connected: false, kind: 'none', loginUrl: '' },
  /* The action under way: '', 'password', 'service' or 'tailscale'. */
  busy: '',
  error: { reason: '', detail: '' },
})

/* The sign-in address already handed to the browser: a poll that still sees
   the same one must not open it a second time. */
let opened = ''

/* Counts the actions begun. A read that was sent before an action began may
   land after the action's own answer and would put the older state back, so
   such a read is dropped. */
let actions = 0

/* Which visit has a read on its way. The page asks again every few seconds; a
   service that answers slowly must not collect a pile of reads that then
   come back in any order. */
let visit = 0
let readingVisit = -1

/* Forgets what a visit before this one left behind: the rows are not shown
   before the service has answered, and an old refusal is not shown at all. */
export function webappReset() {
  visit += 1
  webapp.loaded = false
  webapp.error = { reason: '', detail: '' }
  opened = ''
}

function take(answer) {
  webapp.loaded = true
  webapp.password = !!answer.password
  webapp.passwordMin = answer.password_min ?? webapp.passwordMin
  webapp.running = !!answer.service?.running
  webapp.address = answer.service?.address ?? ''
  webapp.qr = answer.service?.qr ?? ''
  webapp.tailscale = {
    connected: !!answer.tailscale?.connected,
    kind: answer.tailscale?.kind ?? 'none',
    loginUrl: answer.tailscale?.login_url ?? '',
  }
  if (webapp.tailscale.connected) opened = ''
}

function fail(error) {
  const text = String(error?.message ?? '')
  const cut = text.indexOf(': ')
  webapp.error = cut < 0 ? { reason: text, detail: '' } : { reason: text.slice(0, cut), detail: text.slice(cut + 2) }
}

/* Reads the state. A failed read leaves what stands where it is: the page
   polls, and one missed answer is no reason to blank the rows. A read that
   finally works takes back the reason an earlier failed first read left. */
export async function webappLoad() {
  if (readingVisit === visit) return
  const mine = visit
  readingVisit = mine
  const seen = actions
  const first = !webapp.loaded
  try {
    const answer = await api.webApp.state()
    if (seen !== actions) return
    take(answer)
    if (first) webapp.error = { reason: '', detail: '' }
  } catch (error) {
    if (first && seen === actions) fail(error)
  } finally {
    if (readingVisit === mine) readingVisit = -1
  }
}

async function act(what, call) {
  if (webapp.busy) return false
  actions += 1
  webapp.busy = what
  webapp.error = { reason: '', detail: '' }
  try {
    take(await call())
    return true
  } catch (error) {
    fail(error)
    return false
  } finally {
    actions += 1
    webapp.busy = ''
  }
}

/* Hands the sign-in address to the browser once. Tailscale cannot show the
   service before its owner has signed in there; the page goes on by itself
   once the poll sees it connected. */
export function openSignIn(force = false) {
  const url = webapp.tailscale.loginUrl
  if (!url || webapp.tailscale.connected) return
  if (!force && url === opened) return
  /* A window the browser refused is not an address handed over. */
  if (window.open(url, '_blank')) opened = url
}

export const webappSetPassword = (password) => act('password', () => api.webApp.setPassword(password))

export async function webappStartService() {
  const done = await act('service', () => api.webApp.start())
  if (done) openSignIn()
  return done
}

export const webappStopService = () => act('service', () => api.webApp.stop())

export async function webappStartTailscale() {
  const done = await act('tailscale', () => api.webApp.startTailscale())
  if (done) openSignIn()
  return done
}
