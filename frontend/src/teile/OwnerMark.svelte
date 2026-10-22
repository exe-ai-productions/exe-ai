<script>
  /* The mark in front of a model, a hit or an accessory — standing alone, with
     no tile behind it. Which one, in this order:

       1. `mark`, a logo the caller has already chosen (a catalogue card
          names its maker's logo),
       2. the logo the house has of `owner` (lib/logos.js, ownerLogo),
       3. the round picture of `owner` on Hugging Face, which the service
          fetches (lib/ownerPicture.svelte.js),
       4. the letter.

     A failed or missing picture leaves the letter and says nothing. */
  import { ownerLogo } from '../lib/logos.js'
  import { ownerPicture } from '../lib/ownerPicture.svelte.js'

  let { owner = '', mark = null, letter = '', size = 30 } = $props()

  const logo = $derived(mark ?? ownerLogo(owner))
  const picture = $derived(logo ? null : ownerPicture(owner))
  const shown = $derived(letter || String(owner || '').slice(0, 1).toUpperCase())
</script>

<span class="mark" style:width="{size}px" style:height="{size}px">
  {#if logo}
    <svg viewBox={logo.vb} width={size} height={size} aria-hidden="true">{@html logo.html}</svg>
  {:else if picture}
    <img class="round" src={picture} alt="" width={size} height={size} />
  {:else}
    <span class="letter">{shown}</span>
  {/if}
</span>

<style>
  .mark {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .round {
    border-radius: 50%;
    object-fit: cover;
    display: block;
  }
  /* The letter stands where a mark would, in the quiet colour: a place held,
     not a mark of its own. */
  .letter {
    color: var(--text-still);
    font: 700 13px var(--schrift);
  }
</style>
