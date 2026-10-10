<script>
  /* The studio's row of pictures, at the right edge of the surface. On top
     the picture drawing now with its progress and its stop, then the
     waiting ones with their ✕, then the pictures, newest first — of this
     chat or of the whole project. Shut, one tile stays: the picture
     drawing, or else the newest; with no picture at all only the button
     that opens the row stays.

     Above the tiles stands the row's head, built like the zoom above it:
     the house's selection field in glass for "this chat or the whole
     project", and a glass button that folds the row. A chat in no project
     has only its own pictures to show, so its field rests.

     A picture clicked stands in the generation area; "···" on each opens
     the picture menu (StudioPictureMenu.svelte). A picture lies once in the picture folder; it belongs to a chat through
     the message that names it and to a project through its chat. */
  import { untrack } from 'svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import StudioPictureMenu from './StudioPictureMenu.svelte'
  import { api } from '../lib/api.js'
  import { draussen } from '../lib/draussen.js'
  import { chatanzeige } from '../lib/chatanzeige.svelte.js'
  import { pictureProgress, watchPicturePreview, watchPictureProgress } from '../lib/pictureProgress.svelte.js'
  import { chatPictures, startbildWaehlen, werte } from '../lib/studio.svelte.js'
  import { zeichnung } from '../lib/studiozeichnen.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { aktuellerChat, zustand } from '../lib/zustand.svelte.js'

  let offen = $state(true)
  let bereich = $state('chat')
  let projectPictures = $state([])
  const scopes = $derived([
    { wert: 'chat', text: t('studio.dieser_chat') },
    { wert: 'projekt', text: t('studio.ganzes_projekt') },
  ])

  const projekt = $derived(aktuellerChat()?.project_id ?? null)
  const chatId = $derived(chatanzeige.chatId)
  const ofProject = $derived(bereich === 'projekt' && Boolean(projekt))
  /* The chat's pictures are read once for the whole studio
     (lib/studio.svelte.js `chatPictures`); the project's are read here. */
  const bilder = $derived(
    ofProject ? projectPictures : chatPictures.chat === chatId ? chatPictures.names : [],
  )
  const laufend = $derived(zustand.pictureQueue.find((w) => w.running && w.chat_id === chatId) ?? null)
  const wartend = $derived(zustand.pictureQueue.filter((w) => !w.running && w.chat_id === chatId))
  const prozent = $derived(Math.round((pictureProgress.share || 0) * 100))
  /* The glass under the tiles is there only while a tile is: open, every
     tile counts; shut, the one that stays. */
  const hasTiles = $derived(Boolean(laufend || bilder.length || (offen && wartend.length)))

  /* Asked only while a picture of this chat is drawing — its counter, and
     its live preview where the picture is drawn with one. The watch follows
     the picture, not the line: a line rebuilt around the same picture must
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

  /* The project's pictures, read again when the chat, the choice or the
     line changes — a picture finished is a picture more. Only the newest
     answer counts. */
  let anfrage = 0
  async function laden() {
    const nr = ++anfrage
    if (!ofProject) return
    try {
      const antwort = await api.bilderListe({ projekt })
      if (nr === anfrage) projectPictures = antwort.bilder ?? []
    } catch {
      /* The row keeps what it showed. */
    }
  }
  $effect(() => {
    void chatId
    void ofProject
    void projekt
    void zustand.pictureQueue.length
    void zustand.nachrichten.length
    untrack(laden)
  })
  $effect(() => {
    if (!projekt && bereich === 'projekt') bereich = 'chat'
  })
  // Tiles that move take the menu's place away from it: it shuts.
  $effect(() => {
    void bilder
    void laufend
    void wartend.length
    menue = null
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

<div class="gallery" use:draussen={() => (menue = null)}>
  <div class="kopf">
    {#if offen}
      <div class="scope">
        <Auswahlfeld bind:wert={bereich} eintraege={scopes} gesperrt={!projekt}
                     beschriftung={t('studio.bilder')} />
      </div>
    {/if}
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
          {#each bilder as name (name)}
            <div class="kachel bild" class:gewaehlt={werte.startbild === name}>
              <button class="flaeche" onclick={() => startbildWaehlen(name)} title={t('bild.als_eingabe')}
                      aria-label={t('bild.als_eingabe')}>
                <img src={api.bildAdresse(name)} alt="" loading="lazy" draggable="false" />
              </button>
              <button class="mehr" onclick={(e) => menueAuf(name, e)} aria-label="···" aria-haspopup="menu">···</button>
            </div>
          {/each}
        {:else if !laufend && bilder.length}
          <div class="kachel bild">
            <button class="flaeche" onclick={() => startbildWaehlen(bilder[0])} aria-label={t('bild.als_eingabe')}>
              <img src={api.bildAdresse(bilder[0])} alt="" draggable="false" />
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
    /* Wide enough that both entries of the list are read whole, and with
       the button beside it as wide as the zoom above. */
    --scope-field: 160px;
  }
  .kopf {
    flex: none;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .scope {
    width: var(--scope-field);
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
