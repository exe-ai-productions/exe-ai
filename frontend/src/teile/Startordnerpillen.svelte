<script>
  /* The working folders for a job, as pills — the same face the chat wears,
     but with a list of its own.

     A job started from the start window has no chat to borrow folders from, so
     this row keeps them itself and hands them to the start request. The
     agent's own `folders:` apply when none are picked here; picking any lets
     the window's choice win, the way the window's model does. Not the chat's
     store (the folder chip in the input bar, FolderChip.svelte), because that
     one is bound to a chat and this is not. */
  import { onMount } from 'svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { api } from '../lib/api.js'
  import { melde } from '../lib/zustand.svelte.js'
  import {
    ordnerName, ordnerZustand, dialogPruefen,
  } from '../lib/arbeitsordner.svelte.js'

  let { ordner = $bindable([]) } = $props()

  let laeuft = $state(false)

  // Whether this machine has a folder dialog at all. Without one the path
  // is typed by hand. Until the first answer is in, neither the field nor
  // the button stands, so a machine with a dialog never flashes the field.
  let geprueft = $state(ordnerZustand.dialogDa)
  onMount(() => { dialogPruefen().then(() => (geprueft = true)) })

  async function waehlen() {
    if (laeuft) return
    laeuft = true
    try {
      const antwort = await api.ordnerDialogOeffnen(
        t('arbeitsordner.dialog_titel'), ordner[ordner.length - 1] || null,
      )
      // No path means cancelled — say nothing. Sharing the same folder twice
      // is not a second share; merge silently.
      const pfad = antwort?.pfad
      if (pfad && !ordner.includes(pfad)) ordner = [...ordner, pfad]
    } catch (fehler) {
      melde(fehler.message || t('fehler.allgemein'), 'fehler')
    } finally {
      laeuft = false
    }
  }

  function loesen(pfad) {
    ordner = ordner.filter((eintrag) => eintrag !== pfad)
  }

  /* Without a folder dialog (a browser on another device) the path is
     typed by hand; Enter takes it as a pill, the same way a picked folder
     arrives, and the service checks it the same way. */
  let getippt = $state('')
  function uebernehmen() {
    const pfad = getippt.trim()
    if (pfad && !ordner.includes(pfad)) ordner = [...ordner, pfad]
    getippt = ''
  }
  // Enter takes the path; so does leaving the field, so a path typed and
  // then saved without Enter is not lost. The key stays here — the window
  // around must not read it as "send".
  function eintippen(ereignis) {
    if (ereignis.key !== 'Enter') return
    ereignis.preventDefault()
    ereignis.stopPropagation()
    uebernehmen()
  }
</script>

<div class="reihe">
    {#each ordner as pfad (pfad)}
      <div class="pille">
        <!-- No open-in-file-manager here: there is no chat yet whose share the
             service could check the path against. The chip only names the
             folder and lets it go again. -->
        <span class="flaeche" title={pfad}>
          <svg class="zeichen" width="14" height="14" viewBox="0 0 64 64" fill="none"
               stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"
               aria-hidden="true">
            <path d="M11 50 V14 H27 L32 21 H53 V50 Z" stroke-width="5" />
            <path d="M11 26 H53" stroke-width="4.5" />
          </svg>
          <span class="name">{ordnerName(pfad)}</span>
        </span>
        <button class="x" onclick={() => loesen(pfad)}
                aria-label={t('arbeitsordner.loesen')} title={t('arbeitsordner.loesen')}>✕</button>
      </div>
    {/each}

    {#if !geprueft}
      <!-- Nothing until the machine has said whether it has a dialog. -->
    {:else if !ordnerZustand.dialogDa}
      <input
        class="pfadfeld"
        bind:value={getippt}
        onkeydown={eintippen}
        onchange={uebernehmen}
        aria-label={t('arbeitsordner.hinzufuegen')}
        spellcheck="false"
        autocomplete="off"
      />
    {:else}
    <button
      class="mehr"
      class:gesperrt={laeuft}
      onclick={waehlen}
      disabled={laeuft}
      title={t('arbeitsordner.hinzufuegen')}
      aria-label={t('arbeitsordner.hinzufuegen')}
    >
      <!-- The folder of the house, not a bare plus. A round button with a
           plus in it is the sign for "one more of whatever is here" and says
           nothing about WHAT — which is the whole question when somebody is
           looking for where to share a folder.

           Drawn by the house component, not by a path copied in here: the
           same folder is traced by hand in half a dozen files, and the
           moment one of them is changed they stop being the same sign. -->
      <Hauszeichen zeichen="ordner" groesse="klein" />
      <span class="mehrwort">{t('arbeitsordner.hinzufuegen')}</span>
    </button>
    {/if}
</div>

<style>
  .reihe {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .pille {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    height: 28px;
    box-sizing: border-box;
    max-width: 100%;
    min-width: 0;
    border: 1px solid var(--text-leise);
    border-radius: 9px;
    background: var(--bg-erhoben);
    padding: 0 4px;
    overflow: hidden;
  }
  .pille:hover { background: var(--linie); }
  .flaeche {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    height: 22px;
    padding: 0 4px;
  }
  .pille .zeichen {
    flex: none;
    color: var(--text-leise);
  }
  .name {
    font-size: 12.5px;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .x {
    border: none;
    background: none;
    color: var(--text-still);
    font: inherit;
    font-size: 12px;
    padding: 2px 4px;
    border-radius: 9px;
    cursor: pointer;
    flex: none;
  }
  .x:hover {
    background: var(--linie-stark);
    color: var(--text);
  }
  .pille:hover .x { color: var(--text-leise); }
  /* Shaped like the chips it stands beside — same height, same radius, same
     ground. It was a 28-pixel circle at radius 99, the one round control in a
     row of square-cornered ones, and the only radius in this file that was
     not 9. */
  .mehrwort {
    font-size: 12px;
    white-space: nowrap;
  }
  .mehr {
    height: 28px;
    padding: 0 8px 0 6px;
    gap: 5px;
    box-sizing: border-box;
    flex: none;
    border: 1px solid var(--linie-stark);
    border-radius: 9px;
    background: var(--bg-erhoben);
    color: var(--text-leise);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .mehr:hover {
    background: var(--linie);
    color: var(--text);
  }
  .mehr.gesperrt {
    opacity: 0.4;
    cursor: default;
  }
  /* The typed path: a field like the mask's own, as tall as the pills. */
  .pfadfeld {
    flex: 1 1 160px;
    min-width: 0;
    height: 28px;
    box-sizing: border-box;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 400 12.5px var(--schrift-fest);
    outline: none;
  }
  .mehr.gesperrt:hover {
    background: none;
    color: var(--text-leise);
  }
</style>
