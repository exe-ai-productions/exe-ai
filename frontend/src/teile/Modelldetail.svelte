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
  import OwnerMark from './OwnerMark.svelte'
  import DownloadRow from './DownloadRow.svelte'
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatGb } from '../lib/numberDisplay.js'
  import { LOGOS } from '../lib/logos.js'
  import { FAEHIGKEIT_FARBE, farbton } from '../lib/modellempfehlungen.js'

  let {
    name,
    unter = '',
    /* The logo the caller has chosen (a catalogue card's maker) — or, for a
       hit or an accessory, `owner`: the owner's house logo, else the round
       picture on Hugging Face, else the letter. */
    marke = null,
    owner = '',
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
    onDequeue,
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
    {#if marke || owner || buchstabe}
      <OwnerMark mark={marke} {owner} letter={buchstabe} size={30} />
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
        <span class="vram">{t('modell.vram_label')}: {formatGb(maschineGb, texte.sprache)} GB</span>
      {/if}
      {#if hatSeite}
        <button class="hf" onclick={seiteOeffnen}
                title={t('editor.quelle_hf')} aria-label={t('editor.quelle_hf')}>
          <svg viewBox={huggingFace.vb} width="26" height="26" aria-hidden="true">{@html huggingFace.html}</svg>
        </button>
      {/if}
    </div>
  </div>

  {#if satz}
    <div class="satzlang">{satz}</div>
  {/if}

  {#if zeilen}
    <div class="kopf tafelkopf">{t('katalog.dateien')} <span class="zahl">{zeilen.length}</span></div>
    <div class="files">
    {#each zeilen as z (z.schluessel)}
      <div class="zeile" class:empfohlen={z.empfohlen} class:running={z.zustand === 'laedt'}>
        <div class="obere">
          <div class="fwer">
            <div class="fname">{z.name}</div>
            {#if z.satz}<div class="fpasst">{z.satz}</div>{/if}
          </div>
          {#if z.plakette}
            <span class="plakette fplakette" style={`color:${z.plakette.farbe};border:1px solid ${farbton(z.plakette.farbe, 33)};background:${farbton(z.plakette.farbe, 9)}`}>{z.plakette.text}</span>
          {/if}
          {#if z.gb != null && z.zustand !== 'laedt'}<span class="fgb">{t('modell.gb', { zahl: formatGb(z.gb, texte.sprache) })}{#if z.teile > 1}{' · ' + t('modell.teile', { zahl: z.teile })}{/if}</span>{/if}
          <DownloadRow status={z.zustand} percent={z.anteil ?? 0} amounts={z.text ?? ''}
                       disabled={laedt} onDownload={() => onHolen?.(z)}
                       onCancel={onAbbrechen} onDequeue={() => onDequeue?.(z)} />
        </div>
        {#if z.bausatz}
          {@const da = z.bausatz.teile.filter((teil) => teil.da).length}
          {@const fehlt = missingGb(z.bausatz)}
          <div class="bausatz">
            <Bausatzkopf open={Boolean(kitOpen[z.schluessel])} there={da} all={z.bausatz.teile.length}
                         rest={fehlt != null && fehlt > 0 ? t('katalog.bausatz_fehlt_gb', { zahl: formatGb(fehlt, texte.sprache) }) : ''}
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
                  {#if teil.groesse_gb != null}<span class="fgb">{t('modell.gb', { zahl: formatGb(teil.groesse_gb, texte.sprache) })}</span>{/if}
                  <span class="teilstand">{teil.da ? t('katalog.im_ordner') : t('katalog.bausatz_fehlt')}</span>
                </div>
              {/each}
            {/if}
          </div>
        {/if}
      </div>
    {/each}
    </div>
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
    width: 34px;
    height: 34px;
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
  /* The Hugging Face mark alone, no tile and no word: one click opens the
     repository's page. */
  .hf {
    width: 32px;
    height: 32px;
    flex: none;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    cursor: pointer;
  }
  .hf:hover {
    background: color-mix(in srgb, var(--text) 8%, transparent);
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
  /* The files stand in one card, a hairline between the rows. */
  .files {
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    overflow: hidden;
  }
  .zeile {
    padding: 14px 16px;
  }
  .zeile + .zeile {
    border-top: 1px solid var(--linie);
  }
  /* The recommended row steps up onto the denser button glass. */
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
  /* A running row gives the room behind the name to its bar. */
  .zeile.running .fwer {
    flex: 0 1 auto;
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
  .leer {
    font-size: 12px;
    color: var(--text-still);
    padding: 4px 10px 8px;
  }
</style>
