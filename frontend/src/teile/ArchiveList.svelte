<script>
  /* The archive: chats and projects put away instead of deleted.

     It stands under the chats with the number of its entries and opens in
     place. A project is one entry and carries its chats along, so they are
     counted under it, not beside it. Each entry opens the menu that brings
     it back or deletes it for good — deleting happens here and nowhere
     else. Without entries the row is not there at all. */
  import { slide } from 'svelte/transition'
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'

  let { menu } = $props()

  let open = $state(false)

  const count = $derived(zustand.archive.projects.length + zustand.archive.chats.length)

  /* A click on an entry opens its menu where the hand is. It stops here:
     the sidebar closes every menu on a click that reaches the window. */
  function entryMenu(e, kind, item) {
    e.stopPropagation()
    menu(e, kind, item)
  }
</script>

{#if count}
  <div class="archive">
    <button class="head" aria-expanded={open} onclick={() => (open = !open)}>
      <Hauszeichen zeichen="archive" groesse={15} />
      <span class="label">{t('archive.title')}</span>
      <small>{count}</small>
    </button>
    {#if open}
      <div transition:slide={{ duration: 160 }}>
        {#each zustand.archive.projects as project (project.id)}
          <button
            class="entry"
            onclick={(e) => entryMenu(e, 'archived-project', project)}
            oncontextmenu={(e) => entryMenu(e, 'archived-project', project)}
          >
            <Hauszeichen zeichen="ordner" groesse={16} />
            <span class="label">{project.name}</span>
            <small>{project.chat_count}</small>
          </button>
        {/each}
        {#each zustand.archive.chats as chat (chat.id)}
          <button
            class="entry"
            onclick={(e) => entryMenu(e, 'archived-chat', chat)}
            oncontextmenu={(e) => entryMenu(e, 'archived-chat', chat)}
          >
            <span class="label">{chat.title}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .archive {
    margin-top: 8px;
    padding-bottom: 8px;
  }
  .head,
  .entry {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 7px 8px 7px 10px;
    border: none;
    border-radius: 9px;
    margin-bottom: 1px;
    font: inherit;
    font-size: 13px;
    text-align: left;
    background: none;
    /* On the frame it wears the frame's ink; hovered or opened rows bring
       their own ground and take the look's ink back (below). */
    color: var(--rahmen-text, var(--text-leise));
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .head:hover,
  .entry:hover,
  .head[aria-expanded='true'] {
    background: var(--bg-erhoben);
    color: var(--text);
  }
  .entry {
    padding-left: 34px;
  }
  .label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  small {
    flex: none;
    color: var(--rahmen-text, var(--text-still));
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  /* Hovered or opened rows have a ground of their own and keep the ink. */
  .head:hover small,
  .entry:hover small,
  .head[aria-expanded='true'] small {
    color: var(--text-still);
  }
</style>
