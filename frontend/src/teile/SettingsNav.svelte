<script>
  /* The list of the settings as every page that carries it shows it: the
     settings, the local models and the six server pages put this one
     component in the sidebar snippet of their frame, so the rows, their
     figures and their dots are the same wherever the list stands.

     `current` is the id of the row whose page is open. A page that does more
     than the rows do by themselves passes `pick` (what a row does) and `jump`
     (what a switch found by the search does) — the settings window switches
     its own pages and asks first if an edit stands unsaved. Without them a
     row of the settings' own pages opens the settings on it. The version and
     the look for a newer one are the row "Updates" of the list itself.

     `own`: the page keeps the memory switch and the number of agents current
     itself, so the list does not read them a second time. */
  import { untrack } from 'svelte'
  import Einstellungsliste from './Einstellungsliste.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zeile as rowOfList } from '../lib/einstellungsliste.js'
  import { schalterAnspringen } from '../lib/einstellungssuche.js'
  import { chooseRow } from '../lib/settingsrow.js'
  import { rowValue, rowDot, loadSettingsState } from '../lib/settingsState.svelte.js'
  import { checkForUpdates } from '../lib/updates.svelte.js'

  let { current = '', pick = null, jump = null, own = false } = $props()

  /* Where the figures of the rows are read from while the list stands — once
     per appearance, not again when something it reads on the way changes. */
  $effect(() => {
    untrack(() => loadSettingsState({ own }))
  })

  /** Asks for a newer version, as the row of the same name does. */
  export function look() {
    return checkForUpdates()
  }

  const choose = (row) => (pick ?? ((r) => chooseRow(r, { look })))(row)

  /* A switch found by the search: its page opens as its row would open it,
     then the page scrolls to the switch. */
  let stopJump = null
  $effect(() => () => stopJump?.())
  async function jumpToSwitch(field) {
    stopJump?.()
    await choose(rowOfList(field.zeile))
    stopJump = schalterAnspringen(t(field.titel))
  }
</script>

<Einstellungsliste
  aktuell={current}
  wert={rowValue}
  punkt={rowDot}
  waehlen={choose}
  springen={jump ?? jumpToSwitch}
/>
