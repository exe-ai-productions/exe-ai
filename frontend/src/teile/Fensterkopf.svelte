<script>
  /* The head of a window body: a sign on its tile, the name, a short state
     beside the name, and the state pill at the right end. 36 px tall.

     The head stands before the name as either a maker's mark (`marke`, an
     embedded mark: its view box and its markup) on its own, 30 px, or — where
     none is known — a house sign (`zeichen`) on its tile. Never both: the
     mark wins where there is one. */
  import Hauszeichen from './Hauszeichen.svelte'
  import Standpille from './Standpille.svelte'

  let {
    zeichen = '',
    marke = null,
    titel = '',
    unter = '',
    standfarbe = 'still',
    standtext = '',
  } = $props()
</script>

<div class="kopf">
  {#if marke}
    <span class="marke" aria-hidden="true">
      <svg viewBox={marke.vb} width="30" height="30">{@html marke.html}</svg>
    </span>
  {:else if zeichen}
    <span class="kachel"><Hauszeichen {zeichen} groesse="mittel" /></span>
  {/if}
  <div class="name">
    <span class="titel">{titel}</span>
    {#if unter}
      <span class="unter">{unter}</span>
    {/if}
  </div>
  {#if standtext}
    <Standpille farbe={standfarbe}>{standtext}</Standpille>
  {/if}
</div>

<style>
  .kopf {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 36px;
  }
  .kachel {
    flex: none;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border-radius: 9px;
    background: var(--bg-erhoben);
    color: var(--text);
  }
  .marke {
    flex: none;
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
  }
  .name {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: baseline;
    gap: 12px;
  }
  .titel {
    min-width: 0;
    font: 600 var(--schrift-seitentitel) var(--schrift);
    letter-spacing: -0.01em;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .unter {
    min-width: 0;
    font-size: var(--schrift-hinweis);
    line-height: 1.3;
    color: var(--text-still);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
