/* What stands in an agent field when no agent file runs the work: a marker
   no agent name can be — brackets appear in none — for a run with no agent,
   a script and a reminder. Shown as the word, never as the marker. */
import { t } from './texte.svelte.js'

export const OHNE_AGENT = '(none)'

const WORTE = {
  '(none)': 'cronjobs.ohne_agent',
  '(skript)': 'cronjobs.kind_script',
  '(reminder)': 'cronjobs.kind_reminder',
}

export function agentName(name) {
  const schluessel = WORTE[name]
  return schluessel ? t(schluessel) : name
}
