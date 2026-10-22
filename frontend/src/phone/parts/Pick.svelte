<script>
  /* A choice made from a list: one row shows what stands chosen, a tap
     opens the list as a sheet from below. `options` are `{ value, label,
     detail }`; `onpick` gets the value of the one tapped. */
  import { t } from '../../lib/texte.svelte.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Sheet from '../Sheet.svelte'

  let { label, value = '', options = [], onpick, disabled = false } = $props()
  let open = $state(false)

  const shown = $derived(options.find((option) => option.value === value)?.label ?? '')

  function pick(option) {
    open = false
    onpick?.(option.value)
  }
</script>

<Menuezeile titel={label} wert={shown} onclick={() => !disabled && (open = true)} {disabled} />

<Sheet {open} {label} onclose={() => (open = false)}>
  <div class="title">{label}</div>
  {#each options as option (option.value)}
    <button class="choice" class:chosen={option.value === value} onclick={() => pick(option)}>
      <span class="name">{option.label}</span>
      {#if option.detail}<small>{option.detail}</small>{/if}
    </button>
  {:else}
    <div class="none">{t('modell.kein_modell_da')}</div>
  {/each}
</Sheet>

<style>
  .title {
    padding: 4px 4px 10px;
    font: 600 16px var(--schrift);
  }
  .choice {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: var(--menuezeile);
    padding: 6px;
    border: none;
    border-top: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: 400 var(--schrift-text) var(--schrift);
    text-align: left;
  }
  .choice.chosen {
    color: var(--text);
    font-weight: 600;
  }
  .name {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  small {
    flex: none;
    color: var(--text-still);
    font-size: 12px;
  }
  .none {
    padding: 14px 6px;
    color: var(--text-still);
  }
</style>
