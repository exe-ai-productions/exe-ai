/*
  What each tool of the work bar has to say right now, read from the same
  facts the desktop's row of signs reads: the runs of the terminal and the
  calls of the chat, the agents' runs and the schedules.
*/
import { terminal } from '../lib/terminalfenster.svelte.js'
import { historie } from '../lib/werkzeughistorie.js'
import { nachrichtenAnzeige } from '../lib/zustand.svelte.js'
import { laufampel } from '../lib/laufampel.js'
import { punktfarbe as agentColour } from '../lib/agentenampel.svelte.js'
import { punktfarbe as cronColour } from '../lib/cronjobampel.svelte.js'
import { tabColour, terminalColour } from './work.js'

/** The colour of every tab, `null` where a tool has nothing to say. */
export function toolStates() {
  const runs = terminal.laeufe
  const entries = historie(nachrichtenAnzeige(), runs).filter((entry) => entry.art !== 'trennung')
  const last = entries[entries.length - 1] ?? null
  const lastRun = runs[runs.length - 1] ?? null
  return {
    terminal: terminalColour({
      running: runs.some((run) => run.zustand === 'laeuft'),
      lastRefused: last?.art === 'aufruf' && Boolean(last.fehlgeschlagen),
      lastRun: lastRun ? laufampel(lastRun.zustand) : null,
    }),
    agenten: tabColour(agentColour()),
    cronjobs: tabColour(cronColour()),
  }
}

/** Which tool works right now, by tab: blue where a tool runs, nothing
    otherwise. It asks only the three facts that can make a tab blue and never
    the list of tool calls, because it is read while the chat streams. */
export const workBusyByTab = () => ({
  terminal: terminal.laeufe.some((run) => run.zustand === 'laeuft') ? 'blau' : null,
  agenten: tabColour(agentColour()),
  cronjobs: tabColour(cronColour()),
})
