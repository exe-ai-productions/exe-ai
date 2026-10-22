<script>
  /* The plus of the bar, as a sheet from the bottom. Three tiles for what
     comes from the phone (the camera, the photos, files); below them what
     the chat works with and how — the model, how long it thinks, how far it
     may go with tools; then the shared working folders and the skills. A row
     opens its choices under itself, only the model's row leads to a second
     step in the same sheet: the list of models, with a way back.

     What is chosen goes to the same place the desktop's file menu sends it
     (lib/eingabe.svelte.js), the folders, the mode and the model are the
     shared ones (lib/arbeitsordner.svelte.js, lib/berechtigungsmodus.svelte.js,
     lib/modelle.svelte.js). */
  import { untrack } from 'svelte'
  import Sheet from './Sheet.svelte'
  import ModelList from './ModelList.svelte'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import Arbeitsordner from '../teile/Arbeitsordner.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { chatEingabe } from '../lib/eingabe.svelte.js'
  import { aktuellesModell, modellWaehlen } from '../lib/zustand.svelte.js'
  import { auswahlLaden, sichtbare } from '../lib/modelle.svelte.js'
  import { skills, skillsLaden, gefiltert } from '../lib/skills.svelte.js'
  import {
    ordnerListe, ordnerName, ordnerZustand, ordnerLoesen, maskeOeffnen, ersatzBeginnen,
  } from '../lib/arbeitsordner.svelte.js'
  import {
    berechtigungsmodus, berechtigungsmodusLaden, modusOptionen, berechtigungsmodusSetzen,
  } from '../lib/berechtigungsmodus.svelte.js'

  let { open = false, onclose, onskill } = $props()

  const canSeePictures = $derived(chatEingabe.visionFaehig)
  const pictureTypes = $derived(chatEingabe.BILD_TYPEN.join(','))
  const folders = $derived(ordnerListe())
  const missing = $derived(new Set(ordnerZustand.fehlend))
  const modes = $derived(modusOptionen('chat'))
  const modeName = $derived(modes.find(([value]) => value === berechtigungsmodus.chat)?.[1] ?? '')
  /* The commands the window carries out itself (compacting the chat) stand
     in front of the skills, as in the desktop's list. */
  const list = $derived(skills.geladen ? gefiltert('') : [])

  const model = $derived(aktuellesModell())
  /* The green dot says the chosen model can be reached: it stands only while
     the model is among those the service offers (the desktop picker draws the
     same line between the offered and the one only still named). */
  const reachable = $derived(Boolean(model) && sichtbare().some((offered) => offered.id === model.id))
  /* How long the model thinks: the stages it knows, or the one word that
     says it always or never does. */
  const profile = $derived(chatEingabe.denkprofil)
  const stages = $derived(chatEingabe.denkFaehig ? (profile?.stufen ?? []) : [])
  const stageWord = (stage) => t(`denken.stufe.${stage}`)
  const fixedWord = $derived(
    profile?.art === 'immer' ? t('denken.immer') : profile?.art === 'nie' ? t('denken.nie') : '',
  )

  /* Which step the sheet shows, and which of the rows shows its choices. */
  let step = $state('main')
  let section = $state(null)
  function toggle(name) {
    section = section === name ? null : name
  }

  $effect(() => {
    if (!open) return
    /* Untracked: a list that finishes loading must not shut the row the
       person has just opened. The models are read anew at every opening: a
       model switched off elsewhere must not be offered. */
    untrack(() => {
      step = 'main'
      section = null
      void berechtigungsmodusLaden()
      void auswahlLaden()
      if (!skills.geladen) void skillsLaden()
    })
  })

  let camera = $state(null)
  let photos = $state(null)
  let files = $state(null)

  function chosen(event) {
    chatEingabe.filesChosen([...(event.currentTarget.files || [])])
    // The same file can be chosen again straight after.
    event.currentTarget.value = ''
    onclose?.()
  }
  function pickSkill(name) {
    onskill?.(name)
    onclose?.()
  }
  function pickModel(id) {
    modellWaehlen(id)
    step = 'main'
  }
</script>

<input type="file" accept={pictureTypes} capture="environment" bind:this={camera} onchange={chosen} hidden />
<input type="file" accept={pictureTypes} multiple bind:this={photos} onchange={chosen} hidden />
<input type="file" accept={chatEingabe.acceptedFiles} multiple bind:this={files} onchange={chosen} hidden />

