<script>
  /* One model — or one Hugging Face repository — up close, as a page of its
     own with the way back at its head. The same page serves a catalogue card
     (its builds) and a search hit (its files): a head with the name, the
     provider and the machine's memory, a link to the repository, and one row
     per build or file. Every row carries its own button, so there is nothing
     to select first and nothing to confirm at the foot.

     The downloads themselves belong to the parent (Katalog), which owns the
     queue; this page only draws the rows and asks. */
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Bausatzkopf from './Bausatzkopf.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { LOGOS } from '../lib/logos.js'
  import { FAEHIGKEIT_FARBE, farbton } from '../lib/modellempfehlungen.js'

  let {
    name,
    unter = '',
    marke = null,
    buchstabe = '',
    faehigkeiten = [],
    /* Class and kind of an accessory, each as { text, farbe }. */
    plaketten = [],
    maschineGb = null,
    repo = null,
    satz = '',
    zeilen = null,
    laedt = false,
    onZurueck,
    onHolen,
    onAbbrechen,
  } = $props()

  const KANN = {
    werkzeug: 'katalog.kann_winkel',
    auge: 'katalog.kann_auge',
    gluehbirne: 'katalog.kann_gluehbirne',
    blitz: 'katalog.kann_blitz',
  }

  /* A repository identifier has an owner and a name; a card whose build lies
     elsewhere (the program's own files) has no page to show. */
  const hatSeite = $derived(typeof repo === 'string' && repo.includes('/'))
  const huggingFace = LOGOS.huggingface

  /* The kit of a file folds open under its row: one part per line, with its
     role, folder, size and whether it lies there. Closed until asked. */
  let kitOpen = $state({})
  const ROLLE = {
    modell: 'katalog.bausatz_modell',
    textleser: 'katalog.bausatz_textleser',
    vae: 'katalog.sorte_vae',
  }
  /* What is still to fetch, in GB — or null when a missing part's size is
     not known: a sum without it would be a number too small. */
  const missingGb = (bausatz) => {
    const missing = bausatz.teile.filter((teil) => !teil.da)
    if (missing.some((teil) => teil.groesse_gb == null)) return null
    return Math.round(missing.reduce((summe, teil) => summe + teil.groesse_gb, 0) * 10) / 10
  }

  function seiteOeffnen() {
    window.open(`https://huggingface.co/${repo}`, '_blank')
  }
</script>

