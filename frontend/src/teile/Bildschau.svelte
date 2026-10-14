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
  import { bildschau, closeReader } from '../lib/bildschau.svelte.js'
  import { isVideo } from '../lib/media.js'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { hervorheben } from '../lib/einfaerben.js'
  import { codeKopierKlick, dateiTeile, nummernspalte } from '../lib/markdown.js'
  import {
    dateiart, dateiFakten, dateiHerunterladen, dateizeichen, saveFromAddress,
  } from '../lib/dateiarten.js'
  import Dateikarte from './Dateikarte.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import PdfFrame from './PdfFrame.svelte'

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
  const isSource = $derived(Boolean(dateiart(bildschau.language)) && !isMarkdown)
  const codeHtml = $derived(
    text != null && isSource
      ? '<pre>' + nummernspalte(text) + '<code>' + hervorheben(text, bildschau.language) + '</code></pre>'
      : '',
  )

  const report = $derived(bildschau.kind === 'report' ? bildschau.report : null)
  /* The dot at the end of the head: green for a report, red for a run that
     broke, a quiet grey for every other ending. */
  const dotColour = $derived(
    report?.state === 'gescheitert' ? 'rot' : report?.state === 'fertig' ? 'gruen' : 'still',
  )

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
      {#if isVideo(bildschau.adresse)}
        <!-- A video plays here, with its own controls. -->
        <!-- svelte-ignore a11y_media_has_caption -->
        <video class="picture" src={bildschau.adresse} controls autoplay loop playsinline></video>
      {:else}
        <img class="picture" src={bildschau.adresse} alt={bildschau.name} />
      {/if}
    {:else if report}
      <div class="page">
        <div class="head">
          <span class="tile" style:--agentfarbe={report.colour || null} aria-hidden="true">
            {(report.agent || '?').slice(0, 1).toUpperCase()}
          </span>
          <span class="middle">
            <span class="task">{report.task}</span>
            <span class="who">
              <span class="agent" style={report.colour ? `color:${report.colour}` : ''}>{report.agent}</span>
              {#if report.time}
                <span class="divider"></span>
                <span class="time">{report.time}</span>
              {/if}
            </span>
          </span>
          <Leuchtpunkt farbe={dotColour} groesse={9} />
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
    {:else if bildschau.framed}
      <!-- A file the browser's own viewer draws: its pages, one under the
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
        {:else if text != null && isSource}
          <div class="codeblock">{@html codeHtml}</div>
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
  /* A file the browser's viewer draws fills the sheet to its edge: the
     frame is laid out against the sheet and cut at its rounding
     (PdfFrame.svelte). */
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
  .codeblock {
    margin: 0;
    border: none;
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
    display: flex;
    align-items: center;
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
  .task {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .who {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
  }
  .agent {
    font-weight: 500;
    color: var(--blau-text);
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
