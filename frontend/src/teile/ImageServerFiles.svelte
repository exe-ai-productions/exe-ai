<script>
  /* The picture server's model files, as a folding row "Image models in this
     folder" (app/api/v1/image_tools.py), closed to begin with: each file with
     its family's mark, its family, its size and its state — the chips
     "Analyzing imatrix" while pictures add to its importance matrix, and one
     "GGUF <type>" for each GGUF copy beside it. The values a model starts
     with stand at the top of the page (Bildmodellwerte.svelte); the devices
     stand in the memory section (BildGeraete.svelte), converting in the block
     above (ImageConvert.svelte). */
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatGb } from '../lib/numberDisplay.js'
  import { familyOf, familyMark, loadImageFamilies } from '../lib/imageFamilies.svelte.js'
  import { imageFiles } from '../lib/imageModelFiles.svelte.js'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import MakerMark from './MakerMark.svelte'

  /* `familien` maps a file name to its family (`families` of GET
     /bild/modelle). The list of the files is read by the panel
     (Bildserver.svelte) after each new answer. */
  let { familien = {} } = $props()

  loadImageFamilies()

  const familie = (name) => familyOf(familien[name])?.label ?? t('bild.familie_keine')
  const size = (bytes) => t('modell.gb', { zahl: formatGb(bytes / 1e9, texte.sprache) })
</script>

{#if imageFiles.list.length}
  <Serverabschnitt klappbar offen={false} titel={t('bildserver.bildmodelle_im_ordner')}>
    <div class="zeile tabellenkopf">
      <span class="datei">{t('bildserver.datei')}</span>
      <span class="familie">{t('bild.familie')}</span>
      <span class="groesse">{t('bildserver.groesse')}</span>
      <span class="stand">{t('bildserver.stand')}</span>
    </div>
    {#each imageFiles.list as file (file.name)}
      <div class="zeile datei-zeile">
        <span class="datei" title={file.name}>
          <MakerMark mark={familyMark(familien[file.name])} name={file.name} />
          <span class="dateiname">{file.name}</span>
        </span>
        <span class="familie wert">{familie(file.name)}</span>
        <span class="groesse wert">{size(file.size)}</span>
        <span class="stand">
          {#if file.collecting_imatrix}
            <span class="chip imatrix">{t('bildserver.imatrix_laeuft')}</span>
          {/if}
          {#if file.gguf_type}
            <span class="chip gguf">{t('bildserver.gguf_typ', { typ: file.gguf_type })}</span>
          {/if}
        </span>
      </div>
    {/each}
  </Serverabschnitt>
{/if}

<style>
  /* The rows are Serverabschnitt.svelte's; here only their columns: the file
     takes what is left, with its family's mark before the name; the others
     stand 150, 110 and 230 wide. */
  .datei {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .dateiname {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .familie {
    flex: none;
    width: 150px;
  }
  .groesse {
    flex: none;
    width: 110px;
    font-variant-numeric: tabular-nums;
  }
  /* The column is 230 wide; three chips go on a second line. */
  .stand {
    flex: none;
    width: 230px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 6px;
    min-width: 0;
  }
  /* Two classes under the card, so the card's own row height
     (Serverabschnitt.svelte) does not win. */
  :global(.karte) > .zeile.tabellenkopf {
    min-height: 40px;
    font-size: 11px;
    font-weight: 600;
    line-height: 15px;
    color: var(--text-leise);
  }
  /* The head's file column starts where the names do, behind the mark's box
     (22 px and its gap). */
  .tabellenkopf .datei {
    padding-left: 32px;
  }
  .datei-zeile {
    position: relative;
    font-size: 13px;
    line-height: 18px;
    color: var(--text);
  }
  .datei-zeile .datei {
    font-weight: 600;
  }
  .datei-zeile .wert {
    white-space: nowrap;
  }
  /* A state of the file in a few words: 19 tall, in the colour of what it
     says — green for the matrix that is being collected, blue for a copy that
     is there — on twelve parts in a hundred of the same colour. */
  .chip {
    flex: none;
    height: 19px;
    box-sizing: border-box;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 600;
    line-height: 15px;
    white-space: nowrap;
  }
  .chip.imatrix {
    color: var(--gruen-text);
    background: color-mix(in srgb, var(--gruen) 12%, transparent);
  }
  .chip.gguf {
    color: var(--text);
    background: color-mix(in srgb, var(--text) 12%, transparent);
  }
</style>
