<script>
  /* The values one picture model starts with, opened under its row in the
     picture server: two cards side by side, equally tall — on the left the
     values a picture is drawn with, on the right what belongs to the model
     itself and, as its last row, folded, its kit — the VAE and the parts a
     kit family assembles the model from, each picked from its own folder.
     A change is kept when the save button at the head's right end is
     pressed, not before; "reset", beside it, takes the
     model back to its family's start values and to the parts the folder
     offers, and writes that at once. With `modelle` the head's left end is a
     choice of every picture model of the folder (each with its family's mark);
     the page that owns the choice asks before it switches the model over
     changes not saved (`hasUnsaved`). Without `modelle` the head names the
     model.

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
  import { PREDICTIONEN, TAE_PREFIX } from '../lib/bildlisten.js'
  import { EDGE_GRID, EDGE_MAX, EDGE_MIN } from '../lib/studio.svelte.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Schalter from './Schalter.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import WachsendesFeld from './WachsendesFeld.svelte'
  import Bausatzkopf from './Bausatzkopf.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Serverreihe from './Serverreihe.svelte'

  /* `listen` is the picture server's own answer (GET /bild/modelle): its
     sampler and scheduler lists and the files of each kit folder. */
  let { modell, listen = null, onfamily = null, modelle = null, onwechsel = null } = $props()

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
    clip_vision: ['bild.sw_clip_vision', 'textversteher'],
  }

  let w = $state(null)
  let familie = $state('')
  // The model is a kit family's own diffusion model (GET /bild/vorgaben).
  let eigenstaendig = $state(false)
  // The model is a checkpoint of a kit family without text encoders of its
  // own: it is drawn with the parts of its family beside it.
  let checkpoint = $state(false)
  // The further parts its docs name for this diffusion model: it does not
  // start without them.
  let needed = $state([])
  // The further parts of the family that this model takes (GET
  // /bild/vorgaben); a part the family names and the model does not take
  // has no row.
  let taken = $state([])
  let bausatzOffen = $state(false)
  let geladen = ''

  async function laden() {
    try {
      const v = await api.bildVorgaben(modell)
      familie = v.family || ''
      // The row above shows the family: told what was just read, it does
      // not keep the one from before the switch.
      onfamily?.(modell, familie)
      eigenstaendig = Boolean(v.standalone)
      checkpoint = Boolean(v.bare)
      needed = v.needed_parts ?? []
      taken = v.parts_taken ?? []
      w = {
        breite: v.breite, hoehe: v.hoehe, schritte: v.schritte, cfg: v.cfg,
        guidance: v.guidance, flow_shift: v.flow_shift,
        video_frames: v.video_frames, fps: v.fps,
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
  // A checkpoint of a kit family shows the parts its family reads, but no
  // diffusion model: the checkpoint is it, and none of the parts is needed.
  const withParts = $derived(bausatz || Boolean(eintrag?.kit && checkpoint))
  // The parts the family reads: its VAE, its text encoders, its further
  // parts — and every part there is where no family is read.
  const teile = $derived(
    free ? Object.keys(TEILE)
      : withParts
        ? ['vae', ...eintrag.encoders, ...eintrag.parts.filter((teil) => taken.includes(teil))]
        : ['vae'],
  )
  /* What the model cannot start without: its diffusion model, every text
     encoder its family reads and, where the family needs a VAE (its kit
     names one, or it decodes with one of its own), the VAE — and the
     further parts its docs name for it (app/bildbausatz.py
     ``fehlendes_teil``). */
  const noetig = $derived(
    bausatz && !free
      ? [...eintrag.encoders, ...(eintrag.needs_vae ? ['vae'] : []), ...needed] : [],
  )
  const da = $derived(noetig.filter((teil) => w?.[teil]).length)
  // The rows that stand under the head once it is unfolded: the diffusion
  // model where the family is assembled or not read, and one per part.
  const teileZeilen = $derived((bausatz ? 1 : 0) + teile.length)
  const mitFlowShift = $derived(eintrag?.start?.flow_shift != null)
  // A video family starts with frames; its rate is shown unless the
  // family draws at a fixed one.
  const showsFrames = $derived(eintrag?.start?.frames != null)
  const showsFps = $derived(eintrag?.start?.fps != null && !eintrag?.fixed_fps)
  const clipSchichten = $derived(eintrag?.clip_layers ?? null)

  const alsAuswahl = (namen) => (namen ?? []).map((n) => ({ wert: n, text: n }))
  const clipEintraege = $derived([
    { wert: 'auto', text: t('bild.prediction_auto') },
    ...Array.from({ length: clipSchichten ?? 0 }, (_, i) => ({ wert: String(i + 1), text: String(i + 1) })),
  ])

  // The fields that hold a number: left empty they are not set.
  const NUMBER_FIELDS = ['breite', 'hoehe', 'schritte', 'cfg', 'guidance', 'flow_shift', 'video_frames', 'fps']

  /* What a field is stored as: the window's "auto" is no value of the
     model's own, a CLIP skip travels as its number, and an empty part is
     the one the folder offers. */
  function gespeichert(name, wert) {
    // Only "off" is the model's own: switched on again it is like every model.
    if (name === 'family_detection') return wert ? null : false
    if (name in TEILE || name === 'diffusion_model') return wert || null
    if (name === 'clip_skip') return wert === 'auto' ? null : Number(wert)
    if (name === 'prediction') return wert === 'auto' ? '' : wert
    if (wert === '' && NUMBER_FIELDS.includes(name)) return null
    return wert
  }

  /* What the fields held when they were last read or saved, against what
     they hold now: the fields that differ are the changes not saved yet. Only
     those travel when the save button is pressed; the service merges them into
     what the model already holds. Nothing is written by itself. */
  let gesendet = $state(null)
  let saving = $state(false)
  const changes = $derived.by(() => {
    const out = {}
    if (!w || !gesendet) return out
    for (const [name, wert] of Object.entries(w)) {
      if (wert !== gesendet[name]) out[name] = gespeichert(name, wert)
    }
    return out
  })
  const unsaved = $derived(Object.keys(changes).length > 0)

  // The table above asks this before it closes the block or opens another model.
  export function hasUnsaved() {
    return unsaved
  }

  async function save() {
    if (saving || !unsaved) return
    const snapshot = { ...w }
    const change = { ...changes }
    saving = true
    try {
      await api.einstellungMischen('global', SCHLUESSEL, { [modell]: change })
      gesendet = { ...gesendet, ...Object.fromEntries(Object.keys(change).map((n) => [n, snapshot[n]])) }
      // A part given back to the folder shows the file the folder offers,
      // and with the reading of the family switched the model stands at
      // other start values and another kit.
      if (
        'family_detection' in change
        || Object.keys(change).some((n) => n in TEILE && change[n] === null)
      ) await laden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      saving = false
    }
  }

  /* A part's choices: the files of its folder. An empty entry stands for
     the VAE inside a model that is no kit, for a part a kit cannot start
     without and that is missing — the start then names it — and for a part
     the kit can do without, which then stays off. */
  function teilEintraege(teil) {
    const dateien = alsAuswahl(listen?.[TEILE[teil][1]])
    // The VAE is also where a tiny autoencoder is chosen, under a line of its
    // own: the ones of the model's family only, and every one where no
    // family is read.
    if (teil === 'vae') {
      const gruppe = t('bild.vae_group_tae')
      for (const n of listen?.taesd_files ?? []) {
        if (!free && eintrag && !eintrag.tae?.includes(listen?.tae_kinds?.[n])) continue
        dateien.push({ wert: TAE_PREFIX + n, text: n, group: gruppe })
      }
    }
    // No family is read: an empty part is left to sd.cpp.
    if (free) return [{ wert: '', text: t('parameter.auto') }, ...dateien]
    // A checkpoint carries its own VAE; its other parts stay off unless given.
    if (!bausatz && (!withParts || teil === 'vae')) {
      return [{ wert: '', text: t('bild.vae_keins') }, ...dateien]
    }
    if (!noetig.includes(teil)) return [{ wert: '', text: t('bild.adetailer_keins') }, ...dateien]
    return [{ wert: '', text: t('bildserver.teil_fehlt_kurz') }, ...dateien]
  }

  // Takes the same lock as the save: the two never run side by side.
  async function zuruecksetzen() {
    if (saving) return
    saving = true
    try {
      await api.einstellungMischen('global', SCHLUESSEL, { [modell]: null })
      await laden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      saving = false
    }
  }
</script>

{#snippet signs()}
  <!-- The two signs at the head's right end: back to the start values,
       written at once, and save what was changed — pressable only while
       something was. -->
  <span class="signs">
    <button type="button" class="signbutton" onclick={zuruecksetzen} disabled={saving}
            aria-label={t('sprachserver.zuruecksetzen')} title={t('sprachserver.zuruecksetzen')}>
      <Hauszeichen zeichen="refresh" groesse={16} />
    </button>
    <button type="button" class="signbutton" onclick={save} disabled={!unsaved || saving}
            aria-label={t('app.sichern')} title={t('app.sichern')}>
      <Hauszeichen zeichen="save" groesse={16} />
    </button>
  </span>
{/snippet}

{#snippet inhalt()}
  {#if w}
  <Serverreihe>
    {#snippet links()}
      <Serverabschnitt zeichen="settings_two" titel={t('sprachserver.gruppe_parameter')} gewicht={1}>
        <div class="zeile regel">
          <div class="kopfzeile">
            <span class="regelname">{t('bild.breite')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.breite} min={EDGE_MIN} max={EDGE_MAX} schritt={EDGE_GRID} grid={EDGE_GRID} ganzzahlig /></div>
          </div>
          <Schieberegler bind:wert={w.breite} stufen={KANTEN}
                         mit_zahl={false} fuellung beschriftung={t('bild.breite')} />
        </div>
        <div class="zeile regel">
          <div class="kopfzeile">
            <span class="regelname">{t('bild.hoehe')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.hoehe} min={EDGE_MIN} max={EDGE_MAX} schritt={EDGE_GRID} grid={EDGE_GRID} ganzzahlig /></div>
          </div>
          <Schieberegler bind:wert={w.hoehe} stufen={KANTEN}
                         mit_zahl={false} fuellung beschriftung={t('bild.hoehe')} />
        </div>
        <div class="zeile regel">
          <div class="kopfzeile">
            <span class="regelname">{t('bild.schritte')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.schritte} min={1} max={SCHRITTE_MAX} schritt={1} ganzzahlig /></div>
          </div>
          <Schieberegler bind:wert={w.schritte} min={1} max={SCHRITTE_MAX} mit_zahl={false} fuellung
                         beschriftung={t('bild.schritte')} />
        </div>
        <div class="zeile regel">
          <div class="kopfzeile">
            <span class="regelname">{t('bild.cfg')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.cfg} min={0} max={CFG_MAX} schritt={0.5} /></div>
          </div>
          <Schieberegler bind:wert={w.cfg} min={0} max={CFG_MAX} mit_zahl={false} fuellung
                         beschriftung={t('bild.cfg')} />
        </div>
        {#if mitGuidance}
          <div class="zeile regel">
            <div class="kopfzeile">
              <span class="regelname">{t('bild.guidance')}</span>
              <div class="zahlplatz"><Zahlenfeld bind:wert={w.guidance} min={0} max={CFG_MAX} schritt={0.1} /></div>
            </div>
            <Schieberegler bind:wert={w.guidance} stufen={GUIDANCE_STUFEN} mit_zahl={false} fuellung
                           beschriftung={t('bild.guidance')} />
          </div>
        {/if}
        {#if mitFlowShift}
          <div class="zeile">
            <span class="name">{t('bild.flow_shift')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.flow_shift} min={-100} max={100} schritt={0.1} /></div>
          </div>
        {/if}
        {#if showsFrames}
          <div class="zeile">
            <span class="name">{t('bild.video_frames')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.video_frames} min={1} max={10000} schritt={1} ganzzahlig /></div>
          </div>
        {/if}
        {#if showsFps}
          <div class="zeile">
            <span class="name">{t('bild.fps')}</span>
            <div class="zahlplatz"><Zahlenfeld bind:wert={w.fps} min={1} max={1000} schritt={1} ganzzahlig /></div>
          </div>
        {/if}
        <div class="zeile">
          <span class="name">{t('bild.sampler')}</span>
          <div class="wahl">
            <Auswahlfeld bind:wert={w.sampler} eintraege={alsAuswahl(listen?.sampler)} beschriftung={t('bild.sampler')} />
          </div>
        </div>
        <div class="zeile">
          <span class="name">{t('bild.scheduler')}</span>
          <div class="wahl">
            <Auswahlfeld bind:wert={w.scheduler} beschriftung={t('bild.scheduler')}
                         eintraege={[{ wert: '', text: t('parameter.auto') }, ...alsAuswahl(listen?.scheduler)]} />
          </div>
        </div>
      </Serverabschnitt>
    {/snippet}
    {#snippet rechts()}
      <Serverabschnitt zeichen="gear" titel={t('bildserver.modell_spalte')} gewicht={1}>
        <!-- Only the note's row takes up the height the other card has over
             this one: its field stretches, the other rows keep their height. -->
        <!-- Whether the model's family is read from its file. Off, every
             part of the kit below can be given by hand. -->
        <div class="zeile niedrig" style:flex-grow="0">
          <span class="name">{t('bildserver.detect_family')}</span>
          <Schalter an={w.family_detection} beschriftung={t('bildserver.detect_family')}
                    onschalten={(neu) => (w.family_detection = neu)} />
        </div>
        {#if clipSchichten}
          <div class="zeile" style:flex-grow="0">
            <span class="name">{t('bild.clip_skip')}</span>
            <div class="wahl">
              <Auswahlfeld bind:wert={w.clip_skip} eintraege={clipEintraege} beschriftung={t('bild.clip_skip')} />
            </div>
          </div>
        {/if}
        <div class="zeile" style:flex-grow="0">
          <span class="name">{t('bildserver.vorhersage')}</span>
          <div class="wahl">
            <Auswahlfeld bind:wert={w.prediction} beschriftung={t('bildserver.vorhersage')}
                         eintraege={[{ wert: 'auto', text: t('bild.prediction_auto') }, ...alsAuswahl(PREDICTIONEN)]} />
          </div>
        </div>
        <div class="zeile" style:flex-grow="0">
          <label class="name" for="bmw-trigger-{modell}">{t('bildserver.trigger')}</label>
          <input id="bmw-trigger-{modell}" class="eingabe wahl" bind:value={w.trigger} autocomplete="off" />
        </div>
        <div class="zeile stapel">
          <span class="name">{t('bildserver.hinweis')}</span>
          <WachsendesFeld bind:wert={w.hinweis} knapp volleHoehe beschriftung={t('bildserver.hinweis')} />
        </div>
        <!-- The head folds the kit and, at its end, the sign that opens the
             folder the VAE files are picked from. -->
        <div class="zeile liste kithead" style:flex-grow="0">
          <Bausatzkopf open={bausatzOffen} there={bausatz && !free ? da + 1 : null} all={noetig.length + 1}
                       word={t('bildserver.parts_count', { count: teileZeilen })}
                       countRight onToggle={() => (bausatzOffen = !bausatzOffen)} />
          <button class="foldersign" onclick={() => api.bildBegleiterOrdner('vae').catch(() => {})}
                  title={t('bild.vae_ordner')} aria-label={t('bild.vae_ordner')}>
            <Hauszeichen zeichen="ordner" groesse="klein" />
          </button>
        </div>
        {#if bausatzOffen}
          {#if free}
            <div class="zeile" style:flex-grow="0">
              <span class="name" title={t('bild.diffusion_model')}>{t('bild.diffusion_model')}</span>
              <div class="wahl">
                <Auswahlfeld bind:wert={w.diffusion_model} beschriftung={t('bild.diffusion_model')}
                             eintraege={[{ wert: '', text: t('parameter.auto') }, ...alsAuswahl(listen?.modelle)]} />
              </div>
            </div>
          {:else if bausatz}
            <div class="zeile" style:flex-grow="0">
              <span class="name" title={t('bild.diffusion_model')}>{t('bild.diffusion_model')}</span>
              <div class="wahl">
                <Auswahlfeld wert={modell} beschriftung={t('bild.diffusion_model')}
                             eintraege={[{ wert: modell, text: modell }]} />
              </div>
            </div>
          {/if}
          {#each teile as teil (teil)}
            <div class="zeile" style:flex-grow="0">
              <span class="name" title={t(TEILE[teil][0])}>{t(TEILE[teil][0])}</span>
              <div class="wahl">
                <Auswahlfeld bind:wert={w[teil]} beschriftung={t(TEILE[teil][0])}
                             eintraege={teilEintraege(teil)} />
              </div>
            </div>
          {/each}
        {/if}
      </Serverabschnitt>
    {/snippet}
  </Serverreihe>
  {/if}
{/snippet}

{#if modelle}
  <!-- The choice stands where the model's name would: its width is the
       field's own, the signs keep the right end. -->
  <section class="block">
    <div class="kopf tafelkopf">
      <div class="wechsel">
        <Auswahlfeld bind:wert={() => modell, (neu) => onwechsel?.(neu)} eintraege={modelle}
                     beschriftung={t('bild.modell')} search searchLabel={t('app.suchen')} />
      </div>
      {@render signs()}
    </div>
    {@render inhalt()}
  </section>
{:else}
  <!-- The head carries the model's name from the first moment, also while
       its values are still being read. -->
  <Serverabschnitt titel={modell} bare>
    {#snippet rechts()}{@render signs()}{/snippet}
    {@render inhalt()}
  </Serverabschnitt>
{/if}

<style>
  /* The block with the choice in its head: the head is one line, the choice
     takes the room the signs leave, the values stand under it. */
  .block {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .kopf {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .wechsel {
    flex: 0 1 360px;
    min-width: 0;
    margin-right: auto;
  }
  /* The head's two signs: 34 px of button glass, the way the parameter panel
     and the prompt page draw theirs; the head is 26 tall, so they reach
     4 px over it on both sides. */
  .signs {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .signbutton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 34px;
    height: 34px;
    margin: -4px 0;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    cursor: pointer;
  }
  .signbutton:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .signbutton:disabled {
    cursor: default;
    opacity: 0.5;
  }
  /* The rows and their parts are Serverabschnitt.svelte's; here only what
     this block adds. The trigger words stand in a field of the picker's
     width. */
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
  /* The kit's head folds it and, at its end, carries the sign that opens
     the folder the VAE files are picked from. */
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
</style>
