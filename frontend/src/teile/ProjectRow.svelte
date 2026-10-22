<script>
  /* One project in the chat list: a named group that folds open.

     Its chats stand under it — the sidebar draws them, indented, in the
     order they were made. A chat row dragged here and let go moves into the
     project; the row lights up while one hovers over it, and only for a
     chat, not for a file or anything else being dragged across. */
  import Hauszeichen from './Hauszeichen.svelte'
  import { CHAT_DRAG_TYPE } from './Chatzeile.svelte'
  import { t } from '../lib/texte.svelte.js'

  let { project, open = false, onToggle, menu, onDropChat } = $props()

  let over = $state(false)

  function carriesChat(e) {
    return Array.from(e.dataTransfer?.types || []).includes(CHAT_DRAG_TYPE)
  }

  function dragOver(e) {
    if (!carriesChat(e)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    over = true
  }

  function drop(e) {
    over = false
    const chatId = e.dataTransfer?.getData(CHAT_DRAG_TYPE)
    if (!chatId) return
    e.preventDefault()
    onDropChat(chatId)
  }

  /* The menu opens under the dots, the same way a chat row's does. */
  function more(e) {
    e.stopPropagation()
    const edge = e.currentTarget.getBoundingClientRect()
    menu({ preventDefault() {}, clientX: edge.left, clientY: edge.bottom + 4 }, project)
  }
</script>

<button
  class="project"
  class:over
  aria-expanded={open}
  onclick={onToggle}
  oncontextmenu={(e) => menu(e, project)}
  ondragover={dragOver}
  ondragleave={() => (over = false)}
  ondrop={drop}
>
  <span class="chevron" class:open><Hauszeichen zeichen="pfeil_unten" groesse={12} strich={2.6} /></span>
  <Hauszeichen zeichen="ordner" groesse={17} />
  <span class="name">{project.name}</span>
  <!-- A span for the same reason as in the chat row: a button inside a
       button is forbidden. -->
  <span
    class="more"
    role="button"
    tabindex="0"
    title={t('app.mehr')}
    aria-label={t('app.mehr')}
    onclick={more}
    onkeydown={(e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        more(e)
      }
    }}
  >
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" />
    </svg>
  </span>
</button>

<style>
  .project {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 7px 8px 7px 10px;
    border: none;
    border-radius: 9px;
    margin-bottom: 1px;
    font: inherit;
    font-size: var(--schrift-text);
    font-weight: 500;
    text-align: left;
    background: none;
    /* On the frame it wears the frame's ink; on its own hover ground the
       look's ink comes back. */
    color: var(--rahmen-text, var(--text));
    cursor: pointer;
    transition: background 0.12s;
  }
  .project:hover {
    background: var(--bg-erhoben);
    color: var(--text);
  }
  /* A chat hovering over the row, about to be let go: the running blue,
     quietly, the way a live drop target reads everywhere in the house. */
  .project.over {
    background: color-mix(in srgb, var(--blau) 22%, transparent);
  }
  .chevron {
    display: inline-flex;
    /* On the frame it wears the frame's ink; the hovered row has its own
       ground and keeps the look's. */
    color: var(--rahmen-text, var(--text-still));
    transform: rotate(-90deg);
    transition: transform 0.2s;
  }
  /* Only the hovered row has a ground of its own; keyboard focus does not
     (the name beside it keeps the frame's ink, and so does the mark). */
  .project:hover .chevron {
    color: var(--text-still);
  }
  .chevron.open {
    transform: none;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .more {
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
  .project:hover .more,
  .project:focus-within .more {
    opacity: 1;
  }
  /* The row's own hover ground brings the look's ink back. */
  .project:hover .more {
    color: var(--text-still);
  }
  @media (hover: none), (any-pointer: coarse) {
    .more {
      opacity: 1;
    }
  }
  .more:hover,
  .more:focus-visible {
    background: var(--bg-hoch);
    color: var(--text);
  }
  @media (prefers-reduced-motion: reduce) {
    .chevron { transition: none; }
  }
</style>
