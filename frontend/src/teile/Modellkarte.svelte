<script>
  /* One card in the catalogue gallery — a model, not a file.

     Purely a face: the parent (Katalog) knows what is downloaded, what is
     fetching and what the machine holds, and hands this card its state and
     the buttons' actions. The card draws the name, the maker, the one-line
     description, the capability signs, the facts, and — depending on the
     state — a download sign button, a progress bar with a cancel sign
     button, or the green tick with "downloaded".

     The machine plaque speaks only when something is off: a card that fits
     stays silent, one that does not names the machine it needs. A plaque on
     every card would say nothing. It is deliberately colourless either way:
     a fit is a fact, not a state, so it wears brightness and a border,
     never one of the four state colours. */
  import Hauszeichen from './Hauszeichen.svelte'
  import OwnerMark from './OwnerMark.svelte'
  import DownloadRow from './DownloadRow.svelte'
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatGb, formatNumber } from '../lib/numberDisplay.js'
  import { familyOf, loadImageFamilies } from '../lib/imageFamilies.svelte.js'
  import { LOGOS, avatarOwnerOf } from '../lib/logos.js'
  import { brauchtMaschine, farbton, FAEHIGKEIT_FARBE, SORTE_FARBE, SORTE_LABEL as SORTE } from '../lib/modellempfehlungen.js'

  let {
    karte,
    fassung,
    passt = false,
    maschineGb = null,
    status = 'neu', // 'neu' | 'laedt' | 'wartet' | 'bereit'
    fortschritt = null, // { anteil: 0..100, bytes } while laedt
    onOeffnen,
    onDownload,
    onCancel,
    onDequeue,
  } = $props()

  /* An image card has no context window and no row of builds — it is one
     file of a class. Guarded so the chat facts (context, build count) never
     read NaN on it. */
  /* Whole thousands; a context under one thousand (512 tokens) is written
     as a fraction, or it would round up to a thousand it does not have. */
  const kontextK = $derived(
    !karte.kontext ? 0
    : karte.kontext < 1024 ? formatNumber(karte.kontext / 1024, 1, texte.sprache)
    : Math.round(karte.kontext / 1024),
  )
  const bauzahl = $derived(karte.fassungen?.length ?? 1)
  const marke = $derived(karte.marke ? LOGOS[karte.marke] : null)
  /* The size as the page writes it: the decimal sign of the language, two
     digits under 1 GB, one from 1 GB. */
  const size = $derived(t('modell.gb', { zahl: formatGb(fassung.groesse, texte.sprache) }))
  /* An image card's family by the name the service's family table gives it
     (app/image_families.py) — no family list of its own here. */
  loadImageFamilies()
  const familyName = $derived(familyOf(karte.klasse)?.label ?? karte.klasse ?? '')
  /* An accessory shows its kind instead of a class — that is the one thing
     that tells a VAE from a LoRA from a face detector at a glance. Its labels
     come from the shared SORTE_LABEL map (imported as SORTE). */

  /* Full keys in a map, not built inside t(): a composed t('x_'+f) would
     read as a broken key to the interface-text check. */
  const KANN = {
    werkzeug: 'katalog.kann_winkel',
    auge: 'katalog.kann_auge',
    gluehbirne: 'katalog.kann_gluehbirne',
    blitz: 'katalog.kann_blitz',
  }

  /* The accessory's tag colour, used for its corner pill and logo. */
  const farbe = $derived(SORTE_FARBE[karte.sorte] ?? 'var(--text-leise)')

  /* How high the state row of a chat card is: read off the row itself (the
     one in the foot, or the one under it while it loads), so the room a
     card keeps for the loading row is as high as that row and follows it
     when its signs change size. */
  let rowHeight = $state(0)
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="karte"
  class:zub={karte.zubehoer}
  role="button"
  tabindex="0"
  onclick={onOeffnen}
  onkeydown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) onOeffnen?.() }}
