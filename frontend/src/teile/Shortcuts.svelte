<script>
  /* The "Shortcuts" page of the settings: the microphone key, which can be
     assigned, and every other shortcut the program has, to look up.

     The rows to look up come from lib/shortcutList.js, by the system the
     page runs on. Four groups, in the order the settings name them; the
     tile is declared here as well, a component cannot borrow its parent's
     scoped styles (Meldewahl.svelte does the same). */
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { diktat, standLaden, werteSetzen } from '../lib/diktat.svelte.js'
  import { DEFAULT_KEY, inUse, recorder, showCombo, showKeys } from '../lib/microphoneKey.js'
  import { keyNames, system } from '../lib/keyNames.js'
  import { shortcutList } from '../lib/shortcutList.js'
  import { layout, refreshLayout } from '../lib/keyboardLayout.svelte.js'

  /* The keys as the system under the page has them: the Mac's signs, or
     off the Mac the words printed on the keys (lib/keyNames.js). */
  const names = $derived(keyNames())
  const groups = $derived(shortcutList(system, names))

  $effect(() => {
    standLaden()
  })

  const current = $derived(diktat.microphone_key || DEFAULT_KEY)

  /* Recording a new key. While the field listens it takes every key press
     for itself — in the capture phase, before the page's own shortcuts and
     the microphone key's listener see it — until a usable combination is
     complete, Escape is pressed or the field loses focus. */
  let recording = $state(false)
  let field = $state(null)
  let taking = null

  function start() {
    /* Read the layout afresh before every recording: it can be switched
       while the page stands open, and the recorder judges every press by
       the one holder as well (lib/keyboardLayout.svelte.js). */
    refreshLayout()
    taking = recorder(() => layout.map, system)
    recording = true
  }

  function stop() {
    recording = false
    taking = null
  }

  async function store(combo) {
    stop()
    if (combo === current) return
    try {
      await werteSetzen({ microphone_key: combo })
    } catch {
      melde(t('fehler.einstellung_speichern'), 'fehler')
    }
  }

  function swallow(event) {
    event.preventDefault()
    event.stopImmediatePropagation()
  }

  $effect(() => {
    if (!recording) return
    const down = (event) => {
      swallow(event)
      if (event.code === 'Escape') {
        stop()
        field?.blur()
        return
      }
      const combo = taking?.down(event)
      if (combo) store(combo)
    }
    const up = (event) => {
      swallow(event)
      const combo = taking?.up(event)
      if (combo) store(combo)
    }
    window.addEventListener('keydown', down, true)
    window.addEventListener('keyup', up, true)
    return () => {
      window.removeEventListener('keydown', down, true)
      window.removeEventListener('keyup', up, true)
    }
  })
</script>

<div class="bloecke">
  <section class="block">
    <div class="blocktitel tafelkopf">{t('shortcuts.group_microphone')}</div>
    <div class="kachelliste">
      <div class="einstellkachel">
        <span class="mikrozeichen"><Hauszeichen zeichen="microphone" /></span>
        <div class="zeilentext">{t('shortcuts.microphone_assignable')}</div>
        <!-- The key field: shows the key, and listens for a new one once
             clicked. Empty while it listens — nothing stands in it that
             could be read as a key. -->
        <button
          class="taste belegbar"
          class:hoert={recording}
          bind:this={field}
          onclick={() => (recording ? stop() : start())}
          onblur={stop}
          aria-label={t('shortcuts.microphone_assignable')}
          aria-pressed={recording}
        >{recording ? '' : showCombo(current, layout.map, names)}</button>
        <!-- The stored key, under the switched-on layout, is a shortcut of
             the program's: the program's wins, this key does nothing, and
             the field says so until a new key is chosen. The word stands
             before the field, so the fields of both rows keep their
             column. -->
        {#if inUse(current, layout.map, system)}
          <span class="belegt">{t('shortcuts.in_use')}</span>
        {/if}
      </div>
      <div class="einstellkachel">
        <span class="mikrozeichen"><Hauszeichen zeichen="microphone" /></span>
        <div class="zeilentext">{t('shortcuts.microphone_anywhere')}</div>
        <span class="taste">{showKeys(['Mod', 'Shift'], 'M', names)}</span>
      </div>
    </div>
  </section>
  {#each groups as group (group.title)}
    <section class="block">
      <div class="blocktitel tafelkopf">{t(group.title)}</div>
      <div class="kachelliste">
        {#each group.rows as [name, keys] (name)}
          <div class="einstellkachel">
            <div class="zeilentext">{t(name)}</div>
            <span class="taste">{keys}</span>
          </div>
        {/each}
      </div>
    </section>
  {/each}
</div>

<style>
  .bloecke {
    display: flex;
    flex-direction: column;
    gap: 26px;
  }
  .block {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .blocktitel {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 2px;
  }
  .blocktitel::after {
    content: '';
    flex: 1;
    border-top: 1px solid var(--linie);
  }
  .kachelliste {
    display: flex;
    flex-direction: column;
    padding: 0 16px;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
  }
  .einstellkachel {
    padding: 10px 0;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .einstellkachel + .einstellkachel {
    border-top: 1px solid var(--linie);
  }
  .zeilentext {
    flex: 1;
    min-width: 0;
    font-size: 13px;
  }
  .mikrozeichen {
    flex: none;
    display: grid;
    color: var(--text-leise);
  }
  /* The keys as a fact: the fixed-width face in the quiet ink, the way a
     menu shows its shortcuts beside its entries. */
  .taste {
    flex: none;
    min-width: 56px;
    padding: 4px 8px;
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text-leise);
    font-family: var(--schrift-fest);
    font-size: 12.5px;
    text-align: center;
  }
  .belegbar {
    min-height: 26px;
    border: 1px solid var(--linie);
    color: var(--text);
    cursor: pointer;
  }
  .belegbar:hover {
    background: var(--glass-hover);
  }
  /* Listening for a new key: running, so blue. */
  .belegbar.hoert {
    border-color: var(--blau);
    box-shadow: 0 0 0 1px var(--blau);
  }
  /* A key the program has under the switched-on layout: a state of its
     own, so red, as every failure is. */
  .belegt {
    flex: none;
    font-size: 12.5px;
    color: var(--rot);
  }
</style>
