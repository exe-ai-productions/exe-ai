<script>
  /* One card for a file, wherever one appears — an attachment the user
     handed in, or a document the model wrote as a fenced code block. Both
     used to be built twice, in two languages (Svelte markup here, a glued
     HTML string in lib/markdown.js), drifting apart at every change. This
     is the one component both places use now.

     The one difference that survives is the leading mark: a dog-ear for
     something handed in, a typed icon for something written. It arrives
     as a prop (`zeichenHtml`), not as a second component — the card itself
     does not need to know which kind of file it is holding.

     What stays OUTSIDE this component on purpose (Nachricht.svelte keeps
     these, they do not belong here):
       - the ✕ that removes an attachment — a written file is not an
         attachment, there is nothing to remove;
       - the truncation notice under an attachment card — it explains a
         cut that only ever happens to an attachment. */
  import { ADDRESS_KINDS, OFFICE_KINDS, dateiart, dateiHerunterladen, fileKind } from '../lib/dateiarten.js'
  import { tabEinsortieren } from '../lib/vorschautabs.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { bildZeigen, showPage } from '../lib/bildschau.svelte.js'
  import { punktPulsiert } from '../lib/meldewesen.svelte.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'

  let {
    zeichenHtml,
    name,
    fakten,
    /* The fence language, for syntax colour and the download's MIME type.
       Empty for an attachment — its extracted text has no language, and
       the download then falls back to plain text. */
    sprache = '',
    /* Already at hand for a code block; null for an attachment until the
       first opening loads it (below). */
    inhalt = null,
    ladeInhalt = null,
    /* Which conversation this card's file belongs in — the ONLY chat its
       preview tab may ever be filed under. Null means "no conversation":
       a card outside the chat (an agent's report) files nothing at all,
       rather than dropping the report's file into whichever chat happened
       to be open. */
    chatId = null,
    /* A sentence for the pointer over the head, when the caller has one to
       say about the file; without it the head carries no tooltip at all. */
    hinweis = null,
    /* The file is still being written: the answer it stands in is running
       and its fence has not closed. The caller decides — only it knows
       whether the answer runs — and words the facts line to match. */
    writing = false,
    /* Where the file itself is fetched from, for a card that stands for a
       stored file: saving it then saves that file, not a text of it. */
    fileAddress = null,
    /* A file the browser's own viewer draws (a PDF). Such a card holds no
       text: the reader and the rail show the file in a frame. */
    framed = false,
    /* That file's line for its tab: what it is, without the part of the
       card's own line that changes from answer to answer — the tab is filed
       once and would keep saying it. */
    fileFacts = '',
    /* Where the stored file lies on disk, for the field of its tab; empty
       for a file that only stands in an answer's text. */
    filePath = '',
  } = $props()

  /* Follows the prop, and keeps a fetched text only until `inhalt` next
     changes (a writable $derived). NOT a one-time $state seed: Svelte
     reuses this card whenever an index-keyed list moves it to another
     file, and a seed would keep showing, filing and SAVING the previous
     file's text under the new file's name. */
  let geladenerInhalt = $derived(inhalt)

  const art = $derived(dateiart(sprache))
  /* What the file is by its ending: a document, code, text — or a picture, a
     clip or a sound, which have no text and are shown from the file's own
     address. */
  const info = $derived(fileKind(sprache))
  const fromAddress = $derived(ADDRESS_KINDS.includes(info?.kind))

  /* Fetches what the card does not hold yet, at most one flight at a time,
     and hands the text back either way. A failed attempt does not latch:
     only a flight already under way is guarded. */
  let laufendesLaden = null
  async function inhaltHolen() {
    if (geladenerInhalt !== null) return geladenerInhalt
    if (!ladeInhalt) return null
    if (laufendesLaden) return laufendesLaden
    laufendesLaden = (async () => {
      try {
        geladenerInhalt = await ladeInhalt()
        return geladenerInhalt
      } finally {
        laufendesLaden = null
      }
    })()
    return laufendesLaden
  }

  /* Files the model wrote reach the preview by themselves while the answer
     is still being written — but only then. An answer from yesterday was
     never handed over, so the file it carries would be unreachable there
     forever. Filing it when the card is opened closes that gap without a
     second control and without a panel jumping open: the tab is simply
     THERE for whoever goes looking.

     Filed under `chatId` — the card's OWN conversation, handed in from
     outside — never under "whatever is active right now", and only while
     that chat is the one on screen: a background chat's rail is nobody's to
     rearrange. `tabEinsortieren`, not `tabOeffnen`: the card is SHOWING a
     file, not writing one (lib/vorschautabs.svelte.js). */
  function einsortieren(text) {
    if (!info || info.kind === 'pdf' || fromAddress || text == null) return
    if (!chatId || chatId !== zustand.aktiverChat) return
    tabEinsortieren(chatId, { name, art: sprache, inhalt: text, pfad: filePath })
  }

  /* A file shown from its own address (a PDF in a frame, a picture, a clip,
     a sound) is filed the same way and under the same rule — its own chat,
     and only while that chat is on screen. */
  function fileFramed() {
    if (!chatId || chatId !== zustand.aktiverChat) return
    tabEinsortieren(chatId, {
      name, art: framed ? 'pdf' : sprache, inhalt: '', pfad: filePath, adresse: fileAddress, fakten: fileFacts,
    })
  }

  /* The head opens the file in the reader, as a page. */
  function oeffnen() {
    if (framed && fileAddress) {
      showPage({ name, adresse: fileAddress, framed: true })
      fileFramed()
      return
    }
    if (fromAddress && fileAddress) {
      if (OFFICE_KINDS.includes(info.kind)) showPage({ name, adresse: fileAddress, mediaKind: info.kind })
      else bildZeigen(fileAddress, { name, mediaKind: info.kind === 'image' ? '' : info.kind })
      fileFramed()
      return
    }
    showPage({
      name,
      language: sprache,
      text: geladenerInhalt,
      loadText: async () => {
        const text = await inhaltHolen()
        einsortieren(text)
        return text
      },
      /* With the file's own address the reader saves the file from there;
         without one it saves the text this card holds. */
      adresse: fileAddress || '',
      download: fileAddress ? null : () => herunterladenText(),
    })
    einsortieren(geladenerInhalt)
  }

  function tasteOeffnen(ereignis) {
    if (ereignis.key !== 'Enter' && ereignis.key !== ' ') return
    ereignis.preventDefault()
    oeffnen()
  }

  /* The download hands out exactly what the card holds — the extracted
     text for an attachment, since that is all a browser ever received of
     it; the written source for a file. Neither is the original upload's
     raw bytes, and this only ever claims to be what it is. It waits for
     the text: writing whatever happened to be at hand would hand out an
     EMPTY file under the real name. An attachment's text is saved as
     `.txt`, never under the original name — a `.pdf` that opens in no PDF
     reader is worse than an honest text file. */
  async function herunterladenText() {
    const text = await inhaltHolen()
    if (text == null) return
    dateiHerunterladen(art ? name : `${name}.txt`, text, art?.typ)
  }
