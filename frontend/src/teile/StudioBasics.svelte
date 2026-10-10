<script>
  /* The studio's left column: the basics of a picture for this chat — what
     it is drawn with, in which format, at what size and with which LoRAs.
     It stands where the chat list stands, between the mark and the window
     row, and melts out over its last 40 px like the list.

     The values are the chat's own (lib/studio.svelte.js reads and writes
     them): a value changed here
     stands when the chat is opened again. What the chat has no value of its
     own for starts at what the model starts with and is only shown, not
     written — a chat merely looked at keeps its store as it was.

     Every row is one setting: its name on the left, the ⓘ beside the name
     and outside the label, so a screen reader hears the setting's name and
     nothing else; the field at the right end. A slider row carries its
     number at the right end and the slider under the whole row. */
  import { untrack } from 'svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import InfoMark from './InfoMark.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import StudioLoraStack from './StudioLoraStack.svelte'
  import StudioSection from './StudioSection.svelte'
  import StudioSwitches from './StudioSwitches.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import { api } from '../lib/api.js'
  import { chatanzeige } from '../lib/chatanzeige.svelte.js'
  import { familyOf, imageFamilies } from '../lib/imageFamilies.svelte.js'
  import { rollfade } from '../lib/rollfade.js'
  import { seedlage } from '../lib/bildseed.svelte.js'
  import {
    EDGE_GRID, EDGE_MAX, EDGE_MIN, art, auswahl, familie, kindsOf, layingStartValues, listen, listenLaden,
    pictureInArea, search, searchRows, searching, startwerte, vorgabenHolen,
    werte, werteFuellen, werteSchreiben, werteVorschlagen,
  } from '../lib/studio.svelte.js'
  import { t, texte } from '../lib/texte.svelte.js'

  const uid = $props.id()
  const feld = (name) => `${uid}-${name}`
  const alsAuswahl = (namen) => (namen ?? []).map((n) => ({ wert: n, text: n }))

  /* The usual range of each slider; the number beside it takes whatever
     sd.cpp takes (app/bildwahlen.py), so a value past the slider's end is
     typed, and the slider then stands at its end. */
  const reihe = (von, bis, schritt) => Array.from(
    { length: Math.round((bis - von) / schritt) + 1 },
    (_, i) => Math.round((von + i * schritt) * 100) / 100,
  )
  // Edges move on sd.cpp's grid of 64 (app/bildwahlen.py `RASTER`).
  const RASTER = EDGE_GRID
  const KANTEN = reihe(256, 1536, RASTER)
  const CFG_STUFEN = reihe(1, 30, 0.5)
  const GUIDANCE_STUFEN = reihe(1, 20, 0.1)
  // The service's own range for a seed it picks (app/api/v1/bild.py).
  const SEED_BEREICH = 2 ** 31

  const gb = (bytes) => `${(bytes / 1e9).toLocaleString(texte.sprache, { maximumFractionDigits: 1 })} GB`

  /* Grouped by family, in the order of the family table, each named with
     its file's size. */
  const modellEintraege = $derived.by(() => {
    const rang = (name) => {
      const at = imageFamilies.list.findIndex((f) => f.name === listen.families[name])
      return at < 0 ? imageFamilies.list.length : at
    }
    return [...listen.modelle]
      .sort((a, b) => rang(a) - rang(b))
      .map((name) => ({
        wert: name,
        text: listen.groessen[name] ? `${name} · ${gb(listen.groessen[name])}` : name,
        group: familyOf(listen.families[name])?.label ?? t('bild.familie_keine'),
      }))
  })

  const familyEntry = $derived(familie())
  // A family whose model has sd-cli's distilled guidance starts with one.
  const usesGuidance = $derived(familyEntry?.start?.guidance != null)

  /* The kinds of one half the model's family can draw (`kindsOf`); which
     of them is drawn is chosen at the prompt bar. A family that draws only
     one half turns the switch to it. A kind chosen by hand that the model
     or the half cannot draw gives way to its counterpart in the other
     half, or to "auto"; "auto" itself stays through every change of model
     and half. */
  const kinds = $derived(kindsOf(auswahl.medium === 'video'))
  const kindEntry = $derived(art())
  const COUNTERPART = { txt2img: 't2v', t2v: 'txt2img', img2img: 'i2v', i2v: 'img2img' }
  $effect(() => {
    if (!kinds.length && kindsOf(auswahl.medium !== 'video').length) {
      auswahl.medium = auswahl.medium === 'video' ? 'bild' : 'video'
    }
  })
  $effect(() => {
    if (auswahl.art === 'auto' || !kinds.length || kinds.some((k) => k.value === auswahl.art)) return
    auswahl.art = kinds.find((k) => k.value === COUNTERPART[auswahl.art])?.value ?? 'auto'
    // A picture in the area stays what is drawn from, where the family can.
    untrack(() => {
      if (werte.startbild) pictureInArea()
    })
  })

  /* The format tiles. A tile sets the long edge to the size the model
     starts with and works out the short one from its ratio, rounded up onto
     the grid — 4:3 on a 1024 model is 1024 × 768, 2:3 is 704 × 1024. A tile
     stands chosen while the size is exactly what it would set for that long
     edge; any other size is "Custom", which sets nothing. */
  const FORMATE = [[1, 1], [3, 4], [4, 3], [2, 3], [3, 2], [9, 16], [16, 9]]

  function formatPaar([a, b], lang) {
    const kurz = Math.ceil((lang / RASTER) * Math.min(a, b) / Math.max(a, b)) * RASTER
    return a >= b ? [lang, kurz] : [kurz, lang]
  }
  const formatGewaehlt = $derived.by(() => {
    const breite = Number(werte.breite)
    const hoehe = Number(werte.hoehe)
    const lang = Math.max(breite, hoehe)
    if (!lang || lang % RASTER) return null
    return FORMATE.find((f) => {
      const [b, h] = formatPaar(f, lang)
      return b === breite && h === hoehe
    }) ?? null
  })
  function formatSetzen(format) {
    if (gezogen) return
    const lang = auswahl.startKante || Math.max(Number(werte.breite) || 0, Number(werte.hoehe) || 0)
    if (!lang) return
    const [b, h] = formatPaar(format, Math.ceil(lang / RASTER) * RASTER)
    werte.breite = b
    werte.hoehe = h
  }
  // The shape a tile draws: the ratio inside a 16 px square.
  const form = (b, h) => (b >= h ? [16, Math.max(4, (16 * h) / b)] : [Math.max(4, (16 * b) / h), 16])
  // "Custom" draws the size as it stands.
  const eigeneForm = $derived(form(Number(werte.breite) || 1, Number(werte.hoehe) || 1))

  /* The row of tiles is dragged sideways with the mouse as well as scrolled;
     a press that moved is a drag, not a choice. */
  let kachelreihe = $state(null)
  let zug = null
  let gezogen = false
  function ziehenStart(ereignis) {
    gezogen = false
    if (ereignis.pointerType !== 'mouse' || ereignis.button !== 0) return
    zug = { x: ereignis.clientX, links: kachelreihe.scrollLeft, id: ereignis.pointerId }
  }
  function ziehen(ereignis) {
    if (!zug) return
    const weg = ereignis.clientX - zug.x
    if (!gezogen && Math.abs(weg) > 4) {
      gezogen = true
      kachelreihe.setPointerCapture?.(zug.id)
    }
    if (gezogen) kachelreihe.scrollLeft = zug.links - weg
  }
  function ziehenEnde() {
    zug = null
    // The click that ends a drag comes first; the next one is a choice.
    setTimeout(() => (gezogen = false))
  }

  /* A model chosen by hand starts the chat at its values: the measures, the
     CFG and what goes with them. A model whose header names its family
     takes that one, and a family said by hand goes. */
  async function modellGewaehlt(name) {
    werte.modell = name
    return layingStartValues(async () => {
      const v = await vorgabenHolen()
      if (!v || werte.modell !== name) return false
      if (v.family) werte.familie = ''
      Object.assign(werte, startwerte(v))
      return true
    })
  }

  // "Standard": the model's start values again.
  async function standardHolen() {
    return layingStartValues(async () => {
      const v = await vorgabenHolen()
      if (v) Object.assign(werte, startwerte(v))
      return Boolean(v)
    })
  }

  // "last: N": the last drawn seed, held.
  function seedUebernehmen() {
    if (seedlage.letzter === null) return
    werte.seed = String(seedlage.letzter)
    werte.seed_modus = 'fest'
  }

  // The dice: a new seed from the service's own range; the plan stays.
  function wuerfeln() {
    werte.seed = String(crypto.getRandomValues(new Uint32Array(1))[0] % SEED_BEREICH)
  }

  // The lists, read each time the studio opens.
  const listenDa = listenLaden()

  /* Filled from the chat's store whenever another chat opens or its read
     comes back. A model that is not in the folder (any more) shows the
     picture server's default model; every value the chat has none of its
     own for shows the model's start value — each on its own, the CFG of a
     chat with a size of its own too. All of these are shown, not written.
     Nothing is written for a chat this column has not been filled for.
     A value changed since the filling — set by hand while the start values
     were on their way — stays as it was set. Answers whether the start
     values were laid in: a draw waits for that (lib/studio.svelte.js). */
  let gefuellterChat = null
  async function fuellen(id, dabei) {
    const fehlen = werteFuellen()
    const filled = $state.snapshot(werte)
    gefuellterChat = dabei ? id : null
    return layingStartValues(async () => {
      await listenDa
      if (chatanzeige.chatId !== id) return false
      if (listen.geladen && !listen.modelle.includes(werte.modell)) {
        werteVorschlagen({ modell: listen.standardmodell })
      }
      const v = await vorgabenHolen()
      if (!v || chatanzeige.chatId !== id) return false
      const teil = startwerte(v)
      for (const name of Object.keys(teil)) {
        const asFilled = JSON.stringify(werte[name]) === JSON.stringify(filled[name])
        if (!fehlen.includes(name) || !asFilled) delete teil[name]
      }
      if (Object.keys(teil).length) werteVorschlagen(teil)
      return true
    })
  }
  $effect(() => {
    const id = chatanzeige.chatId
    const dabei = chatanzeige.geladen
    untrack(() => {
      fuellen(id, dabei)
    })
  })

  $effect(() => {
    void JSON.stringify(werte)
    if (gefuellterChat === null || gefuellterChat !== chatanzeige.chatId) return
    untrack(werteSchreiben)
  })

  /* The search field stands here and searches both columns
     (lib/studio.svelte.js); what was typed goes with the field. */
  const sucht = $derived(searching())
  $effect(() => () => { search.text = '' })
