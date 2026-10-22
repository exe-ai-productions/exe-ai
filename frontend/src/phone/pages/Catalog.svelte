<script module>
  export const meta = { name: 'catalog', title: 'menue.katalog', sign: 'raster', place: 'list', order: 33 }
</script>

<script>
  /* The catalogue on the phone: the curated cards of each kind of model with
     the builds of one card, a search across Hugging Face for the five kinds
     that can be searched, the files of a hit, and the token that lifts the
     rate limit and opens gated models. */
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import Field from '../parts/Field.svelte'
  import Action from '../parts/Action.svelte'
  import RepoView from '../catalog/RepoView.svelte'
  import CardView from '../catalog/CardView.svelte'
  import {
    SPALTEN_ZUBEHOER, SUCHBARE_ARTEN, brauchtMaschine, dienstArt, katalogFuer, kartePasst, passendeFassung,
  } from '../../lib/modellempfehlungen.js'
  import { feed, watchDownloads } from '../downloadFeed.svelte.js'
  import { buildState, shortCount } from '../catalog.js'

  const KINDS = $derived([
    { value: 'chat', label: t('katalog.art_chat') },
    { value: 'einbettung', label: t('katalog.art_einbettung') },
    { value: 'sprache', label: t('katalog.art_sprache') },
    { value: 'bild', label: t('katalog.art_bild') },
    { value: 'video', label: t('katalog.art_video') },
    { value: 'zubehoer', label: t('katalog.art_zubehoer') },
  ])

  /* The heading each kind's cards stand under. */
  const HEADING = {
    chat: 'katalog.vorauswahl_chat',
    einbettung: 'katalog.vorauswahl_einbettung',
    sprache: 'katalog.vorauswahl_sprache',
    bild: 'katalog.vorauswahl_bild',
    video: 'katalog.vorauswahl_video',
    zubehoer: 'katalog.vorauswahl_zubehoer',
  }

  let timer
  let art = $state('chat')
  let term = $state('')
  let hits = $state(null)
  let searching = $state(false)
  let opened = $state(null)
  let card = $state(null)
  // Only the newest request may write the results: a slow answer for an
  // older term would otherwise land last under the wrong one.
  let run = 0

  async function search() {
    clearTimeout(timer)
    const query = term.trim()
    if (!query) {
      run += 1
      hits = null
      searching = false
      return
    }
    const mine = ++run
    searching = true
    try {
      const answer = await api.modellSuche(query, art)
      if (mine === run) hits = answer
    } catch (error) {
      if (mine !== run) return
      melde(error.message, 'fehler')
      hits = []
    } finally {
      if (mine === run) searching = false
    }
  }

  function pickKind(value) {
    // The chosen kind is a row that stays on the page: a tap on it changes nothing.
    if (value === art) return
    art = value
    hits = null
    // Whatever was asked for the kind before is stale now: its answer must
    // not land under the new one, and its pending beat must not fire.
    clearTimeout(timer)
    run += 1
    searching = false
    // A kind with nothing to search leaves no stale term behind.
    if (!SUCHBARE_ARTEN.includes(value)) term = ''
    else if (term.trim()) search()
  }

  function typing() {
    clearTimeout(timer)
    timer = setTimeout(search, 400)
  }

  // The token: set once, never handed back out.
  let tokenSet = $state(false)
  let tokenEnd = $state('')
  let tokenInput = $state('')
  const takeToken = (state) => {
    tokenSet = state.gesetzt
    tokenEnd = state.ende ?? ''
  }
  $effect(() => {
    api.hfTokenStand().then(takeToken).catch(() => {})
  })
  async function saveToken() {
    try {
      takeToken(await api.hfTokenSetzen(tokenInput.trim()))
      tokenInput = ''
    } catch (error) {
      melde(error.message, 'fehler')
    }
  }
  async function removeToken() {
    try {
      takeToken(await api.hfTokenEntfernen())
    } catch (error) {
      melde(error.message, 'fehler')
    }
  }

  // The files of a hit show how far a fetch is, so the feed runs here too.
  $effect(() => watchDownloads())

  // What the machine holds, read by the download feed: a card says whether a build fits it.
  const memory = $derived(feed.memoryGb)

  const searchable = $derived(SUCHBARE_ARTEN.includes(art))
  const searchOn = $derived(searchable && term.trim().length > 0)
  /* The cards that fit stand first; ties keep the curated order. */
  const cards = $derived(
    [...katalogFuer(art)].sort((a, b) => Number(kartePasst(b, memory)) - Number(kartePasst(a, memory))),
  )
  const cardName = (entry) => (entry.nameKey ? t(entry.nameKey) : entry.name)
  /* What a card's row says: the size of the build it would take, or what the
     machine would need when none fits. */
  function cardValue(entry) {
    const build = passendeFassung(entry, memory)
    return kartePasst(entry, memory)
      ? t('modell.gb', { zahl: build.groesse })
      : t('katalog.braucht_maschine', { gb: brauchtMaschine(build) })
  }
  function cardDot(entry) {
    const phase = buildState(passendeFassung(entry, memory), feed.present, feed.stand)
    return phase === 'bereit' ? 'gruen' : phase === 'laedt' ? 'blau' : null
  }
