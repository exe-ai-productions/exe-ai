<script>
  /* The models the service reports, switched-off ones left out, the chosen
     one with a check. The second step of the plus sheet (AttachSheet.svelte)
     draws it; the list is read anew at every opening of the sheet, so a
     model switched off elsewhere is not offered.

     The list and the pick are the desktop picker's (lib/modelle.svelte.js). */
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { sichtbare, chosenModelOff } from '../lib/modelle.svelte.js'

  let { onpick } = $props()

  const offered = $derived(sichtbare())
  const emptyText = $derived(
    t(chosenModelOff() ? 'fehler.modell_deaktiviert' : 'fehler.kein_modell_verfuegbar'),
  )
  const groups = $derived(
    [
      { key: 'local', title: t('menue.lokal'), models: offered.filter((m) => m.group === 'local') },
      { key: 'cloud', title: t('menue.cloud'), models: offered.filter((m) => m.group !== 'local') },
    ].filter((group) => group.models.length),
  )
</script>

<div class="list" role="menu">
  {#each groups as group (group.key)}
    <div class="title">{group.title}</div>
    {#each group.models as model (model.id)}
      <button class="row" role="menuitemradio" aria-checked={model.id === zustand.modellId}
              onclick={() => onpick?.(model.id)}>
        <span class="check">
          {#if model.id === zustand.modellId}<Hauszeichen zeichen="haken" groesse={14} strich={2.6} />{/if}
        </span>
        <span class="label">{model.name ?? model.id}</span>
        {#if model.capabilities?.vision}
          <span class="lamp"><Hauszeichen zeichen="auge" groesse={13} /></span>
        {/if}
        {#if model.capabilities?.tool_calls}
          <span class="lamp"><Hauszeichen zeichen="werkzeug" groesse={13} /></span>
        {/if}
      </button>
    {/each}
  {:else}
    <p class="nothing">{emptyText}</p>
  {/each}
</div>

<style>
  .list {
    max-height: 56dvh;
    overflow-y: auto;
  }
  .title {
    margin: 10px 4px 4px;
    color: var(--text-still);
    font: var(--schrift-hinweis) var(--schrift);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 44px;
    padding: 0 8px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: 15px var(--schrift);
    text-align: left;
  }
  .row:active {
    background: var(--bg-hoch);
  }
  .check {
    flex: none;
    width: 16px;
    display: inline-flex;
  }
  .label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lamp {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
  }
  .nothing {
    margin: 4px;
    color: var(--text-leise);
    font: var(--schrift-hinweis) var(--schrift);
  }
</style>
