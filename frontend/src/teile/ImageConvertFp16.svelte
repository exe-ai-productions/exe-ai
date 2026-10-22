<script>
  /* The FP16 tab of the conversion block: one file of the folder whose
     weights are mostly BF16, and the sign that writes a copy of it with those
     weights as FP16 (app/fp16_convert.py). The rows are the ones of the card
     they stand in; the bar of a running conversion and its cross are the
     block's (ImageConvert.svelte). */
  import { t } from '../lib/texte.svelte.js'
  import { imageFiles } from '../lib/imageModelFiles.svelte.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'

  let { running = false, onconvert } = $props()

  const convertible = $derived(imageFiles.list.filter((file) => file.fp16_convertible))
  let source = $state('')
  const current = $derived(convertible.find((file) => file.name === source) ?? convertible[0])
  $effect(() => {
    if (current && source !== current.name) source = current.name
  })
</script>

<div class="zeile">
  <span class="zeilentitel">{t('bildserver.datei')}</span>
  <div class="dateiwahl">
    <Auswahlfeld bind:wert={source} beschriftung={t('bildserver.datei')}
                 eintraege={convertible.map((file) => ({ wert: file.name, text: file.name }))}
                 gesperrt={running || !convertible.length} />
  </div>
  <button class="zeichenknopf" disabled={running || !current} onclick={() => onconvert(current.name)}
          title={running ? t('bildserver.umwandeln_laeuft') : t('bildserver.convert_fp16')}
          aria-label={running ? t('bildserver.umwandeln_laeuft') : t('bildserver.convert_fp16')}>
    <Hauszeichen zeichen="refresh" groesse="klein" />
  </button>
</div>

<style>
  .zeilentitel {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
    line-height: 18px;
    color: var(--text);
  }
  .dateiwahl {
    flex: none;
    width: 300px;
  }
  /* A sign on a button of button glass, 34 like the other buttons of a card. */
  .zeichenknopf {
    flex: none;
    width: 34px;
    height: 34px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zeichenknopf:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
  .zeichenknopf:disabled {
    cursor: default;
    opacity: 0.5;
  }
</style>
