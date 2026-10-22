<script>
  /* Memory and devices of the picture generator, on the picture server
     page: kept once for every chat (app/bildgeraete.py). The server's start
     by hand, every picture and the drawing tool read them there.

     Each field takes what the generator takes: the VRAM budget as GiB or
     per device ("cuda0=6"), the threads as a count or "all", the split as
     one mode or one per module ("diffusion=row,te=layer"), the backend
     assignment as the generator writes it, the time limit as whole seconds
     (empty: no limit). Each change is kept a moment
     after the last keystroke, without a save button, like the model values
     above. The generator's further memory switches stand folded at the
     foot, with their count. */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { imageSwitches, loadImageSwitches } from '../lib/imageSwitches.svelte.js'
  import { IDLE_MINUTEN_MAX } from '../lib/feineinstellungen.js'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import Schalter from './Schalter.svelte'
  import InfoMark from './InfoMark.svelte'
  import ImageSwitchRows from './ImageSwitchRows.svelte'

  /* `onklappe` hands two pieces to the page, which draws them in its sd.cpp
     section and under it: the rows of the further switches (`schalter`) and
     the "Advanced" card with the idle time (`erweitert`). Their values and
     their saving stay here with the rest of this card's. */
  let { onklappe = null } = $props()

  const SCHLUESSEL = 'bildgeraete'
  // The split's own choice for "one mode per module", beside the two modes.
  const JE_MODUL = 'modul'

  // The fields that are one value each; the switches are a set of their own.
  const FIELDS = ['vram_limit', 'offload_to_cpu', 'threads', 'split_mode', 'backend', 'zeitgrenze', 'idle_minutes']

  /* A field as the page holds it, read from what the service keeps: the
     same reading at the page's opening and after every write, so the window
     shows what acts and not what was typed. */
  function asHeld(name, v) {
    switch (name) {
      case 'vram_limit': return v.vram_limit ?? ''
      case 'offload_to_cpu': return v.offload_to_cpu === true
      case 'threads': return v.threads > 0 ? v.threads : null
      case 'split_mode': return v.split_mode ?? ''
      case 'backend': return v.backend ?? ''
      case 'zeitgrenze': return Number.isInteger(v.zeitgrenze) && v.zeitgrenze > 0 ? v.zeitgrenze : null
      case 'idle_minutes': return Number.isInteger(v.idle_minutes) && v.idle_minutes > 0 ? v.idle_minutes : null
      default: return undefined
    }
  }

  let w = $state(null)
  let devices = $state([])
  let schalterOffen = $state(false)
  let erweitertOffen = $state(true)
  let vramFokus = $state(false)
  let zeitFokus = $state(false)
  let splitFocus = $state(false)
  let backendFocus = $state(false)
  // The budget as the service keeps it: one it would not read is not kept,
  // and the field goes back to this once it is left.
  let vramGespeichert = ''
  // The time limit as the service keeps it, put back when its field is left.
  let zeitGespeichert = null
  let ausstehend = false
  // The split as chosen in the picker; an assignment per module keeps its
  // text in `splitText`.
  let splitWahl = $state('')
  let splitText = $state('')

  loadImageSwitches()
  api.imageDevices().then((list) => (devices = list)).catch(() => {})

  async function laden() {
    try {
      const antwort = await api.einstellungAufgeloest(SCHLUESSEL)
      const v = antwort?.wert ?? {}
      w = {
        ...Object.fromEntries(FIELDS.map((name) => [name, asHeld(name, v)])),
        switches: v.switches ?? {},
      }
      showSplit(w.split_mode)
      vramGespeichert = w.vram_limit
      zeitGespeichert = w.zeitgrenze
      gesendet = $state.snapshot(w)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  untrack(laden)

  // A stored split, as the picker and the text beside it show it.
  function showSplit(split) {
    splitWahl = split === '' || split === 'layer' || split === 'row' ? split : JE_MODUL
    splitText = splitWahl === JE_MODUL ? split : ''
  }

  /* A change the service did not take is not shown as if it had: each field
     of it shows what is stored again. A limit still being typed is put back
     when its field is left. */
  function showStored(changed) {
    for (const name of Object.keys(changed)) {
      if (name === 'switches') {
        const stored = gesendet.switches ?? {}
        const back = { ...w.switches }
        for (const key of Object.keys(changed.switches)) {
          if (key in stored) back[key] = stored[key]
          else delete back[key]
        }
        w.switches = back
      } else if (!(name === 'vram_limit' && vramFokus) && !(name === 'zeitgrenze' && zeitFokus)) {
        w[name] = gesendet[name]
        if (name === 'split_mode') showSplit(gesendet.split_mode)
      }
    }
  }

  // The split the picker and the text beside it say together.
  $effect(() => {
    if (!w) return
    w.split_mode = splitWahl === JE_MODUL ? splitText.trim() : splitWahl
  })

  /* Kept a moment after the last change, only the fields that changed;
     the service merges them into what it holds and keeps only what the
     generator reads. */
  let gesendet = null
  let zeit
  let writes = 0
  /* One write at a time, in the order of the changes: each goes out once
     the one before has its answer, with what differs from what the service
     holds by then. So no answer comes in after a later one, and after any
     run of writes the page shows what the service holds. */
  let line = Promise.resolve()

  // What differs from what the service holds, as it goes out.
  function changedSince(jetzt) {
    const geaendert = {}
    for (const [name, wert] of Object.entries(jetzt)) {
      if (JSON.stringify(wert) === JSON.stringify(gesendet[name])) continue
      if (name === 'switches') {
        /* Only the switches that changed, each under its own key: the
           service sets them one by one — one sent as off is taken out —
           and those another window set stay as they are. */
        const before = gesendet.switches ?? {}
        geaendert.switches = Object.fromEntries(Object.entries(wert).filter(
          ([key, value]) => JSON.stringify(value) !== JSON.stringify(before[key])))
      } else {
        geaendert[name] = name === 'threads' ? (wert ?? -1) : wert
      }
    }
    return geaendert
  }

  let waiting = 0
  $effect(() => {
    const jetzt = w ? $state.snapshot(w) : null
    if (!jetzt || !gesendet) return
    if (!Object.keys(changedSince(jetzt)).length) return
    clearTimeout(zeit)
    ausstehend = true
    const write = ++writes
    waiting = write
    zeit = setTimeout(() => {
      waiting = 0
      line = line.then(() => store(write))
    }, 350)
    return () => clearTimeout(zeit)
  })

  /* A change still waiting for its moment when the window goes is kept at
     once, not dropped with the timer. */
  $effect(() => () => {
    if (!waiting) return
    clearTimeout(zeit)
    const write = waiting
    waiting = 0
    line = line.then(() => store(write))
  })

  /* What a write left in the service, taken over: every field shows the
     value the service keeps, so a text it corrected (a split it does not
     read becomes "Auto") stands as it acts, and a switch value it refused
     shows the value that is kept — and says so. A field still under the
     fingers is put right when it is left. Returns whether a switch value
     was refused. */
  function adopt(geaendert, jetzt, stored) {
    const focused = {
      vram_limit: vramFokus, zeitgrenze: zeitFokus, split_mode: splitFocus, backend: backendFocus,
    }
    let refused = false
    for (const name of Object.keys(geaendert)) {
      if (name === 'switches') {
        const kept = stored.switches ?? {}
        const known = { ...(gesendet.switches ?? {}) }
        const shown = { ...w.switches }
        for (const key of Object.keys(geaendert.switches)) {
          const sent = jetzt.switches[key]
          const unset = sent === '' || sent === null || sent === false || sent === undefined
          if (key in kept) known[key] = kept[key]
          else if (unset) known[key] = sent
          else delete known[key]
          if (unset || JSON.stringify(sent) === JSON.stringify(kept[key])) continue
          refused = true
          // Only a field still showing what this write sent is put back.
          if (JSON.stringify(w.switches[key]) !== JSON.stringify(sent)) continue
          if (key in kept) shown[key] = kept[key]
          else delete shown[key]
        }
        gesendet.switches = known
        w.switches = shown
        continue
      }
      const held = asHeld(name, stored)
      gesendet[name] = held
      if (name === 'vram_limit') vramGespeichert = held
      if (name === 'zeitgrenze') zeitGespeichert = held
      if (JSON.stringify(held) === JSON.stringify(jetzt[name])) continue
      // Not over a change made since, and not under the fingers.
      if (JSON.stringify(w[name]) !== JSON.stringify(jetzt[name]) || focused[name]) continue
      w[name] = held
      if (name === 'split_mode') showSplit(held)
    }
    return refused
  }

  /* Never fails: whatever goes wrong in a write is said and ends with that
     write, so the line behind it goes on. */
  async function store(write) {
    let geaendert = {}
    try {
      const jetzt = $state.snapshot(w)
      geaendert = changedSince(jetzt)
      // An earlier write may have carried everything already.
      if (!Object.keys(geaendert).length) return
      const antwort = await api.einstellungMischen('global', SCHLUESSEL, geaendert)
      gesendet = { ...gesendet, ...Object.fromEntries(Object.keys(geaendert).map((n) => [n, jetzt[n]])) }
      const refused = adopt(geaendert, jetzt, antwort?.wert ?? {})
      if (refused) melde(t('fehler.einstellung_speichern'), 'fehler')
      /* A field of this write set back while it was under way asked for no
         write of its own — nothing differed from what was held then. It
         goes out now, so the service holds what the page shows. A field
         that is still being typed in is put right by its own field
         instead. */
      const undone = Object.keys(geaendert).some(
        (name) => name !== 'vram_limit' && name !== 'zeitgrenze'
          && JSON.stringify(w[name]) !== JSON.stringify(jetzt[name]))
      if (undone && write === writes) await store(write)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
      /* Only the last write says what is shown: a later one carries
         every field of this one that is still not stored, and its own
         outcome decides for them. */
      if (write === writes) showStored(geaendert)
    } finally {
      ausstehend = false
    }
  }

  const schalterZahl = $derived(imageSwitches.list.filter((row) => row.group === 'memory').length)

  $effect(() => {
    onklappe?.({ schalter, erweitert })
    return () => onklappe?.(null)
  })
</script>

<Serverabschnitt zeichen="chip_bolt" titel={t('bild.gruppe_speicher')}>
  {#if w}
    <div class="zeile">
      <span class="name mitmarke">{t('bild.vram_limit')}<InfoMark text={t('bild.info_vram_limit')} /></span>
      <input class="eingabe kurz" class:wort={!vramFokus && !w.vram_limit}
             aria-label={t('bild.vram_limit')} autocomplete="off" spellcheck="false"
             value={vramFokus || w.vram_limit ? w.vram_limit : t('parameter.auto')}
             onfocus={() => (vramFokus = true)}
             onblur={() => {
               vramFokus = false
               if (!ausstehend) w.vram_limit = vramGespeichert
             }}
             oninput={(e) => (w.vram_limit = e.currentTarget.value.trim())} />
    </div>
    <div class="zeile niedrig">
      <span class="name mitmarke">{t('bild.offload')}<InfoMark text={t('bild.info_offload')} /></span>
      <Schalter an={w.offload_to_cpu} beschriftung={t('bild.offload')}
                onschalten={(an) => (w.offload_to_cpu = an)} />
    </div>
    <div class="zeile">
      <span class="name mitmarke">{t('bild.threads')}<InfoMark text={t('bild.info_threads')} /></span>
      <div class="zahlplatz">
        <Zahlenfeld bind:wert={w.threads} min={1} schritt={1} ganzzahlig nullwort={t('parameter.auto')} />
      </div>
    </div>
    <div class="zeile">
      <span class="name">{t('mcp.zeitgrenze')}</span>
      <input class="eingabe kurz" inputmode="numeric" aria-label={t('mcp.zeitgrenze')}
             class:wort={!zeitFokus && w.zeitgrenze == null}
             autocomplete="off" spellcheck="false"
             value={zeitFokus || w.zeitgrenze != null ? (w.zeitgrenze ?? '') : '-'}
             onfocus={() => (zeitFokus = true)}
             onblur={() => {
               zeitFokus = false
               if (!ausstehend) w.zeitgrenze = zeitGespeichert
             }}
             oninput={(e) => {
               const ziffern = e.currentTarget.value.replace(/\D/g, '')
               if (ziffern !== e.currentTarget.value) e.currentTarget.value = ziffern
               w.zeitgrenze = ziffern ? Number(ziffern) : null
             }} />
      <span class="still">{t('mcp.zeitgrenze_einheit')}</span>
    </div>
    <div class="zeile">
      <span class="name mitmarke">{t('bild.split_mode')}<InfoMark text={t('bild.info_split_mode')} /></span>
      {#if splitWahl === JE_MODUL}
        <input class="eingabe" aria-label={t('bildserver.split_je_modul')} autocomplete="off"
               spellcheck="false" bind:value={splitText}
               onfocus={() => (splitFocus = true)}
               onblur={() => {
                 splitFocus = false
                 if (!ausstehend && splitText.trim() && gesendet.split_mode !== splitText.trim()) {
                   showSplit(gesendet.split_mode)
                 }
               }} />
      {/if}
      <div class="wahl">
        <Auswahlfeld bind:wert={splitWahl} beschriftung={t('bild.split_mode')}
                     eintraege={[{ wert: '', text: t('bild.split_mode_auto') },
                                 { wert: 'layer', text: t('bild.split_mode_layer') },
                                 { wert: 'row', text: t('bild.split_mode_row') },
                                 { wert: JE_MODUL, text: t('bildserver.split_je_modul') }]} />
      </div>
    </div>
    <div class="zeile">
      <span class="name mitmarke">{t('bild.backend')}<InfoMark text={t('bild.info_backend')} /></span>
      <div class="wahl">
        <input class="eingabe" class:wort={!backendFocus && !w.backend}
               aria-label={t('bild.backend')} autocomplete="off" spellcheck="false"
               value={backendFocus || w.backend ? w.backend : '-'}
               oninput={(e) => (w.backend = e.currentTarget.value)}
               onfocus={() => (backendFocus = true)}
               onblur={() => {
                 backendFocus = false
                 if (!ausstehend) w.backend = gesendet.backend
               }} />
      </div>
    </div>
    {#if devices.length}
      <div class="zeile liste">
        <span class="name">{t('bildserver.geraeteliste')}</span>
        <span class="still">{devices.length}</span>
        {#each devices as device (device.name)}
          <span class="still">{device.name} · {device.description}</span>
        {/each}
      </div>
    {/if}
  {/if}
</Serverabschnitt>

<!-- The generator's further switches stand at the foot of the sd.cpp section
     of the page (Bildserver.svelte): they apply to the whole server. Their
     values, their count and their saving stay here, with the rest of what
     this card keeps, and the page draws the rows. -->
{#snippet schalter()}
  {#if w}
    <div class="zeile liste">
      <button class="klappe" aria-expanded={schalterOffen} onclick={() => (schalterOffen = !schalterOffen)}>
        <span class="winkel" class:auf={schalterOffen}><Hauszeichen zeichen="chevron_right" groesse={14} /></span>
        <span class="name">{t('bildserver.sdcpp_schalter')}</span>
        <span class="still">{schalterZahl}</span>
      </button>
    </div>
    {#if schalterOffen}
      <div class="zeile schalterflaeche">
        <ImageSwitchRows group="memory" bind:values={w.switches} conditions={{ video: true }} />
      </div>
    {/if}
  {/if}
{/snippet}

<!-- The idle time of the picture server: after this long without a picture the
     program ends it, and the next picture starts it again; empty is never. -->
{#snippet erweitert()}
  {#if w}
    <Serverabschnitt klappbar bind:offen={erweitertOffen} titel={t('modell.gruppe_erweitert')} gewicht={1}>
      <div class="zeile niedrig">
        <label class="zahlname" for="bg-idle">{t('modell.feld_idle_ttl')}</label>
        <div class="zahlplatz">
          <Zahlenfeld id="bg-idle" bind:wert={w.idle_minutes}
                      min={0} max={IDLE_MINUTEN_MAX} ganzzahlig nullwort="-" />
        </div>
      </div>
    </Serverabschnitt>
  {/if}
{/snippet}

<style>
  /* The rows and their parts are Serverabschnitt.svelte's; here only what
     this section adds. */
  /* The mark right after the name, as on the rest of this page, and its
     sentence on a line of its own below the name when it is open. */
  .mitmarke {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    white-space: normal;
  }
  .mitmarke :global(.mark) {
    margin-left: 0;
  }
  .eingabe {
    flex: none;
    width: 232px;
    height: 32px;
    box-sizing: border-box;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    padding: 0 12px;
  }
  .eingabe.kurz {
    width: 84px;
    text-align: center;
  }
  /* A field in the place of a picker takes that place's width, which grows
     with the row where the field stands under its name. */
  .wahl > .eingabe {
    display: block;
    width: 100%;
  }
  /* "Auto" stands in an empty budget like the number fields' own word, and a
     dash in a field with no value. */
  .eingabe.wort {
    color: var(--text-leise);
  }
  .eingabe:focus {
    outline: 2px solid var(--linie-stark);
    outline-offset: -2px;
  }
  .still {
    flex: none;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-still);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .klappe {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }
  .winkel {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .winkel.auf {
    transform: rotate(90deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .winkel {
      transition: none;
    }
  }
  /* The further switches (ImageSwitchRows.svelte) as rows of this card:
     the name on the left, the control 232 wide at the right end. */
  /* Two classes, so the card's own row rule (Serverabschnitt.svelte), which
     centres its row, does not win. */
  .zeile.schalterflaeche {
    flex-direction: column;
    align-items: stretch;
    gap: 0;
  }
  .schalterflaeche :global(.switchrow) {
    display: flex;
    align-items: center;
    gap: 16px;
    min-height: 44px;
    min-width: 0;
  }
  .schalterflaeche :global(.switchrow > span) {
    flex: 1;
    min-width: 0;
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    line-height: 18px;
    color: var(--text);
    white-space: nowrap;
  }
  .schalterflaeche :global(.switchrow .mark) {
    margin-left: 0;
  }
  .schalterflaeche :global(.switchrow.gesperrt > span) {
    color: var(--text-still);
  }
  .schalterflaeche :global(.switchrow > :not(span)) {
    flex: none;
    width: 232px;
  }
  .schalterflaeche :global(.switchrow .feldein) {
    width: 232px;
    height: 32px;
    box-sizing: border-box;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    padding: 0 12px;
  }
</style>
