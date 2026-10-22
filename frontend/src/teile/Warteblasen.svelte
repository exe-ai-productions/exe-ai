<script>
  /* The queued messages, shown where they will land: at the end of the
     history, below the running answer.

     A waiting message is the bubble it will become, dimmed: it IS the sent
     message's own bubble (Nachricht.svelte), drawn from the same shape the
     send makes of it — text, pictures, documents, the instruction's pill —
     so the width, the place, the parts and the type are the sent one's by
     construction. What says that it waits stands under it, in the row where
     "Copy" will stand once it is sent: the hourglass, the word, and the ✕
     that takes the message back. That makes the waiting bubble exactly as
     high as the sent one, so when the message goes nothing moves — only the
     dimming fills in (the `.from-queue` class in stil/global.css).

     The word says the state and nothing else; the sentence that says what
     the bubble IS stands as a hint while the pointer is on the word, and on
     a screen with no pointer a tap on the word opens it. */
  import Nachricht from './Nachricht.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { fuerChat } from '../lib/warteschlange.svelte.js'
  import { previewOf } from '../lib/picturePreview.js'

  let { takeBack } = $props()

  const wartende = $derived(fuerChat(zustand.aktiverChat))

  /* The message a waiting entry will become, in the shape the send gives it
     (lib/chatlauf.svelte.js): one picture or document in the scalar field,
     more in the list. */
  function asMessage(eintrag) {
    const pictures = (eintrag.bilder || []).map(previewOf)
    const documents = eintrag.dokumente || []
    return {
      // The `eigen-` start marks a bubble that is no stored row of the chat
      // (Nachricht.svelte takes no ✕ for a document on it).
      id: `eigen-waiting-${eintrag.id}`,
      role: 'user',
      content: eintrag.inhalt || '',
      bild: pictures[0] ?? null,
      anhaenge: pictures.length > 1 ? pictures : null,
      dokument: documents.length === 1 ? documents[0] : null,
      dokumente: documents.length > 1 ? documents : null,
    }
  }

  /* The sentence under the word, opened by a tap on a screen with no
     pointer: the id of the entry whose hint stands, or none. The screen is
     asked at the tap, so a pointer that comes and goes is read as it is. */
  let hintOpen = $state(null)
  function tapMark(eintrag) {
    if (!matchMedia('(hover: none)').matches) return
    hintOpen = hintOpen === eintrag.id ? null : eintrag.id
  }
  /* A tap anywhere else closes it. */
  function tapOutside(event) {
    if (hintOpen != null && !event.target.closest?.('.marke')) hintOpen = null
  }
</script>

<svelte:window onpointerdown={tapOutside} />

{#each wartende as eintrag (eintrag.id)}
  {#snippet row()}
    <div class="zeile">
      <svg class="sanduhr" width="13" height="13" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true">
        <path d="M6 3h12M6 21h12M8 3v4l4 5 4-5V3M8 21v-4l4-5 4 5v4" />
      </svg>
      <button class="marke" title={t('warteschlange.erklaerung')}
              aria-expanded={hintOpen === eintrag.id}
              onclick={() => tapMark(eintrag)}>{t('warteschlange.wartet')}</button>
      <button
        class="weg"
        title={t('warteschlange.entfernen')}
        aria-label={t('warteschlange.entfernen')}
        onclick={() => takeBack(eintrag)}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.2" stroke-linecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
      {#if hintOpen === eintrag.id}
        <span class="hint" role="status">{t('warteschlange.erklaerung')}</span>
      {/if}
    </div>
  {/snippet}
  <!-- One block, like the one a sent message stands in: the history spaces
       its blocks, not the two rows inside one. -->
  <div>
    <Nachricht nachricht={asMessage(eintrag)} waiting={true} waitRow={row} />
  </div>
{/each}

<style>
  /* The row under the sent bubble, where "Copy" stands: right-aligned, 6 px
     below the bubble, as high as the row of its buttons (the 6 px, then 4 px
     around a 15 px sign). */
  .zeile {
    position: relative;
    align-self: flex-end;
    display: flex;
    align-items: center;
    gap: 6px;
    padding-top: 6px;
    min-height: 29px;
    font-size: 12px;
    line-height: 15px;
    color: var(--text-still);
  }
  /* The state colour sits on the shape alone, in the shape tokens
     (global.css), at full strength. */
  .sanduhr {
    flex: none;
    color: var(--gelb);
  }
  .marke {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    color: inherit;
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: default;
  }
  .weg {
    background: none;
    border: none;
    padding: 4px;
    border-radius: 9px;
    color: inherit;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
  }
  .weg:hover {
    background: var(--linie);
    color: var(--text);
  }
  /* The sentence a tap on the word opens: it stands under the row and over
     what follows, so the block keeps its height and nothing moves. */
  .hint {
    position: absolute;
    top: 100%;
    right: 0;
    z-index: 5;
    max-width: min(280px, 80vw);
    margin-top: 4px;
    padding: 8px 10px;
    border-radius: 9px;
    background: var(--glass-dropdown);
    box-shadow: 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font-size: 12px;
    line-height: 1.45;
    text-transform: none;
    letter-spacing: normal;
  }
</style>
