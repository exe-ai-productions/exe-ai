<script>
  /* A text the person keeps and edits as a whole: the system prompt, the
     memory, the configuration file, the credentials and the tools file. The
     text stands over the full width; below it the small settings that belong
     to that text (the memory switches, the numbers of the system prompt) and
     the buttons. Loading and saving go through the same calls as the
     desktop's settings window; what is saved is what the service stores, so
     the field shows that afterwards. */
  import { untrack } from 'svelte'
  import { t } from '../../lib/texte.svelte.js'
  import { api } from '../../lib/api.js'
  import { melde, aktuellerChat, chatAendern } from '../../lib/zustand.svelte.js'
  import { begruessung, anredeSpeichern } from '../../lib/begruessung.svelte.js'
  import { useSettingsValues } from '../../lib/settingsvalues.svelte.js'
  import Zahlenfeld from '../../teile/Zahlenfeld.svelte'
  import Leuchtpunkt from '../../teile/Leuchtpunkt.svelte'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import Group from '../parts/Group.svelte'
  import Toggle from '../parts/Toggle.svelte'
  import Action from '../parts/Action.svelte'

  let { kind, dirty = $bindable(false) } = $props()

  const values = useSettingsValues()
  const chat = $derived(aktuellerChat())
  const source = $derived(['konfiguration', 'zugangsdaten', 'tools_datei'].includes(kind))

  let text = $state('')
  let loaded = $state('')
  let broken = $state(null)
  let placeholders = $state([])
  let live = $state(null)
  let busy = $state(true)
  /* Set when the text could not be read: the field stays shut, so an empty
     field is never taken for an empty file and saved over the real one. */
  let failed = $state(false)

  $effect(() => {
    dirty = text !== loaded
  })

  /* The catalogue key of the sentences of one kind: the system prompt, the
     memory, the two files and the tools file each speak in their own words. */
  function say(fall) {
    if (kind === 'system') return `systemprompt.${fall}`
    if (kind === 'memory') return `gedaechtnis.${fall}`
    if (kind === 'tools_datei') return `werkzeuge.${fall}`
    return `dateien.${fall}`
  }

  async function readLive() {
    try {
      live = await api.werkzeuge()
    } catch {
      live = null
    }
  }

  async function load() {
    busy = true
    failed = false
    broken = null
    placeholders = []
    try {
      if (kind === 'system') {
        text = (await api.systemPrompt()).text
      } else if (kind === 'memory') {
        text = (await api.gedaechtnis()).text
        values.gedaechtnisStandLaden()
        values.bildschutzStandLaden()
      } else if (kind === 'tools_datei') {
        const data = await api.werkzeugKonfiguration()
        text = data.content
        broken = data.kaputt
        placeholders = data.platzhalter
        readLive()
      } else {
        const data = await api.datei(kind)
        text = data.inhalt
        broken = data.kaputt
      }
      loaded = text
    } catch {
      failed = true
      melde(t(say('nicht_geladen')), 'fehler')
    } finally {
      busy = false
    }
  }

  $effect(() => {
    void kind
    untrack(() => {
      if (kind === 'system') {
        values.werkzeugRundenLaden()
        values.befehlZeitLaden()
        values.verdichtungSchwelleLaden()
      }
      load()
    })
  })

  /* The service stores the text trimmed; after a save the field shows what
     was stored, so the edit no longer counts as unsaved — unless more was
     typed on the way. */
  async function save() {
    const sent = text
    try {
      if (kind === 'system') {
        const data = await api.systemPromptSichern(text)
        loaded = data.text
        melde(data.text ? t('systemprompt.gesichert') : t('systemprompt.geleert'), 'erfolg')
      } else if (kind === 'memory') {
        const data = await api.gedaechtnisSichern(text)
        loaded = data.text
        melde(data.text ? t('gedaechtnis.gesichert') : t('gedaechtnis.geleert'), 'erfolg')
      } else if (kind === 'tools_datei') {
        const data = await api.werkzeugKonfigurationSichern(text)
        loaded = data.content
        broken = data.kaputt
        placeholders = data.platzhalter
        melde(broken ? t('werkzeuge.gesichert_kaputt') : t('werkzeuge.gesichert'), broken ? 'hinweis' : 'erfolg')
        if (!broken) {
          setTimeout(readLive, 1500)
          setTimeout(readLive, 5000)
        }
      } else {
        const data = await api.dateiSichern(kind, text)
        loaded = data.inhalt
        broken = data.kaputt
        melde(t(broken ? 'dateien.gesichert_kaputt' : 'dateien.gesichert'), broken ? 'hinweis' : 'erfolg')
      }
      if (text === sent) text = loaded
    } catch {
      melde(t(say('nicht_gesichert')), 'fehler')
    }
  }

  async function suspend(on) {
    if (!chat) {
      melde(t('chat.erst_oeffnen'))
      return
    }
    try {
      await chatAendern(chat.id, { prompt_aus: on })
    } catch {
      melde(t('systemprompt.schalter_fehler'), 'fehler')
    }
  }
