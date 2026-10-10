<script>
  /* The "···" on a finished picture, and the one menu it opens — the same
     on a picture in the chat and on a picture in the picture window's
     gallery. The caller hands in the entries; a place that has more to say
     about its picture (the chat: save it, copy its seed) hands in more.

     Each entry is `{ text, action }`, or `{ text, href, download }` for a
     link; `value` puts a quiet value at the right end of the row.

     Opening it puts the focus on its first entry, the arrow keys walk the
     entries. It closes on a press anywhere else, on Tab, on Escape (which
     hands the focus back to its dots), and when the focus moves to
     something else. Only a move WITH a target counts: a click in Safari
     does not focus the button it lands on, and closing then would take the
     menu away under the click. No fade on the way out — its entries would
     stay focusable while they fade. The window is only listened to while
     it is open — a long chat holds many pictures, and each would otherwise
     keep two listeners for nothing. */
  import { t } from '../lib/texte.svelte.js'

  /* `zeile`: the dots stand in a list row instead of on a picture — quiet,
     in the row's own flow, with no glass behind them. */
  let { entries = [], zeile = false } = $props()

  let open = $state(false)
  let button = $state()
  let node = $state()

  /* An entry was used: the focus goes back to the dots before the menu
     goes, or it would fall to the page with the entry it stood on. */
  function close() {
    button?.focus()
    open = false
  }

  function choose(entry) {
    close()
    entry.action?.()
  }

  $effect(() => {
    if (!open) return
    const outside = (e) => {
      if (node?.contains(e.target) || button?.contains(e.target)) return
      open = false
    }
    const key = (e) => {
      const inside = node?.contains(document.activeElement) || document.activeElement === button
      if (!inside) return
      if (e.key === 'Escape') {
        e.stopPropagation()
        close()
        return
      }
      /* Leaving by key closes it: the focus goes back to the dots first,
         so Tab moves on from there — past the menu, not into it. Shift+Tab
         stops ON the dots, the stop right before the menu. */
      if (e.key === 'Tab') {
        if (e.shiftKey && node?.contains(document.activeElement)) e.preventDefault()
        close()
        return
      }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      const row = [...(node?.querySelectorAll('[role="menuitem"]') ?? [])]
      if (!row.length) return
      e.preventDefault()
      const at = row.indexOf(document.activeElement)
      const step = e.key === 'ArrowDown' ? 1 : -1
      const target = at < 0
        ? (step > 0 ? 0 : row.length - 1)
        : (at + step + row.length) % row.length
      row[target].focus()
    }
    node?.querySelector('[role="menuitem"]')?.focus()
    window.addEventListener('pointerdown', outside, true)
    window.addEventListener('keydown', key, true)
    return () => {
      window.removeEventListener('pointerdown', outside, true)
      window.removeEventListener('keydown', key, true)
    }
  })
</script>

{#if entries.length}
  <!-- The same hint as the chat row's "···", from the same text. -->
  <button class="more" class:zeile bind:this={button} aria-haspopup="menu" title={t('app.mehr')}
          aria-label={t('app.mehr')} aria-expanded={open} onclick={() => (open = !open)}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" />
    </svg>
  </button>
  {#if open}
    <div class="menu" class:zeile role="menu" tabindex="-1" bind:this={node}
         onfocusout={(e) => {
           const target = e.relatedTarget
           if (target && !node?.contains(target) && target !== button) open = false
         }}>
      {#each entries as entry (entry.text)}
        {#if entry.href}
          <a role="menuitem" href={entry.href} download={entry.download ?? ''}
             onclick={close}>{entry.text}</a>
        {:else}
          <button role="menuitem" onclick={() => choose(entry)}>
            {entry.text}
            {#if entry.value != null}<span class="menu-value">{entry.value}</span>{/if}
          </button>
        {/if}
      {/each}
    </div>
  {/if}
{/if}

<style>
  /* The dots stand on the picture itself, so they wear a dark glass of
     their own — readable on any picture, light or dark. The caller's
     picture frame is the positioned box they hang in. */
  .more {
    position: absolute;
    top: 8px;
    right: 8px;
    display: grid;
    place-items: center;
    width: 30px;
    height: 22px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: rgba(0, 0, 0, 0.45);
    color: #fff;
    cursor: pointer;
    transition: background 0.12s;
  }
  .more:hover,
  .more:focus-visible,
  .more[aria-expanded='true'] {
    background: rgba(0, 0, 0, 0.62);
  }
  /* In a list row: the row's quiet text colour, a ground only under the
     pointer. The row is still the positioned box the menu hangs from. */
  .more.zeile {
    position: static;
    flex: none;
    width: 24px;
    background: none;
    color: var(--text-still);
  }
  .more.zeile:hover,
  .more.zeile:focus-visible,
  .more.zeile[aria-expanded='true'] {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .menu.zeile {
    top: 40px;
    right: 16px;
  }
  /* The same raised card every menu in the program wears (Seitenleiste
     .svelte, `.kontextmenue`), opening under the dots. */
  .menu {
    position: absolute;
    top: 36px;
    right: 8px;
    z-index: 5;
    min-width: 170px;
    padding: 5px;
    border-radius: 9px;
    background: var(--bg-erhoben);
    box-shadow: 0 0 0 1px var(--linie), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
  }
  .menu a,
  .menu button {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 7px 11px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
  }
  .menu a:hover,
  .menu button:hover,
  .menu a:focus-visible,
  .menu button:focus-visible {
    background: var(--bg-hoch);
  }
  .menu-value {
    margin-left: auto;
    font-family: var(--schrift-fest);
    font-size: 11.5px;
    color: var(--text-still);
  }
</style>