</script>

{#snippet cardRow(entry)}
  <Menuezeile titel={cardName(entry)} wert={cardValue(entry)} punkt={cardDot(entry)} onclick={() => (card = entry)} />
{/snippet}

{#if card}
  <CardView {card} art={dienstArt(art)} {memory} onback={() => (card = null)} />
{:else if opened}
  <RepoView hit={opened} art={dienstArt(art)} onback={() => (opened = null)} />
{:else}
  <!-- The kinds of model, one row each, as on the desktop: the page's own
       head already says what this is. -->
  <Group>
    {#each KINDS as kind (kind.value)}
      <Menuezeile titel={kind.label} gewaehlt={art === kind.value} onclick={() => pickKind(kind.value)} />
    {/each}
  </Group>
  {#if searchable}
    <Group>
      <Field label={t('katalog.von_hf')} bind:value={term} oninput={typing} onchange={search} />
    </Group>
  {/if}

  {#if !searchOn}
    {#if art === 'zubehoer'}
      <!-- One list per accessory kind, in the order the desktop's columns stand. -->
      {#each SPALTEN_ZUBEHOER as sorte (sorte)}
        <Group title={t(`katalog.sorte_${sorte}`)}>
          {#each cards.filter((entry) => entry.sorte === sorte) as entry (entry.id)}
            {@render cardRow(entry)}
          {/each}
        </Group>
      {/each}
    {:else}
      <Group title={t(HEADING[art])}>
        {#each cards as entry (entry.id)}
          {@render cardRow(entry)}
        {:else}
          <Line label={t('katalog.keine_kuratierten')} />
        {/each}
      </Group>
    {/if}
  {/if}

  {#if searching}
    <Group><Line label={t('modell.suche_laeuft')} /></Group>
  {:else if hits}
    <Group>
      {#each hits as hit (hit.id)}
        <Menuezeile titel={hit.name} wert={`${hit.anbieter} · ${shortCount(hit.ladungen)} ↓`} onclick={() => (opened = hit)} />
      {:else}
        <Line label={t('modell.keine_treffer')} />
      {/each}
    </Group>
  {/if}

  <!-- Hugging Face stands once, as the row of the token it holds; the token
       is named only for a screen reader, as on the desktop. -->
  <Group>
    {#if tokenSet}
      <Menuezeile titel={t('editor.quelle_hf')} punkt="gruen" wert={`••••${tokenEnd}`} />
      <Action label={t('editor.hf_entfernen')} onclick={removeToken} />
    {:else}
      <Field label={t('editor.quelle_hf')} ariaLabel={t('modell.hf_token')} bind:value={tokenInput} secret />
      <Action label={t('modell.verbinden')} kind="primary" onclick={saveToken} disabled={tokenInput.trim().length < 8} />
      <Line label={t('editor.hf_fussnote')} />
    {/if}
  </Group>
{/if}
