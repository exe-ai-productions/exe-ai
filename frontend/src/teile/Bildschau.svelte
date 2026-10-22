<script>
  /* The reader: one picture, one document or one report, alone in the
     middle over the darkened window. Every picture and every document the
     program shows opens here (lib/bildschau.svelte.js says from where).

     Three buttons float at the top right, one size: the folder the file
     lives in (only when there is a named one), the download, and close. The
     name stands small under the picture or the page, where the file came
     from beside it. It closes with the cross, Escape, or a click beside the
     picture or the page.

     It hangs at the top of the program, never inside the message or the
     panel that owns the file: an overlay has to cover everything, and
     inside the message list it ended up under the sidebar. Plain HTML and
     CSS — it behaves the same on every system. */
  import { bildschau, bildZeigen, closeReader } from '../lib/bildschau.svelte.js'
  import { bilderVon, nachbar, ohneAbfrage, reiheMit, stelleIn } from '../lib/bildreihe.js'
  import { gestures } from '../lib/pictureGesturesAction.js'
  import { openPictureMenu } from '../lib/pictureMenu.svelte.js'
  import { studio, studioPictures } from '../lib/studio.svelte.js'
  import { isVideo } from '../lib/media.js'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, nachrichtenAnzeige } from '../lib/zustand.svelte.js'
  import { codeKopierKlick, dateiTeile } from '../lib/markdown.js'
  import {
    dateiFakten, dateiHerunterladen, dateizeichen, fileKind, saveFromAddress, svgAddress,
  } from '../lib/dateiarten.js'
  import Dateikarte from './Dateikarte.svelte'
  import FileContent from './FileContent.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import PdfFrame from './PdfFrame.svelte'
  import PictureSheet from '../phone/studio/PictureSheet.svelte'

  /* A page's text, fetched once per opened file; an answer that comes back
     after another file was opened is dropped. */
  let text = $state(null)
  let loading = $state(false)
  let failure = $state(null)
  let preview = $state('')
  let opened = 0
  $effect(() => {
    if (!bildschau.offen || bildschau.kind !== 'page') return
    /* Only the reader's own fields are read here: reading `text` or
       `preview` back would make the answer that fills them start the next
       fetch. */
    const number = ++opened
    const startText = bildschau.text
    const startPreview = bildschau.preview
    text = startText
    preview = startPreview
    failure = null
    loading = false
    const loadText = bildschau.loadText
    if (startText == null && loadText) {
      loading = true
      Promise.resolve()
        .then(loadText)
        .then((value) => { if (number === opened) text = value })
        .catch((error) => { if (number === opened) failure = String(error?.message || error) })
        .finally(() => { if (number === opened) loading = false })
    }
    const loadPreview = bildschau.loadPreview
    if (!startPreview && loadPreview) {
      Promise.resolve()
        .then(loadPreview)
        .then((value) => { if (number === opened && value) preview = value })
        .catch(() => {})
    }
  })

  /* Set the way the rail beside the chat sets it: Markdown drawn by the
     renderer the chat itself uses, a written file in a known source format
     with line numbers and colour, everything else as prose — numbering
     prose would say something untrue about it. */
  const MARKDOWN = new Set(['md', 'markdown'])
  const isMarkdown = $derived(MARKDOWN.has(String(bildschau.language ?? '').toLowerCase()))
  const info = $derived(fileKind(bildschau.language))
  /* A drawing is shown as a picture of its text. */
  const isSvg = $derived(String(bildschau.language ?? '').toLowerCase() === 'svg')
  /* Code, and the source of a document: colours and a number on every line,
     through the component the rail shares. Plain text stays text. */
  const isCode = $derived(
    info?.kind === 'code' || (info?.kind === 'doc' && !isMarkdown && !isSvg),
  )
  const isPlainText = $derived(info?.kind === 'text')

  const report = $derived(bildschau.kind === 'report' ? bildschau.report : null)
  /* The dot at the end of the head: green for a report, red for a run that
     broke, a quiet grey for every other ending. */
  const dotColour = $derived(
    report?.state === 'gescheitert' ? 'rot' : report?.state === 'fertig' ? 'gruen' : 'still',
  )

  /* The task in the head of a report stands at most two lines tall; a longer
     one has a fold under it that opens the whole task with its paragraphs.
     Every opening of a report starts folded. `taskCut` is what the measure
     says about the folded text: cut or not. */
  let taskOpen = $state(false)
  let taskCut = $state(false)
  let taskNode = $state(null)
  $effect(() => {
    void bildschau.offen
    void report
    taskOpen = false
  })
  $effect(() => {
    if (!taskNode) {
      taskCut = false
      return undefined
    }
    const node = taskNode
    /* Read so a new report is measured again, also where its folded text
       happens to be as tall as the last one's. */
    void report
    const measure = () => {
      if (!taskOpen) taskCut = node.scrollHeight > node.clientHeight + 1
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const watcher = new ResizeObserver(measure)
    watcher.observe(node)
    return () => watcher.disconnect()
  })

  /* Escape closes the reader and nothing under it: heard first, on the way
     down, and kept from the shortcuts that would close a page too. */
  function key(event) {
    if (!bildschau.offen || event.key !== 'Escape') return
    event.stopPropagation()
    event.preventDefault()
    closeReader()
  }

  /* In the shell the PDF viewer is a window part of its own: Escape pressed
     with the focus inside it never reaches this page. The shell hears it
     there and says so; an open reader closes on it, as on every other
     Escape. In a browser there is no shell, and nothing is listened for. */
  $effect(() => {
    const huelle = typeof window !== 'undefined' ? window.exeHuelle : null
    if (!huelle || typeof huelle.aufBetrachterEscape !== 'function') return undefined
    return huelle.aufBetrachterEscape(() => {
      if (bildschau.offen) closeReader()
    })
  })

  async function openFolder() {
    try {
      await api.speicherortOeffnen(bildschau.folder)
    } catch (error) {
      melde(error.message || t('fehler.allgemein'), 'fehler')
    }
  }

  async function download() {
    if (bildschau.download) {
      await bildschau.download()
      return
    }
    if (report) {
      // A script's output is plain text, an agent's report is markdown.
      const [ending, type] = report.plain ? ['txt', 'text/plain'] : ['md', 'text/markdown']
      dateiHerunterladen(`${report.name || 'report'}.${ending}`, report.text ?? '', type)
      return
    }
    saveFromAddress(bildschau.name, bildschau.adresse)
  }

  /* A click on a code block's copy sign in a report copies the block. */
  function copyCode(event) {
    codeKopierKlick(event, () => melde(t('nachricht.code_kopiert'), 'erfolg'))
  }

  /* The reader takes the focus when it opens, so the keys work in it and
     not in the controls under the veil. */
  function takeFocus(node) {
    node.focus()
  }

  /* The pictures of the pictures folder, read when a picture of that folder
     is opened: the reader is opened from the folder's tiles too, which carry
     no row of their own. */
  let folderNames = $state([])
  $effect(() => {
    if (!bildschau.offen || bildschau.kind !== 'picture' || bildschau.folder !== 'images') return
    let current = true
    api.bilderListe().then((answer) => { if (current) folderNames = answer.bilder ?? [] }).catch(() => {})
    return () => { current = false }
  })

  /* The pictures this one can be swiped to: those of the open chat, those of
     the studio's gallery or those of the pictures folder. The row of the
     place it was opened from comes first, so a picture that two places
     hold is stepped through where the person is. */
  const row = $derived.by(() => {
    if (!bildschau.offen || bildschau.kind !== 'picture') return []
    const chat = (nachrichtenAnzeige() ?? []).flatMap(bilderVon).map((name) => api.bildAdresse(name))
    const gallery = studioPictures.names.map((name) => api.bildAdresse(name))
    const folder = folderNames.map((name) => api.bildAdresse(name))
    const rows = bildschau.folder === 'images' ? [folder, chat, gallery] : studio.offen ? [gallery, chat, folder] : [chat, gallery, folder]
    return reiheMit(bildschau.adresse, rows)
  })
  const place = $derived(stelleIn(row, bildschau.adresse))

  /* What the fingers do with the picture (lib/pictureGestures.js): a swipe
     to the side steps through the row, a swipe down closes the reader, two
     fingers zoom, a double tap goes to the picture's own size and back, a
     long press asks for its menu. Zoomed, one finger moves the picture. A
     video keeps its own controls and takes none of this. */
  let view = $state({ zoom: 1, x: 0, y: 0 })
  let pictureNode = $state(null)
  /* The zoom belongs to the picture shown and to the reader being open: a new
     picture, or the reader opened again, starts whole. */
  $effect(() => {
    void bildschau.adresse
    void bildschau.offen
    view = { zoom: 1, x: 0, y: 0 }
  })
  const gestureOptions = $derived({
    swipe: true,
    resetKey: bildschau.adresse,
    natural: () => (pictureNode ? { w: pictureNode.naturalWidth, h: pictureNode.naturalHeight } : null),
    shown: () => (pictureNode ? { w: pictureNode.clientWidth } : null),
    onview: (next) => (view = next),
    onswipe: (step) => {
      const next = row.length > 1 ? nachbar(row, bildschau.adresse, step) : null
      if (next) bildZeigen(next, { folder: bildschau.folder })
    },
    onswipedown: closeReader,
    onlong: () => {
      // The menu is the phone's sheet; only a picture of the pictures folder has one.
      if (!document.documentElement.hasAttribute('data-phone')) return
      const path = ohneAbfrage(bildschau.adresse)
      if (path.includes('/images/')) openPictureMenu(decodeURIComponent(path.split('/').pop()), true)
    },
  })

  /* A click on the darkened ground — beside the picture or the page —
     closes; a click on what is shown does not. */
  function beside(event) {
    if (event.target === event.currentTarget) closeReader()
  }
</script>

<svelte:window onkeydowncapture={key} />

{#if bildschau.offen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="reader" role="dialog" aria-modal="true" aria-label={bildschau.name} tabindex="-1"
       use:takeFocus onclick={beside}>
    <div class="floating">
      {#if bildschau.folder}
        <button class="sign" onclick={openFolder}
                title={t('speicherorte.oeffnen')} aria-label={t('speicherorte.oeffnen')}>
          <Hauszeichen zeichen="ordner" groesse={20} />
        </button>
      {/if}
      <button class="sign" onclick={download}
              title={t('datei.herunterladen')} aria-label={t('datei.herunterladen')}>
        <Hauszeichen zeichen="download" groesse={20} />
      </button>
      <button class="sign" onclick={closeReader} title={t('app.schliessen')} aria-label={t('app.schliessen')}>
        <Hauszeichen zeichen="kreuz" groesse={20} />
      </button>
    </div>

    {#if bildschau.kind === 'picture'}
      {#if bildschau.mediaKind}
        <!-- A clip or a sound handed in as a file: the player with its own
             controls, not starting by itself (the studio's own clips below
             keep their way). -->
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="stage" onclick={beside}>
          <div class="media">
            <FileContent kind={bildschau.mediaKind} address={bildschau.adresse} name={bildschau.name} />
          </div>
        </div>
      {:else if isVideo(bildschau.adresse)}
        <!-- A video plays here, with its own controls; a touch that begins on it
             is its own, the ground around it hears the swipes. -->
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="stage" onclick={beside} use:gestures={gestureOptions}>
          <!-- svelte-ignore a11y_media_has_caption -->
          <video class="picture" src={bildschau.adresse} controls autoplay loop playsinline></video>
        </div>
      {:else}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="stage" onclick={beside} use:gestures={gestureOptions}>
          <img class="picture" src={bildschau.adresse} alt={bildschau.name} bind:this={pictureNode}
               draggable="false"
               style:transform={view.zoom > 1.001 ? `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` : null} />
        </div>
      {/if}
    {:else if report}
      <div class="page">
        <div class="head">
          <span class="tile" style:--agentfarbe={report.colour || null} aria-hidden="true">
            {(report.agent || '?').slice(0, 1).toUpperCase()}
          </span>
          <span class="middle">
            <span class="task" class:folded={!taskOpen} bind:this={taskNode}>{report.task}</span>
            {#if taskCut || taskOpen}
              <button class="fold" class:open={taskOpen} aria-expanded={taskOpen}
                      aria-label={report.task} onclick={() => (taskOpen = !taskOpen)}>
                <span class="fold-sign"><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
              </button>
            {/if}
            <span class="who">
              <span class="agent" style={report.colour ? `color:${report.colour}` : ''}>{report.agent}</span>
              {#if report.time}
                <span class="divider"></span>
                <span class="time">{report.time}</span>
              {/if}
            </span>
          </span>
          <span class="dotbox"><Leuchtpunkt farbe={dotColour} groesse={9} /></span>
        </div>
        {#if report.chain}
          <p class="chain">↳ {report.chain}</p>
        {/if}
        {#if report.reason}
          <p class="reason" class:broke={report.state === 'gescheitert'}>
            {#if report.timedOut}
              <span class="reasonsign"><Hauszeichen zeichen="stopwatch" groesse={16} /></span>
            {/if}
            <span>{report.reason}</span>
          </p>
        {/if}
        {#if report.plain}
          <!-- What a script wrote is not markdown: its lines stand as it
               wrote them, not folded into one by the markdown reader. -->
          <div class="body"><p class="prose">{report.text ?? ''}</p></div>
        {:else}
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
          <div class="body berichttext" onclick={copyCode}>
            {#each dateiTeile(report.text ?? '') as piece, i (i)}
              {#if piece.art === 'html'}
                {@html piece.wert}
              {:else if piece.wert}
                <Dateikarte
                  zeichenHtml={dateizeichen(piece.wert.art)}
                  name={piece.wert.name}
                  fakten={report.facts?.(piece.wert) ?? ''}
                  sprache={piece.wert.art}
                  inhalt={piece.wert.inhalt}
                />
              {/if}
            {/each}
          </div>
        {/if}
      </div>
    {:else if bildschau.mediaKind}
      <!-- An Office file the page draws itself from its address: the sheet
           is its holder, as for a PDF below. -->
      <div class="page framed">
        <FileContent kind={bildschau.mediaKind} address={bildschau.adresse} name={bildschau.name} />
      </div>
    {:else if bildschau.framed}
      <!-- A file the page draws itself (pdf.js): its pages, one under the
           other, fitted to the width of the sheet (PdfFrame.svelte). -->
      <div class="page framed">
        <PdfFrame address={bildschau.adresse} title={bildschau.name} />
      </div>
    {:else}
      <div class="page" class:pictured={text == null && !loading && !failure}>
        {#if loading}
          <p class="quiet">{t('nachricht.dokument_liest')}</p>
        {:else if failure}
          <p class="failure">{failure}</p>
        {:else if text != null && isSvg}
          <FileContent kind="image" address={svgAddress(text)} name={bildschau.name} />
        {:else if text != null && isCode}
          <FileContent kind="code" language={info.language} text={text} />
        {:else if text != null && isPlainText}
          <FileContent kind="text" text={text} />
        {:else if text != null && isMarkdown}
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
          <div class="body berichttext" onclick={copyCode}>
            {#each dateiTeile(text) as piece, i (i)}
              {#if piece.art === 'html'}
                {@html piece.wert}
              {:else if piece.wert}
                <!-- A file inside the file: its card, as in an answer. -->
                <Dateikarte
                  zeichenHtml={dateizeichen(piece.wert.art)}
                  name={piece.wert.name}
                  fakten={dateiFakten(piece.wert)}
                  sprache={piece.wert.art}
                  inhalt={piece.wert.inhalt}
                />
              {/if}
            {/each}
          </div>
        {:else if text != null}
          <p class="prose">{text}</p>
        {:else if preview}
          <img class="shell" src={preview} alt={bildschau.name} />
        {:else}
          <span class="pagesign"><Hauszeichen zeichen="dokument_zeilen" groesse={64} /></span>
        {/if}
      </div>
    {/if}

    <div class="caption">
      <span class="name">{bildschau.name}</span>
      {#if place.von > 1}<span class="origin">{place.nummer} / {place.von}</span>{/if}
      {#if bildschau.origin}<span class="origin">{bildschau.origin}</span>{/if}
    </div>
  </div>
{/if}

<style>
  /* The darkened, softly blurred window with the one thing in the middle. */
  .reader {
    position: fixed;
    inset: 0;
    z-index: 90;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 64px 24px 24px;
    background: rgba(4, 6, 10, 0.66);
    -webkit-backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
  }
  /* Folder, download, close: the house's sign button in glass, one size.
     The ink is light on every look: they stand on the darkened window. */
  .floating {
    position: absolute;
    top: 14px;
    right: 14px;
    display: flex;
    gap: 8px;
  }
  .sign {
    width: 40px;
    height: 40px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: rgba(236, 235, 230, 0.09);
    box-shadow: inset 0 0 0 1px rgba(236, 235, 230, 0.16);
    color: #ecebe6;
    cursor: pointer;
    transition: background 0.12s;
  }
  .sign:hover { background: rgba(236, 235, 230, 0.16); }

  /* The ground the picture lies on, where the fingers are heard: all the room
     the picture and its name leave. */
  .stage {
    flex: 1;
    min-height: 0;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }
  /* A player's width: as the window allows, without the height a picture
     is bound by. */
  .media {
    width: min(760px, 100%);
  }
  .picture {
    display: block;
    max-width: min(72vh, 100%);
    max-height: min(72vh, 100%);
    min-height: 0;
    border-radius: 9px;
    box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
  }
  /* The page: a sheet of paper, 210 to 297, on the look's own ground. It
     is 760 wide where the window has the height for that; where it has not,
     the height is what the window leaves — its padding, the gap and the
     line of the name — and the width follows from it, so the sheet keeps
     its shape in a tall window and in a flat one. The text scrolls in it. */
  .page {
    --room: calc(100vh - 64px - 24px - 12px - 18px);
    flex: none;
    box-sizing: border-box;
    height: min(var(--room), calc(min(760px, 100vw - 48px) * 297 / 210));
    aspect-ratio: 210 / 297;
    overflow-y: auto;
    border-radius: 9px;
    padding: 36px 44px;
    background: var(--bg);
    color: var(--text);
    font-size: 14.5px;
    line-height: 1.6;
    box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
    scrollbar-width: none;
  }
  .page::-webkit-scrollbar { display: none; }
  /* A file the page draws itself fills the sheet to its edge: the pages are
     laid out against the sheet and cut at its rounding (PdfFrame.svelte). */
  .page.framed {
    position: relative;
    padding: 0;
    border: none;
  }
  /* A page the browser cannot set as text: its picture, or the page sign. */
  .page.pictured {
    display: grid;
    place-items: center;
  }
  /* The picture of a file's first page, not a picture to save: it takes no
     pointer, so a right click lands on the sheet and the menu offers no
     "save image" for it. The file itself is saved by the button above. */
  .shell {
    display: block;
    max-width: 100%;
    border-radius: 9px;
    pointer-events: none;
  }
  .pagesign { color: var(--text-still); }
  .prose {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .quiet,
  .failure {
    margin: 0;
    font-size: 13px;
    color: var(--text-still);
  }
  .failure { color: var(--rot-text); }

  /* The report's head: the agent's tile, the task, who and when, the dot of
     the ending. */
  .head {
    --task-size: 13.5px;
    --task-line: 1.4;
    display: flex;
    align-items: flex-start;
    gap: 11px;
    margin-bottom: 12px;
  }
  .tile {
    --farbe: var(--agentfarbe, var(--text-still));
    flex: none;
    width: 30px;
    height: 30px;
    display: grid;
    place-items: center;
    border-radius: 9px;
    background: color-mix(in srgb, var(--farbe) 24%, var(--bg-erhoben));
    color: var(--farbe);
    font-size: 13px;
    font-weight: 600;
  }
  .middle {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  /* The task keeps its paragraphs and stands at most two lines tall until
     its fold is opened. */
  .task {
    font-size: var(--task-size);
    line-height: var(--task-line);
    font-weight: 600;
    color: var(--text);
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }
  .task.folded {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }
  .fold {
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    padding: 2px 0;
    border: none;
    background: none;
    color: var(--text-still);
    cursor: pointer;
  }
  .fold:hover { color: var(--text); }
  .fold-sign {
    display: inline-flex;
    transition: transform 0.18s;
  }
  .fold.open .fold-sign { transform: rotate(180deg); }
  /* The dot stands beside the first line of the task. */
  .dotbox {
    flex: none;
    display: flex;
    align-items: center;
    height: calc(var(--task-size) * var(--task-line));
  }
  .who {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
  }
  .agent {
    font-weight: 500;
    color: var(--text);
  }
  .divider {
    flex: none;
    width: 1px;
    height: 9px;
    background: var(--linie-stark);
  }
  .time {
    font-variant-numeric: tabular-nums;
    color: var(--text-leise);
  }
  .chain {
    margin: 0 0 6px;
    font-size: 11.5px;
    color: var(--text-still);
  }
  /* An ending is a fact; only a run that broke is a state. */
  .reason {
    margin: 0 0 14px;
    padding: 8px 12px;
    border-radius: 9px;
    font-size: 12.5px;
    color: var(--text-still);
  }
  /* A run stopped by its time limit says so with the stopwatch before the
     words. */
  .reason {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .reasonsign {
    display: inline-flex;
    flex: none;
  }
  .reason.broke {
    background: color-mix(in srgb, var(--rot) 12%, var(--bg));
    color: var(--rot-text);
  }
  .body {
    font-size: 15px;
    line-height: 26px;
    color: var(--text);
    overflow-wrap: anywhere;
  }

  /* The name small in the fixed face, where it came from beside it — light,
     on the darkened window. */
  .caption {
    flex: none;
    display: flex;
    gap: 10px;
    max-width: min(760px, 100%);
    font: 12px var(--schrift-fest);
    color: #ecebe6;
    white-space: nowrap;
  }
  .caption .name {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .caption .origin {
    flex: none;
    color: #b1aea6;
  }
</style>

<PictureSheet reader={true} />
