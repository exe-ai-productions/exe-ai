<script>
  /* The sign that asks for a newer build of a program, and fetches it once
     one is found — one button for both steps, in the version row of every
     program the windows carry (llama.cpp and sd.cpp).

     The first press only asks: nothing is fetched. If a newer build exists
     the sign turns yellow (`found`) and waits; the second press fetches it.
     Where nothing newer exists the row says so beside the sign, and the sign
     stays quiet and asks again when pressed. While a check or a fetch runs
     the sign is locked.

     The name and the tooltip are the word, since the button carries no text
     of its own. */
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'

  let { found = false, locked = false, oncheck = null, onupdate = null } = $props()
</script>

<button class="updatezeichen" class:gefunden={found} disabled={locked}
        title={t('bildserver.generator_aktualisieren')}
        aria-label={t('bildserver.generator_aktualisieren')}
        onclick={() => (found ? onupdate?.() : oncheck?.())}>
  <Hauszeichen zeichen="update_available" groesse={16} />
</button>

<style>
  .updatezeichen {
    flex: none;
    width: 30px;
    height: 30px;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .updatezeichen:hover:not(:disabled) {
    background: var(--glass-hover);
    color: var(--text);
  }
  /* A newer build was found and waits for the second press: the colour of
     a wait. */
  .updatezeichen.gefunden,
  .updatezeichen.gefunden:hover:not(:disabled) {
    color: var(--gelb);
  }
  .updatezeichen:disabled {
    cursor: default;
    opacity: 0.5;
  }
</style>
