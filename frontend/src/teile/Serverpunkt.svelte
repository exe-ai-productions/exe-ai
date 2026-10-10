<!-- The model server at a glance: a filled dot and one word, right of the
     spacer in the header. Green while the server runs, grey while it does
     not — "off" is a fact about the machine, not a failure, and the colour
     table reserves red for something having gone wrong.

     Told, not asked. This readout lives the whole session and used to fetch
     `/runner` every five seconds for an answer that changes about twice a
     day; the service announces it now and the answer lands in
     `serverzustand.svelte.js`. Nothing is fetched from here at all — the one
     ask a window still needs belongs to the line itself, where a reconnect
     can repeat it (`verbinden`, lib/ereignisstrom.svelte.js).

     In the picture studio it speaks of the picture server instead: its
     state and the model it holds. That one is asked while the studio
     shows, every few seconds — it starts and stops with a picture. -->
<script>
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { api } from '../lib/api.js'
  import { familyOf } from '../lib/imageFamilies.svelte.js'
  import { serverzustand } from '../lib/serverzustand.svelte.js'
  import { listen, studioSichtbar } from '../lib/studio.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  const imStudio = $derived(studioSichtbar())
  let bild = $state(null)

  // How often the picture server is asked while the studio shows.
  const TAKT_MS = 3000
  $effect(() => {
    if (!imStudio) return
    let aus = false
    const fragen = () => api.turboStand().then((a) => { if (!aus) bild = a }).catch(() => {})
    fragen()
    const takt = setInterval(fragen, TAKT_MS)
    return () => {
      aus = true
      clearInterval(takt)
    }
  })

  // aus (grey) | bereit (green) | zeichnet (blue) | fehler (red)
  const FARBE = { aus: 'still', bereit: 'gruen', zeichnet: 'blau', fehler: 'rot' }
  const WORT = {
    aus: 'studio.bildserver_aus', bereit: 'studio.bildserver_bereit',
    zeichnet: 'studio.bildserver_zeichnet', fehler: 'studio.bildserver_fehler',
  }
  const bildModell = $derived.by(() => {
    const name = bild?.modell
    if (!name) return ''
    return familyOf(listen.families?.[name])?.label ?? name.replace(/\.[^.]+$/, '')
  })
</script>

{#if imStudio}
  <span class="gruppe">
    <Leuchtpunkt farbe={FARBE[bild?.zustand] ?? 'still'} groesse={9} />
    <span class="wort">
      {t(WORT[bild?.zustand] ?? WORT.aus)}{#if bildModell}&nbsp;· {bildModell}{/if}
    </span>
  </span>
{:else}
  <span class="gruppe">
    <Leuchtpunkt farbe={serverzustand.laeuft ? 'gruen' : 'still'} groesse={9} />
    <span class="wort">
      {serverzustand.laeuft ? t('kopf.bereit') : t('kopf.server_aus')}
    </span>
  </span>
{/if}

<style>
  .gruppe {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
  }
  .wort {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }
</style>
