<script>
  /* The values one picture model starts with, opened under its row in the
     picture server: on the left the values a picture is drawn with, on the
     right what belongs to the model itself, and under both, folded, its kit
     — the VAE and the parts a kit family assembles the model from, each
     picked from its own folder. Each change is kept at once, without a save
     button, like the speech server's settings; "reset" takes the model back
     to its family's start values and to the parts the folder offers.

     What it shows is what `/bild/vorgaben` answers for the model — its
     family's start values with the user's own laid over them
     (app/bildmodellwerte.py) — so the panel, the picture window and the
     drawing tool read one and the same thing. A field the family does not
     have is not drawn: guidance only where the family's model has that
     input, CLIP skip only with a CLIP text encoder, flow shift only where the
     family starts with one. */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { familyOf } from '../lib/imageFamilies.svelte.js'
  import { PREDICTIONEN } from '../lib/bildlisten.js'
  import { EDGE_GRID, EDGE_MAX, EDGE_MIN } from '../lib/studio.svelte.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Schalter from './Schalter.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import WachsendesFeld from './WachsendesFeld.svelte'
  import Bausatzkopf from './Bausatzkopf.svelte'
  import Hauszeichen from './Hauszeichen.svelte'

  /* `listen` is the picture server's own answer (GET /bild/modelle): its
     sampler and scheduler lists and the files of each kit folder. */
  let { modell, listen = null, onfamily = null } = $props()

  const SCHLUESSEL = 'bildmodellwerte'
  /* The edges a slider stops at: every step of the grid from 256 to 2048,
     the range the studio's sliders run across too. The number field beside
     a slider ends where the service does (app/bildwahlen.py), so an edge
     past the slider's end can still be typed. */
  const SLIDER_MIN = 256
  const SLIDER_MAX = 2048
  const KANTEN = Array.from(
    { length: (SLIDER_MAX - SLIDER_MIN) / EDGE_GRID + 1 }, (_, i) => SLIDER_MIN + i * EDGE_GRID,
  )
  const SCHRITTE_MAX = 80
  const CFG_MAX = 30
  // Guidance moves in halves on the track; the field above it takes any value.
  const GUIDANCE_STUFEN = Array.from({ length: CFG_MAX * 2 + 1 }, (_, i) => i / 2)

  /* Each kit part: its label and the folder list it is picked from (the
     names the draw route takes them under, app/api/v1/bild.py
     ``_KIT_PART_FOLDERS``). */
  const TEILE = {
    vae: ['bild.vae', 'vaes'],
    t5xxl: ['bild.t5xxl', 'textversteher'],
    clip_l: ['bild.clip_l', 'textversteher'],
    clip_g: ['bild.clip_g', 'textversteher'],
    llm: ['bild.llm', 'textversteher'],
    llm_vision: ['bild.llm_vision', 'sehteile'],
    tokenizer: ['bild.tokenizer', 'tokenizers'],
    uncond_diffusion_model: ['bild.uncond_modell', 'modelle'],
    high_noise_diffusion_model: ['bild.high_noise_modell', 'modelle'],
    audio_vae: ['bild.audio_vae', 'vaes'],
    audio_encoder: ['bild.audio_encoder', 'textversteher'],
    embeddings_connectors: ['bild.embeddings_connectors', 'textversteher'],
  }

  let w = $state(null)
  let familie = $state('')
  // The model is a kit family's own diffusion model (GET /bild/vorgaben).
  let eigenstaendig = $state(false)
  let bausatzOffen = $state(true)
  let geladen = ''

  async function laden() {
    try {
      const v = await api.bildVorgaben(modell)
      familie = v.family || ''
      // The row above shows the family: told what was just read, it does
      // not keep the one from before the switch.
      onfamily?.(familie)
      eigenstaendig = Boolean(v.standalone)
      w = {
        breite: v.breite, hoehe: v.hoehe, schritte: v.schritte, cfg: v.cfg,
        guidance: v.guidance, flow_shift: v.flow_shift,
        sampler: v.sampler, scheduler: v.scheduler ?? '',
        clip_skip: v.clip_skip ? String(v.clip_skip) : 'auto',
        prediction: v.prediction || 'auto', trigger: v.trigger ?? '', hinweis: v.hinweis ?? '',
        // Whether the model's family is read from its file; on unless the
        // user switched it off for this model.
        family_detection: v.family_detection !== false,
        // The diffusion model chosen while the family is not read; empty,
        // the model's own file goes to sd.cpp as it is.
        diffusion_model: v.diffusion_model ?? '',
        // The kit as every picture of the model takes it: the parts given
        // here over the ones the folder offers.
        ...Object.fromEntries(Object.keys(TEILE).map((teil) => [teil, v.parts?.[teil] ?? ''])),
      }
      gesendet = { ...w }
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  $effect(() => {
    if (modell && modell !== geladen) {
      geladen = modell
      untrack(laden)
    }
  })

  const eintrag = $derived(familyOf(familie))
  const mitGuidance = $derived(eintrag?.start?.guidance != null)
  /* The family is not read for this model: no family says which parts
     belong, so every part can be given and each may stay empty — the
     diffusion model too, and then the model's own file goes to sd.cpp as
     it is. Exactly the given parts are sent. */
  const free = $derived(Boolean(w) && !w.family_detection)
  // A kit family's own diffusion model is assembled from its parts; any
  // other model has only its VAE here.
  const bausatz = $derived(free || Boolean(eintrag?.kit && eigenstaendig))
  // The parts the family reads: its VAE, its text encoders, its further
  // parts — and every part there is where no family is read.
  const teile = $derived(
    free ? Object.keys(TEILE) : bausatz ? ['vae', ...eintrag.encoders, ...eintrag.parts] : ['vae'],
  )
  /* What the model cannot start without: its diffusion model, every text
     encoder its family reads and, where the family needs a VAE (its kit
     names one, or it decodes with one of its own), the VAE
     (app/bildbausatz.py ``fehlendes_teil``). */
  const noetig = $derived(
    bausatz && !free
      ? [...eintrag.encoders, ...(eintrag.needs_vae ? ['vae'] : [])] : [],
  )
  const da = $derived(noetig.filter((teil) => w?.[teil]).length)
  const mitFlowShift = $derived(eintrag?.start?.flow_shift != null)
  const clipSchichten = $derived(eintrag?.clip_layers ?? null)

  const alsAuswahl = (namen) => (namen ?? []).map((n) => ({ wert: n, text: n }))
  const clipEintraege = $derived([
    { wert: 'auto', text: t('bild.prediction_auto') },
    ...Array.from({ length: clipSchichten ?? 0 }, (_, i) => ({ wert: String(i + 1), text: String(i + 1) })),
  ])

  /* What a field is stored as: the window's "auto" is no value of the
     model's own, a CLIP skip travels as its number, and an empty part is
     the one the folder offers. */
  function gespeichert(name, wert) {
    // Only "off" is the model's own: switched on again it is like every model.
    if (name === 'family_detection') return wert ? null : false
    if (name in TEILE || name === 'diffusion_model') return wert || null
    if (name === 'clip_skip') return wert === 'auto' ? null : Number(wert)
    if (name === 'prediction') return wert === 'auto' ? '' : wert
    if (wert === '' && ['breite', 'hoehe', 'schritte', 'cfg', 'guidance', 'flow_shift'].includes(name)) return null
    return wert
  }

  /* Kept at once, a moment after the last change, so dragging a slider is
     one write and not thirty. Only the fields that changed travel; the
     service merges them into what the model already holds. */
  let gesendet = null
  let zeit
  // The write that waits for its moment; the window going away does not
  // wait for it.
  let pendingWrite = null
  $effect(() => {
    const jetzt = w ? { ...w } : null
    if (!jetzt || !gesendet) return
    const geaendert = {}
    for (const [name, wert] of Object.entries(jetzt)) {
      if (wert !== gesendet[name]) geaendert[name] = gespeichert(name, wert)
    }
    if (!Object.keys(geaendert).length) return
    clearTimeout(zeit)
    const schreiben = async () => {
      try {
        await api.einstellungMischen('global', SCHLUESSEL, { [modell]: geaendert })
        gesendet = { ...gesendet, ...Object.fromEntries(Object.keys(geaendert).map((n) => [n, jetzt[n]])) }
        // A part given back to the folder shows the file the folder offers,
        // and with the reading of the family switched the model stands at
        // other start values and another kit.
        if (
          'family_detection' in geaendert
          || Object.keys(geaendert).some((n) => n in TEILE && geaendert[n] === null)
        ) await laden()
      } catch (fehler) {
        melde(String(fehler.message || fehler), 'fehler')
      }
    }
    pendingWrite = schreiben
    zeit = setTimeout(() => {
      pendingWrite = null
      schreiben()
    }, 350)
    return () => clearTimeout(zeit)
  })

  /* A change still waiting when the row closes is kept at once, not dropped
     with the timer. */
  $effect(() => () => {
    if (!pendingWrite) return
    clearTimeout(zeit)
    const schreiben = pendingWrite
    pendingWrite = null
    schreiben()
  })

  /* A part's choices: the files of its folder. An empty entry stands for
     the VAE inside a model that is no kit, for a part a kit cannot start
     without and that is missing — the start then names it — and for a part
     the kit can do without, which then stays off. */
  function teilEintraege(teil) {
    const dateien = alsAuswahl(listen?.[TEILE[teil][1]])
    // No family is read: an empty part is left to sd.cpp.
    if (free) return [{ wert: '', text: t('parameter.auto') }, ...dateien]
    if (!bausatz) return [{ wert: '', text: t('bild.vae_keins') }, ...dateien]
    if (!noetig.includes(teil)) return [{ wert: '', text: t('bild.adetailer_keins') }, ...dateien]
    return [{ wert: '', text: t('bildserver.teil_fehlt_kurz') }, ...dateien]
  }

  async function zuruecksetzen() {
    clearTimeout(zeit)
    pendingWrite = null
    try {
      await api.einstellungMischen('global', SCHLUESSEL, { [modell]: null })
      await laden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
</script>

{#if w}
  <div class="zeile werte">
    <div class="spalten">
      <div class="spalte">
        <div class="kopf tafelkopf">{t('bildserver.werte')}</div>
        <div class="feld regel">
          <div class="kopfzeile">
            <span class="was">{t('bild.breite')}</span>
            <div class="zahl"><Zahlenfeld bind:wert={w.breite} min={EDGE_MIN} max={EDGE_MAX} schritt={EDGE_GRID} grid={EDGE_GRID} ganzzahlig /></div>
          </div>
          <Schieberegler bind:wert={w.breite} stufen={KANTEN}
                         mit_zahl={false} fuellung beschriftung={t('bild.breite')} />
        </div>
        <div class="feld regel">
          <div class="kopfzeile">
            <span class="was">{t('bild.hoehe')}</span>
            <div class="zahl"><Zahlenfeld bind:wert={w.hoehe} min={EDGE_MIN} max={EDGE_MAX} schritt={EDGE_GRID} grid={EDGE_GRID} ganzzahlig /></div>
          </div>
          <Schieberegler bind:wert={w.hoehe} stufen={KANTEN}
                         mit_zahl={false} fuellung beschriftung={t('bild.hoehe')} />
        </div>
        <div class="feld regel">
          <div class="kopfzeile">
            <span class="was">{t('bild.schritte')}</span>
            <div class="zahl"><Zahlenfeld bind:wert={w.schritte} min={1} max={SCHRITTE_MAX} schritt={1} ganzzahlig /></div>
          </div>
          <Schieberegler bind:wert={w.schritte} min={1} max={SCHRITTE_MAX} mit_zahl={false} fuellung
                         beschriftung={t('bild.schritte')} />
        </div>
        <div class="feld regel">
          <div class="kopfzeile">
            <span class="was">{t('bild.cfg')}</span>
            <div class="zahl"><Zahlenfeld bind:wert={w.cfg} min={0} max={CFG_MAX} schritt={0.5} /></div>
          </div>
          <Schieberegler bind:wert={w.cfg} min={0} max={CFG_MAX} mit_zahl={false} fuellung
                         beschriftung={t('bild.cfg')} />
        </div>
        {#if mitGuidance}
          <div class="feld regel">
            <div class="kopfzeile">
              <span class="was">{t('bild.guidance')}</span>
              <div class="zahl"><Zahlenfeld bind:wert={w.guidance} min={0} max={CFG_MAX} schritt={0.1} /></div>
            </div>
            <Schieberegler bind:wert={w.guidance} stufen={GUIDANCE_STUFEN} mit_zahl={false} fuellung
                           beschriftung={t('bild.guidance')} />
          </div>
        {/if}
        {#if mitFlowShift}
          <div class="feld">
            <span class="was">{t('bild.flow_shift')}</span>
            <div class="breit"></div>
            <div class="zahl"><Zahlenfeld bind:wert={w.flow_shift} min={-100} max={100} schritt={0.1} /></div>
          </div>
        {/if}
        <div class="feld">
          <span class="was">{t('bild.sampler')}</span>
          <div class="breit">
            <Auswahlfeld bind:wert={w.sampler} eintraege={alsAuswahl(listen?.sampler)} beschriftung={t('bild.sampler')} />
          </div>
        </div>
        <div class="feld">
          <span class="was">{t('bild.scheduler')}</span>
          <div class="breit">
            <Auswahlfeld bind:wert={w.scheduler} beschriftung={t('bild.scheduler')}
                         eintraege={[{ wert: '', text: t('parameter.auto') }, ...alsAuswahl(listen?.scheduler)]} />
          </div>
        </div>
      </div>

      <div class="spalte">
        <div class="kopf tafelkopf">{t('bildserver.modell_spalte')}</div>
        <!-- Whether the model's family is read from its file. Off, every
             part of the kit below can be given by hand. -->
        <div class="feld">
          <span class="was">{t('bildserver.detect_family')}</span>
          <div class="breit"></div>
          <Schalter an={w.family_detection} beschriftung={t('bildserver.detect_family')}
                    onschalten={(neu) => (w.family_detection = neu)} />
        </div>
        {#if clipSchichten}
          <div class="feld">
            <span class="was">{t('bild.clip_skip')}</span>
            <div class="breit">
              <Auswahlfeld bind:wert={w.clip_skip} eintraege={clipEintraege} beschriftung={t('bild.clip_skip')} />
            </div>
          </div>
        {/if}
        <div class="feld">
          <span class="was">{t('bildserver.vorhersage')}</span>
          <div class="breit">
            <Auswahlfeld bind:wert={w.prediction} beschriftung={t('bildserver.vorhersage')}
                         eintraege={[{ wert: 'auto', text: t('bild.prediction_auto') }, ...alsAuswahl(PREDICTIONEN)]} />
          </div>
        </div>
        <div class="feld">
          <label class="was" for="bmw-trigger-{modell}">{t('bildserver.trigger')}</label>
          <input id="bmw-trigger-{modell}" class="eingabe breit" bind:value={w.trigger} autocomplete="off" />
        </div>
        <div class="feld hoch">
          <span class="was">{t('bildserver.hinweis')}</span>
          <div class="breit">
            <WachsendesFeld bind:wert={w.hinweis} knapp zeilen={3} beschriftung={t('bildserver.hinweis')} />
          </div>
        </div>
      </div>
    </div>
    <div class="bausatz">
      <!-- The head and, at its end, the sign that opens the folder the VAE
           files are picked from. -->
      <div class="kithead">
        <Bausatzkopf open={bausatzOffen} there={bausatz && !free ? da + 1 : null} all={noetig.length + 1}
                     countRight onToggle={() => (bausatzOffen = !bausatzOffen)} />
        <button class="foldersign" onclick={() => api.bildBegleiterOrdner('vae').catch(() => {})}
                title={t('bild.vae_ordner')} aria-label={t('bild.vae_ordner')}>
          <Hauszeichen zeichen="ordner" groesse="klein" />
        </button>
      </div>
      {#if bausatzOffen}
        <div class="teile">
          {#if free}
            <div class="feld">
              <span class="was">{t('bild.diffusion_model')}</span>
              <div class="breit">
                <Auswahlfeld bind:wert={w.diffusion_model} beschriftung={t('bild.diffusion_model')}
                             eintraege={[{ wert: '', text: t('parameter.auto') }, ...alsAuswahl(listen?.modelle)]} />
              </div>
            </div>
          {:else if bausatz}
            <div class="feld">
              <span class="was">{t('bild.diffusion_model')}</span>
              <div class="breit">
                <Auswahlfeld wert={modell} beschriftung={t('bild.diffusion_model')}
                             eintraege={[{ wert: modell, text: modell }]} />
              </div>
            </div>
          {/if}
          {#each teile as teil (teil)}
            <div class="feld">
              <span class="was">{t(TEILE[teil][0])}</span>
              <div class="breit">
                <Auswahlfeld bind:wert={w[teil]} beschriftung={t(TEILE[teil][0])}
                             eintraege={teilEintraege(teil)} />
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>
    <button class="stillknopf" onclick={zuruecksetzen}>{t('sprachserver.zuruecksetzen')}</button>
  </div>
{/if}

<style>
  /* One row of the model card, taller than the others: two columns of
     fields, 24 apart — a field 44 px, a slider field taller — and the reset
     button under them at the right. */
  .zeile.werte {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
    padding: 4px 16px 16px;
  }
  .spalten {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 0 24px;
  }
  .spalte {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .kopf {
    height: 18px;
    line-height: 18px;
  }
  .feld {
    min-height: 44px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  /* A slider field: its name and its number on one line, the slider over
     the whole width under them. */
  .feld.regel {
    flex-direction: column;
    align-items: stretch;
    justify-content: center;
    gap: 2px;
    padding: 6px 0;
  }
  /* The head line itself is the card's (Serverabschnitt.svelte); here its
     name takes the room up to the number. */
  .kopfzeile .was {
    flex: 1;
    width: auto;
    min-width: 0;
  }
  .kopfzeile .zahl {
    width: auto;
  }
  .feld.hoch {
    align-items: flex-start;
    padding-top: 7px;
    padding-bottom: 6px;
  }
  /* The note's field stands three lines tall before anything is written. */
  .feld.hoch :global(textarea) {
    min-height: 76px;
  }
  .was {
    flex: none;
    width: 104px;
    font-size: 13px;
    line-height: 18px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .zahl {
    flex: none;
    width: 84px;
  }
  .breit {
    flex: 1;
    min-width: 0;
  }
  .eingabe {
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
  .eingabe:focus {
    outline: 2px solid var(--linie-stark);
    outline-offset: -2px;
  }
  .stillknopf {
    align-self: flex-end;
  }
  /* The kit: under a hairline, its head folds it, and its parts stand in
     the same two columns as the values above. */
  .bausatz {
    border-top: 1px solid var(--linie);
    padding-top: 12px;
  }
  .kithead {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .kithead :global(.kitkopf) {
    flex: 1;
    min-width: 0;
    width: auto;
  }
  .foldersign {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .foldersign:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .teile {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 0 24px;
  }
</style>
