<script>
  /* sd.cpp's further switches of one studio section (ImageSwitchRows.svelte),
     folded away under one row: its name and how many of them are set out of
     how many there are. A standing search opens the fold, so its rows are
     found like any other. Two rows of a StudioSection card. */
  import ImageSwitchRows from './ImageSwitchRows.svelte'
  import { hasNoPlace } from '../lib/imageSwitchPlace.js'
  import { imageSwitches } from '../lib/imageSwitches.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  let { group, values = $bindable({}), conditions = {}, upload = null, sucht = false } = $props()

  let offen = $state(false)
  const reihen = $derived(imageSwitches.list.filter((row) => row.group === group
    && !hasNoPlace(row, conditions)
    && (row.video == null || row.video === Boolean(conditions.video))))
  const gesetzt = $derived(reihen.filter((row) => {
    const wert = values?.[row.key]
    return wert !== undefined && wert !== '' && wert !== false && wert !== null
  }).length)
</script>

{#if reihen.length}
  <div class="zeile" hidden={sucht}>
    <button class="klappe" aria-expanded={offen} onclick={() => (offen = !offen)}>
      <svg class="winkel" class:auf={offen} width="11" height="11" viewBox="0 0 11 11" fill="none"
           stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true">
        <path d="M4.125 2.75L6.875 5.5L4.125 8.25" />
      </svg>
      <span>{t('bildserver.sdcpp_schalter')}</span>
      <span class="zaehler">{gesetzt}/{reihen.length}</span>
    </button>
  </div>
  {#if offen || sucht}
    <div class="zeile schalterflaeche">
      <ImageSwitchRows {group} bind:values {conditions} {upload} />
    </div>
  {/if}
{/if}
