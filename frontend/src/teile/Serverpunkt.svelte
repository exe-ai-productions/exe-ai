<!-- The server behind the model in use, at a glance: a filled dot and one
     word, right of the spacer in the header. Three words, the service's own
     (app/server_state.py): `active` while an answer is being written on
     that server — blue, the colour of running; `idle` while it is reachable
     and quiet — green; `offline` while it is not reachable — grey, a fact
     about the machine, not a failure, and the colour table reserves red for
     something having gone wrong. Without a model in use there is nothing
     to say, and nothing is shown.

     Told, not asked. The word rides on the model list the window loads
     anyway, and the live line keeps it current in place
     (`server_state`, lib/ereignisstrom.svelte.js). Nothing is fetched from
     here at all.

     In the picture studio it speaks of the picture server instead: its
     state and the model it holds. That one is asked while the studio
     shows, every few seconds — it starts and stops with a picture. While
     the server is down for a picture sd-cli draws, or would be as the
     studio is set, it says "pauses for" and the control that sends the
     picture there, in grey; the service names the control. -->
<script>
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { familyOf } from '../lib/imageFamilies.svelte.js'
  import { listen, studioSichtbar } from '../lib/studio.svelte.js'
  import { painterQuery } from '../lib/studiozeichnen.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { aktuellesModell } from '../lib/zustand.svelte.js'

  const imStudio = $derived(studioSichtbar())
  let bild = $state(null)

  // How often the picture server is asked while the studio shows.
  const TAKT_MS = 3000
  $effect(() => {
    if (!imStudio) return
    let aus = false
    /* The control that sends the picture to sd-cli, named by the service:
       while the server is down for such a picture, and — asked with the
       values the studio holds — while it is up and the picture, as set,
       would go there. */
    const fragen = async () => {
      try {
        const stand = await api.turboStand()
        let control = stand.paused_for ?? null
        const query = !control && stand.zustand === 'bereit' ? painterQuery() : null
        if (query) control = (await api.turboReason(query)).control ?? null
        if (!aus) bild = { ...stand, control }
      } catch {
        // The next beat asks again.
      }
    }
    fragen()
    const stop = pollWithoutOverlap(fragen, TAKT_MS)
    return () => {
      aus = true
      stop()
    }
  })

  // aus (grey) | bereit (green) | zeichnet (blue) | fehler (red). While the
  // server is paused for a picture sd-cli draws, or would draw as set, the
  // footer says so in grey, like a server that is off.
  const FARBE = { aus: 'still', bereit: 'gruen', zeichnet: 'blau', fehler: 'rot' }
  const WORT = {
    aus: 'studio.bildserver_aus', bereit: 'studio.bildserver_bereit',
    zeichnet: 'studio.bildserver_zeichnet', fehler: 'studio.bildserver_fehler',
  }
  // active (blue) | idle (green) | offline (grey) — the service's words.
  const FARBE_SERVER = { active: 'blau', idle: 'gruen', offline: 'still' }
  const WORT_SERVER = { active: 'kopf.server_active', idle: 'kopf.bereit', offline: 'kopf.server_aus' }
  const serverWort = $derived(aktuellesModell()?.server_state ?? '')

  const pictureWord = $derived(
    bild?.control
      ? t('studio.bildserver_pausiert', { control: t(bild.control) })
      : t(WORT[bild?.zustand] ?? WORT.aus),
  )
  const pictureColor = $derived(bild?.control ? 'still' : FARBE[bild?.zustand] ?? 'still')

  const bildModell = $derived.by(() => {
    const name = bild?.modell
    if (!name) return ''
    return familyOf(listen.families?.[name])?.label ?? name.replace(/\.[^.]+$/, '')
  })
</script>

{#if imStudio}
  <span class="gruppe">
    <Leuchtpunkt farbe={pictureColor} groesse={9} />
    <span class="wort">
      {pictureWord}{#if bildModell}&nbsp;· {bildModell}{/if}
    </span>
  </span>
{:else if WORT_SERVER[serverWort]}
  <span class="gruppe">
    <Leuchtpunkt farbe={FARBE_SERVER[serverWort]} groesse={9} />
    <span class="wort">{t(WORT_SERVER[serverWort])}</span>
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
