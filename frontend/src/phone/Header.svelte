<script>
  /* The head of the phone page: the chat list on the left, the mark and the
     name of the house in the middle, the context ring and a new chat on the
     right. The head stands on the frame under the status bar and is as tall
     as a list row; the chat under it is a tile of its own, and the edge of
     that tile is the line between the two.

     The model is chosen in the plus sheet of the bar (AttachSheet.svelte);
     the tools of the work bar are rows at the foot of the chat list
     (Drawer.svelte). */
  import { t } from '../lib/texte.svelte.js'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import ContextRing from '../teile/ContextRing.svelte'
  import Wortmarke from '../teile/Wortmarke.svelte'
  import { neuerChat } from '../lib/zustand.svelte.js'
  import { newChatIdle } from '../lib/newChatIdle.svelte.js'
  import { drawerSet } from './phone.svelte.js'

  // Nothing would happen on a click: the button says so instead of lying.
  const idle = $derived(newChatIdle())
</script>

<header class="head">
  <div class="left">
    <button class="icon" onclick={() => drawerSet(true)} aria-label={t('phone.chat_list')}>
      <!-- The sidebar sign of the house catalogue: a window with its left
           column. -->
      <svg width="24" height="24" viewBox="0 0 64 64" fill="none" stroke="currentColor"
           stroke-width="5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="9" y="13" width="46" height="38" rx="8" />
        <path d="M25 13 V51" />
      </svg>
    </button>
  </div>
  <Wortmarke hoehe={26} />
  <div class="right">
    <ContextRing tippbar />
    <button class="icon" class:idle aria-disabled={idle}
            onclick={() => { if (!idle) neuerChat() }} aria-label={t('chat.neu')}>
      <Hauszeichen zeichen="plus" groesse={24} />
    </button>
  </div>
</header>

<style>
  /* Three columns, the middle one as wide as its content: the mark stays in
     the middle whatever stands on either side. */
  .head {
    flex: none;
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    height: calc(52px + env(safe-area-inset-top));
    padding: env(safe-area-inset-top) calc(6px + env(safe-area-inset-right)) 0
      calc(6px + env(safe-area-inset-left));
    color: var(--text);
  }
  .left,
  .right {
    display: flex;
    align-items: center;
  }
  .right {
    justify-content: flex-end;
  }
  .icon {
    flex: none;
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
  }
  .icon:active {
    background: var(--glass-button);
  }
  /* The house's one look for a button that has nothing to do: half the
     strength, no ground under the finger. */
  .icon.idle {
    opacity: 0.5;
    cursor: default;
  }
  .icon.idle:active {
    background: none;
  }
</style>