</script>

<section class="grundlagen" use:rollfade={40} use:searchRows aria-label={t('studio.grundlagen')}>
  <div class="suche">
    <Hauszeichen zeichen="lupe" groesse={14} />
    <input type="search" bind:value={search.text} aria-label={t('app.suchen')} />
  </div>

  <!-- Picture or video: the half of the kinds below. A half the chosen
       model cannot draw is shut. -->
  <div class="medium" role="group" aria-label={t('bild.art')}>
    {#each [['bild', false], ['video', true]] as [name, video] (name)}
      <button aria-pressed={auswahl.medium === name} class:an={auswahl.medium === name}
              disabled={!kindsOf(video).length}
              onclick={() => (auswahl.medium = name)}>{t(`bild.medium_${name}`)}</button>
    {/each}
  </div>

  <StudioSection titel={t('studio.modell')}>
      {#if !listen.programmDa}
        <p class="zeile leer" data-suche={t('bild.modell')}>{t('bild.kein_programm')}</p>
      {:else if listen.geladen && !listen.modelle.length}
        <p class="zeile leer" data-suche={t('bild.modell')}>{t('bild.kein_modell')}</p>
      {:else}
        <div class="zeile voll" data-suche={t('bild.modell')}>
          <Auswahlfeld wert={werte.modell} eintraege={modellEintraege} gewaehlt={modellGewaehlt}
                       beschriftung={t('bild.modell')} search searchLabel={t('app.suchen')} />
        </div>
      {/if}
      {#if usesGuidance}
        <!-- The family's own distilled guidance, sd-cli's --guidance: a
             different dial from the CFG under the measures. Empty is
             sd-cli's own value. -->
        <div class="zeile regel" data-suche={t('bild.guidance')}>
          <div class="kopfzeile">
            <label class="name" for={feld('guidance')}>{t('bild.guidance')}</label>
            <InfoMark text={t('bild.info_guidance')} />
            <div class="rechts">
              <Zahlenfeld id={feld('guidance')} bind:wert={werte.guidance} min={0} schritt={0.1}
                          nullwort={t('parameter.auto')} />
            </div>
          </div>
          <Schieberegler bind:wert={werte.guidance} stufen={GUIDANCE_STUFEN} mit_zahl={false} fuellung
                         beschriftung={t('bild.guidance')} />
        </div>
      {/if}
  </StudioSection>

  <StudioSection titel={t('studio.format')}>
      <div class="zeile kacheln" data-suche={t('studio.format')}>
        <div class="kachelreihe" role="group" aria-label={t('studio.format')} bind:this={kachelreihe}
             onpointerdown={ziehenStart} onpointermove={ziehen} onpointerup={ziehenEnde}
             onpointercancel={ziehenEnde}>
          {#each FORMATE as format (format.join(':'))}
            {@const [fb, fh] = form(format[0], format[1])}
            <button class="kachel" class:an={formatGewaehlt === format} aria-pressed={formatGewaehlt === format}
                    onclick={() => formatSetzen(format)}>
              <span class="form" style:width="{fb}px" style:height="{fh}px"></span>
              <span class="verhaeltnis">{format.join(':')}</span>
            </button>
          {/each}
          <!-- Not a button: it only says that the size is one of no tile's,
               and pressing it would set nothing. -->
          <div class="kachel eigene" class:an={!formatGewaehlt}>
            <span class="form" style:width="{eigeneForm[0]}px" style:height="{eigeneForm[1]}px"></span>
            <span class="verhaeltnis">{t('studio.eigene')}</span>
          </div>
        </div>
      </div>
      <div class="zeile regel" data-suche={t('bild.breite')}>
        <div class="kopfzeile">
          <label class="name" for={feld('breite')}>{t('bild.breite')}</label>
          <InfoMark text={t('bild.info_breite')} />
          <div class="rechts">
            <!-- A typed edge stands, once the field is left, at what the
                 service keeps: rounded up onto the grid. -->
            <Zahlenfeld id={feld('breite')} bind:wert={werte.breite} min={EDGE_MIN} max={EDGE_MAX}
                        schritt={RASTER} grid={RASTER} ganzzahlig />
          </div>
        </div>
        <Schieberegler bind:wert={werte.breite} stufen={KANTEN} mit_zahl={false} fuellung
                       beschriftung={t('bild.breite')} />
      </div>
      <div class="zeile regel" data-suche={t('bild.hoehe')}>
        <div class="kopfzeile">
          <label class="name" for={feld('hoehe')}>{t('bild.hoehe')}</label>
          <InfoMark text={t('bild.info_hoehe')} />
          <div class="rechts">
            <Zahlenfeld id={feld('hoehe')} bind:wert={werte.hoehe} min={EDGE_MIN} max={EDGE_MAX}
                        schritt={RASTER} grid={RASTER} ganzzahlig />
          </div>
        </div>
        <Schieberegler bind:wert={werte.hoehe} stufen={KANTEN} mit_zahl={false} fuellung
                       beschriftung={t('bild.hoehe')} />
      </div>
  </StudioSection>

  <StudioSection titel={t('bild.gruppe_masse')}>
    {#snippet rechts()}
      {#if seedlage.letzter !== null}
        <button class="kopfknopf" onclick={seedUebernehmen} title={t('bild.seed_uebernehmen')}>
          {t('bild.seed_zuletzt', { zahl: seedlage.letzter })}
        </button>
      {/if}
      {#if werte.modell}
        <button class="kopfknopf" onclick={standardHolen}>{t('bild.standard')}</button>
      {/if}
    {/snippet}
      <div class="zeile regel" data-suche={t('bild.schritte')}>
        <div class="kopfzeile">
          <label class="name" for={feld('schritte')}>{t('bild.schritte')}</label>
          <InfoMark text={t('bild.info_schritte')} />
          <div class="rechts">
            <Zahlenfeld id={feld('schritte')} bind:wert={werte.schritte} min={1} schritt={1} ganzzahlig />
          </div>
        </div>
        <Schieberegler bind:wert={werte.schritte} min={1} max={150} mit_zahl={false} fuellung
                       beschriftung={t('bild.schritte')} />
      </div>
      <div class="zeile regel" data-suche={t('bild.cfg')}>
        <div class="kopfzeile">
          <label class="name" for={feld('cfg')}>{t('bild.cfg')}</label>
          <InfoMark text={t('bild.info_cfg')} />
          <div class="rechts">
            <Zahlenfeld id={feld('cfg')} bind:wert={werte.cfg} min={0} schritt={0.5} />
          </div>
        </div>
        <Schieberegler bind:wert={werte.cfg} stufen={CFG_STUFEN} mit_zahl={false} fuellung
                       beschriftung={t('bild.cfg')} />
      </div>
      <div class="zeile" data-suche={t('bild.sampler')}>
        <label class="name" for={feld('sampler')}>{t('bild.sampler')}</label>
        <InfoMark text={t('bild.info_sampler')} />
        <div class="rechts wahl">
          <Auswahlfeld id={feld('sampler')} bind:wert={werte.sampler} beschriftung={t('bild.sampler')}
                       eintraege={[{ wert: '', text: t('parameter.auto') }, ...alsAuswahl(listen.sampler)]} />
        </div>
      </div>
      <div class="zeile" data-suche={t('bild.scheduler')}>
        <label class="name" for={feld('scheduler')}>{t('bild.scheduler')}</label>
        <InfoMark text={t('bild.info_scheduler')} />
        <div class="rechts wahl">
          <Auswahlfeld id={feld('scheduler')} bind:wert={werte.scheduler} beschriftung={t('bild.scheduler')}
                       eintraege={[{ wert: '', text: t('parameter.auto') }, ...alsAuswahl(listen.scheduler)]} />
        </div>
      </div>
      <div class="zeile" data-suche={t('bild.seed')}>
        <label class="name" for={feld('seed')}>{t('bild.seed')}</label>
        <InfoMark text={t('bild.info_seed')} />
        <div class="rechts seedplatz">
          <input id={feld('seed')} class="eingabe" bind:value={werte.seed} inputmode="numeric" />
          <!-- The dice of the house's sign catalogue, its paths unchanged. -->
          <button class="wuerfel" onclick={wuerfeln} title={t('studio.wuerfel')} aria-label={t('studio.wuerfel')}>
            <svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-linecap="round"
                 stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="46" height="46" rx="11" stroke-width="5" /><path d="M22 22 h0 M42 22 h0 M32 32 h0 M22 42 h0 M42 42 h0" stroke-width="6.5" /></svg>
          </button>
        </div>
      </div>
      <div class="zeile" data-suche={t('bild.seed_modus')}>
        <label class="name" for={feld('seed_modus')}>{t('bild.seed_modus')}</label>
        <InfoMark text={t('bild.info_seed_modus')} />
        <div class="rechts wahl">
          <Auswahlfeld id={feld('seed_modus')} bind:wert={werte.seed_modus} beschriftung={t('bild.seed_modus')}
                       eintraege={[{ wert: 'zufall', text: t('bild.seed_zufall') },
                                   { wert: 'fest', text: t('bild.seed_fest') },
                                   { wert: 'plus', text: t('bild.seed_plus') },
                                   { wert: 'minus', text: t('bild.seed_minus') }]} />
        </div>
      </div>
      {#if kindEntry.video}
        <!-- sd.cpp takes any count and rounds it to the model's own step. -->
        <div class="zeile" data-suche={t('bild.video_frames')}>
          <label class="name" for={feld('video_frames')}>{t('bild.video_frames')}</label>
          <InfoMark text={t('bild.info_video_frames')} />
          <div class="rechts">
            <Zahlenfeld id={feld('video_frames')} bind:wert={werte.video_frames} min={1} schritt={1}
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
        <div class="zeile" data-suche={t('bild.fps')}>
          <label class="name" for={feld('fps')}>{t('bild.fps')}</label>
          <InfoMark text={t('bild.info_fps')} />
          <div class="rechts">
            <Zahlenfeld id={feld('fps')} bind:wert={werte.fps} min={1} schritt={1}
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
      {/if}
      <div class="zeile regel" data-suche={t('bild.bilder_zahl')}>
        <div class="kopfzeile">
          <label class="name" for={feld('bilder')}>{t('bild.bilder_zahl')}</label>
          <InfoMark text={t('bild.info_bilder_zahl')} />
          <div class="rechts">
            <Zahlenfeld id={feld('bilder')} bind:wert={werte.bilder_je_lauf} min={1} schritt={1} ganzzahlig />
          </div>
        </div>
        <Schieberegler bind:wert={werte.bilder_je_lauf} min={1} max={8} mit_zahl={false} fuellung
                       beschriftung={t('bild.bilder_zahl')} />
      </div>
      <StudioSwitches group="size" bind:values={werte.switches} conditions={{ video: kindEntry.video }} {sucht} />
  </StudioSection>

  <StudioSection titel={t('bild.lora')}>
    {#snippet rechts()}
      <button class="ordnerzeichen" onclick={() => api.bildBegleiterOrdner('lora').catch(() => {})}
              title={listen.loraOrdner || t('bild.lora_ordner')} aria-label={t('bild.lora_ordner')}>
        <Hauszeichen zeichen="ordner" groesse="klein" />
      </button>
    {/snippet}
      <StudioLoraStack bind:stapel={werte.stapel} dateien={listen.loras} name={t('bild.lora')} />
      <div class="zeile" data-suche={t('bild.lora_modus')}>
        <label class="name" for={feld('lora_modus')}>{t('bild.lora_modus')}</label>
        <InfoMark text={t('bild.info_lora_modus')} />
        <!-- Narrower than the other pickers: with its two short entries it
             leaves the name room on the same line. -->
        <div class="rechts wahl schmal">
          <Auswahlfeld id={feld('lora_modus')} bind:wert={werte.lora_modus} beschriftung={t('bild.lora_modus')}
                       eintraege={[{ wert: 'at_runtime', text: t('bild.lora_modus_at_runtime') },
                                   { wert: 'auto', text: t('bild.lora_modus_auto') }]} />
        </div>
      </div>
      <div class="zeile" data-suche={t('bild.embedding')}>
        <span class="name">{t('bild.embedding')}</span>
        <InfoMark text={t('bild.info_embedding')} />
        <button class="rechts ordnerzeichen" onclick={() => api.bildBegleiterOrdner('embedding').catch(() => {})}
                title={listen.embeddingOrdner || t('bild.embedding_ordner')} aria-label={t('bild.embedding_ordner')}>
          <Hauszeichen zeichen="ordner" groesse="klein" />
        </button>
      </div>
  </StudioSection>
</section>

<style>
  .grundlagen {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 0 12px 12px;
  }

  /* The search reads like the chat list's: a quiet row until it is used. */
  .suche {
    flex: none;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 12px;
    border-radius: 9px;
    color: var(--rahmen-text, var(--text-still));
    transition: background 0.12s;
  }
  .suche:hover,
  .suche:focus-within {
    background: var(--glass-hover);
    color: var(--text);
  }
  .suche input {
    flex: 1;
    min-width: 0;
    border: none;
    background: none;
    outline: none;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
  }
  .suche input::-webkit-search-cancel-button {
    display: none;
  }

  .medium {
    flex: none;
    display: flex;
    gap: 2px;
    padding: 3px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .medium button {
    flex: 1 1 0;
    height: 28px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px/18px var(--schrift);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .medium button:hover:not(:disabled) {
    color: var(--text);
  }
  .medium button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .medium button:disabled {
    cursor: default;
    opacity: 0.5;
  }

  .wahl.schmal {
    width: 112px;
  }
  .seedplatz {
    gap: 6px;
  }
  .seedplatz .eingabe {
    width: 108px;
  }
  .wuerfel {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
  }
  .wuerfel:hover {
    color: var(--text);
  }
  .wuerfel svg {
    width: 14px;
    height: 14px;
  }

  /* The format tiles: one row, exactly four in view, dragged or scrolled
     sideways; no faded edge. */
  .zeile.kacheln {
    padding: 8px 0;
  }
  .kachelreihe {
    flex: 1;
    min-width: 0;
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: calc((100% - 18px) / 4);
    gap: 6px;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    cursor: grab;
    user-select: none;
  }
  .kachel {
    height: 56px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-hover);
    color: var(--text-leise);
    font: 400 11px/14px var(--schrift);
    cursor: inherit;
  }
  .kachel.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .kachel .form {
    box-sizing: border-box;
    border: 1.5px solid currentColor;
    border-radius: 3px;
  }
  .verhaeltnis {
    white-space: nowrap;
  }
</style>