<Sheet {open} {onclose} label={step === 'models' ? t('modell.titel') : t('eingabe.attach_files')}>
  {#if step === 'models'}
    <div class="stephead">
      <button class="back" onclick={() => (step = 'main')} aria-label={t('app.zurueck')}>
        <span class="arrow"><Hauszeichen zeichen="pfeil_unten" groesse={14} strich={2.6} /></span>
      </button>
      <span class="steptitle">{t('modell.titel')}</span>
    </div>
    <ModelList onpick={pickModel} />
  {:else}
    <div class="tiles">
      <button class="tile" disabled={!canSeePictures} onclick={() => camera?.click()}>
        <Hauszeichen zeichen="kamera" groesse={22} strich={1.8} />
        <span>{t('phone_chat.camera')}</span>
      </button>
      <button class="tile" disabled={!canSeePictures} onclick={() => photos?.click()}>
        <Hauszeichen zeichen="bild" groesse={22} strich={1.8} />
        <span>{t('phone_chat.photos')}</span>
      </button>
      <button class="tile" disabled={!chatEingabe.acceptedFiles} onclick={() => files?.click()}>
        <Hauszeichen zeichen="dokument" groesse={22} strich={1.8} />
        <span>{t('phone_chat.files')}</span>
      </button>
    </div>
    <p class="hint">{chatEingabe.filesHint}</p>

    <!-- The model, how long it thinks and how far it may go with tools. -->
    <div class="group">
      <button class="row" onclick={() => (step = 'models')}>
        <span class="sign"><Hauszeichen zeichen="server" groesse={20} strich={1.8} /></span>
        <span class="label">{t('modell.titel')}</span>
        <span class="value">
          {#if reachable}<span class="dot" aria-hidden="true"></span>{/if}
          <span class="valuetext">{model?.name ?? t('fehler.kein_modell_verfuegbar')}</span>
        </span>
        <span class="chevron next"><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
      </button>

      <div class="row plain">
        <span class="sign"><Hauszeichen zeichen="gluehbirne" groesse={20} strich={1.8} /></span>
        <span class="label">{t('eingabe.denken')}</span>
        {#if stages.length}
          <div class="segment" role="radiogroup" aria-label={t('eingabe.denken')}>
            {#each stages as stage (stage)}
              <button role="radio" aria-checked={stage === chatEingabe.denkStufe}
                      class:on={stage === chatEingabe.denkStufe}
                      onclick={() => chatEingabe.denkenSetzen(stage)}>{stageWord(stage)}</button>
            {/each}
          </div>
        {:else}
          <span class="value"><span class="valuetext">{fixedWord}</span></span>
        {/if}
      </div>

      <button class="row" aria-expanded={section === 'mode'} onclick={() => toggle('mode')}>
        <span class="sign"><Hauszeichen zeichen="schild" groesse={20} strich={1.8} /></span>
        <span class="label">{t('berechtigungen.modus_beschriftung')}</span>
        <span class="value"><span class="valuetext">{modeName}</span></span>
        <span class="chevron" class:open={section === 'mode'}><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
      </button>
      {#if section === 'mode'}
        <div class="choices">
          {#each modes as [value, name] (value)}
            <button class="choice" role="menuitemradio" aria-checked={value === berechtigungsmodus.chat}
                    onclick={() => berechtigungsmodusSetzen('chat', value)}>
              <span class="check">
                {#if value === berechtigungsmodus.chat}<Hauszeichen zeichen="haken" groesse={13} strich={2.6} />{/if}
              </span>
              <span class="label">{name}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- What the chat works with: the shared folders and the skills. -->
    <div class="group">
      <button class="row" aria-expanded={section === 'folder'} onclick={() => toggle('folder')}>
        <span class="sign"><Hauszeichen zeichen="ordner" groesse={20} strich={1.8} /></span>
        <span class="label">{t('arbeitsordner.titel')}</span>
        <span class="value"><span class="valuetext">{folders.length ? ordnerName(folders[0]) : ''}{folders.length > 1 ? ` +${folders.length - 1}` : ''}</span></span>
        <span class="chevron" class:open={section === 'folder'}><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
      </button>
      {#if section === 'folder'}
        <div class="choices">
          {#each folders as path (path)}
            <div class="choice" class:missing={missing.has(path)}>
              <span class="label">{ordnerName(path)}</span>
              {#if missing.has(path)}
                <button class="small" onclick={() => ersatzBeginnen(path)}>{t('arbeitsordner.neu_waehlen')}</button>
              {:else}
                <button class="mini" aria-label={t('arbeitsordner.loesen')} onclick={() => ordnerLoesen(path)}>
                  <Hauszeichen zeichen="kreuz" groesse={11} />
                </button>
              {/if}
            </div>
          {/each}
          <button class="choice add" onclick={maskeOeffnen}>
            <Hauszeichen zeichen="plus" groesse={14} />
            <span class="label">{t(folders.length ? 'arbeitsordner.hinzufuegen' : 'arbeitsordner.waehlen')}</span>
          </button>
        </div>
      {/if}

      <!-- The skills: a pick writes the command into the field. -->
      <button class="row" aria-expanded={section === 'skills'} onclick={() => toggle('skills')}>
        <span class="sign"><Hauszeichen zeichen="buch" groesse={20} strich={1.8} /></span>
        <span class="label">{t('skills.quelle')}</span>
        <span class="value"><span class="valuetext">{list.length || ''}</span></span>
        <span class="chevron" class:open={section === 'skills'}><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
      </button>
      {#if section === 'skills'}
        <div class="choices">
          {#each list as skill (skill.name)}
            <button class="choice" onclick={() => pickSkill(skill.name)}>
              <span class="label mono">/{skill.name}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</Sheet>

<!-- The mask that adds a folder; it stands over the sheet. -->
<Arbeitsordner />

<style>
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-width: 0;
    height: 72px;
    padding: 0 8px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 var(--schrift-hinweis) var(--schrift);
  }
  .tile:active {
    background: var(--bg-hoch);
  }
  .tile:disabled {
    opacity: 0.45;
  }
  .hint {
    margin: 8px 2px 12px;
    color: var(--text-still);
    font: var(--schrift-hinweis) var(--schrift);
  }
  /* The rows stand in cards of glass, as the lists of the settings do. */
  .group {
    display: flex;
    flex-direction: column;
    margin-bottom: 12px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    overflow: hidden;
  }
  .row,
  .choice {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    border: none;
    background: none;
    color: var(--text);
    font: 15px var(--schrift);
    text-align: left;
  }
  .row {
    min-height: var(--menuezeile, 52px);
    padding: 0 14px;
  }
  .group > :not(:first-child) {
    box-shadow: inset 0 1px 0 var(--glass-card-line);
  }
  .choice {
    min-height: 44px;
    padding: 0 10px;
    color: var(--text-leise);
    font-size: 14px;
  }
  .row:active,
  .choice:active {
    background: var(--glass-hover, var(--bg-hoch));
  }
  .row.plain:active {
    background: none;
  }
  .sign {
    flex: none;
    display: inline-flex;
    color: var(--text-leise);
  }
  .label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mono {
    font-family: var(--schrift-fest);
    font-size: 14px;
  }
  .value {
    flex: 0 1 auto;
    min-width: 0;
    max-width: 52%;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--text-leise);
    font-size: 14px;
  }
  .valuetext {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* A chosen model is ready: green, the house's colour for it. */
  .dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--gruen);
  }
  .chevron {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
    transition: transform 0.2s;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  /* The house arrow points down; turned a quarter it points on. */
  .chevron.next {
    transform: rotate(-90deg);
  }
  .segment {
    flex: 0 1 auto;
    min-width: 0;
    display: inline-flex;
    padding: 2px;
    border-radius: 8px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    overflow-x: auto;
    scrollbar-width: none;
  }
  .segment button {
    flex: none;
    padding: 5px 12px;
    border: none;
    border-radius: 6px;
    background: none;
    color: var(--text-leise);
    font: 13px var(--schrift);
  }
  .segment button.on {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .choices {
    display: flex;
    flex-direction: column;
    padding: 0 6px 6px 40px;
    max-height: 32dvh;
    overflow-y: auto;
  }
  .choice.missing .label {
    color: var(--gelb-text);
  }
  .check {
    flex: none;
    width: 16px;
    display: inline-flex;
    color: var(--text);
  }
  .mini,
  .small {
    flex: none;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
  }
  .mini {
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    border-radius: 50%;
  }
  .small {
    padding: 6px 10px;
    font: var(--schrift-hinweis) var(--schrift);
  }
  /* The second step: the way back and the name of what is chosen here. */
  .stephead {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-bottom: 4px;
  }
  .back {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
  }
  .back:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .arrow {
    display: inline-flex;
    transform: rotate(90deg);
  }
  .steptitle {
    font: 600 16px var(--schrift);
  }
</style>
