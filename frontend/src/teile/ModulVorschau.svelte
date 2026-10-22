<script>
  /* The preview module: what the model built, shown beside the chat.

     A small browser, not a window: the tabs on top as loose pills, under
     them the address line — reload, the file's name with its facts, the
     switch to the source, the download — and under that the page itself,
     filling the rail to its lower edge. One name, one way to save, no
     frame around the page and no row of buttons below it.

     What a file shows depends on its kind (lib/dateiarten.js): HTML is
     drawn by the browser in the sandboxed frame, a drawing (SVG) as a picture
     by an image element, Markdown by the renderer the chat itself uses, CSV
     as a table, code and text through the one component both views share
     (FileContent.svelte: colours and a number on every line, or the text as
     written), everything else of a document as its source. Whatever has a
     drawn form can be switched to its source and back. A PDF, a picture, a
     clip and a sound are not text at all: their tab carries the address of
     the file — the page draws the pages of a PDF with pdf.js (PdfFrame.svelte),
     the others come through FileContent — no source to switch to, and saving
     one saves the file.

     The frame is sandboxed WITHOUT allow-same-origin, and that pairing is
     the point: the document comes from the model, and with our origin its
     scripts would sit inside our own program and could talk to our own API
     with our own session. Scripts stay allowed — a page that cannot run is
     not a preview of that page — but they run next to nothing.

     What the sandbox leaves open is the way OUT: it never stopped the
     document from calling a foreign address. That is what the rule from
     lib/vorschauschutz.js closes, and it rides in the document itself
     because srcdoc has no response to carry a header. */
  import Dateikarte from './Dateikarte.svelte'
  import DataTable from './DataTable.svelte'
  import FileContent from './FileContent.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import PdfFrame from './PdfFrame.svelte'
  import {
    ADDRESS_KINDS, OFFICE_KINDS, dateiart, dateiFakten, dateiHerunterladen, dateizeichen, fileKind, saveFromAddress,
    svgAddress, tabelleLesen,
  } from '../lib/dateiarten.js'
  import { lebendHtml } from '../lib/lebendhtml.js'
  import { displayPath } from '../lib/paths.js'
  import { codeKopierKlick, dateiTeile } from '../lib/markdown.js'
  import { t } from '../lib/texte.svelte.js'
  import { mitSchutzregel } from '../lib/vorschauschutz.js'
  import {
    aktiverTab, tabSchliessen, tabWaehlen, tabsVon,
  } from '../lib/vorschautabs.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'

  const chatId = $derived(zustand.aktiverChat)
  const liste = $derived(tabsVon(chatId))
  const offen = $derived(aktiverTab(chatId))

  const eintrag = $derived(offen ? dateiart(offen.art) : null)
  const info = $derived(offen ? fileKind(offen.art) : null)
  /* A PDF shown from its own address, drawn by the page. */
  const isFramed = $derived(Boolean(offen?.adresse) && info?.kind === 'pdf')
  /* A picture, a clip or a sound shown from its own address. */
  const fromAddress = $derived(
    Boolean(offen?.adresse) && ADDRESS_KINDS.includes(info?.kind) && !OFFICE_KINDS.includes(info?.kind),
  )
  /* A Word document, a spreadsheet or a presentation, drawn by the page from
     its own address and held the way a PDF is. */
  const isOffice = $derived(Boolean(offen?.adresse) && OFFICE_KINDS.includes(info?.kind))
  /* Code and text that is no document: the text itself, set by the shared
     component. */
  const isCodeOrText = $derived(['code', 'text'].includes(info?.kind))
  /* A drawing is a picture of its text, and its text stays one switch away. */
  const isSvg = $derived(eintrag?.endung === 'svg')
  /* Markdown is drawn too, but by our own renderer and into the page
     itself; only what the browser has to draw goes into the frame. */
  const isMarkdown = $derived(eintrag?.zeigen === 'gerendert' && eintrag.endung === 'md')
  const kannZeichnen = $derived(eintrag?.zeigen === 'gerendert' && !isMarkdown && !isSvg)
  const kannTabelle = $derived(eintrag?.zeigen === 'tabelle')
  /* Whether there are two views to switch between at all: a file that is
     only ever shown as its source has no second one, and so no switch. */
  const hasTwoViews = $derived(kannZeichnen || kannTabelle || isMarkdown || isSvg)
  const zeilen = $derived(
    kannTabelle ? tabelleLesen(offen.inhalt, offen.art === 'tsv' ? '\t' : ',') : [],
  )

  /* Reloading means handing the page its content again — the same trick a
     browser's reload button plays, and enough for a document that lives in
     memory. */
  let stand = $state(0)
  /* Drawn or as source. A new tab starts drawn again: the last file's view
     should not decide how the next one opens. */
  let quelltextZeigen = $state(false)
  $effect(() => {
    void offen?.id
    quelltextZeigen = false
  })

  /* The same facts line the file card writes (lib/dateiarten.js) — one
     wording for one fact, wherever it is shown. */
  const fakten = $derived(!offen ? '' : offen.adresse ? offen.fakten : dateiFakten(offen))

  function herunterladen() {
    if (!offen) return
    if (offen.adresse) {
      /* The file itself, under its own name: saved from its address, the
         browser keeps what the service hands out instead of showing it. */
      saveFromAddress(offen.name, offen.adresse)
      return
    }
    dateiHerunterladen(offen.name, offen.inhalt, eintrag?.typ)
  }