</script>

<div class="dateikarte">
  <!-- The whole card opens the file in the reader; saving it is done there
       and in the rail beside the chat, so the card carries no second
       control. role="button" with the click and the two key presses a
       button answers to, since the card is a box of several parts. -->
  <div
    class="datei-kopf"
    role="button"
    tabindex="0"
    title={hinweis}
    onclick={oeffnen}
    onkeydown={tasteOeffnen}
  >
    <span class="datei-zeichen">{@html zeichenHtml}</span>
    <span class="datei-text">
      <span class="datei-name">{name}</span>
      <span class="datei-fakten">{fakten}</span>
    </span>
    <!-- The state of the file, in the colour the house gives that state:
         blue while it is being written, green once it is there. A file
         handed in is there from the start. The blue dot breathes like every
         running dot in the chat, and like them only where the chat's dots
         are allowed to move. -->
    <span class="datei-punkt">
      <Leuchtpunkt farbe={writing ? 'blau' : 'gruen'} groesse={9} atmet={writing && punktPulsiert('chat')} />
    </span>
  </div>
</div>

<style>
  /* One card, one size, wherever a file stands in the chat — written by
     the model or handed in by the user. A fixed size on purpose: a card as
     wide as its bubble changed shape with every answer, and several files
     in a row could not stand side by side. The fine line and the small
     shadow are what lift it off the chat's glass; its ground alone sits on
     that glass almost without a difference in tone. */
  .dateikarte {
    box-sizing: border-box;
    display: inline-flex;
    vertical-align: top;
    width: 300px;
    max-width: 100%;
    height: 56px;
    margin: 0 0 0.95em;
    border: 1px solid var(--linie);
    border-radius: 9px;
    background: var(--bg-erhoben);
    box-shadow: var(--karten-schatten);
    overflow: hidden;
  }
  .datei-kopf {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 12px 0 10px;
    cursor: pointer;
  }
  /* Same quiet lift as the other rows this run gave a hover (Punkt 2/3) —
     a fact about the card (it can be clicked), not a state. */
  .datei-kopf:hover {
    background: var(--bg-hoch);
  }
  .datei-zeichen {
    flex: none;
    display: inline-flex;
    color: var(--text-leise);
  }
  /* Every caller's mark at the one size the card is drawn with. */
  .datei-zeichen :global(svg) {
    width: 20px;
    height: 20px;
  }
  .datei-text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    line-height: normal;
  }
  .datei-name {
    display: block;
    color: var(--text);
    font-size: 13.5px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .datei-fakten {
    display: block;
    font-size: 11.5px;
    color: var(--text-leise);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .datei-punkt {
    flex: none;
    display: inline-flex;
  }
</style>
