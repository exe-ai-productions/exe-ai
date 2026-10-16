<script>
  /* The program's version in the settings, and the place to look for a
     newer one by hand: the running version, the button that asks the shell
     to look again, and under them what came of it — up to date, a newer
     version with the way to fetch and then install it, or why the look
     failed.

     It shows what the shell says (lib/updates.svelte.js) and nothing of
     its own. In a browser there is no shell: a button that could do
     nothing is not shown, so the whole row stays away — as it does until
     the shell has said which version runs. */
  import { tick } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import {
    updates, checkForUpdates, downloadUpdate, failedKey, installUpdate,
  } from '../lib/updates.svelte.js'

  /* What a look brings stands under the button, at the very foot of a list
     that scrolls: it is rolled into sight once it is there, or it would
     come in under the list's lower edge. Only the look: its answer comes at
     once, while a download answers when it has ended — by then the hand may
     be elsewhere in the list, and its line changes in place anyway. */
  let part = $state(null)

  async function look() {
    await checkForUpdates()
    await tick()
    part?.scrollIntoView({ block: 'end' })
  }
</script>

{#if updates.present && updates.version}
  <div class="updates" bind:this={part}>
    <div class="row">
      <span class="version">{t('updates.version', { version: updates.version })}</span>
      {#if updates.state !== 'store'}
        <button class="act" onclick={look} disabled={updates.state === 'checking'}>
          {t('updates.check')}
        </button>
      {/if}
    </div>
    {#if updates.state === 'store'}
      <!-- A copy from the Microsoft Store: the Store keeps it current, so
           there is nothing to look for here, and no button that could. -->
      <div class="row">
        <span class="result done">{t('updates.store')}</span>
      </div>
    {:else if updates.state === 'available'}
      <div class="row">
        <span class="result">{t('updates.found', { version: updates.found })}</span>
        <button class="act" onclick={downloadUpdate}>{t('updates.download')}</button>
      </div>
    {:else if updates.state === 'downloading'}
      <div class="row">
        <span class="result running">{t('updates.downloading', { percent: updates.percent })}</span>
      </div>
    {:else if updates.state === 'downloaded'}
      <div class="row">
        <span class="result">{t('updates.found', { version: updates.found })}</span>
        <button class="act" onclick={installUpdate}>{t('updates.install')}</button>
      </div>
    {:else if updates.state === 'error'}
      <div class="row">
        <span class="result failed">{t(failedKey(), { reason: updates.reason })}</span>
      </div>
    {:else if updates.state === 'none' && updates.looked}
      <div class="row">
        <span class="result done">{t('updates.current')}</span>
      </div>
    {/if}
  </div>
{/if}

<style>
  .updates {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 12px 8px 10px;
    /* Rolled into sight, it comes to stand clear of the edge the list melts
       out at — which is the list's very end. */
    scroll-margin-bottom: 40px;
    /* On the frame it wears the frame's ink, as the rows above it do. */
    color: var(--rahmen-text, var(--text-leise));
    font: 500 12.5px var(--schrift);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 10px;
  }
  .version,
  .result {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  /* A state says itself in its colour: fetching runs, a look that failed
     failed, a look that found nothing newer is done. */
  .result.running { color: var(--blau); }
  .result.failed { color: var(--rot); }
  .result.done { color: var(--gruen); }
  .act {
    flex: none;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 12.5px var(--schrift);
    padding: 6px 10px;
    cursor: pointer;
  }
  .act:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .act:disabled {
    opacity: 0.55;
    cursor: default;
  }
</style>
