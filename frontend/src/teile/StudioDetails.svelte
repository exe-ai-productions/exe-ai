<script>
  /* The studio's right column, "Details": the fine settings of a picture
     for this chat, under the head the column gives it and above the row of
     tool signs, which stays. From the top: the inputs of the kind (for a
     kind that starts from pictures, and the sound of a video), the face,
     the face transfer, pose and structure, upscaling — all open — then the
     fine tuning and "Advanced", both shut. sd.cpp's further switches stand
     folded at the foot of their section. A row that only acts beside a
     switch or a choice stands there once that one is on.

     The values are the chat's own, in the one store the left column fills
     and writes (lib/studio.svelte.js); this column only reads and sets
     them. Pictures go up like any attachment and travel by the name the
     service gave them; one that arrives after the chat was switched, or
     after a newer choice, is set nowhere. */
  import { untrack } from 'svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Bildablage from './Bildablage.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import ImageSwitchRows from './ImageSwitchRows.svelte'
  import InfoMark from './InfoMark.svelte'
  import Schalter from './Schalter.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import StudioLoraStack from './StudioLoraStack.svelte'
  import StudioSection from './StudioSection.svelte'
  import StudioSwitches from './StudioSwitches.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import { api } from '../lib/api.js'
  import { PREDICTIONEN } from '../lib/bildlisten.js'
  import { chatanzeige } from '../lib/chatanzeige.svelte.js'
  import { familyOf, imageFamilies } from '../lib/imageFamilies.svelte.js'
  import { imageSwitches } from '../lib/imageSwitches.svelte.js'
  import { rollfade } from '../lib/rollfade.js'
  import {
    art, auswahl, emptyArea, familie, familieWaehlen, listen, refVideo, refVideoRelease, refVideoSet, searchRows,
    searching, startbildWaehlen, steuervideo, steuervideoLoesen, steuervideoSetzen, strengthDecides,
    takesRefVideo, werte,
  } from '../lib/studio.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'

  const uid = $props.id()
  const feld = (name) => `${uid}-${name}`
  const alsAuswahl = (namen) => (namen ?? []).map((n) => ({ wert: n, text: n }))
  const keins = (namen) => [{ wert: '', text: t('bild.adetailer_keins') }, ...alsAuswahl(namen)]

  /* The usual range of each slider (the table of the picture limits); the
     number beside it takes what sd.cpp takes. */
  const reihe = (von, bis, schritt) => Array.from(
    { length: Math.round((bis - von) / schritt) + 1 },
    (_, i) => Math.round((von + i * schritt) * 100) / 100,
  )
  const IMG_CFG_STUFEN = reihe(1, 30, 0.5)
  const STAERKE_STUFEN = reihe(0, 1, 0.05)
  const ID_STUFEN = reihe(0, 2, 0.05)
  const CONTROL_STUFEN = reihe(-1, 2, 0.05)
  const HIRES_STUFEN = reihe(1, 4, 0.05)
  const ZIEL_STUFEN = reihe(0, 2048, 8)
  const SLG_STUFEN = reihe(0, 10, 0.1)
  const ETA_STUFEN = reihe(0, 1, 0.01)
  const FLOW_STUFEN = reihe(0, 10, 0.1)
  // A hires target edge takes what a picture's edge takes (app/bildwahlen.py).
  const KANTE_MAX = 4096
  // The scale a switched-on highres pass starts at.
  const HIRES_START = '1.5'

  const kind = $derived(art())
  /* The strength stays in reach while it is what "auto" goes by, also when
     the next press draws from the text. */
  const strengthShown = $derived(strengthDecides())
  const familyEntry = $derived(familie())
  /* The pose section stands only where sd.cpp computes a ControlNet: the
     family table's `control_net`. A model whose family is unknown keeps it. */
  const controlNetOffered = $derived(!familyEntry || familyEntry.control_net !== false)
  // A family that takes several references (the family table's `many_references`).
  const viele = $derived(Boolean(familyEntry?.many_references))
  /* How many CLIP layers can be skipped: the family's own CLIP encoder's
     count; a model whose family is unknown gets the smallest any family has. */
  const clipSchichten = $derived.by(() => {
    if (familyEntry) return familyEntry.clip_layers
    const bekannt = imageFamilies.list.map((f) => f.clip_layers).filter(Boolean)
    return bekannt.length ? Math.min(...bekannt) : null
  })
  const hires = $derived(Boolean(werte.hires_wahl))
  // sd-cli's own rule: a set target size beats the ×-scale.
  const zielGesetzt = $derived(hires && (Number(werte.hires_breite) > 0 || Number(werte.hires_hoehe) > 0))
  const bedingungen = $derived({
    ad_model: Boolean(werte.ad_modell), photomaker: Boolean(werte.pm_klasse), hires,
    high_noise: Boolean(familyEntry?.parts?.includes('high_noise_diffusion_model')), video: kind.video,
    ref_video: Boolean(refVideo.datei),
  })

  /* sd.cpp's switches of the model itself stand where they are used. The
     sound a video is drawn to is an input like the control video, for a
     video model. The layer count and the motion module stand under
     "Advanced", each for the family that reads it: the layers for the one
     model that splits a picture into layers, the motion module for a
     picture family that draws a video only with one beside it. */
  // What of a set of them is drawn now: a row for videos only stands with a
  // video.
  const modelRowsOf = (keys) => imageSwitches.list.filter((row) => row.group === 'model'
    && keys.includes(row.key) && (row.video == null || row.video === kind.video))
  const SOUND_KEYS = ['audio', 'ref_audio']
  const soundShown = $derived(kind.video && (familyEntry?.video ?? true) && modelRowsOf(SOUND_KEYS).length > 0)
  // The reference video and its sound, for the family that reads one.
  const REF_VIDEO_KEYS = ['ref_video_audio']
  const refVideoShown = $derived(takesRefVideo(kind, familyEntry))
  const VIDEO_TASKS = ['t2v', 'i2v']
  const modelKeys = $derived([
    ...(familyEntry?.name === 'qwen_image_layered' ? ['qwen_image_layers'] : []),
    ...(familyEntry && !familyEntry.video && familyEntry.tasks.some((task) => VIDEO_TASKS.includes(task))
      ? ['motion_module'] : []),
  ])
  const modelRows = $derived(modelRowsOf(modelKeys))

  /* One upload: the name the service gave the picture, or null when it
     failed or no longer counts — the chat was switched, or `gilt` says a
     newer choice came. A failure is said only where it still counts. */
  async function hochladen(datei, gilt = () => true) {
    if (!datei) return null
    const fuer = chatanzeige.chatId
    const zaehlt = () => fuer === chatanzeige.chatId && gilt()
    try {
      const ergebnis = await api.bildHochladen(datei)
      return zaehlt() ? ergebnis.bild : null
    } catch (fehler) {
      if (zaehlt()) melde(String(fehler.message || fehler), 'fehler')
      return null
    }
  }
  const adresse = (name) => (name ? api.bildAdresse(name) : '')

  /* The further references of an edit, for a family that takes several:
     the first one is the picture in the generation area, these go after it
     (lib/studiozeichnen.svelte.js). Pictures picked together go up
     together and keep the order they were picked in — the reference index
     counts in that order. */
  async function refsSetzen(dateien) {
    const namen = await Promise.all(dateien.map((d) => hochladen(d)))
    const neu = namen.filter(Boolean)
    if (!neu.length) return
    werte.ref_bilder = [...werte.ref_bilder, ...neu]
  }
  function refEntfernen(index) {
    werte.ref_bilder = werte.ref_bilder.filter((_, i) => i !== index)
  }
  function refGewaehlt(ereignis) {
    const dateien = [...(ereignis.currentTarget.files ?? [])]
    ereignis.currentTarget.value = ''
    refsSetzen(dateien)
  }
  let refZiel = $state(false)
  function refAbgelegt(ereignis) {
    ereignis.preventDefault()
    refZiel = false
    const dateien = [...(ereignis.dataTransfer?.files ?? [])].filter((d) => d.type.startsWith('image/'))
    refsSetzen(dateien)
  }

  // The first and the last frame of a video drawn between two pictures.
  let startWahl = 0
  async function startbildSetzen(datei) {
    const wahl = ++startWahl
    const name = await hochladen(datei, () => wahl === startWahl)
    if (!name) return false
    startbildWaehlen(name)
    return true
  }
  function startbildLoesen() {
    startWahl += 1
    emptyArea()
  }
  let endWahl = 0
  async function endBildSetzen(datei) {
    const wahl = ++endWahl
    const name = await hochladen(datei, () => wahl === endWahl)
    if (!name) return false
    werte.end_bild = name
    return true
  }
  function endBildLoesen() {
    endWahl += 1
    werte.end_bild = ''
  }

  // ControlNet's guide picture.
  let vorlageWahl = 0
  async function vorlageSetzen(datei) {
    const wahl = ++vorlageWahl
    const name = await hochladen(datei, () => wahl === vorlageWahl)
    if (!name) return false
    werte.control_image = name
    return true
  }
  function vorlageLoesen() {
    vorlageWahl += 1
    werte.control_image = ''
  }

  // A picture for one of sd.cpp's switches.
  const schalterBild = (datei) => hochladen(datei)

  /* A control video is not kept with a chat: another chat lets it go —
     also one opened while this column was hidden behind a tool. The same
     for a reference video. */
  $effect(() => {
    const chat = chatanzeige.chatId
    untrack(() => {
      if (steuervideo.datei && steuervideo.chat !== chat) steuervideoLoesen()
      if (refVideo.datei && refVideo.chat !== chat) refVideoRelease()
    })
  })

  /* The highres pass: the picker switches it, the scale row sets how much.
     The chat keeps the scale as the one value `hires_wahl`, empty while the
     pass is off. */
  function hiresSchalten(wert) {
    werte.hires_wahl = wert ? String(werte.hires_wahl || HIRES_START) : ''
  }
  const faktor = () => Number(werte.hires_wahl)
  const faktorSetzen = (wert) => {
    if (hires && Number.isFinite(Number(wert))) werte.hires_wahl = String(wert)
  }

  /* The model "Upscale" enlarges a finished picture with — apart from the
     highres pass, and always a file of the folder: the row shows the one
     chosen, otherwise the first, which is the one that is used. What the
     chat keeps is only what was chosen. */
  const upscaleAnzeige = () => (
    listen.upscalers.includes(werte.upscale_model) ? werte.upscale_model : (listen.upscalers[0] ?? '')
  )
  const upscaleSetzen = (wert) => {
    werte.upscale_model = wert
  }

  /* The face pass: the switch turns it on with the detector chosen last, or
     the folder's first; the chat keeps the detector's file, empty while the
     pass is off. */
  let lastDetector = ''
  function detectorSwitch(on) {
    if (!on) {
      lastDetector = werte.ad_modell
      werte.ad_modell = ''
      return
    }
    werte.ad_modell = listen.yolos.includes(lastDetector) ? lastDetector : (listen.yolos[0] ?? '')
  }

  let tuningOpen = $state(false)
  let erweitertOffen = $state(false)
  /* The search of the left column goes over these rows too
     (lib/studio.svelte.js). While it stands, the two folded sections and
     every fold of switches show their rows, so they are found like any
     other; a click on a head changes nothing then, and afterwards each
     stands as it stood before. */