</script>

{#if !liste.length}
  <p class="leer">{t('vorschau.leer')}</p>
{:else}
  <div class="reiter">
    {#each liste as tab (tab.id)}
      <div class="reiter-eintrag" class:aktiv={tab.id === offen?.id}>
        <button class="reiter-name" onclick={() => tabWaehlen(chatId, tab.id)}>{displayPath(tab.name)}</button>
        <button
          class="reiter-zu"
          onclick={() => tabSchliessen(chatId, tab.id)}
          aria-label={t('app.schliessen')}
          title={t('app.schliessen')}
        ><Hauszeichen zeichen="kreuz" groesse={10} /></button>
      </div>
    {/each}
  </div>

  <div class="adresszeile">
    <button
      class="zeichenknopf"
      onclick={() => (stand += 1)}
      aria-label={t('vorschau.neu_laden')}
      title={t('vorschau.neu_laden')}
    ><Hauszeichen zeichen="neu_laden" groesse={16} /></button>
    <div class="adresse">
      <!-- Where the file lies, as a browser's bar shows an address: cut at
           its front where it does not fit, so the file's name stays in
           view, whole under the pointer. The name stands in the tab above;
           a file without a place on disk shows it here as well. -->
      <span class="adresse-name" title={offen?.pfad ? displayPath(offen.pfad) : null}><span>{displayPath(offen?.pfad || offen?.name)}</span></span>
      <span class="fakten">{fakten}</span>
    </div>
    {#if hasTwoViews}
      <!-- One sign for both ways: it says where the click leads. -->
      <button
        class="zeichenknopf"
        class:gedrueckt={quelltextZeigen}
        aria-pressed={quelltextZeigen}
        onclick={() => (quelltextZeigen = !quelltextZeigen)}
        aria-label={quelltextZeigen ? t('datei.gerendert') : t('datei.quelltext')}
        title={quelltextZeigen ? t('datei.gerendert') : t('datei.quelltext')}
      ><Hauszeichen zeichen="dokument_zeilen" groesse={16} /></button>
    {/if}
    <button
      class="zeichenknopf"
      onclick={herunterladen}
      aria-label={t('datei.herunterladen')}
      title={t('datei.herunterladen')}
    ><Hauszeichen zeichen="download" groesse={16} /></button>
  </div>

  <div class="buehne">
    {#key `${offen?.id}-${stand}`}
      {#if isFramed}
        <div class="seite rahmen viewer">
          <PdfFrame address={offen.adresse} title={offen.name} />
        </div>
      {:else if isOffice}
        <div class="seite rahmen viewer">
          <FileContent kind={info.kind} address={offen.adresse} name={offen.name} />
        </div>
      {:else if fromAddress}
        <div class="seite file-content">
          <FileContent kind={info.kind} address={offen.adresse} name={offen.name} />
        </div>
      {:else if isSvg && !quelltextZeigen}
        <div class="seite file-content">
          <FileContent kind="image" address={svgAddress(offen.inhalt)} name={offen.name} />
        </div>
      {:else if kannZeichnen && !quelltextZeigen}
        <iframe
          class="seite rahmen"
          title={offen.name}
          srcdoc={mitSchutzregel(offen.inhalt)}
          sandbox="allow-scripts"
          referrerpolicy="no-referrer"
        ></iframe>
      {:else if isMarkdown && !quelltextZeigen}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="seite dokument berichttext" onclick={codeKopierKlick}>
          {#each dateiTeile(offen.inhalt) as stueck, i (i)}
            {#if stueck.art === 'html'}
              <!-- Drawn in place: the file grows here while it is being
                   written, and a page torn out on every piece would throw
                   the reader back to its top (lib/lebendhtml.js). -->
              <div use:lebendHtml={stueck.wert}></div>
            {:else if stueck.wert}
              <!-- A file inside the file: its card, as in an answer. No
                   chat of its own, so it files no tab. -->
              <Dateikarte
                zeichenHtml={dateizeichen(stueck.wert.art)}
                name={stueck.wert.name}
                fakten={dateiFakten(stueck.wert)}
                sprache={stueck.wert.art}
                inhalt={stueck.wert.inhalt}
              />
            {/if}
          {/each}
        </div>
      {:else if kannTabelle && !quelltextZeigen}
        <div class="seite tabellenfeld">
          <DataTable rows={zeilen} />
        </div>
      {:else if isCodeOrText}
        <div class="seite quelle">
          <FileContent kind={info.kind} language={info.language} text={offen?.inhalt} />
        </div>
      {:else}
        <!-- The source of a document: the colours of its grammar and a
             number on every line, as the reader shows it. -->
        <div class="seite quelle">
          <FileContent kind="code" language={isSvg ? 'xml' : (info?.language ?? '')} text={offen?.inhalt} />
        </div>
      {/if}
    {/key}
  </div>
{/if}

<style>
  .leer {
    margin: 14px;
    font-size: 13px;
    color: var(--text-still);
  }
  /* The tabs: loose pills, one row, one size — every tab is the same
     height whatever it is called. A tab is an outline with the glass edge;
     the one shown is filled with button glass. */
  .reiter {
    flex: none;
    display: flex;
    gap: 6px;
    padding: 12px 12px 0;
    overflow-x: auto;
  }
  .reiter-eintrag {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 26px;
    box-sizing: border-box;
    max-width: 180px;
    border: 1px solid var(--glass-button-edge);
    border-radius: 9px;
    background: none;
    padding: 0 7px 0 10px;
  }
  .reiter-eintrag.aktiv {
    background: var(--glass-button);
  }
  /* The highlight sits on the whole tab, so the close sign lights up with
     the name instead of staying dark beside it — same rule as the folder
     chips and the tool rows. */
  .reiter-eintrag:hover {
    background: var(--glass-hover);
  }
  .reiter-eintrag:hover .reiter-name,
  .reiter-eintrag:hover .reiter-zu { color: var(--text); }
  .reiter-name {
    min-width: 0;
    border: none;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12px;
    padding: 0;
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .reiter-eintrag.aktiv .reiter-name { color: var(--text); }
  .reiter-zu {
    flex: none;
    display: inline-flex;
    border: none;
    background: none;
    color: var(--text-still);
    padding: 0;
    cursor: pointer;
  }

  .adresszeile {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
  }
  /* The field: where the file lies — or its name, where it lies nowhere —
     and to its right what the file is and how much it weighs. A field on
     glass: glass with the house's field outline. */
  .adresse {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 28px;
    box-sizing: border-box;
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 0 12px;
  }
  .adresse-name {
    flex: 1;
    min-width: 0;
    font-size: 12.5px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    /* Cut at the front, the way the command's folder line does
       (ModulTerminal): the box reads right to left, so the ellipsis stands
       at the left end and the file's name at the right one stays. The path
       itself, in the inner span, keeps reading left to right — the digits
       and marks of a path stay in their order. */
    direction: rtl;
    text-align: left;
  }
  .adresse-name span {
    direction: ltr;
    unicode-bidi: bidi-override;
  }
  .fakten {
    flex: none;
    font-size: 11.5px;
    color: var(--text-still);
    white-space: nowrap;
  }
  /* Three signs in one row, all the same box. */
  .zeichenknopf {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    box-sizing: border-box;
    border: 1px solid var(--glass-button-edge);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text-leise);
    padding: 0;
    cursor: pointer;
  }
  .zeichenknopf:hover { background: var(--glass-hover); color: var(--text); }
  /* Switched on, in the colour that means on, the quiet way: the colour for
     the sign and 12 % of it mixed into the button's glass. */
  .zeichenknopf.gedrueckt {
    color: var(--blau);
    background: color-mix(in srgb, var(--blau) 12%, var(--glass-button));
  }

  .buehne {
    flex: 1;
    min-height: 0;
    display: flex;
    padding: 4px 12px 12px;
  }
  /* The page lies in the rail as it is: no frame around it, only the
     house's shadow under it, and it reaches the rail's lower edge and rolls
     in itself. It is paper, not glass: it shows a document, and a ground
     that let the look through would run under its text. */
  .seite {
    flex: 1;
    min-width: 0;
    min-height: 0;
    box-sizing: border-box;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.55), 0 2px 6px -2px rgba(0, 0, 0, 0.25);
    overflow: auto;
  }
  /* A page the browser draws brings its own colours and expects white
     under them, as in any browser. */
  .rahmen {
    background: #fff;
  }
  /* The page that holds a PDF's pages: they are laid out against it and
     cut at its rounding (PdfFrame.svelte). */
  .viewer {
    position: relative;
  }
  /* A written page: the text of the chat, set for the width of a rail. The
     rest of its dress — lists, quotes, tables, code — is the shared sheet
     for rendered text (stil/berichttext.css). */
  .dokument {
    padding: 26px 28px;
    font-size: 12.5px;
    line-height: 19px;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  /* One distance between everything that stands on the page. */
  .dokument :global(p),
  .dokument :global(ul),
  .dokument :global(ol),
  .dokument :global(blockquote),
  .dokument :global(h2),
  .dokument :global(h3),
  .dokument :global(h4),
  .dokument :global(h5) { margin: 0 0 8px; }
  .dokument :global(h2) { font-size: 20px; line-height: 30px; letter-spacing: 0; }
  .dokument :global(h3) { font-size: 15px; line-height: 23px; }
  .dokument :global(h4),
  .dokument :global(h5) { font-size: 12.5px; line-height: 19px; }
  .dokument :global(a) { color: var(--text); }
  .dokument :global(.dateikarte) { margin-bottom: 8px; }
  .tabellenfeld {
    padding: 14px 16px;
  }
  /* The source: not a page but the text itself, in the typewriter face on
     a glass card — code with its colours and numbers, text as written. */
  .quelle {
    flex: 1;
    min-width: 0;
    min-height: 0;
    box-sizing: border-box;
    overflow: auto;
    margin: 0;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 14px 16px;
    font-family: var(--schrift-fest);
    font-size: 11.5px;
    line-height: 18px;
    color: var(--text);
  }
  /* A picture, a clip or a sound on the sheet, with the air a page has. */
  .file-content {
    padding: 14px 16px;
  }
</style>
