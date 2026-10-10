<script>
  /* The picture server's model files, as rows of the model card under
     "Local" (app/api/v1/image_tools.py): each file with its family, its
     size, a "···" for the rare jobs — converting it to a smaller GGUF where
     a copy would be smaller, collecting an importance matrix — and an arrow
     that opens the values the model starts with and its kit
     (Bildmodellwerte.svelte). The devices stand in the memory section
     (BildGeraete.svelte). */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { familyOf, loadImageFamilies } from '../lib/imageFamilies.svelte.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import PictureMenu from './PictureMenu.svelte'
  import Bildmodellwerte from './Bildmodellwerte.svelte'

  /* Each new answer of the panel reads the list again; `familien` maps a
     file name to its family (GET /bild/modelle, `families`). */
  let { reload = null, familien = {} } = $props()

  let files = $state([])
  // The file a conversion is being set up for, its type, and whether it runs.
  let converting = $state(null)
  let weightType = $state('')
  let running = $state(false)
  // The one model whose values stand open, or none.
  let offen = $state('')
  /* The family the open values last read for their model (GET
     /bild/vorgaben): newer than the list's where the reading of the family
     was just switched for it. A new list is the newest word again. */
  let read = $state({})
  $effect(() => {
    if (familien) read = {}
  })

  function load() {
    api.imageModelFiles().then((list) => (files = list)).catch(() => {})
  }
  $effect(() => {
    if (reload !== undefined) load()
  })
  loadImageFamilies()

  /* Only the types a copy gets smaller in, as the service reads them off
     the file; the first of them stands chosen. */
  function convertStart(file) {
    converting = file.name
    weightType = file.convert_types[0]
  }

  const familie = (name) => familyOf(read[name] ?? familien[name])?.label ?? t('bild.familie_keine')
  const size = (bytes) => `${(bytes / 1e9).toLocaleString(undefined, { maximumFractionDigits: 1 })} GB`

  async function startConverting() {
    if (!converting || running) return
    running = true
    try {
      const answer = await api.convertModel(converting, weightType)
      meldeText('bildserver.umgewandelt', { datei: answer.file }, 'erfolg')
      converting = null
      load()
    } catch (error) {
      /* Stopped on request is no failure, as with a stopped picture: nothing
         is told, and the row stands as it did before the start. */
      if (error.status !== 499) melde(String(error.message || error), 'fehler')
    } finally {
      running = false
    }
  }

  async function toggleImatrix(file) {
    try {
      await api.collectImatrix(file.name, !file.collecting_imatrix)
      load()
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    }
  }
</script>

{#each files as file (file.name)}
  <div class="zeile liste datei">
    <span class="name" title={file.name}>{file.name}</span>
    <span class="familie">{familie(file.name)}</span>
    <span class="groesse">{size(file.size)}</span>
    <PictureMenu zeile entries={[
      ...(file.convert_types?.length
        ? [{ text: t('bildserver.umwandeln'), action: () => convertStart(file) }]
        : []),
      { text: t('bildserver.wichtigkeitsmatrix'), action: () => toggleImatrix(file),
        value: file.collecting_imatrix ? t('bild.offload_an') : t('bild.offload_aus') },
    ]} />
    <button class="auf" class:offen={offen === file.name} aria-expanded={offen === file.name}
            aria-label={t('bildserver.werte_auf')} title={t('bildserver.werte_auf')}
            onclick={() => (offen = offen === file.name ? '' : file.name)}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor"
           stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M3.5 5.25L7 8.75L10.5 5.25" />
      </svg>
    </button>
  </div>
  {#if offen === file.name}
    <Bildmodellwerte modell={file.name} listen={reload}
                     onfamily={(family) => (read[file.name] = family)} />
  {/if}
  {#if converting === file.name}
    <div class="zeile liste">
      <div class="gewicht">
        <Auswahlfeld bind:wert={weightType} beschriftung={t('bild.weight_type')}
                     eintraege={file.convert_types.map((w) => ({ wert: w, text: w }))}
                     gesperrt={running} />
      </div>
      <button class="feldknopf" disabled={running} onclick={startConverting}>
        {running ? t('bildserver.umwandeln_laeuft') : t('bildserver.umwandeln')}
      </button>
    </div>
  {/if}
{/each}

<style>
  /* The rows are Serverabschnitt.svelte's; here only their parts. A file
     row is the positioned box its menu hangs from. */
  .datei {
    position: relative;
  }
  /* The family as a small pill on the field ground. */
  .familie {
    flex: none;
    padding: 2px 9px;
    border-radius: 9px;
    background: var(--bg-hoch);
    font-size: 12px;
    line-height: 16px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .groesse {
    flex: none;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-still);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .gewicht {
    flex: 1;
    min-width: 0;
  }
  /* The arrow that opens a model's values: quiet like the "···" beside it,
     turned up while they stand open. */
  .auf {
    flex: none;
    width: 24px;
    height: 24px;
    margin-left: -4px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
    cursor: pointer;
  }
  .auf:hover {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .auf svg {
    transition: transform 0.15s;
  }
  .auf.offen svg {
    transform: rotate(180deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .auf svg {
      transition: none;
    }
  }
</style>
