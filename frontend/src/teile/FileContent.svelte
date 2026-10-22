<script>
  /* The content of one file, drawn the one way both views draw it — the rail
     beside the chat and the reader over the window.

       code    the text with its colours and a number on every line; a long
               line breaks, and the number stands before the start of its
               line, once
       text    the text, as written
       image   a picture from the file's address (a drawing too: it is drawn
               by an image element, which runs no script in it)
       video   a player with its own controls, never starting by itself
       audio   the same for sound
       word    a Word document, drawn page by page
       sheet   a spreadsheet: a tab for each sheet above its values
       slides  a presentation: its slides one under the other

     The parent decides what the file is (lib/dateiarten.js, `fileKind`) and
     what holds this: a sheet in the rail, a page in the reader. The text
     arrives as `text`; a picture, a clip, a sound or an Office file as
     `address`, which the Office views read themselves. */
  import { hervorheben } from '../lib/einfaerben.js'
  import { zeilenReihen } from '../lib/markdown.js'
  import SheetView from './SheetView.svelte'
  import SlidesView from './SlidesView.svelte'
  import WordView from './WordView.svelte'

  let { kind, language = '', text = null, address = '', name = '' } = $props()

  /* Every written line is a row that draws its own number, so a line that
     breaks keeps one (the same rows an answer's code block uses, with the
     colours of the grammar of `language` where there is one). One line is
     numbered too. */
  const rows = $derived(kind === 'code' && text != null ? zeilenReihen(hervorheben(text, language)) : '')
  const digits = $derived(String((text ?? '').split('\n').length).length)
</script>

{#if kind === 'code'}
  <div class="codeblock nummeriert file-content-code" style:--ziffern={digits}>
    <pre><code>{@html rows}</code></pre>
  </div>
{:else if kind === 'text'}
  <p class="file-content-text">{text ?? ''}</p>
{:else if kind === 'image'}
  <img class="file-content-image" src={address} alt={name} draggable="false" />
{:else if kind === 'video'}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video class="file-content-video" src={address} controls preload="metadata" playsinline></video>
{:else if kind === 'audio'}
  <audio class="file-content-audio" src={address} controls preload="metadata"></audio>
{:else if kind === 'word'}
  <WordView {address} {name} />
{:else if kind === 'sheet'}
  <SheetView {address} {name} />
{:else if kind === 'slides'}
  <SlidesView {address} {name} />
{/if}

<style>
  .file-content-code {
    margin: 0;
    border: none;
  }
  /* A line breaks where it must, even one with no space in it: nothing
     rolls sideways, since the page shows no scrollbar to find the rest by. */
  .file-content-code :global(code) {
    min-width: 0;
    flex: 1;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .file-content-text {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  /* A picture or a clip is as wide as its holder lets it be and keeps its
     shape; nothing is cut off. */
  .file-content-image,
  .file-content-video {
    display: block;
    max-width: 100%;
    height: auto;
    margin: 0 auto;
    border-radius: 9px;
  }
  .file-content-audio {
    display: block;
    width: 100%;
  }
</style>
