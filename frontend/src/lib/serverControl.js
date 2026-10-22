/*
  Start and stop of the six local servers from the overview, without a server
  window open.

  Every server window starts its server on what is stored: the file it names
  goes out with the request and the numbers (window, layers, port, levers) are
  read from the stored choice by the service itself. The overview does the
  same with what each report says is chosen (`selected_model`), so there is no
  second way to bring a server up — and it writes no number by hand.

  Where a button is locked is decided beside the rows (lib/serverOverviewRows.js).
*/
import { api } from './api.js'
import { t } from './texte.svelte.js'
import { isRunning } from './serverOverviewRows.js'

/* What starts and stops each server, from the report it gave last. */
const ACTIONS = {
  server: {
    start: (report) => api.runnerStarten({ modell: report.selected_model }),
    stop: () => api.runnerStoppen(),
  },
  agent: {
    start: (report) => api.agentenmodellStarten(report.selected_model),
    stop: () => api.agentenmodellStoppen(),
  },
  einbettung: {
    start: (report) => api.einbettungStarten(report.selected_model, report.port),
    stop: () => api.einbettungStoppen(),
  },
  sprache: {
    // The numbers of the start are the stored ones; only the file goes along.
    start: (report) => api.spracheStarten(report.selected_model),
    stop: () => api.spracheStoppen(),
  },
  bereinigung: {
    start: (report) => api.bereinigungStarten(report.selected_model, report.port),
    stop: () => api.bereinigungStoppen(),
  },
  bild: {
    start: (report) => {
      // Nothing chooses the default picture model by itself; the window says
      // where it is chosen, and so does this.
      if (!report.selected_model) return Promise.reject(new Error(t('bildserver.kein_standardmodell')))
      return api.turboStarten(report.selected_model)
    },
    stop: () => api.turboStoppen(),
  },
}

/** Starts the server if it is down, stops it if it runs; resolves with the new report. */
export function toggleServer(name, report) {
  const action = ACTIONS[name]
  return isRunning(name, report) ? action.stop() : action.start(report)
}
