<script>
  /* The queued messages, shown where they will land: at the end of the
     history, below the running answer.

     They wear the user's bubble, but quietly — dimmed and outlined
     instead of filled. That difference is the whole message of the thing:
     what stands here has been typed but not yet said, and it must not be
     mistaken for something already in the conversation.

     A held queue says so at every bubble it holds, not only at the first —
     whoever scrolls in from below should not have to look for the reason. */
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { entfernen, fuerChat } from '../lib/warteschlange.svelte.js'

  let { losschicken } = $props()

  const wartende = $derived(fuerChat(zustand.aktiverChat))

  /* Every queued attachment by name — images and documents in one line. */
  function anhangNamen(eintrag) {
    return [...(eintrag.bilder || []), ...(eintrag.dokumente || [])]
      .map((datei) => datei.name)
      .join(', ')
  }
</script>

{#each wartende as eintrag (eintrag.id)}
  <div class="wartet" class:haelt={eintrag.haelt}>
    <div class="zeile">
      <svg class="sanduhr" width="13" height="13" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true">
        <path d="M6 3h12M6 21h12M8 3v4l4 5 4-5V3M8 21v-4l4-5 4 5v4" />
      </svg>
      <span class="marke">{eintrag.haelt ? t('warteschlange.haelt') : t('warteschlange.wartet')}</span>
      {#if eintrag.haelt}
        <button class="weiter" onclick={() => losschicken(eintrag)}>
          {t('warteschlange.jetzt_senden')}
        </button>
      {/if}
      <button
        class="weg"
        title={t('warteschlange.entfernen')}
        aria-label={t('warteschlange.entfernen')}
        onclick={() => entfernen(eintrag.id)}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.2" stroke-linecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
    <!-- What the bubble IS, in one sentence. The mark above says the state
         and nothing else, and an outlined bubble at the end of the history
         was easy to read as a message that had failed to send.

         Not on a held queue: that one does NOT go out when the answer is
         through — it waits for the button beside it, and saying otherwise
         would be the quieter of two lies. -->
    {#if !eintrag.haelt}
      <div class="erklaerung">{t('warteschlange.erklaerung')}</div>
    {/if}
    {#if eintrag.inhalt}
      <div class="text">{eintrag.inhalt}</div>
    {/if}
    {#if eintrag.bilder?.length || eintrag.dokumente?.length}
      <div class="anhang">{anhangNamen(eintrag)}</div>
    {/if}
  </div>
{/each}

<style>
  .wartet {
    align-self: flex-end;
    max-width: 76%;
    min-width: 0;
    border-radius: 9px;
    padding: 8px 15px 10px;
    /* The ground and ink of one's own bubble (Nachricht.svelte, `.von-mir`),
       dimmed, and no frame: it will be that bubble, it is not one yet. The
       dimming is on the parts, never on the bubble as a whole: an opacity
       there would take the hourglass down with it, and the hourglass in the
       corner is what carries the state — yellow while it waits, red while it
       is held, at full strength. The ground is dimmed by its alpha channel,
       the word and the text by their own opacity. */
    background: color-mix(
      in srgb,
      var(--blase-eigen, var(--blase-eigen-standard, var(--blase))) 60%,
      transparent
    );
    color: var(--blase-eigen-text, var(--blase-eigen-text-standard, inherit));
    line-height: 1.55;
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 2px;
  }
  /* The state colour sits on the shape alone, in the shape tokens
     (global.css): the ground is a colour the user picked, so no text colour
     is sure to reach 4.5:1 on it, and the word must stay readable. */
  .sanduhr {
    flex: none;
    color: var(--gelb);
  }
  /* The hold is a state of its own — the send did not go through — so it
     carries the house's failure colour, red, not the waiting queue's
     yellow. */
  .wartet.haelt .sanduhr {
    color: var(--rot);
  }
  .marke {
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* The bubble's own ink: the only colour sure to read on a ground the
       user picked. The state is the hourglass's colour beside it. */
    color: inherit;
    opacity: 0.6;
  }
  /* A statement of fact, so brightness alone — no state colour. It sits
     above the typed text and below the mark, quieter than both, in the
     bubble's own ink: a theme grey is not sure to read on a ground the
     user picked. */
  .erklaerung {
    font-size: 0.82rem;
    opacity: 0.45;
    margin-bottom: 3px;
  }
  .text {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    opacity: 0.6;
  }
  .anhang {
    font-size: 0.82rem;
    opacity: 0.45;
    overflow-wrap: anywhere;
  }
  .weiter,
  .weg {
    margin-left: auto;
    background: none;
    border: none;
    padding: 2px 6px;
    border-radius: 9px;
    color: inherit;
    cursor: pointer;
    display: flex;
    align-items: center;
    opacity: 0.6;
  }
  .weiter {
    font-size: 0.78rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }
  /* Only one of the two may claim the free space, or the ✕ would be
     pushed off the edge whenever the hold notice stands. */
  .weiter + .weg {
    margin-left: 0;
  }
  .weiter:hover,
  .weg:hover {
    background: color-mix(in srgb, var(--text) 10%, transparent);
    color: var(--text);
  }
</style>
