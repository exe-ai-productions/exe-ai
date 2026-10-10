<script>
  /* The pictures module: every picture the generator has drawn, as a wall of
     thumbnails, and above them the folder they live in.

     It lives in the work rail beside the note, not in a window: the rail is
     the resizable side surface, so dragging it wider grows the pictures and
     narrower shrinks them — the tiles fill the width the way the document
     dock's do, only a size larger. The catalogue's folder mark opens the
     move-it dialog; the same glyph everywhere for "this is about a folder".

     Read fresh whenever the module is shown, never held between visits — the
     folder on disk is the truth, not a copy kept here. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { bildZeigen } from '../lib/bildschau.svelte.js'
  import Speicherortzeile from './Speicherortzeile.svelte'

  let bilder = $state([])
  let laedt = $state(false)

  async function laden() {
    laedt = true
    try {
      bilder = (await api.bilderListe()).bilder
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      laedt = false
    }
  }

  /* The module is mounted only while shown, so mounting is the moment to
     refresh: a picture drawn since the last look appears without a reload. */
  $effect(() => { laden() })

  /* The tiles come in one after the other, the way the design shows its
     eight: from the ninth on they arrive together, so a folder of hundreds
     is not a wall still building itself seconds later. */
  const STAGGERED = 8

  /* Dragging a picture toward the chat, the agents' shelf's road exactly
     (ModulAgenten): the name travels in the payload and the input bar
     fetches the bytes itself from the picture route. Its own data type, so
     a picture off this wall and a file off a dock cannot be mistaken for
     one another at the drop. */
  function ziehenStart(ereignis, name) {
    ereignis.dataTransfer.setData('application/x-exe-bild', name)
    ereignis.dataTransfer.effectAllowed = 'copy'
  }
</script>

<div class="modul">
  <div class="ordnerzeile">
    <Speicherortzeile name="images" etikett={t('bilder.bildordner')} onaendern={laden} />
  </div>

  <div class="rollen">
    {#if laedt && bilder.length === 0}
      <div class="tilewall"><p class="leer">{t('bilder.laedt')}</p></div>
    {:else if bilder.length === 0}
      <div class="tilewall"><p class="leer">{t('bilder.leer')}</p></div>
    {:else}
      <div class="tilewall">
        {#each bilder as name, index (name)}
          <button
            class="kachel kachel-ein"
            style:animation-delay="{Math.min(index, STAGGERED) * 0.05}s"
            draggable="true"
            ondragstart={(e) => ziehenStart(e, name)}
            onclick={() => bildZeigen(api.bildAdresse(name), { name, folder: 'images' })}
          >
            <img src={api.bildAdresse(name)} alt="" loading="lazy" draggable="false" />
          </button>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .modul {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
  }
  /* Just the frame around the shared folder row — the row draws itself. */
  .ordnerzeile {
    flex: none;
    padding: 12px 14px;
    border-bottom: none;
  }
  /* The wall of pictures scrolls; nothing else in the module does. */
  .rollen {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 12px 14px;
  }
  /* Grid, square, fade-in, the picture fill and the empty line are the
     shared wall — stil/tiles.css, the same one the doc folder stands in.
     Only what is ITS own stays here: the hand on the tile and its answer. */
  .kachel {
    padding: 0;
    cursor: pointer;
  }
  .kachel:hover { opacity: 0.88; }
</style>
