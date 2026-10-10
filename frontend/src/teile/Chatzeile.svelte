<script module>
  /* What a row carries while it is dragged: only the chat's id. A project
     row takes a drop of this type and no other (ProjectRow.svelte). */
  export const CHAT_DRAG_TYPE = 'application/x-exe-chat'
</script>

<script>
  /* One row of the chat list.

     It used to stand twice in the sidebar, once for the pinned chats and
     once for the rest — two copies that had to be changed in step, and
     every state the row learns would have doubled that work. Here it is
     one thing, and the difference between the two lists is a single flag.

     The row reads from left to right in the order one needs it: what the
     conversation is called, then — under the hand — the door to its menu,
     then what the conversation is doing right now. The dot stands only
     when the chat has something to report and sits last on purpose: at the
     right edge it lines up down the whole list, and its box stays even
     while empty, so nothing shifts under the hand. A pinned chat carries no
     mark of its own; the heading it stands under says it. */
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { ringFarbe } from '../lib/chatringe.svelte.js'
  import { punktAtmet } from '../lib/meldewesen.svelte.js'

  /* What each colour is called. On the module and not inside the component:
     a list of thirty chats would otherwise build thirty copies of the same
     four entries. */
  const RINGTEXTE = {
    gelb: 'chat.wartet_auf_dich',
    blau: 'chat.laeuft_gerade',
    rot: 'chat.lauf_gescheitert',
    gruen: 'chat.antwort_fertig',
  }

  /* `nested` indents the row under the project it lies in. */
  let { chat, oeffnen, menue, nested = false } = $props()

  const farbe = $derived(ringFarbe(chat.id))
  const punkttext = $derived(RINGTEXTE[farbe] ? t(RINGTEXTE[farbe]) : '')

  /* The menu opens under the dots, wherever the hand pressed — a key has no
     pointer position, so the mark's own corner stands in for it. */
  function mehr(e) {
    e.stopPropagation()
    const rand = e.currentTarget.getBoundingClientRect()
    menue({ preventDefault() {}, clientX: rand.left, clientY: rand.bottom + 4 }, chat)
  }
</script>

<button
  class="chat"
  class:aktiv={chat.id === zustand.aktiverChat}
  class:nested
  draggable="true"
  onclick={() => oeffnen(chat.id)}
  oncontextmenu={(e) => menue(e, chat)}
  ondragstart={(e) => {
    e.dataTransfer.setData(CHAT_DRAG_TYPE, chat.id)
    e.dataTransfer.effectAllowed = 'move'
  }}
>
  <span class="titel">{chat.title}</span>
  <!-- The door to the row's menu, only under the hand; the right click opens
       the same menu. A span, because a button inside a button is
       forbidden. -->
  <span
    class="mehr"
    role="button"
    tabindex="0"
    title={t('app.mehr')}
    aria-label={t('app.mehr')}
    onclick={mehr}
    onkeydown={(e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        mehr(e)
      }
    }}
  >
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" />
    </svg>
  </span>
  <span class="punkt" title={punkttext || null} aria-label={punkttext || null}>
    <!-- The row's four states all mean "this wants you": a question
         standing, an answer running, a run that fell over, an answer
         nobody has opened. A row with nothing to report shows no dot. -->
    {#if punkttext}
      <Leuchtpunkt {farbe} groesse={11} atmet={punktAtmet('chat', farbe)} />
    {/if}
  </span>
</button>

<style>
  .chat {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 7px 8px 7px 10px;
    border: none;
    border-radius: 9px;
    margin-bottom: 1px;
    font: inherit;
    /* The list reads at the size of the program's text. */
    font-size: var(--schrift-text);
    text-align: left;
    background: none;
    /* On the frame it wears the frame's ink; hover and actives bring their
       own ground and take the look's ink back. */
    color: var(--rahmen-text, var(--text-leise));
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .chat:hover {
    background: var(--bg-erhoben);
    color: var(--text);
  }
  /* The chosen row wears glass with a fine edge, inset so the row keeps
     its height. */
  .chat.aktiv {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .chat.nested {
    padding-left: 34px;
  }
  .titel {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  /* The dot sits INSIDE the row, right-aligned against the row's own
     padding and centred on its height, the same distance from the edge
     whether the row is hovered or not. The box is wider than the dot so its
     glow has somewhere to fall without touching the row's edge. */
  .punkt {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
  }
  /* Invisible until the hand is on the row, but it keeps its box, so the
     title does not jump when it appears. */
  .mehr {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 9px;
    color: var(--rahmen-text, var(--text-still));
    opacity: 0;
    cursor: pointer;
    transition: opacity 0.12s, background 0.12s, color 0.12s;
  }
  /* The row's own hover ground brings the look's ink back. */
  .chat:hover .mehr {
    color: var(--text-still);
  }
  .chat:hover .mehr,
  .chat:focus-within .mehr {
    opacity: 1;
  }
  /* A touch screen has no hover: there the dots stay in sight, or a tap at
     the row's right edge would open a menu nobody saw. */
  @media (hover: none) {
    .mehr {
      opacity: 1;
    }
  }
  .mehr:hover,
  .mehr:focus-visible {
    background: var(--bg-hoch);
    color: var(--text);
  }
</style>
