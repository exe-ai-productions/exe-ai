<script>
  /* A stack of LoRAs in a studio card. On top a search field that adds: a
     click shows every LoRA of the folder that is not in the stack yet,
     typing narrows the list, a click on a name adds it at 0.7; the arrow
     keys walk the list and Enter adds the marked name. Under it one
     card per LoRA — its name without the file's ending, the ✕, and its
     strength in the studio's slider form: the word, the number, the slider
     under both. The same stack serves the picture and the face pass. Rows of
     a StudioSection card. */
  import { tick } from 'svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import { t } from '../lib/texte.svelte.js'

  /* `name` names the cards for the column's search. */
  let { stapel = $bindable([]), dateien = [], name } = $props()

  const uid = $props.id()

  // The slider covers the usual range; the number takes what the service
  // takes (app/bildwahlen.py LORA_MIN, LORA_MAX).
  const STUFEN = Array.from({ length: 301 }, (_, i) => Math.round((-1 + i * 0.01) * 100) / 100)
  const MIN = -10
  const MAX = 10
  // The strength a LoRA starts at (app/bildwahlen.py LORA_VORGABE).
  const VORGABE = 0.7

  // A LoRA is called by its file's name without the ending.
  const bare = (file) => file.replace(/\.[^.]+$/, '')

  let query = $state('')
  let open = $state(false)
  const matches = $derived.by(() => {
    const asked = query.trim().toLowerCase()
    return dateien.filter(
      (file) => !stapel.some((entry) => entry.name === file) && bare(file).toLowerCase().includes(asked),
    )
  })

  const shown = $derived(open && matches.length > 0)
  // The marked name of the list, moved by the arrows and by the pointer; a
  // list that got shorter marks its last one.
  let marked = $state(0)
  const at = $derived(Math.min(marked, matches.length - 1))

  function add(file) {
    stapel = [...stapel, { name: file, staerke: VORGABE }]
    query = ''
    marked = 0
  }

  async function mark(index) {
    marked = index
    await tick()
    document.getElementById(`${uid}-name-${index}`)?.scrollIntoView({ block: 'nearest' })
  }

  // The arrows walk the list, Enter adds the marked name, Escape puts the
  // list away; every other key is typing, which starts at the top again.
  function keyed(event) {
    // A key that belongs to a character being composed is typing, never a
    // command.
    if (event.isComposing) {
      open = true
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!matches.length) return
      const step = event.key === 'ArrowDown' ? 1 : -1
      mark(shown ? (at + step + matches.length) % matches.length : at)
      open = true
    } else if (event.key === 'Enter') {
      if (!shown) return
      event.preventDefault()
      add(matches[at])
    } else if (event.key === 'Escape') {
      open = false
    } else {
      open = true
    }
  }
</script>

<div class="zeile finder" data-suche={t('bild.lora_hinzufuegen')}>
  <div class="suchfeld" class:leer={!dateien.length}>
    <Hauszeichen zeichen="lupe" groesse={14} />
    <input type="search" bind:value={query} aria-label={t('bild.lora_hinzufuegen')}
           role="combobox" aria-autocomplete="list" aria-expanded={shown} aria-controls="{uid}-names"
           aria-activedescendant={shown ? `${uid}-name-${at}` : undefined}
           disabled={!dateien.length} autocomplete="off"
           onfocus={() => (open = true)} onclick={() => (open = true)} onblur={() => (open = false)}
           oninput={() => (marked = 0)} onkeydown={keyed} />
  </div>
  {#if shown}
    <div class="treffer" id="{uid}-names" role="listbox" aria-label={t('bild.lora_hinzufuegen')}>
      {#each matches as file, n (file)}
        <!-- Pressing a name must not take the focus off the field: the list
             closes when the field is left. -->
        <button id="{uid}-name-{n}" role="option" aria-selected={n === at} class:marked={n === at}
                tabindex="-1" title={file}
                onmousedown={(event) => event.preventDefault()} onmousemove={() => (marked = n)}
                onclick={() => add(file)}>
          {bare(file)}
        </button>
      {/each}
    </div>
  {/if}
  {#if !dateien.length}
    <p class="hinweis">{t('bild.lora_keine')}</p>
  {/if}
</div>
{#each stapel as eintrag, i (i)}
  <div class="zeile regel lora" data-suche={name}>
    <div class="kopfzeile">
      <span class="loraname" title={eintrag.name}>{bare(eintrag.name)}</span>
      <button class="weg" aria-label={t('bild.entfernen')} title={t('bild.entfernen')}
              onclick={() => (stapel = stapel.filter((_, n) => n !== i))}>
        <Hauszeichen zeichen="kreuz" groesse={12} />
      </button>
    </div>
    <div class="kopfzeile">
      <label class="name" for="{uid}-{i}">{t('bild.lora_staerke')}</label>
      <div class="rechts">
        <Zahlenfeld id="{uid}-{i}" bind:wert={eintrag.staerke} min={MIN} max={MAX} schritt={0.05} />
      </div>
    </div>
    <Schieberegler bind:wert={eintrag.staerke} stufen={STUFEN} mit_zahl={false} fuellung
                   beschriftung={t('bild.lora_staerke')} />
  </div>
{/each}

<style>
  .finder {
    gap: 6px;
  }
  /* The field reads like the studio's pickers: glass, the house's radius. */
  .suchfeld {
    flex: 1 1 100%;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 32px;
    box-sizing: border-box;
    padding: 0 10px;
    border: 1px solid var(--feldstrich, transparent);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text-still);
  }
  .suchfeld:focus-within {
    color: var(--text);
  }
  .suchfeld.leer {
    opacity: 0.5;
  }
  .suchfeld input {
    flex: 1;
    min-width: 0;
    border: none;
    background: none;
    outline: none;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
  }
  .suchfeld input::-webkit-search-cancel-button {
    display: none;
  }
  .treffer {
    flex: 1 1 100%;
    min-width: 0;
    max-height: 208px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  .treffer button {
    flex: none;
    min-height: 30px;
    padding: 0 10px;
    border: none;
    background: none;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  .treffer button.marked {
    background: var(--glass-hover);
  }
  .lora {
    gap: 4px;
  }
  .loraname {
    flex: 1;
    min-width: 0;
    font: 500 13px/18px var(--schrift);
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .weg {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
    cursor: pointer;
  }
  .weg:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
</style>
