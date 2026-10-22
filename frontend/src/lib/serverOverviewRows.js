/*
  What one row of the server overview says, from the report its server gave.

  Plain functions with nothing reactive in them, so the rules can be read and
  run on their own: when a server counts as running, when its button is
  locked (by the rule of the button in its window), and what the state, port
  and model cells show.
*/
import { fileMark } from './fileMark.js'

/** Whether the server of this report runs (the picture server also while it draws). */
export function isRunning(name, report) {
  if (name === 'bild') return report?.zustand === 'bereit' || report?.zustand === 'zeichnet'
  return Boolean(report?.laeuft)
}

/** Whether the button of this server is locked, by the rule of its window.
 *  `agentLoading`: the agent server's slot is still taking its file. */
export function isBlocked(name, report, { agentLoading = false } = {}) {
  if (!report) return true
  const running = isRunning(name, report)
  switch (name) {
    case 'server':
      return !running && !report.selected_model
    case 'agent':
      return agentLoading || (!running && !report.selected_model)
    case 'bild':
      return Boolean(report.picture_running) || (!running && !report.programm_da)
    default:
      // Embedding, speech and clean-up: a file and a program to start it with.
      return !running && !(report.selected_model && report.programm)
  }
}

/** The cells of one row. `state` is `active`, `inactive` or — the picture
 *  server alone — `failed`; `model` is the chosen one, also while the server
 *  stands, `mark` the maker's logo of its file where one is found (lib/fileMark.js)
 *  and `letter` the first letter that stands in its place. */
export function overviewRow(server, report, { busy = false, agentLoading = false } = {}) {
  const running = isRunning(server.name, report)
  const failed = server.name === 'bild' && report?.zustand === 'fehler'
  const model = report?.selected_model || ''
  return {
    ...server,
    running,
    state: failed ? 'failed' : running ? 'active' : 'inactive',
    port: report?.port ?? null,
    model,
    mark: model ? fileMark(model) : null,
    letter: model ? model.slice(0, 1).toUpperCase() : '',
    blocked: busy || isBlocked(server.name, report, { agentLoading }),
  }
}