<div class="detail">
  <div class="oben">
    <button class="zurueck" onclick={onZurueck} aria-label={t('app.zurueck')} title={t('app.zurueck')}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M15 5 8 12l7 7" />
      </svg>
    </button>
    {#if marke}
      <div class="logo"><svg viewBox={marke.vb} width="26" height="26" aria-hidden="true">{@html marke.html}</svg></div>
    {:else if buchstabe}
      <div class="logo">{buchstabe}</div>
    {/if}
    <div class="wer">
      <div class="name" title={name}>{name}</div>
      {#if unter}<div class="unter">{unter}</div>{/if}
    </div>
    <div class="zeichenreihe">
      {#each plaketten as { text, farbe } (text)}
        <span class="plakette" style={`color:${farbe};border:1px solid ${farbton(farbe, 33)};background:${farbton(farbe, 9)}`}>{text}</span>
      {/each}
      {#each faehigkeiten as f (f)}
        <span class="zeichen" title={t(KANN[f])} style={FAEHIGKEIT_FARBE[f] ? `color:${FAEHIGKEIT_FARBE[f]}` : undefined}><Hauszeichen zeichen={f} groesse="mittel" /></span>
      {/each}
      {#if maschineGb}
        <span class="vram">{t('modell.vram_label')}: {maschineGb} GB</span>
      {/if}
      {#if hatSeite}
        <button class="hf" onclick={seiteOeffnen}>
          <svg viewBox={huggingFace.vb} width="16" height="16" aria-hidden="true">{@html huggingFace.html}</svg>
          {t('editor.quelle_hf')}
        </button>
      {/if}
    </div>
  </div>

  {#if satz}
    <div class="satzlang">{satz}</div>
  {/if}

  {#if zeilen}
    <div class="kopf tafelkopf">{t('katalog.dateien')} <span class="zahl">{zeilen.length}</span></div>
    {#each zeilen as z (z.schluessel)}
      <div class="zeile" class:empfohlen={z.empfohlen}>
        <div class="obere">
          <div class="fwer">
            <div class="fname">{z.name}</div>
            {#if z.satz}<div class="fpasst">{z.satz}</div>{/if}
          </div>
          {#if z.plakette}
            <span class="plakette fplakette" style={`color:${z.plakette.farbe};border:1px solid ${farbton(z.plakette.farbe, 33)};background:${farbton(z.plakette.farbe, 9)}`}>{z.plakette.text}</span>
          {/if}
          {#if z.gb != null}<span class="fgb">{t('modell.gb', { zahl: z.gb })}{#if z.teile > 1}{' · ' + t('modell.teile', { zahl: z.teile })}{/if}</span>{/if}
          {#if z.zustand === 'laedt'}
            <button class="knopf still" onclick={onAbbrechen}>{t('katalog.abbrechen')}</button>
          {:else if z.zustand === 'bereit'}
            <span class="imordner">{t('katalog.im_ordner')}</span>
          {:else}
            <button class="knopf wichtig" onclick={() => onHolen?.(z)} disabled={laedt}>{t('katalog.herunterladen')}</button>
          {/if}
        </div>
        {#if z.bausatz}
          {@const da = z.bausatz.teile.filter((teil) => teil.da).length}
          {@const fehlt = missingGb(z.bausatz)}
          <div class="bausatz">
            <Bausatzkopf open={Boolean(kitOpen[z.schluessel])} there={da} all={z.bausatz.teile.length}
                         rest={fehlt != null && fehlt > 0 ? t('katalog.bausatz_fehlt_gb', { zahl: fehlt }) : ''}
                         onToggle={() => (kitOpen[z.schluessel] = !kitOpen[z.schluessel])} />
            {#if kitOpen[z.schluessel]}
              {#each z.bausatz.teile as teil (teil.rolle + teil.name)}
                <div class="teil">
                  <Leuchtpunkt farbe={teil.da ? 'gruen' : 'still'} groesse={10} />
                  <span class="rolle">{t(ROLLE[teil.rolle])}</span>
                  <div class="fwer">
                    <div class="fname">{teil.name}</div>
                    <div class="fpasst">{teil.ordner ? `${teil.ordner}/` : t('katalog.bausatz_bildordner')}</div>
                  </div>
                  {#if teil.groesse_gb != null}<span class="fgb">{t('modell.gb', { zahl: teil.groesse_gb })}</span>{/if}
                  <span class="teilstand">{teil.da ? t('katalog.im_ordner') : t('katalog.bausatz_fehlt')}</span>
                </div>
              {/each}
            {/if}
          </div>
        {/if}
        {#if z.zustand === 'laedt'}
          <div class="laufbalken">
            <span class="balken"><i style="width:{z.anteil ?? 0}%"></i></span>
            <span class="prozent">{z.anteil ?? 0} %</span>
          </div>
          <div class="laufzahl">{z.text ?? ''}</div>
        {/if}
      </div>
    {/each}
    {#if !zeilen.length}
      <p class="leer">{t('modell.keine_dateien')}</p>
    {/if}
  {:else}
    <p class="leer">{t('modell.dateien_laden')}</p>
  {/if}

</div>

<style>
  .detail {
    max-width: 760px;
    margin: 0 auto;
    padding: 4px 2px;
  }
  .oben {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 14px;
  }
  .zurueck {
    width: 30px;
    height: 30px;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 9px;
    /* Button glass with its fine edge, like every button on glass. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
  }
  .zurueck:hover {
    color: var(--text);
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .logo {
    width: 44px;
    height: 44px;
    flex: none;
    border-radius: 9px;
    color: var(--text-still);
    display: flex;
    align-items: center;
    justify-content: center;
    font: 700 13px var(--schrift);
    background: var(--glass-button);
  }
  .wer {
    min-width: 0;
  }
  /* A long name stays in its line and its block, cut with an ellipsis like
     the line under it; the full name stands in the title. */
  .name {
    font: 600 17px var(--schrift);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .unter {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .zeichenreihe {
    margin-left: auto;
    display: flex;
    gap: 12px;
    align-items: center;
    color: var(--text-leise);
    flex: none;
  }
  .zeichen {
    display: inline-flex;
  }
  .plakette {
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11.5px;
    font-weight: 600;
  }
  /* The kind of a file on its row: the same plaque, kept on one line. */
  .fplakette {
    flex: none;
    white-space: nowrap;
  }
  .vram {
    font: 500 12px var(--schrift);
    color: var(--text-leise);
    white-space: nowrap;
  }
  .hf {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 500 12.5px var(--schrift);
    padding: 6px 12px;
    border-radius: 9px;
    cursor: pointer;
  }
  .hf:hover {
    background: var(--glass-hover);
  }
  .satzlang {
    font-size: 13px;
    color: var(--text-leise);
    line-height: 1.6;
    margin-bottom: 14px;
  }
  .kopf {
    margin: 4px 0 8px 2px;
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .zahl {
    font-weight: 400;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .zeile {
    border-radius: 9px;
    padding: 11px 14px;
    margin-bottom: 4px;
    /* A card on the page: card glass with its fine line; the recommended
       row steps up onto the denser button glass. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .zeile.empfohlen {
    background: var(--glass-button);
  }
  .obere {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .fwer {
    flex: 1;
    min-width: 0;
  }
  .fname {
    font: 500 13px var(--schrift);
    overflow-wrap: anywhere;
  }
  .fpasst {
    font-size: 11px;
    color: var(--text-leise);
    margin-top: 1px;
  }
  .fgb {
    font: 500 12px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .imordner {
    font-size: 12px;
    color: var(--text-still);
    white-space: nowrap;
  }
  /* The kit: under the row's line, its head (Bausatzkopf), and one line per
     part in the same shape as a file. */
  .bausatz {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid var(--linie);
  }
  .teil {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 4px 0;
  }
  .rolle {
    width: 92px;
    flex: none;
    font-size: 11.5px;
    color: var(--text-leise);
  }
  .teilstand {
    width: 64px;
    flex: none;
    text-align: right;
    font-size: 12px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .laufbalken {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 10px 0 4px;
  }
  .balken {
    flex: 1;
    height: 4px;
    border-radius: 9px;
    background: var(--glass-button);
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--blau);
    transition: width 0.3s;
  }
  /* The percentage stands at the end of the bar, in the bar's own line. */
  .prozent {
    font: 500 12.5px var(--schrift);
    color: var(--blau);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .laufzahl {
    font: 400 11.5px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .leer {
    font-size: 12px;
    color: var(--text-still);
    padding: 4px 10px 8px;
  }
  .knopf {
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 500 12.5px var(--schrift);
    padding: 7px 14px;
    border-radius: 9px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.12s, opacity 0.12s, transform 0.08s;
  }
  .knopf:hover {
    background: var(--glass-hover);
  }
  .knopf:active {
    transform: scale(0.975);
  }
  .knopf:disabled {
    opacity: 0.45;
    cursor: default;
  }
  /* The main button is button glass with its fine edge, like the start
     button; only Send stays filled. */
  .knopf.wichtig {
    background: var(--glass-button);
    color: var(--text);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    font-size: 13px;
    padding: 7px 15px;
  }
  .knopf.wichtig:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
</style>
