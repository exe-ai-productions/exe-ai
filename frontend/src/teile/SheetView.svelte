<script>
  /* A spreadsheet (xlsx, xls): a tab for each sheet above its values, set as
     the same table a CSV file is (DataTable.svelte). The values are read by
     SheetJS in the page (lib/officeDocument.js) and shown as text. */
  import { onMount } from 'svelte'
  import { readBytes, readSheets } from '../lib/officeDocument.js'
  import DataTable from './DataTable.svelte'
  import OfficeFrame from './OfficeFrame.svelte'

  let { address, name = '' } = $props()

  let sheets = $state([])
  let active = $state(0)
  let phase = $state('reading')

  $effect(() => {
    const source = address
    if (!source) return
    let current = true
    phase = 'reading'
    ;(async () => {
      try {
        const read = await readSheets(await readBytes(source))
        if (!current) return
        sheets = read
        active = 0
        phase = 'ready'
      } catch {
        if (current) phase = 'failed'
      }
    })()
    return () => { current = false }
  })
</script>

<OfficeFrame {phase} {name}>
  {#if phase === 'ready' && sheets.length}
    <div class="sheets" role="tablist">
      {#each sheets as sheet, index}
        <button
          type="button"
          role="tab"
          class="sheet"
          class:on={index === active}
          aria-selected={index === active}
          onclick={() => (active = index)}
        >{sheet.name}</button>
      {/each}
    </div>
    <div class="values"><DataTable rows={sheets[active].rows} /></div>
  {/if}
</OfficeFrame>

<style>
  .sheets {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 12px 16px 0;
  }
  .sheet {
    border: none;
    border-radius: 9px;
    padding: 4px 11px;
    background: transparent;
    box-shadow: inset 0 0 0 1px var(--linie);
    color: var(--text-still);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .sheet.on {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    color: var(--text);
  }
  .values { padding: 12px 16px 16px; }
</style>
