<script module>
  export const meta = { name: 'tools', title: 'werkzeuge.titel', sign: 'werkzeug', place: 'list', order: 35 }
</script>

<script>
  /* The tools the model can call, on the phone: the sources they come from
     with their state, and a page for each source with its switches. */
  import { t } from '../../lib/texte.svelte.js'
  import {
    quellen, aktivStand, istAn, werkzeugeLaden, EINGEBAUTE_NAMEN,
  } from '../../lib/werkzeuge.svelte.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Group from '../parts/Group.svelte'
  import SourceView from '../tools/SourceView.svelte'

  let view = $state({ id: null })
  const sources = $derived(quellen())
  const shown = $derived(sources.find((source) => source.id === view.id) ?? null)

  /* Read again every time the page opens: a server added or switched off on
     the connections page changes what belongs here. */
  $effect(() => {
    werkzeugeLaden()
  })

  function nameOf(source) {
    if (!source.eingebaut) return source.name
    const key = EINGEBAUTE_NAMEN[source.kennung]
    return key ? t(key) : source.kennung
  }

  /* Why a source is quiet: switched off by hand is not unreachable. */
  const quietWord = (source) =>
    source.laeuft ? null : source.enabled === false ? 'ausgeschaltet' : 'nicht_verbunden'
  const QUIET_TEXT = { ausgeschaltet: 'werkzeuge.ausgeschaltet', nicht_verbunden: 'werkzeuge.nicht_verbunden' }

  function wordOf(source) {
    if (quietWord(source)) return t(QUIET_TEXT[quietWord(source)])
    const total = source.eingebaut ? source.werkzeuge.length : source.katalog.length
    return t('werkzeuge.von_zahl', { an: source.werkzeuge.filter((tool) => istAn(tool.name)).length, gesamt: total })
  }
</script>

{#if shown}
  <SourceView source={shown} title={nameOf(shown)} quiet={quietWord(shown) ? QUIET_TEXT[quietWord(shown)] : null} dim={quietWord(shown) === 'ausgeschaltet'} onback={() => (view = { id: null })} />
{:else}
  <Group title={t('werkzeuge.aktiv_zahl', aktivStand(sources))}>
    {#each sources as source (source.id)}
      <Menuezeile
        titel={nameOf(source)}
        wert={wordOf(source)}
        punkt={source.laeuft ? 'gruen' : quietWord(source) === 'ausgeschaltet' ? 'gelb' : null}
        onclick={() => (view = { id: source.id })}
      />
    {/each}
  </Group>
{/if}
