<script>
  /* The tools of the work bar as a page over the chat: the way back, the
     tool's name, a row of tabs — one sign each, wearing the state of its
     tool — and the tool itself. The tools are the desktop's own, the ones
     the column on the right holds; the terminal client is not among them. */
  import { t } from '../lib/texte.svelte.js'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import Modulzeichen from '../teile/Modulzeichen.svelte'
  import Agentenmarke from '../teile/Agentenmarke.svelte'
  import Leuchtpunkt from '../teile/Leuchtpunkt.svelte'
  import ModulTerminal from '../teile/ModulTerminal.svelte'
  import ModulVorschau from '../teile/ModulVorschau.svelte'
  import ModulBilder from '../teile/ModulBilder.svelte'
  import DocFolder from '../teile/DocFolder.svelte'
  import ModulAgenten from '../teile/ModulAgenten.svelte'
  import ModulCronjobs from '../teile/ModulCronjobs.svelte'
  import { terminal, terminalGesehen } from '../lib/terminalfenster.svelte.js'
  import { TABS } from './work.js'
  import { work, workClose, workTab } from './workbar.svelte.js'
  import { toolStates } from './workState.svelte.js'

  const states = $derived(toolStates())
  /* Looking at the terminal marks its runs as seen, as the open column does
     on the desktop; otherwise a finished run's dot would breathe for good. */
  $effect(() => {
    if (work.tab === 'terminal' && terminal.laeufe) terminalGesehen()
  })

  const shown = $derived(TABS.find((tab) => tab.name === work.tab) ?? TABS[0])
</script>

<section class="work">
  <header class="head">
    <button class="back" onclick={workClose} aria-label={t('app.zurueck')}>
      <span class="arrow"><Hauszeichen zeichen="pfeil_unten" groesse={15} strich={2.6} /></span>
    </button>
    <h1>{t(shown.title)}</h1>
  </header>

  <nav class="tabs" aria-label={t('phone_work.titel')}>
    {#each TABS as tab (tab.name)}
      <button
        class="tab"
        class:on={tab.name === work.tab}
        aria-pressed={tab.name === work.tab}
        aria-label={t(tab.title)}
        onclick={() => workTab(tab.name)}
      >
        {#if tab.name === 'agenten'}
          <Agentenmarke groesse={25} />
        {:else}
          <Modulzeichen modul={tab.name} groesse={24} />
        {/if}
        {#if states[tab.name]}
          <span class="dot"><Leuchtpunkt farbe={states[tab.name]} groesse={9} /></span>
        {/if}
      </button>
    {/each}
  </nav>

  <div class="body">
    {#key work.tab}
      {#if work.tab === 'terminal'}
        <ModulTerminal />
      {:else if work.tab === 'vorschau'}
        <ModulVorschau />
      {:else if work.tab === 'bilder'}
        <ModulBilder />
      {:else if work.tab === 'docfolder'}
        <DocFolder />
      {:else if work.tab === 'agenten'}
        <ModulAgenten />
      {:else if work.tab === 'cronjobs'}
        <ModulCronjobs />
      {/if}
    {/key}
  </div>
</section>

<style>
  .work {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    /* The side margin the tools read, as in the desktop column. */
    --rand: 12px;
  }
  .head {
    flex: none;
    display: flex;
    align-items: center;
    gap: 6px;
    height: calc(52px + env(safe-area-inset-top));
    padding: env(safe-area-inset-top) calc(8px + env(safe-area-inset-right)) 0
      calc(8px + env(safe-area-inset-left));
  }
  .back {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
  }
  .back:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  /* The house arrow points down; turned a quarter it points back. */
  .arrow {
    display: inline-flex;
    transform: rotate(90deg);
  }
  h1 {
    margin: 0;
    font: 600 16px var(--schrift);
  }
  .tabs {
    flex: none;
    display: flex;
    gap: 2px;
    padding: 0 calc(8px + env(safe-area-inset-right)) 6px calc(8px + env(safe-area-inset-left));
  }
  .tab {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 44px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
  }
  .tab.on {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .dot {
    position: absolute;
    top: 6px;
    right: 8px;
    display: inline-flex;
  }
  .body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding-bottom: env(safe-area-inset-bottom);
  }
</style>