</script>

<section class="feinheiten" use:rollfade={40} use:searchRows aria-label={t('studio.feinheiten')}>
  {#if kind.input || strengthShown || soundShown || refVideoShown}
    <StudioSection titel={t('studio.eingaben')}>
      {#if kind.value === 'edit'}
        <!-- The picture in the generation area is the first reference; a
             family that takes several has room for more here. -->
        {#if viele}
          <div class="zeile stapel" data-suche={t('studio.referenzbilder')}>
            <div class="kopfzeile">
              <span class="name">{t('studio.referenzbilder')}</span>
              <InfoMark text={t('studio.info_referenzbilder')} />
            </div>
            <div class="refs">
              {#each werte.ref_bilder as name, i (name + i)}
                <div class="ref">
                  <img src={adresse(name)} alt="" />
                  <button class="weg" aria-label={t('bild.entfernen')} title={t('bild.entfernen')}
                          onclick={() => refEntfernen(i)}>
                    <Hauszeichen zeichen="kreuz" groesse={10} />
                  </button>
                </div>
              {/each}
              <label class="dazu" class:ziel={refZiel} title={t('studio.referenz_dazu')}
                     ondragover={(e) => { e.preventDefault(); refZiel = true }}
                     ondragleave={() => (refZiel = false)} ondrop={refAbgelegt}>
                <Hauszeichen zeichen="plus" groesse={12} />
                <input type="file" accept="image/png,image/jpeg,image/webp" multiple
                       aria-label={t('studio.referenz_dazu')} onchange={refGewaehlt} />
              </label>
            </div>
          </div>
        {/if}
        <div class="zeile regel" data-suche={t('bild.img_cfg')}>
          <div class="kopfzeile">
            <label class="name" for={feld('img_cfg')}>{t('bild.img_cfg')}</label>
            <InfoMark text={t('bild.info_img_cfg')} />
            <div class="rechts">
              <Zahlenfeld id={feld('img_cfg')} bind:wert={werte.img_cfg} min={0} schritt={0.5}
                          nullwort={t('parameter.auto')} />
            </div>
          </div>
          <Schieberegler bind:wert={werte.img_cfg} stufen={IMG_CFG_STUFEN} mit_zahl={false} fuellung
                         beschriftung={t('bild.img_cfg')} />
        </div>
        <div class="zeile" data-suche={t('bild.ref_image_args')}>
          <label class="name" for={feld('ref_args')}>{t('bild.ref_image_args')}</label>
          <InfoMark text={t('bild.info_ref_image_args')} />
          <input id={feld('ref_args')} class="eingabe rechts" type="text" bind:value={werte.ref_image_args} />
        </div>
        <div class="zeile" data-suche={t('bild.increase_ref_index')}>
          <label class="name" for={feld('ref_index')}>{t('bild.increase_ref_index')}</label>
          <InfoMark text={t('bild.info_increase_ref_index')} />
          <div class="rechts">
            <Schalter id={feld('ref_index')} an={Boolean(werte.increase_ref_index)}
                      beschriftung={t('bild.increase_ref_index')}
                      onschalten={(an) => (werte.increase_ref_index = an)} />
          </div>
        </div>
      {:else if kind.input || strengthShown}
        {#if kind.value === 'flf2v'}
          <div class="zeile paar">
            <div class="halb">
              <span class="name">{t('bild.erstes_bild')}</span>
              <Bildablage url={adresse(werte.startbild)} waehlen={startbildSetzen} loesen={startbildLoesen}
                          label={t('bild.erstes_bild')} fill />
            </div>
            <div class="halb">
              <span class="name">{t('bild.letztes_bild')}</span>
              <Bildablage url={adresse(werte.end_bild)} waehlen={endBildSetzen} loesen={endBildLoesen}
                          label={t('bild.letztes_bild')} fill />
            </div>
          </div>
        {:else if kind.value === 'v2v'}
          <div class="zeile stapel" data-suche={t('bild.steuervideo')}>
            <span class="name">{t('bild.steuervideo')}</span>
            <div class="video">
              <Bildablage url={steuervideo.url} waehlen={steuervideoSetzen} loesen={steuervideoLoesen}
                          label={t('bild.steuervideo')} video fill />
            </div>
          </div>
        {/if}
        <div class="zeile regel" data-suche={t('bild.staerke')}>
          <div class="kopfzeile">
            <label class="name" for={feld('staerke')}>{t('bild.staerke')}</label>
            <InfoMark text={t('bild.info_staerke')} />
            <div class="rechts">
              <Zahlenfeld id={feld('staerke')} bind:wert={werte.staerke} min={0} max={1} schritt={0.05} />
            </div>
          </div>
          <Schieberegler bind:wert={werte.staerke} stufen={STAERKE_STUFEN} mit_zahl={false} fuellung
                         beschriftung={t('bild.staerke')} />
        </div>
      {/if}
      {#if refVideoShown}
        <!-- Its frames are taken when a video is drawn, like the control
             video's; its sound acts only beside it. -->
        <div class="zeile stapel" data-suche={t('bild.referenzvideo')}>
          <span class="name">{t('bild.referenzvideo')}</span>
          <div class="video">
            <Bildablage url={refVideo.url} waehlen={refVideoSet} loesen={refVideoRelease}
                        label={t('bild.referenzvideo')} video fill />
          </div>
        </div>
        <div class="zeile schalterflaeche">
          <ImageSwitchRows group="model" keys={REF_VIDEO_KEYS} bind:values={werte.switches}
                           conditions={bedingungen} upload={schalterBild} />
        </div>
      {/if}
      {#if soundShown}
        <div class="zeile schalterflaeche">
          <ImageSwitchRows group="model" keys={SOUND_KEYS} bind:values={werte.switches}
                           conditions={bedingungen} upload={schalterBild} />
        </div>
      {/if}
    </StudioSection>
  {/if}

  <StudioSection titel={t('studio.gesicht')}>
    {#snippet rechts()}
      <button class="ordnerzeichen" onclick={() => api.bildBegleiterOrdner('faces').catch(() => {})}
              title={t('bild.photomaker_ordner')} aria-label={t('bild.photomaker_ordner')}>
        <Hauszeichen zeichen="ordner" groesse="klein" />
      </button>
    {/snippet}
    <div class="zeile" data-suche={t('bild.photomaker')}>
      <label class="name" for={feld('pm')}>{t('bild.photomaker')}</label>
      <InfoMark text={t('bild.info_photomaker')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('pm')} bind:wert={werte.pm_klasse} beschriftung={t('bild.photomaker')}
                     eintraege={[{ wert: '', text: t('bild.adetailer_keins') },
                                 { wert: 'man', text: t('bild.pm_man') },
                                 { wert: 'woman', text: t('bild.pm_woman') },
                                 { wert: 'boy', text: t('bild.pm_boy') },
                                 { wert: 'girl', text: t('bild.pm_girl') }]} />
      </div>
    </div>
    <!-- Without a detector in the folder there is nothing to turn on. -->
    <div class="zeile" data-suche={t('bild.adetailer')}>
      <label class="name" for={feld('ad')}>{t('bild.adetailer')}</label>
      <InfoMark text={t('bild.info_adetailer')} />
      <div class="rechts">
        <Schalter id={feld('ad')} an={Boolean(werte.ad_modell)} beschriftung={t('bild.adetailer')}
                  gesperrt={!werte.ad_modell && !listen.yolos.length} onschalten={detectorSwitch} />
      </div>
    </div>
    {#if werte.ad_modell}
      <div class="zeile" data-suche={t('studio.modell')}>
        <label class="name" for={feld('ad_m')}>{t('studio.modell')}</label>
        <div class="rechts wahl">
          <Auswahlfeld id={feld('ad_m')} bind:wert={werte.ad_modell} eintraege={alsAuswahl(listen.yolos)}
                       beschriftung={t('studio.modell')} />
        </div>
      </div>
      <StudioLoraStack bind:stapel={werte.ad_stapel} dateien={listen.loras} name={t('bild.ad_lora')} />
      <div class="zeile" data-suche={t('bild.ad_prompt')}>
        <label class="name" for={feld('ad_prompt')}>{t('bild.ad_prompt')}</label>
        <InfoMark text={t('bild.info_ad_prompt')} />
        <input id={feld('ad_prompt')} class="eingabe rechts" type="text" bind:value={werte.ad_prompt} />
      </div>
      <div class="zeile" data-suche={t('bild.ad_negativ')}>
        <label class="name" for={feld('ad_negativ')}>{t('bild.ad_negativ')}</label>
        <InfoMark text={t('bild.info_ad_negativ')} />
        <input id={feld('ad_negativ')} class="eingabe rechts" type="text" bind:value={werte.ad_negativ} />
      </div>
      <div class="zeile" data-suche={t('bild.ad_confidence')}>
        <label class="name" for={feld('ad_conf')}>{t('bild.ad_confidence')}</label>
        <InfoMark text={t('bild.info_ad_confidence')} />
        <div class="rechts">
          <Zahlenfeld id={feld('ad_conf')} bind:wert={werte.ad_confidence} min={0} max={1} schritt={0.05}
                      nullwort={t('parameter.auto')} />
        </div>
      </div>
    {/if}
    <StudioSwitches group="face" bind:values={werte.switches} conditions={bedingungen} upload={schalterBild}
                    sucht={searching()} />
  </StudioSection>

  <StudioSection titel={t('bild.gruppe_gesichtstransfer')}>
    {#snippet rechts()}
      <button class="ordnerzeichen" onclick={() => api.bildBegleiterOrdner('pulid').catch(() => {})}
              title={t('bild.pulid_ordner')} aria-label={t('bild.pulid_ordner')}>
        <Hauszeichen zeichen="ordner" groesse="klein" />
      </button>
    {/snippet}
    <div class="zeile" data-suche={t('bild.pulid')}>
      <label class="name" for={feld('pulid')}>{t('bild.pulid')}</label>
      <InfoMark text={t('bild.info_pulid')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('pulid')} bind:wert={werte.pulid_weights} eintraege={keins(listen.pulids)}
                     beschriftung={t('bild.pulid')} />
      </div>
    </div>
    {#if werte.pulid_weights}
      <!-- A finished face embedding from the PuLID folder, never a photo:
           sd.cpp takes a photo without a word and draws as if PuLID were
           off. -->
      <div class="zeile" data-suche={t('bild.pulid_embedding')}>
        <label class="name" for={feld('pulid_emb')}>{t('bild.pulid_embedding')}</label>
        <InfoMark text={t('bild.info_pulid_embedding')} />
        <div class="rechts wahl">
          <Auswahlfeld id={feld('pulid_emb')} bind:wert={werte.pulid_id_embedding}
                       eintraege={keins(listen.pulidEmbeddings)} beschriftung={t('bild.pulid_embedding')} />
        </div>
      </div>
      {#if werte.pulid_id_embedding}
        <div class="zeile regel" data-suche={t('bild.pulid_id_weight')}>
          <div class="kopfzeile">
            <label class="name" for={feld('pulid_w')}>{t('bild.pulid_id_weight')}</label>
            <InfoMark text={t('bild.info_pulid_id_weight')} />
            <div class="rechts">
              <Zahlenfeld id={feld('pulid_w')} bind:wert={werte.pulid_id_weight} min={0} schritt={0.05} />
            </div>
          </div>
          <Schieberegler bind:wert={werte.pulid_id_weight} stufen={ID_STUFEN} mit_zahl={false} fuellung
                         beschriftung={t('bild.pulid_id_weight')} />
        </div>
      {/if}
    {/if}
  </StudioSection>

  {#if controlNetOffered}
  <StudioSection titel={t('bild.gruppe_pose')}>
    {#snippet rechts()}
      <button class="ordnerzeichen" onclick={() => api.bildBegleiterOrdner('controlnet').catch(() => {})}
              title={t('bild.control_net_ordner')} aria-label={t('bild.control_net_ordner')}>
        <Hauszeichen zeichen="ordner" groesse="klein" />
      </button>
    {/snippet}
    <div class="zeile" data-suche={t('bild.control_net')}>
      <label class="name" for={feld('cn')}>{t('bild.control_net')}</label>
      <InfoMark text={t('bild.info_control_net')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('cn')} bind:wert={werte.control_net} eintraege={keins(listen.controlnets)}
                     beschriftung={t('bild.control_net')} />
      </div>
    </div>
    {#if werte.control_net}
      <div class="zeile stapel" data-suche={t('bild.gruppe_startbild')}>
        <span class="name">{t('bild.gruppe_startbild')}</span>
        <Bildablage url={adresse(werte.control_image)} waehlen={vorlageSetzen} loesen={vorlageLoesen} />
      </div>
      {#if werte.control_image}
        <div class="zeile regel" data-suche={t('bild.control_strength')}>
          <div class="kopfzeile">
            <label class="name" for={feld('cn_s')}>{t('bild.control_strength')}</label>
            <InfoMark text={t('bild.info_control_strength')} />
            <div class="rechts">
              <Zahlenfeld id={feld('cn_s')} bind:wert={werte.control_strength} min={CONTROL_STUFEN[0]} schritt={0.05} />
            </div>
          </div>
          <Schieberegler bind:wert={werte.control_strength} stufen={CONTROL_STUFEN} mit_zahl={false} fuellung
                         beschriftung={t('bild.control_strength')} />
        </div>
        <div class="zeile" data-suche={t('bild.canny')}>
          <label class="name" for={feld('canny')}>{t('bild.canny')}</label>
          <InfoMark text={t('bild.info_canny')} />
          <div class="rechts">
            <Schalter id={feld('canny')} an={Boolean(werte.canny)} beschriftung={t('bild.canny')}
                      onschalten={(an) => (werte.canny = an)} />
          </div>
        </div>
      {/if}
    {/if}
    <StudioSwitches group="guide" bind:values={werte.switches} conditions={bedingungen} upload={schalterBild}
                    sucht={searching()} />
  </StudioSection>
  {/if}

  <StudioSection titel={t('bild.gruppe_upscaling')}>
    {#snippet rechts()}
      <button class="ordnerzeichen" onclick={() => api.bildBegleiterOrdner('upscaler').catch(() => {})}
              title={t('bild.hires_upscaler_ordner')} aria-label={t('bild.hires_upscaler_ordner')}>
        <Hauszeichen zeichen="ordner" groesse="klein" />
      </button>
    {/snippet}
    <!-- Always there, whatever the highres switch says: an enlarging reads a
         file of the folder and no built-in name. -->
    <div class="zeile" data-suche={t('bild.upscaler')}>
      <label class="name" for={feld('upscale_m')}>{t('bild.upscaler')}</label>
      <div class="rechts wahl">
        <Auswahlfeld id={feld('upscale_m')} bind:wert={upscaleAnzeige, upscaleSetzen}
                     beschriftung={t('bild.upscaler')}
                     eintraege={listen.upscalers.length ? alsAuswahl(listen.upscalers) : keins([])} />
      </div>
    </div>
    <div class="zeile" data-suche={t('bild.hires')}>
      <label class="name" for={feld('hires')}>{t('bild.hires')}</label>
      <InfoMark text={t('bild.info_hires')} />
      <div class="rechts">
        <Schalter id={feld('hires')} an={hires} beschriftung={t('bild.hires')} onschalten={hiresSchalten} />
      </div>
    </div>
    {#if hires}
      <div class="zeile regel" data-suche={t('studio.hires_faktor')}>
        <div class="kopfzeile">
          <label class="name" for={feld('hires_f')}>{t('studio.hires_faktor')}</label>
          <InfoMark text={t('studio.info_hires_faktor')} />
          <div class="rechts">
            <Zahlenfeld id={feld('hires_f')} bind:wert={faktor, faktorSetzen} min={1} schritt={0.05} />
          </div>
        </div>
        <Schieberegler bind:wert={faktor, faktorSetzen} stufen={HIRES_STUFEN} mit_zahl={false} fuellung
                       beschriftung={t('studio.hires_faktor')} />
      </div>
      <div class="zeile regel" data-suche={t('bild.hires_steps')}>
        <div class="kopfzeile">
          <label class="name" for={feld('hires_s')}>{t('bild.hires_steps')}</label>
          <InfoMark text={t('bild.info_hires_steps')} />
          <div class="rechts">
            <Zahlenfeld id={feld('hires_s')} bind:wert={werte.hires_steps} min={0} schritt={1} ganzzahlig
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
        <Schieberegler bind:wert={werte.hires_steps} min={0} max={150} mit_zahl={false} fuellung
                       beschriftung={t('bild.hires_steps')} />
      </div>
      <div class="zeile" data-suche={t('bild.hires_denoise')}>
        <label class="name" for={feld('hires_d')}>{t('bild.hires_denoise')}</label>
        <InfoMark text={t('bild.info_hires_denoise')} />
        <div class="rechts">
          <Zahlenfeld id={feld('hires_d')} bind:wert={werte.hires_denoise} min={0} max={1} schritt={0.05}
                      nullwort={t('parameter.auto')} />
        </div>
      </div>
      <div class="zeile" data-suche={t('bild.hires_upscaler')}>
        <label class="name" for={feld('hires_u')}>{t('bild.hires_upscaler')}</label>
        <InfoMark text={t('bild.info_hires_upscaler')} />
        <div class="rechts wahl">
          <Auswahlfeld id={feld('hires_u')} bind:wert={werte.hires_upscaler}
                       beschriftung={t('bild.hires_upscaler')}
                       eintraege={[{ wert: '', text: t('bild.hires_upscaler_vorgabe') },
                                   ...alsAuswahl(listen.upscalerFeste), ...alsAuswahl(listen.upscalers)]} />
        </div>
      </div>
      {#each [['hires_breite', 'bild.hires_breite', 'bild.info_hires_breite'],
              ['hires_hoehe', 'bild.hires_hoehe', 'bild.info_hires_hoehe']] as [name, text, info] (name)}
        <div class="zeile regel" data-suche={t(text)}>
          <div class="kopfzeile">
            <label class="name" for={feld(name)}>{t(text)}</label>
            <InfoMark text={t(info)} />
            <div class="rechts">
              <Zahlenfeld id={feld(name)} bind:wert={werte[name]} min={0} max={KANTE_MAX} schritt={8} ganzzahlig
                          nullwort={t('parameter.auto')} />
            </div>
          </div>
          <Schieberegler bind:wert={werte[name]} stufen={ZIEL_STUFEN} mit_zahl={false} fuellung
                         beschriftung={t(text)} />
        </div>
      {/each}
    {/if}
    {#if zielGesetzt}
      <p class="zeile hinweiszeile">{t('bild.hires_ziel_hinweis')}</p>
    {/if}
    <StudioSwitches group="upscale" bind:values={werte.switches} conditions={bedingungen} upload={schalterBild}
                    sucht={searching()} />
  </StudioSection>

  <StudioSection titel={t('bild.gruppe_feintuning')} klappbar
                 bind:offen={() => tuningOpen || searching(), (open) => (tuningOpen = searching() ? tuningOpen : open)}>
    <div class="zeile regel" data-suche={t('bild.slg_scale')}>
      <div class="kopfzeile">
        <label class="name" for={feld('slg')}>{t('bild.slg_scale')}</label>
        <InfoMark text={t('bild.info_slg_scale')} />
        <div class="rechts">
          <Zahlenfeld id={feld('slg')} bind:wert={werte.slg_scale} min={0} schritt={0.1}
                      nullwort={t('parameter.auto')} />
        </div>
      </div>
      <Schieberegler bind:wert={werte.slg_scale} stufen={SLG_STUFEN} mit_zahl={false} fuellung
                     beschriftung={t('bild.slg_scale')} />
    </div>
    {#if werte.slg_scale}
      <div class="zeile" data-suche={t('bild.skip_layers')}>
        <label class="name" for={feld('skip')}>{t('bild.skip_layers')}</label>
        <InfoMark text={t('bild.info_skip_layers')} />
        <input id={feld('skip')} class="eingabe rechts" type="text" bind:value={werte.skip_layers} />
      </div>
      {#each [['skip_layer_start', 'bild.skip_layer_start', 'bild.info_skip_layer_start'],
              ['skip_layer_end', 'bild.skip_layer_end', 'bild.info_skip_layer_end']] as [name, text, info] (name)}
        <div class="zeile" data-suche={t(text)}>
          <label class="name" for={feld(name)}>{t(text)}</label>
          <InfoMark text={t(info)} />
          <div class="rechts">
            <Zahlenfeld id={feld(name)} bind:wert={werte[name]} min={0} max={1} schritt={0.01} />
          </div>
        </div>
      {/each}
    {/if}
    <div class="zeile" data-suche={t('bild.live_preview')}>
      <label class="name" for={feld('live')}>{t('bild.live_preview')}</label>
      <InfoMark text={t('bild.info_live_preview')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('live')} bind:wert={werte.live_preview} beschriftung={t('bild.live_preview')}
                     eintraege={[{ wert: '', text: t('bild.adetailer_keins') }, { wert: 'proj', text: 'Proj' },
                                 { wert: 'tae', text: 'TAE' }, { wert: 'vae', text: 'VAE' }]} />
      </div>
    </div>
    {#if werte.live_preview}
      <div class="zeile" data-suche={t('bild.preview_interval')}>
        <label class="name" for={feld('takt')}>{t('bild.preview_interval')}</label>
        <InfoMark text={t('bild.info_preview_interval')} />
        <div class="rechts">
          <Zahlenfeld id={feld('takt')} bind:wert={werte.preview_interval} min={1} schritt={1} ganzzahlig
                      nullwort={t('parameter.auto')} />
        </div>
      </div>
      <div class="zeile" data-suche={t('bild.preview_noisy')}>
        <label class="name" for={feld('noisy')}>{t('bild.preview_noisy')}</label>
        <InfoMark text={t('bild.info_preview_noisy')} />
        <div class="rechts">
          <Schalter id={feld('noisy')} an={Boolean(werte.preview_noisy)} beschriftung={t('bild.preview_noisy')}
                    onschalten={(an) => (werte.preview_noisy = an)} />
        </div>
      </div>
    {/if}
    {#if werte.live_preview === 'tae'}
      <div class="zeile" data-suche={t('bild.taesd')}>
        <label class="name" for={feld('taesd')}>{t('bild.taesd')}</label>
        <InfoMark text={t('bild.info_taesd')} />
        <div class="rechts wahl">
          <Auswahlfeld id={feld('taesd')} bind:wert={werte.taesd}
                       beschriftung={t('bild.taesd')} eintraege={keins(listen.taesd)} />
        </div>
      </div>
    {/if}
    <!-- Empty leaves sd-cli's own per-sampler values alone: there is no
         number to repeat them with. The sliders cover the usual range; the
         numbers take what sd.cpp takes. -->
    <div class="zeile regel" data-suche={t('bild.eta')}>
      <div class="kopfzeile">
        <label class="name" for={feld('eta')}>{t('bild.eta')}</label>
        <InfoMark text={t('bild.info_eta')} />
        <div class="rechts">
          <Zahlenfeld id={feld('eta')} bind:wert={werte.eta} min={0} schritt={0.01} nullwort={t('parameter.auto')} />
        </div>
      </div>
      <Schieberegler bind:wert={werte.eta} stufen={ETA_STUFEN} mit_zahl={false} fuellung
                     beschriftung={t('bild.eta')} />
    </div>
    <!-- The number's range is the one the picture server's per-model value
         takes (Bildmodellwerte.svelte). -->
    <div class="zeile regel" data-suche={t('bild.flow_shift')}>
      <div class="kopfzeile">
        <label class="name" for={feld('flow')}>{t('bild.flow_shift')}</label>
        <InfoMark text={t('bild.info_flow_shift')} />
        <div class="rechts">
          <Zahlenfeld id={feld('flow')} bind:wert={werte.flow_shift} min={-100} max={100} schritt={0.1}
                      nullwort={t('parameter.auto')} />
        </div>
      </div>
      <Schieberegler bind:wert={werte.flow_shift} stufen={FLOW_STUFEN} mit_zahl={false} fuellung
                     beschriftung={t('bild.flow_shift')} />
    </div>
    <div class="zeile" data-suche={t('bild.sigmas')}>
      <label class="name" for={feld('sigmas')}>{t('bild.sigmas')}</label>
      <InfoMark text={t('bild.info_sigmas')} />
      <input id={feld('sigmas')} class="eingabe rechts" type="text" bind:value={werte.sigmas} />
    </div>
    <div class="zeile" data-suche={t('bild.extra_sample_args')}>
      <label class="name" for={feld('extra')}>{t('bild.extra_sample_args')}</label>
      <InfoMark text={t('bild.info_extra_sample_args')} />
      <input id={feld('extra')} class="eingabe rechts" type="text" bind:value={werte.extra_sample_args} />
    </div>
    <StudioSwitches group="tuning" bind:values={werte.switches} conditions={bedingungen} upload={schalterBild}
                    sucht={searching()} />
  </StudioSection>

  <!-- The technical dials that may stay on Auto, shut to begin with. -->
  <StudioSection titel={t('modell.gruppe_erweitert')} klappbar
                 bind:offen={() => erweitertOffen || searching(),
                             (open) => (erweitertOffen = searching() ? erweitertOffen : open)}>
    <div class="zeile" data-suche={t('bild.vae_format')}>
      <label class="name" for={feld('vae_f')}>{t('bild.vae_format')}</label>
      <InfoMark text={t('bild.info_vae_format')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('vae_f')} bind:wert={werte.vae_format} beschriftung={t('bild.vae_format')}
                     eintraege={[{ wert: 'auto', text: t('bild.vae_format_auto') },
                                 { wert: 'flux', text: t('bild.vae_format_flux') },
                                 { wert: 'sd3', text: t('bild.vae_format_sd3') },
                                 { wert: 'flux2', text: t('bild.vae_format_flux2') }]} />
      </div>
    </div>
    {#if clipSchichten}
      <div class="zeile regel" data-suche={t('bild.clip_skip')}>
        <div class="kopfzeile">
          <label class="name" for={feld('clip')}>{t('bild.clip_skip')}</label>
          <InfoMark text={t('bild.info_clip_skip')} />
          <div class="rechts">
            <Zahlenfeld id={feld('clip')} bind:wert={werte.clip_skip} min={1} max={clipSchichten} schritt={1}
                        ganzzahlig nullwort={t('parameter.auto')} />
          </div>
        </div>
        <Schieberegler bind:wert={werte.clip_skip} min={1} max={clipSchichten} mit_zahl={false} fuellung
                       beschriftung={t('bild.clip_skip')} />
      </div>
    {/if}
    <div class="zeile" data-suche={t('bild.rng')}>
      <label class="name" for={feld('rng')}>{t('bild.rng')}</label>
      <InfoMark text={t('bild.info_rng')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('rng')} bind:wert={werte.rng} beschriftung={t('bild.rng')}
                     eintraege={[{ wert: 'cuda', text: t('bild.rng_cuda') }, { wert: 'cpu', text: t('bild.rng_cpu') },
                                 { wert: 'std_default', text: 'std_default' }]} />
      </div>
    </div>
    <div class="zeile" data-suche={t('bild.weight_type')}>
      <label class="name" for={feld('wt')}>{t('bild.weight_type')}</label>
      <InfoMark text={t('bild.info_weight_type')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('wt')} bind:wert={werte.weight_type} beschriftung={t('bild.weight_type')}
                     eintraege={[{ wert: 'auto', text: t('bild.weight_type_auto') },
                                 ...alsAuswahl(imageSwitches.weightTypes)]} />
      </div>
    </div>
    <div class="zeile" data-suche={t('bild.prediction')}>
      <label class="name" for={feld('pred')}>{t('bild.prediction')}</label>
      <InfoMark text={t('bild.info_prediction')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('pred')} bind:wert={werte.prediction} beschriftung={t('bild.prediction')}
                     eintraege={[{ wert: 'auto', text: t('bild.prediction_auto') }, ...alsAuswahl(PREDICTIONEN)]} />
      </div>
    </div>
    <!-- What the model IS: a family said by hand is for a model whose header
         names none, and the chat starts at its values. -->
    <div class="zeile" data-suche={t('bild.familie')}>
      <label class="name" for={feld('fam')}>{t('bild.familie')}</label>
      <InfoMark text={t('bild.info_familie')} />
      <div class="rechts wahl">
        <Auswahlfeld id={feld('fam')} wert={werte.familie} gewaehlt={familieWaehlen}
                     beschriftung={t('bild.familie')}
                     eintraege={[{ wert: '', text: auswahl.klasse
                                     ? t('bild.familie_auto_erkannt', { klasse: familyOf(auswahl.klasse)?.label ?? auswahl.klasse })
                                     : t('bild.familie_auto') },
                                 ...imageFamilies.list.map((f) => ({ wert: f.name, text: f.label }))]} />
      </div>
    </div>
    <div class="zeile" data-suche={t('bild.model_args')}>
      <label class="name" for={feld('margs')}>{t('bild.model_args')}</label>
      <InfoMark text={t('bild.info_model_args')} />
      <input id={feld('margs')} class="eingabe rechts" type="text" bind:value={werte.model_args} />
    </div>
    {#if modelRows.length}
      <div class="zeile schalterflaeche">
        <ImageSwitchRows group="model" keys={modelKeys} bind:values={werte.switches}
                         conditions={bedingungen} upload={schalterBild} />
      </div>
    {/if}
  </StudioSection>
</section>

<style>
  .feinheiten {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 0 var(--rand, 16px) 12px;
  }

  /* The references of an edit: small squares in a row, and a dashed one
     that adds another. */
  .refs {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .ref,
  .dazu {
    position: relative;
    width: 56px;
    height: 56px;
    box-sizing: border-box;
    border-radius: 9px;
  }
  .ref img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 9px;
    display: block;
  }
  .ref .weg {
    position: absolute;
    top: 3px;
    right: 3px;
    width: 18px;
    height: 18px;
    padding: 0;
    display: none;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 99px;
    background: var(--glass-dropdown);
    color: var(--text);
    cursor: pointer;
  }
  .ref:hover .weg,
  .ref .weg:focus-visible {
    display: inline-flex;
  }
  .dazu {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px dashed var(--feldstrich, var(--linie-stark));
    color: var(--text-leise);
    cursor: pointer;
  }
  .dazu:hover,
  .dazu.ziel {
    background: var(--glass-hover);
    color: var(--text);
  }
  .dazu input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }

  /* The first and the last frame side by side, one size. */
  .zeile.paar {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    align-items: stretch;
  }
  .halb {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .halb :global(.ablage) {
    aspect-ratio: 1;
  }
  .video :global(.ablage) {
    aspect-ratio: 16 / 9;
  }
  .hinweiszeile {
    margin: 0;
    font-size: 11.5px;
    line-height: 1.45;
    color: var(--text-still);
  }
</style>
