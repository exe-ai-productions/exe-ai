<script>
  /* A small sign at the right end of the chat's head while a download runs
     or waits. A click takes the way the downloads row of the settings list
     takes — the catalogue on its downloads page, with no way back laid down —
     so what is running can be looked at from the chat, and the sign is gone
     once nothing runs or waits. A window that starts while the service is
     already loading asks it once, so the sign stands after a reload too. */
  import { onMount } from 'svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import { anzahlAktiv, readRunning } from '../lib/downloads.svelte.js'
  import { chooseRow } from '../lib/settingsrow.js'
  import { zeile } from '../lib/einstellungsliste.js'
  import { t } from '../lib/texte.svelte.js'

  const downloadsActive = $derived(anzahlAktiv() > 0)

  onMount(() => {
    readRunning()
  })
</script>

{#if downloadsActive}
  <button class="download-indicator" onclick={() => chooseRow(zeile('downloads'))}
          aria-label={t('downloads.titel')} title={t('downloads.titel')}>
    <Hauszeichen zeichen="download" groesse={16} />
  </button>
{/if}

<style>
  /* A glass sign button, 26 px, in the blue of "running"; it stands at the
     right end of the head's row. */
  .download-indicator {
    margin-left: auto;
    flex: none;
    width: 26px;
    height: 26px;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--blau);
    cursor: pointer;
    transition: background 0.12s, transform 0.08s;
  }
  .download-indicator:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .download-indicator:active {
    transform: scale(0.975);
  }
</style>