>
  {#if karte.zubehoer}
    <!-- The compact accessory card: the maker's round picture, the name with
         its class as plain text, the maker under it; the foot holds the kind
         in its colour, the size and the download sign button. No VRAM plaque
         (a companion has no memory cost of its own). -->
    <div class="oben">
      <OwnerMark owner={avatarOwnerOf(karte)} mark={marke} letter={karte.logo} size={30} />
      <div class="wer">
        <div class="zname">
          {karte.nameKey ? t(karte.nameKey) : karte.name}
          {#if karte.klasse}
            <!-- Class-bound accessories (LoRA, VAE) name their class in full
                 text colour — an SD-1.5 file on an XL model was a real mishap,
                 so the answer stands beside the name, not in fine print. -->
            <span class="zklasse">{familyName}</span>
          {/if}
        </div>
        <div class="von">{karte.von}</div>
      </div>
    </div>
    <div class="fuss">
      {#if status === 'laedt'}
        {@render loading(true)}
      {:else if status === 'wartet'}
        <!-- Too narrow for the kind and the size beside the state: the column
             names the kind, and the size comes back with the button. -->
        <span class="rest"></span>
        {@render stateSlot()}
      {:else}
        <span class="zpille" style={`color:${farbe};border-color:${farbton(farbe, 33)};background:${farbton(farbe, 9)}`}>
          {t(SORTE[karte.sorte] ?? 'katalog.sorte_vae')}
        </span>
        <span class="zgb">{size}</span>
        {@render stateSlot()}
      {/if}
    </div>
  {:else}
  {#if !passt}
    <span class="plakette">{t('katalog.braucht_maschine', { gb: formatGb(brauchtMaschine(fassung), texte.sprache) })}</span>
  {/if}

  <div class="oben">
    <OwnerMark mark={marke} letter={karte.logo} size={30} />
    <div class="wer">
      <div class="name">{karte.name}</div>
      <div class="von">{karte.von}</div>
    </div>
  </div>

  <div class="satz" title={t(karte.satz)}>{t(karte.satz)}</div>

  <div class="zeichenreihe">
    {#if karte.bild}
      <!-- An image model shows the one sign that decides how it draws: its
           class, which sets the resolution it opens at. -->
      {#if familyName}<span class="klassepille">{familyName}</span>{/if}
    {:else}
      {#each karte.faehigkeiten as f (f)}
        <span class="zeichen" title={t(KANN[f])} style={FAEHIGKEIT_FARBE[f] ? `color:${FAEHIGKEIT_FARBE[f]}` : undefined}><Hauszeichen zeichen={f} groesse="mittel" /></span>
      {/each}
    {/if}
  </div>

  <!-- The room of the loading row, kept free over the line while nothing
       loads: a card does not grow when its download starts. -->
  {#if status !== 'laedt'}
    <div class="load-room" style:height={rowHeight ? `${rowHeight}px` : undefined} aria-hidden="true"></div>
  {/if}

  <div class="unten">
    <div class="fuss">
      <div class="fakten">
        <span>{size}</span>
        {#if karte.bild}
          <span>·</span>
          <span>{t('katalog.einzeldatei')}</span>
        {:else}
          <span>·</span>
          <span>{t('katalog.n_kontext', { n: kontextK })}</span>
          <span>·</span>
          <span>{bauzahl === 1 ? t('katalog.bau_eins') : t('katalog.bau_mehr', { n: bauzahl })}</span>
        {/if}
      </div>
      {#if status !== 'laedt'}
        <div class="slot" bind:clientHeight={rowHeight}>{@render stateSlot()}</div>
      {/if}
    </div>
    {#if status === 'laedt'}
      <!-- The facts stay; the loading row stands under them, its lower edge
           where the foot of a card at rest ends. -->
      <div class="lauf" bind:clientHeight={rowHeight}>{@render loading(false)}</div>
    {/if}
  </div>
  {/if}
</div>

<!-- The state sits at the foot's right end, where the download sign button
     stands: that button, "Waiting" with its cross, or the green tick alone.
     While a chat card loads, its facts stay and the bar, the percentage and
     "loaded / total GB" with the cancel cross stand in one row under them,
     in the room the card keeps free for it, so a card keeps its size in
     every state; the speed stands on the model page and the downloads page.
     An accessory card is too narrow for the amounts, takes the loading row
     in its foot and keeps the amounts in the tooltip. -->
{#snippet stateSlot()}
  <DownloadRow {status} sealed onDownload={onDownload} onDequeue={onDequeue} />
{/snippet}

{#snippet loading(compact)}
  <DownloadRow {status} {compact} percent={fortschritt?.anteil ?? 0} amounts={fortschritt?.bytes ?? ''}
               onCancel={onCancel} />
{/snippet}

<style>
  .karte {
    position: relative;
    /* A card on the page: card glass with its fine line. */
    border: 1px solid var(--glass-card-line);
    border-radius: 9px;
    background: var(--glass-card);
    padding: 16px 16px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }
  .karte:hover {
    background: color-mix(in srgb, var(--text) 3%, var(--glass-card));
  }

  /* The compact accessory card: tighter, the kind as a coloured pill in
     the foot and the size as a bright value in even figures. */
  .karte.zub {
    gap: 10px;
    padding: 12px 13px;
  }
  .zpille {
    flex: none;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    border: 1px solid;
    border-radius: 9px;
    padding: 2px 9px;
    white-space: nowrap;
  }
  .zname {
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The class of a class-bound accessory — plain text in the full text
     colour, so the SD 1.5 / SDXL question is answered before anything is
     downloaded. */
  .zklasse {
    margin-left: 6px;
    font: 500 11.5px var(--schrift);
    color: var(--text);
  }
  /* The size stands out as a technical value: brighter, bolder, even
     figures. */
  .rest {
    flex: 1;
  }
  .zgb {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-leise);
    font-family: var(--schrift);
    letter-spacing: normal;
    margin-right: auto;
    font-variant-numeric: tabular-nums;
  }
  /* Colourless on purpose: a fit is a fact, so it carries brightness and a
     filled ground, not a state colour. */
  .plakette {
    position: absolute;
    top: -9px;
    right: 12px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--linie);
    border: none;
    border-radius: 9px;
    padding: 2px 10px;
    font: 700 10.5px var(--schrift);
    color: var(--text-leise);
  }
  .oben {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .wer {
    min-width: 0;
  }
  .name {
    font: 600 16px var(--schrift);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .von {
    font-size: 11.5px;
    color: var(--text-still);
    margin-top: 1px;
  }
  .karte:not(.zub) .von {
    font-size: 12px;
    margin-top: 2px;
  }
  /* Two lines, a longer sentence ends with an ellipsis (the whole of it is
     the tooltip), and a short one keeps the room of two, so the tiles of one
     group stay one size. */
  .satz {
    font-size: 13px;
    color: var(--text-leise);
    line-height: 1.45;
    min-height: 2.9em;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }
  /* A fixed height, with signs or without: the cards of every tab stand one
     size, whether the model has a sign to show or not. */
  .zeichenreihe {
    display: flex;
    gap: 9px;
    align-items: center;
    height: 20px;
    flex: none;
    color: var(--text-leise);
  }
  .zeichen {
    display: inline-flex;
  }
  /* The image model's class, worn as a quiet pill — a fact about the model,
     so it carries a filled ground, not a state colour. */
  .klassepille {
    border: 1px solid var(--linie);
    border-radius: 9px;
    padding: 2px 10px;
    font: 600 11px var(--schrift);
    color: var(--text-leise);
    background: var(--glass-button);
  }
  /* One line of the foot's height in every state: beside a waiting card's
     "Waiting" and its cross the facts keep to one line instead of wrapping
     into a second, and give way with an ellipsis where the card is too
     narrow, never cut off mid-word. */
  .fakten {
    flex: 1;
    min-width: 0;
    height: 26px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font: 400 12px/26px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .fakten > span + span {
    margin-left: 10px;
  }
  /* The foot sinks to the card's bottom edge: the grid stretches every card
     of a row to one height, and the signs then stand on one line. On a chat
     card a hairline stands over the facts. */
  .fuss {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: auto;
    min-height: 26px;
  }
  /* The chat card's bottom: the foot and, while it loads, the loading row
     under it, together sunk to the card's bottom edge. */
  .unten {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: auto;
  }
  .unten .fuss {
    margin-top: 0;
    border-top: 1px solid var(--linie);
    padding-top: 10px;
  }
  .slot {
    display: flex;
    flex: none;
  }
  .lauf {
    display: flex;
  }
</style>
