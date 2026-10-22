<script>
  /* The state of one download, drawn the same in every place of the
     catalogue: a file row of the model page and the foot of a card.

       neu     the download sign button
       laedt   the bar, the percentage, a fine divider, "loaded / total GB"
               (the caller adds the speed where it has room) and the cancel
               cross, all in one line
       wartet  "Waiting" in yellow and the cross that takes it out of the queue
       bereit  the green tick, with "downloaded" beside it unless `sealed`
       frage   nothing yet, in the room of a sign: the folder has not been read,
               so neither "download" nor "downloaded" is true of the file

     The row owns its signs: every button is 22 px with a 14 px sign, so a row
     never grows with its state. The numbers stand quiet, the word of a state
     in the text colour of its colour. */
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'

  let {
    status = 'neu', // 'neu' | 'laedt' | 'wartet' | 'bereit' | 'frage'
    percent = 0,
    amounts = '',
    /* Only the tick, without its word — where a card has no room for it. */
    sealed = false,
    /* Where the amounts do not fit: the bar and the percentage only, the
       amounts in the tooltip. */
    compact = false,
    disabled = false,
    onDownload,
    onCancel,
    onDequeue,
  } = $props()

  /* A sign inside a clickable card must not open the card. */
  const press = (e, action) => {
    e.stopPropagation()
    action?.()
  }
</script>

<div class="state" class:running={status === 'laedt'} title={status === 'laedt' && compact ? amounts : undefined}>
  {#if status === 'laedt'}
    <span class="bar"><i style="width:{percent}%"></i></span>
    <span class="percent">{percent} %</span>
    {#if !compact}
      <span class="divider" aria-hidden="true"></span>
      <span class="amounts" title={amounts}>{amounts}</span>
    {/if}
    <button class="sign-button" onclick={(e) => press(e, onCancel)}
            title={t('katalog.abbrechen')} aria-label={t('katalog.abbrechen')}>
      <Hauszeichen zeichen="kreuz" groesse={14} />
    </button>
  {:else if status === 'wartet'}
    <span class="waiting">{t('katalog.wartet')}</span>
    <button class="sign-button" onclick={(e) => press(e, onDequeue)}
            title={t('katalog.abbrechen')} aria-label={t('katalog.abbrechen')}>
      <Hauszeichen zeichen="kreuz" groesse={14} />
    </button>
  {:else if status === 'bereit'}
    <span class="done" class:sealed role={sealed ? 'img' : undefined}
          aria-label={sealed ? t('katalog.im_ordner') : undefined}
          title={sealed ? t('katalog.im_ordner') : undefined}>
      <span class="tick"><Hauszeichen zeichen="haken" groesse={14} strich={2.6} /></span>
      {#if !sealed}{t('katalog.im_ordner')}{/if}
    </span>
  {:else if status === 'frage'}
    <span class="asking" aria-hidden="true"></span>
  {:else}
    <button class="sign-button" onclick={(e) => press(e, onDownload)} {disabled}
            title={t('katalog.herunterladen')} aria-label={t('katalog.herunterladen')}>
      <Hauszeichen zeichen="download" groesse={14} />
    </button>
  {/if}
</div>

<style>
  .state {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: none;
  }
  /* The room of one sign, empty: a row and a card keep their size while the
     folder is being read. */
  .asking {
    width: 22px;
    height: 22px;
  }
  /* A running row takes the room the name leaves. */
  .state.running {
    flex: 1;
    min-width: 0;
  }
  .bar {
    flex: 1;
    min-width: 24px;
    height: 4px;
    border-radius: 9px;
    background: var(--glass-button);
    overflow: hidden;
  }
  .bar i {
    display: block;
    height: 100%;
    background: var(--blau);
    transition: width 0.3s;
  }
  .percent {
    font: 400 12px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  /* Fine and vertical, between the percentage and the amounts. */
  .divider {
    width: 1px;
    height: 12px;
    background: var(--linie);
  }
  /* On a narrow card the amounts give way, cut with an ellipsis, before the
     cross is pushed out of the foot. */
  .amounts {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    font: 400 12px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .waiting {
    font: 500 12.5px var(--schrift);
    color: var(--gelb-text);
    white-space: nowrap;
  }
  .done {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    gap: 6px;
    font: 500 12.5px var(--schrift);
    color: var(--gruen-text);
    white-space: nowrap;
  }
  /* The tick alone stands where the download sign button stood. */
  .done.sealed {
    width: 22px;
    height: 22px;
    justify-content: center;
    gap: 0;
  }
  /* The tick is a sign, not a word: it keeps the plain green. */
  .tick {
    display: inline-flex;
    color: var(--gruen);
  }
  /* A sign button, 22 px: button glass with its fine edge. */
  .sign-button {
    width: 22px;
    height: 22px;
    flex: none;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: pointer;
    transition: background 0.12s, opacity 0.12s, transform 0.08s;
  }
  .sign-button:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .sign-button:active {
    transform: scale(0.975);
  }
  .sign-button:disabled {
    opacity: 0.45;
    cursor: default;
  }
</style>
