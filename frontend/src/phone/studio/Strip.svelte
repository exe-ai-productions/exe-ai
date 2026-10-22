<script>
  /* The strip of small pictures under the surface: the picture drawing now
     in front with its percentage and a bar, the waiting ones behind it, each
     with its way out, then the studio's pictures, newest first — and, first of
     the pictures, the one that came from outside, with its word. A tap on a
     picture brings the surface to it. The one on show wears a ring. */
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'

  /* `tiles` as `tilesOf` makes them; `shown` the key of the tile on show;
     `percent` the picture drawing now. `onpick(tile)`, `onremove(id)`;
     `onbroken(tile)`: a picture's file is gone. */
  let { tiles, shown, percent, onpick, onremove, onbroken } = $props()

  let strip = $state(null)
  /* What is on show stays in view: the strip follows a swipe of the surface. */
  $effect(() => {
    const key = shown
    if (!strip || !key) return
    const tile = [...strip.children].find((node) => node.dataset.key === key)
    tile?.scrollIntoView({ inline: 'nearest', block: 'nearest' })
  })
</script>

{#if tiles.length}
  <div class="strip" bind:this={strip} role="group" aria-label={t('studio.bilder')}>
    {#each tiles as tile (tile.key)}
      {#if tile.kind === 'waiting'}
        <div class="tile waiting" data-key={tile.key}>
          <button class="away" onclick={() => onremove?.(tile.id)} aria-label={t('bild.entfernen')}>
            <Hauszeichen zeichen="kreuz" groesse={14} />
          </button>
        </div>
      {:else if tile.kind === 'running'}
        <button class="tile run" class:on={shown === tile.key} data-key={tile.key}
                onclick={() => onpick?.(tile)}>
          {percent} %
          <span class="bar" style:width="{percent}%"></span>
        </button>
      {:else}
        <button class="tile pic" class:on={shown === tile.key} data-key={tile.key}
                onclick={() => onpick?.(tile)} aria-label={tile.original ? t('studio.original') : t('bild.als_eingabe')}>
          <img src={api.bildAdresse(tile.name)} alt="" loading="lazy" draggable="false"
               onerror={() => onbroken?.(tile)} />
          {#if tile.original}<span class="word">{t('studio.original')}</span>{/if}
        </button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .strip {
    flex: none;
    display: flex;
    gap: 8px;
    /* The ring of the tile on show lies outside it: room for it. */
    padding: 6px 14px 6px;
    overflow-x: auto;
    scrollbar-width: none;
    overscroll-behavior-x: contain;
  }
  .strip::-webkit-scrollbar {
    display: none;
  }
  .tile {
    position: relative;
    flex: 0 0 56px;
    width: 56px;
    height: 56px;
    padding: 0;
    border: none;
    border-radius: 7px;
    overflow: hidden;
    background: var(--bg-hoch);
    color: var(--text-leise);
    font: 600 11px var(--schrift);
  }
  .tile.on {
    overflow: visible;
    box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--text);
  }
  .pic img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 7px;
    pointer-events: none;
  }
  .word {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 2px 0;
    font: 600 9px var(--schrift);
    text-align: center;
    color: var(--text);
    background: var(--glass-dropdown);
  }
  .run {
    display: grid;
    place-items: center;
  }
  .bar {
    position: absolute;
    left: 0;
    bottom: 0;
    height: 3px;
    background: var(--blau);
  }
  .waiting {
    display: grid;
    place-items: center;
    border: 1.5px dashed var(--glass-button-edge);
    background: none;
  }
  .away {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    padding: 0;
    border: none;
    background: none;
    color: inherit;
  }
</style>
