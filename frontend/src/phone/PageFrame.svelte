<script>
  /* The frame of a page that stands over the chat: the way back, the page's
     name, and the room for its content. The page brings its own rows; the
     frame brings the head and the scrolling. While a page inside the page is
     open the head says that one — the way back with the name of the page it
     leads back to on the left, the inner page's name in the middle — and
     there is no second head under it. At the right end stands at most one
     thing: a sign of the page (the studio's fine settings) or, on an inner
     page, a button with a word ("Done"). */
  import { t } from '../lib/texte.svelte.js'
  import Fensterzeichen from '../teile/Fensterzeichen.svelte'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import { head, headTop, headBefore } from './head.svelte.js'

  let { title, onback, children } = $props()

  const inner = $derived(headTop())
  const right = $derived(inner ? inner.right : head.right)
</script>

<section class="page">
  <header class="head" class:inner={Boolean(inner)}>
    {#if inner?.backText}
      <button class="back word" onclick={inner.onback}>{inner.backText}</button>
    {:else}
      <button class="back" onclick={inner ? inner.onback : onback}
              aria-label={inner ? `${t('app.zurueck')}: ${headBefore(title)}` : t('app.zurueck')}>
        <span class="arrow"><Hauszeichen zeichen="pfeil_unten" groesse={15} strich={2.6} /></span>
        {#if inner}<span class="from">{headBefore(title)}</span>{/if}
      </button>
    {/if}
    <h1>{inner ? inner.title : title}</h1>
    {#if right}
      <button class="right" class:word={Boolean(right.text)} onclick={right.onclick} disabled={right.disabled}
              aria-label={right.label ?? right.text}>
        {#if right.text}{right.text}{:else}<Fensterzeichen name={right.sign} groesse={22} />{/if}
      </button>
    {/if}
  </header>
  <div class="body">
    {@render children?.()}
  </div>
</section>

<style>
  .page {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg);
  }
  .head {
    flex: none;
    display: flex;
    align-items: center;
    gap: 6px;
    height: calc(52px + env(safe-area-inset-top));
    padding: env(safe-area-inset-top) calc(8px + env(safe-area-inset-right)) 0
      calc(8px + env(safe-area-inset-left));
  }
  .back {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
  }
  .back:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  /* The house arrow points down; turned a quarter it points back. */
  .arrow {
    display: inline-flex;
    transform: rotate(90deg);
  }
  h1 {
    margin: 0;
    font: 600 16px var(--schrift);
  }
  /* The page's own sign, at the right end, the size of the way back. */
  .right {
    display: grid;
    place-items: center;
    min-width: 44px;
    height: 44px;
    margin-left: auto;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
  }
  .right:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  /* A word instead of a sign: "Cancel" at the left, "Done" at the right. The
     one on the right is the full button of the house, the one on the left is
     plain text. */
  .back.word {
    width: auto;
    padding: 0 10px;
    font: 400 15px var(--schrift);
    color: var(--text);
  }
  .right.word {
    min-width: 0;
    height: 34px;
    padding: 0 14px;
    background: var(--text);
    color: var(--bg);
    font: 600 14px var(--schrift);
  }
  .right.word:disabled {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-still);
  }
  /* An inner page: the way back on the left with its name, the title in the
     middle between two equal sides, so it stands centred however long the
     name on the left is. */
  .head.inner {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 0;
  }
  .head.inner .right {
    grid-column: 3;
    justify-self: end;
  }
  .head.inner .back {
    grid-column: 1;
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    width: auto;
    min-width: 44px;
    max-width: 100%;
    padding: 0 8px 0 0;
  }
  .head.inner .from {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font: 400 15px var(--schrift);
  }
  .head.inner h1 {
    grid-column: 2;
    max-width: 52vw;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: center;
  }
  .body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0 calc(8px + env(safe-area-inset-right)) env(safe-area-inset-bottom)
      calc(8px + env(safe-area-inset-left));
  }
</style>
