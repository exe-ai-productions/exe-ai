<script>
  /* The studio's row of pictures, at the right edge of the surface. On top
     the picture drawing now with its progress and its stop, then the
     waiting ones with their ✕, then the pictures the studio drew, newest
     first. Shut, one tile stays: the picture drawing, or else the newest;
     with no picture at all only the button that opens the row stays.

     Above all of them stands the original — the picture that last came
     from outside — with its badge, shut as well as open. A click lays it
     in the area again, with no mask. No such picture, or its file gone: no
     tile.

     Above the tiles stands the row's head: a glass button that folds the
     row, built like the zoom beside it.

     A picture clicked stands in the generation area; "···" on each opens
     the picture menu (StudioPictureMenu.svelte). A picture lies once in the
     picture folder; the studio keeps the list of those it drew
     (app/studio_pictures.py) and belongs to no chat. */
  import Hauszeichen from './Hauszeichen.svelte'
  import StudioPictureMenu from './StudioPictureMenu.svelte'
  import { api } from '../lib/api.js'
  import { draussen } from '../lib/draussen.js'
  import { pictureProgress, watchPicturePreview, watchPictureProgress } from '../lib/pictureProgress.svelte.js'
  import { startbildWaehlen, studioPictures, surface, werte } from '../lib/studio.svelte.js'
  import { rowPictures } from '../lib/studioRow.js'
  import { zeichnung } from '../lib/studiozeichnen.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { reportHeadBottom } from '../lib/noticeStart.js'

  let offen = $state(true)

  /* The studio's pictures are read once for the whole studio
     (lib/studio.svelte.js `studioPictures`). */
  const bilder = $derived(studioPictures.names)
  /* The original's file may be gone (the pictures folder was cleared): its
     tile then does not show. */
  let originalGone = $state('')
  const original = $derived(werte.original && originalGone !== werte.original ? werte.original : '')
  // The line holds the studio's pictures only.
  const laufend = $derived(zustand.pictureQueue.find((w) => w.running) ?? null)
  const wartend = $derived(zustand.pictureQueue.filter((w) => !w.running))
  const prozent = $derived(Math.round((pictureProgress.share || 0) * 100))
  // The studio's pictures the row shows: all of them open, the one that stays shut.
  const row = $derived(rowPictures({ original, names: bilder, open: offen, running: Boolean(laufend) }))
  /* The glass under the tiles is there only while a tile is: the original,
     the picture drawing, a studio's picture, or — open — a waiting one. */
  const hasTiles = $derived(Boolean(original || laufend || bilder.length || (offen && wartend.length)))

  /* Asked only while a picture is drawing — its counter, and its live
     preview where the picture is drawn with one. The watch follows the
     picture, not the line: a line rebuilt around the same picture must
     not end it and start it over. */
  const runningId = $derived(laufend?.id ?? null)
  $effect(() => {
    if (runningId === null) return
    const stopProgress = watchPictureProgress()
    const stopPreview = watchPicturePreview(runningId)
    return () => {
      stopPreview()
      stopProgress()
    }
  })

  // Tiles that move take the menu's place away from it: it shuts.
  $effect(() => {
    void bilder
    void original
    void laufend
    void wartend.length
    menue = null
  })

  /* The notices begin under the studio's bars: the head of this row is the
     lowest of them (the brush bar and the zoom stand above it, on a narrow
     screen the brush bar in a row of its own, still above). */
  let kopfKnoten = $state(null)
  $effect(() => {
    if (!kopfKnoten) return undefined
    return reportHeadBottom(() => [kopfKnoten])
  })

  // --- "···" on a picture --------------------------------------------

  /* The menu stands beside the rail, level with its tile — placed in the
     rail's own layout pixels, which an ancestor zoom keeps apart from the
     measured ones. */
  let menue = $state(null)
  let leisteKnoten = $state(null)
  function menueAuf(name, ereignis) {
    ereignis.stopPropagation()
    const kachel = ereignis.currentTarget.closest('.kachel').getBoundingClientRect()
    const rahmen = leisteKnoten.getBoundingClientRect()
    const faktor = leisteKnoten.offsetWidth ? rahmen.width / leisteKnoten.offsetWidth : 1
    menue = menue?.name === name ? null : { name, top: (kachel.top - rahmen.top) / faktor }
  }
</script>

