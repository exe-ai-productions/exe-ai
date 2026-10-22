<script>
  /* How the program looks on the phone: Exe, Pearl, Snow, or whichever the
     device is on; the colours of code and the colour of the own bubbles.
     The look is held by the phone page (it saves what is chosen here); the
     code colours and the bubble are the desktop's own settings, written
     through the same calls. */
  import { tick } from 'svelte'
  import { t } from '../../lib/texte.svelte.js'
  import { zustand, codefarbenSetzen, blasenfarbeSetzen } from '../../lib/zustand.svelte.js'
  import { CODE_PACKS, blasenStandard } from '../../lib/darstellungswerte.js'
  import { lookPick, pickLook } from '../phone.svelte.js'
  import { shownLook } from '../settings.js'
  import Group from '../parts/Group.svelte'
  import Pick from '../parts/Pick.svelte'
  import Action from '../parts/Action.svelte'

  const looks = $derived([
    { value: 'auto', label: t('einstellungen.auto') },
    { value: 'dunkel', label: t('einstellungen.dunkel') },
    { value: 'hell', label: t('einstellungen.hell') },
    { value: 'snow', label: t('einstellungen.snow') },
  ])
  const packs = $derived(CODE_PACKS.map(([value, key]) => ({ value, label: t(key) })))
  /* Whatever look the desktop stands on besides these three is shown on the
     phone as Exe, so the row says Exe for it. */
  const shown = $derived(shownLook(lookPick.mode))
  /* The default bubble colour is the look's: read again after every change
     of the look the page draws (a new choice, or the device turning light or
     dark under "auto"), once the page has put the new one on. */
  let standard = $state(blasenStandard())
  $effect(() => {
    void lookPick.drawn
    tick().then(() => {
      const value = blasenStandard()
      if (value !== standard) standard = value
    })
  })
  const bubble = $derived(zustand.blasenfarbe || standard)
</script>

<Group>
  <Pick label={t('einstellungen.erscheinungsbild')} value={shown} options={looks} onpick={pickLook} />
  <Pick label={t('einstellungen.codefarben')} value={zustand.codefarben} options={packs}
        onpick={(value) => codefarbenSetzen(value)} />
  <label class="color">
    <span>{t('einstellungen.blase')}</span>
    <input type="color" value={bubble} aria-label={t('einstellungen.blase')}
           oninput={(event) => blasenfarbeSetzen(event.currentTarget.value)} />
  </label>
  {#if zustand.blasenfarbe}
    <Action label={t('einstellungen.blase_standard')} onclick={() => blasenfarbeSetzen('')} />
  {/if}
</Group>

<style>
  .color {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: var(--menuezeile);
    padding: 6px 12px 6px 10px;
    color: var(--text-leise);
    font: 500 var(--schrift-text) var(--schrift);
  }
  .color span {
    flex: 1;
  }
  .color input {
    width: 44px;
    height: 32px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
  }
</style>