</script>

<textarea
  class="text"
  class:source
  class:dim={kind === 'system' && chat?.prompt_aus}
  bind:value={text}
  disabled={busy || failed}
  spellcheck="false"
  autocapitalize="off"
  placeholder={kind === 'system' ? t('systemprompt.platzhalter') : ''}
  aria-label={t('editor.titel')}
></textarea>

{#if broken}
  <p class="warning">{t('werkzeuge.kaputt', { grund: broken })}</p>
{/if}

{#if kind === 'tools_datei'}
  {#if placeholders.length}
    <div class="lamps">
      {#each placeholders as entry (entry.name)}
        <span class="lamp">
          <Leuchtpunkt farbe={entry.gesetzt ? 'gruen' : 'rot'} groesse={11} />
          <span class="key-name">{entry.name}</span>
          <span class="key-state" class:set={entry.gesetzt} class:missing={!entry.gesetzt}>
            {t(entry.gesetzt ? 'werkzeuge.platzhalter_gesetzt' : 'werkzeuge.platzhalter_fehlt')}
            <!-- The sign says the state for a reader that cannot see it. -->
            <span class="key-sign" role="img" aria-label={t(entry.gesetzt ? 'modell.schluessel_gesetzt' : 'modell.schluessel_fehlt')}>
              <Hauszeichen zeichen={entry.gesetzt ? 'haken' : 'kreuz'} groesse={14} />
            </span>
          </span>
        </span>
      {/each}
    </div>
  {/if}
  {#if live}
    <Group title={t('werkzeuge.live')}>
      {#if !live.aktiv}
        <p class="note">{t('werkzeuge.abgeschaltet')}</p>
      {:else}
        {#each live.server as server (server)}
          <span class="lamp"><Leuchtpunkt farbe="gruen" groesse={11} />{server}</span>
        {/each}
      {/if}
    </Group>
  {/if}
{/if}

{#if kind === 'memory'}
  <Group>
    <Toggle label={t('gedaechtnis.an_lokal')} on={values.gedaechtnisSchalter.lokal}
            onswitch={() => values.gedaechtnisSchalten('lokal', !values.gedaechtnisSchalter.lokal)} />
    <Toggle label={t('gedaechtnis.an_cloud')} on={values.gedaechtnisSchalter.cloud}
            onswitch={() => values.gedaechtnisSchalten('cloud', !values.gedaechtnisSchalter.cloud)} />
    <Toggle label={t('bildschutz.titel')} on={values.bildschutzSchalter.an}
            onswitch={() => values.bildschutzSchalten(!values.bildschutzSchalter.an)} />
  </Group>
{/if}

{#if kind === 'system'}
  <Group>
    <label class="number">
      <span>{t('editor.anrede_titel')}</span>
      <input class="name" value={begruessung.name} placeholder={begruessung.vorschlag}
             aria-label={t('editor.anrede_titel')}
             onchange={(event) => anredeSpeichern(event.currentTarget.value, begruessung.an)} />
    </label>
    <Toggle label={t('editor.anrede_schalter')} on={begruessung.an}
            onswitch={() => anredeSpeichern(begruessung.name, !begruessung.an)} />
    <Toggle label={t('systemprompt.aussetzen')} on={Boolean(chat?.prompt_aus)}
            onswitch={() => suspend(!chat?.prompt_aus)} />
    <div class="number">
      <span>{t('editor.werkzeugrunden_titel')}</span>
      <div class="digits"><Zahlenfeld bind:wert={values.werkzeugRunden} min={0} ganzzahlig nullwort={t('parameter.auto')} /></div>
    </div>
    <div class="number">
      <span>{t('editor.befehlszeit_titel')}</span>
      <div class="digits"><Zahlenfeld bind:wert={values.befehlZeit} min={0} ganzzahlig nullwort={t('parameter.auto')} /></div>
    </div>
    <div class="number">
      <span>{t('editor.kontextkomprimierung_titel')}</span>
      <div class="digits"><Zahlenfeld bind:wert={values.verdichtungSchwelle} min={0} max={85} ganzzahlig nullwort={t('parameter.auto')} /></div>
    </div>
  </Group>
{/if}

<div class="buttons">
  {#if kind === 'system' || kind === 'memory'}
    <Action label={t('app.leeren')} onclick={() => (text = '')} disabled={failed} />
  {/if}
  <div class="signs">
    <button class="button sign" onclick={() => (text = loaded)} disabled={!dirty}
            aria-label={t('app.abbrechen')} title={t('app.abbrechen')}>
      <Hauszeichen zeichen="kreuz" groesse={18} />
    </button>
    <button class="button sign" onclick={save} disabled={!dirty || failed}
            aria-label={t('app.sichern')} title={t('app.sichern')}>
      <Hauszeichen zeichen="save" groesse={18} />
    </button>
  </div>
</div>

<style>
  .text {
    display: block;
    width: 100%;
    box-sizing: border-box;
    min-height: 38dvh;
    margin: 4px 0 8px;
    padding: 12px;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    outline: none;
    resize: vertical;
    background: var(--glass-card);
    color: var(--text);
    /* 16 px: a smaller field makes the phone zoom the page in. */
    font: 16px/1.5 var(--schrift);
  }
  .text:focus {
    background: color-mix(in srgb, var(--text) 5%, var(--glass-card));
  }
  .text.source {
    font-family: var(--schrift-fest);
    font-size: 16px;
    white-space: pre;
    overflow-x: auto;
  }
  .text.dim {
    opacity: 0.55;
  }
  .warning,
  .note {
    margin: 6px 10px;
    color: var(--gelb-text);
    font: var(--schrift-hinweis) var(--schrift);
  }
  .note {
    color: var(--text-still);
  }
  .lamps {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 6px 10px;
  }
  .lamp {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 10px;
    color: var(--text-leise);
    font: var(--schrift-hinweis) var(--schrift);
  }
  /* The name on the left, on the right the file that holds the value: green
     with a check where it is there, red with a cross where it is not. */
  .key-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .key-state {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .key-sign {
    display: inline-flex;
  }
  .key-state.set {
    color: var(--gruen-text);
  }
  .key-state.missing {
    color: var(--rot-text);
  }
  /* The tick and the cross are signs, not words: the colour of the shape. */
  .key-state.set .key-sign {
    color: var(--gruen);
  }
  .key-state.missing .key-sign {
    color: var(--rot);
  }
  .number {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: var(--menuezeile);
    padding: 6px 12px 6px 10px;
    color: var(--text-leise);
    font: 500 var(--schrift-text) var(--schrift);
  }
  .digits {
    width: 140px;
    flex: none;
  }
  .number span {
    flex: 1;
    min-width: 0;
  }
  .name {
    width: 45%;
    padding: 8px 10px;
    border: none;
    border-radius: 9px;
    outline: none;
    background: var(--bg-hoch);
    color: var(--text);
    font: 16px var(--schrift);
  }
  .buttons {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 8px 0 20px;
  }
  /* Cancel and save are two signs on one line, as on the desktop page. */
  .signs {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding: 4px 10px;
  }
  .sign {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    padding: 0;
  }
</style>
