<script>
  /* The greeting of the empty chat — centred under the wordmark (App.svelte,
     `.anlauf .marke`), with the weekday and date quietly below it. It stays
     in the wordmark's box and folds away with it on send, so the group
     shrinks in one motion instead of jumping first; the corner above stays
     empty.

     The name wears the user's own message colour (white when none is
     chosen): that colour already means "you" in the chat, so the accent
     comes from the house instead of decorating. The split marker keeps the
     name a separate span however the translation arranges the sentence. */
  import { zustand } from '../lib/zustand.svelte.js'
  import { begruessung, grussSchluessel } from '../lib/begruessung.svelte.js'
  import { t, texte } from '../lib/texte.svelte.js'

  const MARKE = '\u0000'
  const teile = $derived.by(() => {
    const satz = t(grussSchluessel(), { name: MARKE })
    const [vor, nach] = satz.split(MARKE)
    return { vor, nach: nach ?? '' }
  })
  const datum = $derived(
    new Date().toLocaleDateString(texte.sprache === 'de' ? 'de-DE' : 'en-GB', {
      weekday: 'long', day: 'numeric', month: 'long',
    })
  )
</script>

{#if begruessung.an && begruessung.name}
  <div class="gruss">
    <div class="zeile">{teile.vor}<b style:color={zustand.blasenfarbe || 'var(--text)'}>{begruessung.name}</b>{teile.nach}</div>
    <div class="datum">{datum}</div>
  </div>
{/if}

<style>
  .gruss {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    margin-top: 16px;
    text-align: center;
  }
  .zeile {
    font-size: 13.5px;
    color: var(--text-leise);
  }
  .zeile b {
    font-weight: 500;
  }
  .datum {
    font-size: 12px;
    color: var(--text-still);
  }
</style>
