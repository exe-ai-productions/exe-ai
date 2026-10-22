/*
  The tools of the work bar on the phone: which tabs there are, which one a
  remembered name stands for, and the colour a tool wears.

  The bar carries six tools — the log of the tool calls, the preview, the
  pictures, the notes folder, the agents and the schedules. The terminal
  client of the desktop window is not among them: it runs in the window's
  shell and has nothing to show on a phone.

  No imports on purpose: names and colours in, a decision out, so it can be
  tried without a window around it.
*/

export const TABS = [
  { name: 'terminal', title: 'terminal.titel' },
  { name: 'vorschau', title: 'vorschau.titel' },
  { name: 'bilder', title: 'bilder.titel' },
  { name: 'docfolder', title: 'docfolder.title' },
  { name: 'agenten', title: 'agenten.titel' },
  { name: 'cronjobs', title: 'cronjobs.titel' },
]

/** The tab a name stands for; the first one for a name that is none. */
export function pickTab(wanted, tabs = TABS) {
  return tabs.some((tab) => tab.name === wanted) ? wanted : tabs[0].name
}

/** The colour the terminal tab wears: blue while a run goes, red while the
    last thing that was asked for or ran failed, nothing otherwise — a run
    that ended well is no news on a phone. */
export function terminalColour({ running = false, lastRefused = false, lastRun = null } = {}) {
  if (running) return 'blau'
  if (lastRefused) return 'rot'
  return lastRun === 'rot' ? 'rot' : null
}

const URGENCY = ['rot', 'gelb', 'blau', 'gruen']

/** What a tab says in its colour: only the four colours of the house; the
    grey of an ampel with nothing to say is no colour at all. */
export const tabColour = (colour) => (URGENCY.includes(colour) ? colour : null)