<div class="gallery" class:unter={surface.brushRow} use:draussen={() => (menue = null)}>
  <div class="kopf" bind:this={kopfKnoten}>
    <button class="step glas" onclick={() => (offen = !offen)}
            aria-label={offen ? t('studio.bilder_zu') : t('studio.bilder_auf')}
            title={offen ? t('studio.bilder_zu') : t('studio.bilder_auf')}>
      <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" stroke-width="1.2"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d={offen ? 'M4.125 2.75L6.875 5.5L4.125 8.25' : 'M6.875 2.75L4.125 5.5L6.875 8.25'} />
      </svg>
    </button>
  </div>

  {#if hasTiles}
    <div class="leiste glas" bind:this={leisteKnoten}>
      <div class="kacheln" onscroll={() => (menue = null)}>
        {#if original}
          <div class="kachel bild" class:gewaehlt={werte.startbild === original}>
            <button class="flaeche" onclick={() => startbildWaehlen(original)} title={t('bild.als_eingabe')}
                    aria-label={t('bild.als_eingabe')}>
              <img src={api.bildAdresse(original)} alt="" draggable="false"
                   onerror={() => (originalGone = original)} />
            </button>
            <span class="schild">{t('studio.original')}</span>
            <button class="mehr" onclick={(e) => menueAuf(original, e)} aria-label="···" aria-haspopup="menu">···</button>
          </div>
          <span class="trenner" aria-hidden="true"></span>
        {/if}
        {#if laufend}
          <div class="kachel lauf">
            {#if pictureProgress.previewUrl}<img src={pictureProgress.previewUrl} alt="" />{/if}
            <span class="lauftext">{prozent} %</span>
            <button class="stopp" onclick={() => zeichnung.stopEins?.(laufend.id)}>{t('bild.stopp')}</button>
            <span class="balken" style:width="{prozent}%"></span>
          </div>
        {/if}
        {#if offen}
          {#each wartend as w (w.id)}
            <div class="kachel wartet">
              <span>{t('bild.wartet')}</span>
              <button class="weg" onclick={() => zeichnung.entfernen?.(w.id)} aria-label={t('bild.entfernen')}
                      title={t('bild.entfernen')}><Hauszeichen zeichen="kreuz" groesse={9} /></button>
            </div>
          {/each}
          {#if laufend || wartend.length}<span class="trenner" aria-hidden="true"></span>{/if}
          {#each row.pictures as name (name)}
            <div class="kachel bild" class:gewaehlt={werte.startbild === name}>
              <button class="flaeche" onclick={() => startbildWaehlen(name)} title={t('bild.als_eingabe')}
                      aria-label={t('bild.als_eingabe')}>
                <img src={api.bildAdresse(name)} alt="" loading="lazy" draggable="false" />
              </button>
              <button class="mehr" onclick={(e) => menueAuf(name, e)} aria-label="···" aria-haspopup="menu">···</button>
            </div>
          {/each}
        {:else if row.pictures.length}
          <div class="kachel bild">
            <button class="flaeche" onclick={() => startbildWaehlen(row.pictures[0])} aria-label={t('bild.als_eingabe')}>
              <img src={api.bildAdresse(row.pictures[0])} alt="" draggable="false" />
            </button>
          </div>
        {/if}
      </div>

      {#if menue}
        <div class="menueplatz" style="top:{menue.top}px">
          <StudioPictureMenu name={menue.name} zu={() => (menue = null)} />
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .glas {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    backdrop-filter: blur(14px);
  }
  /* The head and, under it, the tiles — both against the right edge. */
  .gallery {
    position: absolute;
    top: 62px;
    right: 14px;
    max-height: calc(100% - 242px);
    z-index: 3;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
  }
  /* Under the brush bar, which has a row of its own on a surface too
     narrow for it between the tools and the zoom. */
  .gallery.unter {
    top: 96px;
    max-height: calc(100% - 290px);
  }
  .kopf {
    flex: none;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  /* The button that folds the row: the size of the zoom's steps. */
  .step {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: none;
    color: var(--text);
    cursor: pointer;
  }
  .step:hover {
    background: var(--glass-hover);
  }
  .leiste {
    position: relative;
    min-height: 0;
    width: 76px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    padding: 8px;
  }
  .kacheln {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .kachel {
    position: relative;
    flex: none;
    width: 60px;
    height: 60px;
    border-radius: 9px;
    overflow: hidden;
  }
  .kachel img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .kachel.bild .flaeche {
    width: 100%;
    height: 100%;
    padding: 0;
    border: none;
    background: var(--glass-button);
    cursor: pointer;
  }
  .kachel.bild.gewaehlt {
    box-shadow: 0 0 0 2px var(--text);
  }
  .schild {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 1px 0;
    background: color-mix(in srgb, var(--bg) 75%, transparent);
    color: var(--text);
    font: 600 10px/14px var(--schrift);
    text-align: center;
    pointer-events: none;
  }
  .kachel .mehr {
    position: absolute;
    top: 3px;
    right: 3px;
    height: 16px;
    padding: 0 4px;
    border: none;
    border-radius: 9px;
    background: color-mix(in srgb, var(--bg) 75%, transparent);
    color: var(--text);
    font: 600 10px/16px var(--schrift);
    opacity: 0;
    cursor: pointer;
  }
  .kachel:hover .mehr,
  .kachel .mehr:focus-visible {
    opacity: 1;
  }
  /* A touch screen has no hover: the menu's button stays in sight. */
  @media (hover: none), (any-pointer: coarse) {
    .kachel .mehr {
      opacity: 1;
    }
  }
  .kachel.lauf {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    background: color-mix(in srgb, var(--text) 45%, var(--bg));
    color: var(--bg);
    font: 600 11px/14px var(--schrift);
  }
  .kachel.lauf img {
    position: absolute;
    inset: 0;
    opacity: 0.5;
  }
  .lauftext,
  .stopp {
    position: relative;
  }
  .stopp {
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: 400 11px/14px var(--schrift);
    cursor: pointer;
  }
  .balken {
    position: absolute;
    left: 0;
    bottom: 0;
    height: 3px;
    background: var(--blau);
  }
  .kachel.wartet {
    display: grid;
    place-items: center;
    border: 1px dashed var(--glass-card-line);
    color: var(--text-leise);
    font: 400 10px/12px var(--schrift);
  }
  .weg {
    position: absolute;
    top: 3px;
    right: 3px;
    display: grid;
    place-items: center;
    width: 16px;
    height: 16px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .weg:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .trenner {
    flex: none;
    height: 1px;
    background: var(--glass-card-line);
  }
  .menueplatz {
    position: absolute;
    right: calc(100% + 6px);
    z-index: 30;
  }
</style>
