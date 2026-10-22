<script>
  /* The catalogue — a gallery of curated models, and the whole of Hugging
     Face one search away. A page beside the sidebar (Seitenrahmen.svelte):
     the kinds of model on the left, the downloads below them with the
     Hugging Face token over their list.

     Its own page because getting a model is its own act, apart from
     running one: the curated cards answer "which of these is for my
     machine", the search answers "I already know what I want". The card is
     a model; clicking it opens the build chooser. A finished download turns
     the card's button into Start, which brings the server up with sensible
     defaults and hands over to the local view.

     One download runs at a time. Companions (vision, speed module) follow
     the model on the same button, and each carries which model it belongs
     to and its role, so the service records the association and the runner
     attaches it later without guessing. */
  import { untrack } from 'svelte'
  import Seitenrahmen from './Seitenrahmen.svelte'
  import Menueseite from './Menueseite.svelte'
  import SettingsNav from './SettingsNav.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Menuezeile from './Menuezeile.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import OwnerMark from './OwnerMark.svelte'
  import Modellkarte from './Modellkarte.svelte'
  import Modelldetail from './Modelldetail.svelte'
  import Downloadseite from './Downloadseite.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import {
    downloads, einreihen, ausreihen, zieldatei, fertigMerken, antreiben, anzahlAktiv,
  } from '../lib/downloads.svelte.js'
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { weg, zurueckgehen } from '../lib/fensterweg.svelte.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatGb, formatNumber } from '../lib/numberDisplay.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'
  import {
    ARTEN, ZUBEHOER_ZIEL, SPALTEN_ZUBEHOER, ZUBEHOER_ORDNER, SUCHBARE_ARTEN, dienstArt,
    kartePasst, katalogFuer, passendeFassung, passt, brauchtMaschine,
    SORTE_FARBE, SORTE_LABEL,
  } from '../lib/modellempfehlungen.js'
  import { LOGOS, avatarOwnerOf } from '../lib/logos.js'
  import { familyOf, loadImageFamilies } from '../lib/imageFamilies.svelte.js'

  let { offen = $bindable(false) } = $props()

  /* Which kind is open — Chat, Embedding, Speech, Picture, Video, Accessories.
     Always one of them, always switchable back to Chat: the search below is
     scoped to this, and so is the curated gallery. */
  let art = $state('chat')
  /* Each kind's sign in the list: the speech bubble for chat models, the
     servers' own signs for embedding, speech and pictures, the puzzle piece
     for the add-ons a model reads beside it. */
  const ARTZEICHEN = {
    chat: 'sprechblase', einbettung: 'einbettung', sprache: 'sprache_welle',
    bild: 'bild', video: 'clapperboard', zubehoer: 'puzzle',
  }

  /* The heading each kind's page opens with. */
  const VORAUSWAHL = {
    chat: 'katalog.vorauswahl_chat', einbettung: 'katalog.vorauswahl_einbettung',
    sprache: 'katalog.vorauswahl_sprache', bild: 'katalog.vorauswahl_bild',
    video: 'katalog.vorauswahl_video', zubehoer: 'katalog.vorauswahl_zubehoer',
  }

  /* Whether the right side shows the downloads page. */
  let dlOffen = $state(false)

  /* The Hugging Face token: lifts rate limits, opens gated models. Set and
     taken out here; the service never hands it back, only whether one is
     there and its last four characters, shown behind masking dots. */
  let hfGesetzt = $state(false)
  let hfEnde = $state('')
  let hfEingabe = $state('')
  function hfStand(s) {
    hfGesetzt = s.gesetzt
    hfEnde = s.ende ?? ''
  }
  async function hfSetzen() {
    try {
      hfStand(await api.hfTokenSetzen(hfEingabe.trim()))
      hfEingabe = ''
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    }
  }
  async function hfEntfernen() {
    try {
      hfStand(await api.hfTokenEntfernen())
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    }
  }
  $effect(() => {
    if (!offen) return
    api.hfTokenStand().then(hfStand).catch(() => {})
  })
  /* Whether this tab searches at all, and whether it is the accessory tab
     (five columns instead of the plain grid). */
  const suchbar = $derived(SUCHBARE_ARTEN.includes(art))
  const istZubehoer = $derived(art === 'zubehoer')
  /* Picture and video models both lie in the picture folder and carry a kit,
     so the two tabs share everything that reads the picture side. */
  const bildSeite = $derived(art === 'bild' || art === 'video')
  /* The page of the downloads, in place of a kind of model. */
  function dlOeffnen() {
    dlOffen = true
    detail = null
    trefferSeite = null
  }
  function artWaehlen(neu) {
    dlOffen = false
    // Choosing the kind already shown still leaves a model's detail.
    detail = null
    trefferSeite = null
    if (neu === art) return
    art = neu
    // Leaving for a tab without a search: clear the field and its results,
    // or a stale term would keep the gallery dimmed on a tab that cannot search.
    if (!SUCHBARE_ARTEN.includes(neu)) {
      suchbegriff = ''
      treffer = null
    } else if (suchAktiv) {
      suchen()
    }
  }

  /* Open the file manager at one accessory folder — the picture side and the
     chat side each have their own whitelisted route. */
  function ordnerOeffnen(sorte) {
    const ziel = ZUBEHOER_ORDNER[sorte]
    if (!ziel) return
    const ruf = ziel.seite === 'chat'
      ? api.chatBegleiterOrdner(ziel.unter)
      : api.bildBegleiterOrdner(ziel.unter)
    ruf.catch(() => {})
  }

  /* A server panel can send the user here with its own tab already open —
     the wish is read once and cleared, so the next plain open starts on
     Chat as always. */
  $effect(() => {
    if (offen && zustand.katalogArtWunsch) {
      if (zustand.katalogArtWunsch === 'downloads') dlOeffnen()
      else artWaehlen(zustand.katalogArtWunsch)
      zustand.katalogArtWunsch = null
    }
  })

  /* What the machine holds and what already lies in the folder — the two
     facts every card reads. Polled gently while the window is open, so a
     finished download lights up the right card without a reopen. */
  let maschineGb = $state(null)
  let vorhanden = $state([])
  /* The kind of model `vorhanden` was read for. A card says "download" or
     "downloaded" only for a kind whose files were read in full: before that,
     and while the other kind's list still stands after a change of kind,
     the place stays empty. A read that fails leaves the last full one where it
     is, and says why once (`letzterFehler`). */
  let vorhandenArt = $state(null)
  const bekannt = $derived(vorhandenArt === art)
  let letzterFehler = null
  let holenLauf = 0
  let stand = $state(null)
  /* The file this window saw running last, and the failed download already
     reported on top (by file and reason): a failure is told once, and only
     for a download this window saw start — the service keeps the state of
     an old failure until the next download. */
  let watchedFile = null
  let lastFailure = null

  /* Which model the detail shows, or null for the gallery. */
  let detail = $state(null)

  const laedt = $derived(Boolean(stand) && !stand.fertig && !stand.fehler)

  /* Download speed, measured between two polls and lightly smoothed — the
     difference between "waiting" and "stuck" is this number. */
  let tempo = $state(0)
  let messung = null
  function tempoMessen(neu) {
    const jetzt = Date.now()
    if (neu && messung && messung.datei === neu.datei && jetzt > messung.zeit) {
      const frisch = ((neu.geladen - messung.geladen) / (jetzt - messung.zeit)) * 1000
      tempo = tempo ? tempo * 0.4 + frisch * 0.6 : frisch
    } else {
      tempo = 0
    }
    messung = neu ? { datei: neu.datei, geladen: neu.geladen, zeit: jetzt } : null
  }
  const mbs = $derived(tempo > 50_000 ? formatNumber(tempo / 1e6, 1, texte.sprache) + ' MB/s' : '')

  const gb = (bytes) => formatGb(bytes / 1e9, texte.sprache)
  const istDa = (datei) => Boolean(datei) && vorhanden.includes(datei)
  /* The kit parts the picture side offers, by the sub-folder they belong
     in: a part is tied to its model without a download only when it is one
     of these. Null until the lists have been read once. */
  let partLists = $state(null)
  const wirdGeholt = (datei) => laedt && stand?.datei === datei
  /* Lined up behind the running download, not started yet. */
  const isQueued = (datei) => Boolean(datei) && downloads.warteschlange.some((job) => zieldatei(job) === datei)
  /* Takes every job of these local names out of the queue — the model and
     the companions that were lined up with it. */
  function dequeueNames(names) {
    for (const job of [...downloads.warteschlange]) {
      if (names.includes(zieldatei(job))) ausreihen(job)
    }
  }

  /* The local names a build downloads: the model and its companions.
     An accessory keeps its local name in `ziel` (the remote file is named
     the same across repositories); the progress and the presence check must
     follow that name, not the remote one, or a renamed card never registers. */
  const buildNames = (f) => [f.ziel ?? f.datei, f.mmproj_ziel, f.drafter_ziel, f.partner?.ziel].filter(Boolean)
  const dran = (f) => buildNames(f).some(wirdGeholt)
  function status(f) {
    if (dran(f)) return 'laedt'
    // A pair is ready only with both of its models.
    if (bekannt && istDa(f.ziel ?? f.datei) && (!f.partner || istDa(f.partner.ziel))) return 'bereit'
    if (buildNames(f).some(isQueued)) return 'wartet'
    return bekannt ? 'neu' : 'frage'
  }
  function fortschritt(f) {
    if (!dran(f) || !stand) return null
    const teil =
      stand.datei === f.mmproj_ziel ? t('modell.augen') + ' · '
      : stand.datei === f.drafter_ziel ? t('modell.feld_drafter') + ' · '
      : ''
    const anteil = Math.round((stand.anteil ?? 0) * 100)
    const bytes = `${teil}${gb(stand.geladen)} / ${gb(stand.gesamt)} GB`
    return { anteil, bytes }
  }

  /* Fitting cards to the front — a fit is a fact worth surfacing. Ties keep
     the curated order. */
  const karten = $derived(
    [...katalogFuer(art)].sort((a, b) => Number(kartePasst(b, maschineGb)) - Number(kartePasst(a, maschineGb))),
  )

  /* Something runs or waits. A boolean on purpose: every answer of the poll
     sets a new object into `downloads.laufend`, and an effect reading that
     would start over with each answer. */
  const downloadsActive = $derived(anzahlAktiv() > 0)

  /* Asked while the page is open — and, closed, for as long as something runs
     or waits, so the sign in the chat's head goes out when it is done and the
     next download in the row starts without the page being open. */
  async function holen() {
    // The newest read wins: one that began while this one was on its way
    // (the change of kind below) hands in its answer instead of this.
    const mein = ++holenLauf
    const fuerArt = art
    try {
      stand = await api.modellHolenStand()
      tempoMessen(stand && !stand.fertig && !stand.fehler ? stand : null)
      const auskunft = await api.runnerAuskunft()
      maschineGb = auskunft.speicher_gb ?? null
      // Collected fully, assigned ONCE at the end: an intermediate
      // assignment made every card flip to "download" for a blink on
      // each 2-second poll while the picture list was still in flight.
      const liste = [
        ...auskunft.modelle.map((m) => m.name),
        ...(auskunft.mmproj ?? []),
        ...(auskunft.mtp ?? []).map((m) => m.name),
      ]
      // Picture checkpoints and accessories land in the picture side's own
      // folders, which the runner's list does not see. On those two tabs,
      // add what the picture side already has, or a downloaded model keeps
      // offering itself and a second click only earns a "already there"
      // error (found live with CyberRealistic XL on the picture tab).
      if (fuerArt === 'zubehoer' || fuerArt === 'bild' || fuerArt === 'video') {
        const bild = await api.bildmodelle()
        partLists = {
          vae: bild.vaes ?? [],
          text_encoders: [...(bild.textversteher ?? []), ...(bild.sehteile ?? [])],
        }
        liste.push(
          ...(bild.modelle ?? []),
          ...(bild.vaes ?? []), ...(bild.loras ?? []), ...(bild.yolos ?? []),
          ...(bild.textversteher ?? []), ...(bild.sehteile ?? []),
        )
      }
      // Embedding models land in the embedding server's own folder, which
      // the runner's list does not see either — same story as the picture
      // side, same fix, or a finished download keeps offering itself.
      if (fuerArt === 'einbettung') {
        const einbettung = await api.einbettungAuskunft()
        liste.push(...(einbettung.modelle ?? []).map((m) => m.name))
      }
      // And speech models land in the speech server's own folder, with
      // their projectors beside them — same story again, same fix.
      if (fuerArt === 'sprache') {
        const sprache = await api.spracheAuskunft()
        liste.push(...(sprache.modelle ?? []).map((m) => m.name), ...(sprache.mmproj ?? []))
      }
      // A newer read took over while this one waited: its answer counts.
      if (mein !== holenLauf) return
      vorhanden = liste
      vorhandenArt = fuerArt
      letzterFehler = null
      // A file that arrived stays in the panel as a receipt; a cancelled
      // or failed one does not.
      if (stand && stand.fertig && !stand.fehler) fertigMerken(stand.datei, stand.gesamt)
      // A download that broke says so, once: its row is gone from the
      // panel and nothing else would tell. Cancelling is no breaking.
      if (stand && !stand.fertig && !stand.fehler) watchedFile = stand.datei
      if (stand?.fehler && stand.fehler !== 'abgebrochen' && stand.datei === watchedFile) {
        const mark = `${stand.datei}:${stand.fehler}`
        if (mark !== lastFailure) {
          lastFailure = mark
          melde(t('bildserver.generator_fehler'), 'fehler')
        }
      } else if (!stand?.fehler) {
        lastFailure = null
      }
      // The panel's own copy, so the header count is right even while the
      // list below still shows the card that started it.
      downloads.laufend = stand && !stand.fertig && !stand.fehler ? stand : null
      // Nothing running any more: the next in the row goes. Cancelling
      // ONE download is not cancelling the others that were asked for.
      if (!downloads.laufend && downloads.warteschlange.length) {
        try {
          const naechster = await antreiben(vorhanden)
          if (naechster) {
            stand = naechster
            watchedFile = naechster.datei
            lastFailure = null
          }
        } catch (fehler) {
          melde(fehler.message, 'fehler')
        }
      }
    } catch (fehler) {
      if (fehler.message !== letzterFehler) melde(fehler.message, 'fehler')
      letzterFehler = fehler.message
    }
  }
  $effect(() => {
    // Read before the condition, not inside it: the effect has to start over
    // when this flips, whichever way the page stands.
    const active = downloadsActive
    if (!offen && !active) return
    holen()
    return pollWithoutOverlap(holen, 2000)
  })
  /* A change of kind asks at once: the next beat would leave the cards of
     the new kind on the files of the old one for up to two seconds. */
  let gesehenArt = untrack(() => art)
  $effect(() => {
    if (art === gesehenArt) return
    gesehenArt = art
    if (offen || untrack(() => downloadsActive)) untrack(() => holen())
  })

  /* The companions a build fetches after the model: its vision, then its
     speed module, each named locally so two bare files never collide and
     each tagged with the model it belongs to. Each also carries the
     sub-folder its role belongs in — the same one the accessory column
     downloads to — so a companion lands in vision/ or mtp/ right away
     instead of sitting in the root until the next service start sorts it. */
  function begleiterJobs(f) {
    const jobs = []
    if (f.mmproj) jobs.push({ repo: f.id, datei: f.mmproj, ziel: f.mmproj_ziel, gehoert_zu: f.datei, rolle: 'mmproj', unterordner: ZUBEHOER_ZIEL.mmproj.unterordner })
    if (f.drafter) jobs.push({ repo: f.drafter_repo ?? f.id, datei: f.drafter, ziel: f.drafter_ziel, gehoert_zu: f.datei, rolle: 'mtp', unterordner: ZUBEHOER_ZIEL.mtp.unterordner })
    return jobs
  }
  /* Where a card downloads to. An accessory card carries its own destination
     by its sorte (folder art + sub-folder, or a companion role in the model
     folder); everything else lands in the open tab's art. */
  function routing(karte) {
    if (karte?.zubehoer) return ZUBEHOER_ZIEL[karte.sorte] ?? { art: dienstArt(art) }
    return { art: dienstArt(art) }
  }
  /* Every wish goes into the queue; the driver decides what actually
     starts. Clicking is thus the same act whether something runs or not —
     and no click can race the poll into a "already running" error. */
  async function starteJob(job, rest, ziel) {
    const gerichtet = (j) => ({
      ...j,
      rolle: j.rolle ?? ziel.rolle ?? null,
      art: ziel.art,
      unterordner: j.unterordner ?? ziel.unterordner ?? null,
    })
    for (const j of [job, ...rest]) einreihen(gerichtet(j))
    try {
      const frisch = await antreiben(vorhanden)
      if (frisch) {
        stand = frisch
        watchedFile = frisch.datei
        lastFailure = null
      }
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    }
  }
  /* Fetch what is missing — the model, or only the companions that never
     arrived. The follow-up list lives in memory, so a reopen mid-download
     never strands a model without its projector or its draft. An accessory
     names its local file with `ziel` (two LoRA repositories share a file
     name), so the presence check follows that name, not the remote one. */
  async function fassungHolen(f, karte) {
    if (karte.bild && !karte.zubehoer) {
      await bildFassungHolen(f, karte)
      return
    }
    const ziel = routing(karte)
    const fehlend = begleiterJobs(f).filter((j) => !istDa(j.ziel))
    const lokal = f.ziel ?? f.datei
    if (!istDa(lokal)) {
      await starteJob({ repo: f.id, datei: f.datei, ziel: f.ziel ?? null, groesse: f.groesse }, fehlend, ziel)
      return
    }
    const [erst, ...rest] = fehlend
    if (erst) await starteJob(erst, rest, ziel)
  }

  async function abbrechen() {
    try {
      await api.modellHolenAbbrechen()
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    }
  }

  // ---- Free search across Hugging Face ------------------------------------
  let suchbegriff = $state('')
  let treffer = $state(null)
  let sucht = $state(false)
  /* The search hit whose page stands open, or null. */
  let trefferSeite = $state(null)
  let dateien = $state(null)
  let repoAugen = $state(null)
  let taktSuche = null

  const suchAktiv = $derived(suchbegriff.trim().length > 0)

  function tippt() {
    clearTimeout(taktSuche)
    taktSuche = setTimeout(suchen, 400)
  }
  /* Only the newest request may write the results: a slow answer for the
     PREVIOUS tab or term would otherwise land last and show its models
     under the wrong tab. */
  let suchlauf = 0
  async function suchen() {
    clearTimeout(taktSuche)
    const begriff = suchbegriff.trim()
    if (!begriff) {
      treffer = null
      return
    }
    const lauf = ++suchlauf
    sucht = true
    try {
      const antwort = await api.modellSuche(begriff, art)
      if (lauf !== suchlauf) return
      treffer = antwort
    } catch (fehler) {
      if (lauf !== suchlauf) return
      melde(fehler.message, 'fehler')
      treffer = []
    } finally {
      if (lauf === suchlauf) sucht = false
    }
  }
  /* The picture tab's rows say what they are, and bring their kit, only
     once the service has read the head of their file. The list stands first;
     each row then asks for its own answer, four at a time, and takes it in
     place — the order of the rows never changes. A newer page makes the
     older answers fall away. */
  const HEADS_AT_ONCE = 4
  let headPage = 0
  let heads = new Map()
  function headFor(repo, row) {
    const page = headPage
    let pending = heads.get(row.datei)
    if (!pending) {
      pending = api.fileHead(repo, row).then((answer) => {
        const index = page === headPage ? (dateien?.findIndex((d) => d.datei === row.datei) ?? -1) : -1
        if (index >= 0) dateien[index] = answer
        return answer
      })
      heads.set(row.datei, pending)
      // A request that failed may be asked again by the next click.
      pending.catch(() => {
        if (heads.get(row.datei) === pending) heads.delete(row.datei)
      })
    }
    return pending
  }
  function readHeads(repo, rows) {
    const page = headPage
    const queue = [...rows]
    const worker = async () => {
      while (queue.length && page === headPage) {
        try {
          await headFor(repo, queue.shift())
        } catch {
          // The row stays as the list gave it.
        }
      }
    }
    for (let n = 0; n < HEADS_AT_ONCE; n++) worker()
  }
  async function trefferOeffnen(fund) {
    trefferSeite = fund
    dateien = null
    repoAugen = null
    headPage += 1
    heads = new Map()
    try {
      const antwort = await api.modellDateien(fund.id, dienstArt(art))
      // A slow answer for a page that was left in the meantime must not
      // write the files of the page that stands now.
      if (trefferSeite?.id !== fund.id) return
      dateien = antwort.dateien
      repoAugen = antwort.mmproj
      if (bildSeite) readHeads(fund.id, antwort.dateien)
    } catch (fehler) {
      if (trefferSeite?.id !== fund.id) return
      melde(fehler.message, 'fehler')
      dateien = []
    }
  }
  /* A found file may sit in a sub-folder of its repository; in our folder it
     lies flat, under its last segment — so presence, progress and the
     projector's name all go by that. */
  const flach = (pfad) => pfad.split('/').pop()
  /* The name a file of the hub is kept under in its folder, and whether it
     is there — the service's word (`local_name`, `collision`, `app/api/v1/modelldateien.py`),
     not the window's: a file of the same name and another size is another
     file, and the new one is kept as `<repo>-<name>`. `istDa` reads the
     lists polled every two seconds, so what arrived since shows at once. */
  const localName = (e) => e.local_name || flach(e.datei ?? e.name)
  const isThere = (e) => !e.collision && istDa(localName(e))
  /* Local name for a found projector: the model's own stem plus the
     projector's tail, so the runner can tie the two together. */
  const augenZiel = (modellDatei, mmprojDatei) =>
    flach(modellDatei).replace(/\.gguf$/i, '') + '-' + mmprojDatei.slice(mmprojDatei.toLowerCase().indexOf('mmproj'))

  /* A model file with a kit comes with every part of it: the text encoders
     and the VAE, each into its own sub-folder. Every part is also tied to
     the model — fetched now or long ago, it is the model's part — so each one
     goes to the service: a part that lies there already is not fetched
     again, the service only writes the bond. */
  async function suchDateiHolen(repo, picked) {
    // A picture file brings its kit with its head: the click waits for the
    // row's answer, so a model is never fetched without its parts.
    let d = picked
    if (bildSeite) {
      try {
        d = await headFor(repo, picked)
      } catch (fehler) {
        melde(fehler.message, 'fehler')
        return
      }
    }
    const modelThere = isThere(d)
    if (modelThere && !d.bausatz) return
    const modell = localName(d)
    const jobs = []
    if (repoAugen && !modelThere) {
      const ziel = augenZiel(modell, repoAugen.datei)
      if (!istDa(ziel)) jobs.push({ repo, datei: repoAugen.datei, ziel, gehoert_zu: modell, rolle: 'mmproj', groesse: repoAugen.groesse_gb })
    }
    jobs.push(...(await kitJobs(d, modell)))
    // A search hit downloads into the open tab's art (search runs only on the
    // searchable tabs; the video tab fetches into the picture side); the
    // routing argument is what starteJob requires.
    const ziel = { art: dienstArt(art) }
    if (modelThere) {
      const [erst, ...rest] = jobs
      if (erst) await starteJob(erst, rest, ziel)
      return
    }
    await starteJob(
      { repo, datei: d.datei, ziel: modell === flach(d.datei) ? null : modell, groesse: d.groesse_gb },
      jobs, ziel,
    )
  }
  /* The jobs of the kit parts of a model whose head has been read: each part
     that is not there yet, and — for a part that lies in its folder — only
     its bond to the model. */
  async function kitJobs(d, modell) {
    const jobs = []
    for (const teil of d.bausatz?.teile ?? []) {
      if (teil.rolle === 'modell') continue
      const job = {
        repo: teil.repo, datei: teil.datei, ziel: localName(teil), unterordner: teil.ordner,
        gehoert_zu: modell, rolle: teil.feld, groesse: teil.groesse_gb,
      }
      // The lists read just now decide what is there; the file list's own
      // answer only until those lists have been read once. A part of another
      // size under the name is not it (`collision`: nothing can be stored).
      const da = teil.collision
        ? false
        : partLists ? (partLists[teil.ordner] ?? []).includes(localName(teil)) : teil.da
      if (da) await tiePart(job)
      else jobs.push(job)
    }
    return jobs
  }
  /* A curated picture or video card downloads as a search hit does: its file
     is looked up in the list of its repository, the head of that file names
     its kit (text encoders, VAE) and the parts come with it — one way for
     both. Where the hub or the head cannot be read, the file alone is fetched
     and the model's own form asks for the rest. A pair (Wan 2.2 A14B) brings
     its second model. */
  async function bildFassungHolen(f, karte) {
    const ziel = routing(karte)
    let d = null
    try {
      const liste = await api.modellDateien(f.id, 'bild')
      const zeile = liste.dateien.find((e) => e.datei === f.datei)
      if (zeile) d = await api.fileHead(f.id, zeile)
    } catch {
      d = null
    }
    const modell = d ? localName(d) : (f.ziel ?? flach(f.datei))
    const modelThere = d ? isThere(d) : istDa(modell)
    const jobs = []
    if (f.partner && !istDa(f.partner.ziel)) {
      jobs.push({ repo: f.id, datei: f.partner.datei, ziel: f.partner.ziel })
    }
    if (d) jobs.push(...(await kitJobs(d, modell)))
    if (modelThere) {
      const [erst, ...rest] = jobs
      if (erst) await starteJob(erst, rest, ziel)
      return
    }
    await starteJob(
      { repo: f.id, datei: f.datei, ziel: modell === flach(f.datei) ? null : modell, groesse: d?.groesse_gb ?? f.groesse },
      jobs, ziel,
    )
  }
  /* A part that lies in its folder already needs no download, only its bond
     to the model; the service writes it and answers at once. */
  async function tiePart(job) {
    try {
      await api.modellHolen(job.repo, job.datei, job.ziel, job.gehoert_zu, job.rolle, 'bild', job.unterordner)
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    }
  }
  /* The local names a found file downloads: itself, its projector and — a
     kit's parts are shared by every file of its family — the parts of the
     kit of a model that is here already, and of no other. */
  function foundNames(d) {
    const ziel = repoAugen ? augenZiel(localName(d), repoAugen.datei) : null
    return [
      localName(d),
      ...(ziel ? [ziel] : []),
      ...(isThere(d) ? (d.bausatz?.teile ?? []).map(localName) : []),
    ]
  }
  /* An accessory's kind and, where it is bound to a family, that family. */
  loadImageFamilies()
  const detailPlaketten = $derived(
    detail?.zubehoer
      ? [
          { text: t(SORTE_LABEL[detail.sorte] ?? 'katalog.sorte_vae'), farbe: SORTE_FARBE[detail.sorte] ?? 'var(--text-leise)' },
          ...(detail.klasse ? [{ text: familyOf(detail.klasse)?.label ?? detail.klasse, farbe: 'var(--text)' }] : []),
        ]
      : [],
  )
  /* What a file row says it is, from the head of the file the service read:
     "Image model · <family>" in the full text colour, "VAE" and "Text
     encoder" in the quiet one. Nothing where the head said nothing. */
  function artPlakette(d) {
    if (!d.art) return null
    if (d.art === 'vae') return { text: t('katalog.sorte_vae'), farbe: 'var(--text-leise)' }
    if (d.art === 'textleser') return { text: t('katalog.bausatz_textleser'), farbe: 'var(--text-leise)' }
    const wort = t('katalog.bausatz_modell')
    const familie = d.familie ? (familyOf(d.familie)?.label ?? d.familie) : ''
    return { text: familie ? `${wort} · ${familie}` : wort, farbe: 'var(--text)' }
  }
  /* The rows of the open page: a hit's files, or a card's builds. */
  const trefferZeilen = $derived(
    dateien
      ? dateien.map((d) => {
          const ziel = repoAugen ? augenZielFuer(d) : null
          // A part counts as there when the service saw it lying in its folder
          // or the model list shows it now; the row is complete when the model
          // and every part are.
          const teile = d.bausatz?.teile.map((teil) => ({ ...teil, da: !teil.collision && (teil.da || istDa(localName(teil))) }))
          const da = bekannt && isThere(d) && (!ziel || istDa(ziel)) && (!teile || teile.every((teil) => teil.da))
          const names = foundNames(d)
          return {
            bausatz: teile ? { ...d.bausatz, teile } : null,
            plakette: artPlakette(d),
            schluessel: d.datei,
            name: d.datei,
            gb: d.groesse_gb,
            teile: d.teile ?? 1,
            zustand: da ? 'bereit' : names.some(wirdGeholt) ? 'laedt' : names.some(isQueued) ? 'wartet' : bekannt ? 'neu' : 'frage',
            anteil: Math.round((stand?.anteil ?? 0) * 100),
            text: stand ? `${gb(stand.geladen)} / ${gb(stand.gesamt)} GB${mbs ? ' · ' + mbs : ''}` : '',
            datei: d,
            names,
          }
        })
      : null,
  )
  const augenZielFuer = (d) => augenZiel(localName(d), repoAugen.datei)
  function kartenSatz(fassung, empfohlen) {
    if (passt(fassung, maschineGb)) {
      return empfohlen
        ? t('katalog.empfohlen_fuer', { gb: formatGb(maschineGb, texte.sprache) })
        : t('katalog.passt_fuer', { gb: formatGb(maschineGb, texte.sprache) })
    }
    return t('katalog.braucht_maschine', { gb: formatGb(brauchtMaschine(fassung), texte.sprache) })
  }
  const kartenZeilen = $derived.by(() => {
    if (!detail) return null
    const empfohlen = passendeFassung(detail, maschineGb)
    return detail.fassungen.map((f) => {
      const st = status(f)
      const fort = fortschritt(f)
      return {
        schluessel: f.id + f.datei,
        name: f.name,
        satz: kartenSatz(f, f === empfohlen),
        gb: f.groesse,
        empfohlen: f === empfohlen,
        zustand: st,
        names: buildNames(f),
        anteil: fort?.anteil ?? 0,
        text: fort ? fort.bytes + (mbs ? ' · ' + mbs : '') : '',
        fassung: f,
      }
    })
  })
  const zahlKurz = (n) => (n >= 1000 ? Math.round(n / 1000) + 'k' : String(n))
</script>

<!-- The kinds of model, one row each, and the downloads below them after a
     line (Hugging Face is no kind of model but the account the downloads run
     under, so it stands with them): the left column of the page. -->
{#snippet kindRows()}
  {#each ARTEN as eintrag (eintrag)}
    <Menuezeile
      titel={t(`katalog.art_${eintrag}`)}
      gewaehlt={art === eintrag && !dlOffen}
      size="list"
      onclick={() => artWaehlen(eintrag)}
    >
      {#snippet zeichen()}<Hauszeichen zeichen={ARTZEICHEN[eintrag]} groesse={18} />{/snippet}
    </Menuezeile>
  {/each}
  <div class="divider" role="separator"></div>
  <Menuezeile
    titel={t('downloads.titel')}
    gewaehlt={dlOffen}
    size="list"
    onclick={dlOeffnen}
  >
    {#snippet zeichen()}<Hauszeichen zeichen="download" groesse={18} />{/snippet}
    {#snippet rechts()}
      {#if anzahlAktiv()}<span class="dlzahl">{anzahlAktiv()}</span>{/if}
    {/snippet}
  </Menuezeile>
{/snippet}

<Seitenrahmen {offen} beschriftung={t('menue.katalog')}>
  <!-- The page stays mounted under its frame while closed (Seitenrahmen
       hides it), so a chosen version and the gallery's scroll survive a
       look away. `offen` tells the frame whether its sections stand in
       the sidebar. -->
  <Menueseite offen={offen} beschriftung={t('menue.katalog')} fuellen>
    {#snippet liste()}
      <SettingsNav current={dlOffen ? 'downloads' : 'katalog'} />
    {/snippet}

    {#snippet kopf()}
      <div class="titelblock">
        <div class="markenzeile">
          {#if weg.zurueck}
            <!-- The way back into the page this one was opened from (a
                 server panel's first-run steps). -->
            <button class="zurueck" onclick={zurueckgehen} aria-label={t('app.zurueck')} title={t('app.zurueck')}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M15 5 8 12l7 7" />
              </svg>
            </button>
          {/if}
          <span class="sign-box"><Fensterzeichen name="katalog" groesse={22} /></span>
          <h2 class="title">{t('menue.katalog')}</h2>
        </div>
      </div>
      <div class="kopfecke">
        {#if maschineGb}
          <div class="maschine">
            <span class="wort">{t('modell.vram_label')}:</span>
            <span class="wert">{formatGb(maschineGb, texte.sprache)} GB</span>
          </div>
        {/if}
      </div>
    {/snippet}

    <!-- Every page of the catalogue opens the same way: what it holds,
         quietly, with the page's own sign at the far end, over a hairline
         that spans the columns below. -->
    {#snippet seitenkopf(text, zeichen)}
      <div class="vorauswahl">
        <span>{text}</span>
        <span class="kopfzeichen"><Hauszeichen {zeichen} groesse="klein" /></span>
      </div>
    {/snippet}

    {#snippet inhalt()}
     <div class="two-columns">
      <!-- The page's own left column: the kinds and the downloads. -->
      <nav class="kinds" aria-label={t('menue.katalog')}>
        <div class="kind-rows">
          {@render kindRows()}
        </div>
      </nav>
      <div class="page">
      {#if dlOffen}
        {@render seitenkopf(t('downloads.titel'), 'download')}
        <!-- The Hugging Face token sits over the downloads it acts on: it
             lifts the rate limit and opens gated models. Once set it stands
             as masking dots with its last four characters, and "Remove"
             takes it out again (app/api/v1/hf_token.py). -->
        <div class="hf-zeile">
          <svg class="hf-marke" viewBox={LOGOS.huggingface.vb} width="24" height="24" aria-hidden="true">{@html LOGOS.huggingface.html}</svg>
          <span class="hf-name">{t('editor.quelle_hf')}</span>
          <Leuchtpunkt farbe={hfGesetzt ? 'gruen' : 'still'} groesse={9} />
          {#if hfGesetzt}
            <span class="feld maskiert" aria-label={t('modell.hf_token')}>••••••••••••{hfEnde}</span>
            <button class="sign-button" onclick={hfEntfernen}
                    title={t('editor.hf_entfernen')} aria-label={t('editor.hf_entfernen')}>
              <Hauszeichen zeichen="trash" groesse={14} />
            </button>
          {:else}
            <input class="feld" type="password" bind:value={hfEingabe} aria-label={t('modell.hf_token')}
                   autocomplete="off" onkeydown={(e) => { if (e.key === 'Enter' && hfEingabe.trim().length >= 8) hfSetzen() }} />
            <button class="knopf" disabled={hfEingabe.trim().length < 8} onclick={hfSetzen}>{t('modell.verbinden')}</button>
          {/if}
        </div>
        {#if !hfGesetzt}
          <div class="fussnote">{t('editor.hf_fussnote')}</div>
        {/if}
        <Downloadseite {stand} tempo={mbs} onAbbrechen={abbrechen} />
      {:else if detail}
        {@const erste = detail.fassungen[0]}
        <Modelldetail
          name={detail.nameKey ? t(detail.nameKey) : detail.name}
          unter={detail.von}
          marke={detail.marke ? LOGOS[detail.marke] : null}
          buchstabe={detail.logo}
          owner={detail.zubehoer ? avatarOwnerOf(detail) : ''}
          faehigkeiten={detail.zubehoer ? [] : (detail.faehigkeiten ?? [])}
          plaketten={detailPlaketten}
          {maschineGb}
          repo={erste?.id}
          satz={t(detail.langsatz ?? detail.satz)}
          zeilen={kartenZeilen}
          onZurueck={() => (detail = null)}
          onHolen={(z) => fassungHolen(z.fassung, detail)}
          onAbbrechen={abbrechen}
          onDequeue={(z) => dequeueNames(z.names)}
        />
      {:else if trefferSeite}
        <Modelldetail
          name={trefferSeite.name}
          unter={`${trefferSeite.anbieter} · ${zahlKurz(trefferSeite.ladungen)} ↓`}
          owner={trefferSeite.anbieter}
          buchstabe={String(trefferSeite.anbieter || '?').slice(0, 1).toUpperCase()}
          {maschineGb}
          repo={trefferSeite.id}
          zeilen={trefferZeilen}
          onZurueck={() => (trefferSeite = null)}
          onHolen={(z) => suchDateiHolen(trefferSeite.id, z.datei)}
          onAbbrechen={abbrechen}
          onDequeue={(z) => dequeueNames(z.names)}
        />
      {:else}
        {@render seitenkopf(t(VORAUSWAHL[art]), ARTZEICHEN[art])}
        {#if suchbar}
          <div class="suchrahmen">
            <span class="lupe" aria-hidden="true"><Hauszeichen zeichen="lupe" groesse="klein" /></span>
            <input
              class="suchfeld"
              bind:value={suchbegriff}
              aria-label={t('katalog.von_hf')}
              oninput={tippt}
              onkeydown={(e) => { if (e.key === 'Enter') suchen() }}
            />
          </div>
        {/if}

        {#snippet karteBlock(karte)}
          {@const f = passendeFassung(karte, maschineGb)}
          <Modellkarte
            {karte}
            fassung={f}
            passt={kartePasst(karte, maschineGb)}
            {maschineGb}
            status={status(f)}
            fortschritt={fortschritt(f)}
            onOeffnen={() => (detail = karte)}
            onDownload={() => fassungHolen(f, karte)}
            onCancel={abbrechen}
            onDequeue={() => dequeueNames(buildNames(f))}
          />
        {/snippet}

        {#if !(suchbar && suchAktiv)}
        <div class="galerie">
        {#if istZubehoer}
          <!-- One column per accessory kind, each with its own "open folder"
               button; no search box on this kind. -->
          <div class="spaltenraster">
            {#each SPALTEN_ZUBEHOER as sorte (sorte)}
              <div class="zspalte">
                <div class="zkopf">
                  <span class="ztitel tafelkopf">{t(`katalog.sorte_${sorte}`)}</span>
                  <button class="ordnerknopf" onclick={() => ordnerOeffnen(sorte)}
                          title={t('katalog.ordner_zeigen')} aria-label={t('katalog.ordner_zeigen')}>
                    <Hauszeichen zeichen="ordner" groesse="klein" />
                  </button>
                </div>
                {#each karten.filter((k) => k.sorte === sorte) as karte (karte.id)}
                  {@render karteBlock(karte)}
                {/each}
              </div>
            {/each}
          </div>
        {:else}
          <div class="raster">
            {#each karten as karte (karte.id)}
              {@render karteBlock(karte)}
            {/each}
          </div>
          {#if !karten.length}
            <p class="leer">{t('katalog.keine_kuratierten')}</p>
          {/if}
        {/if}
        </div>
        {/if}

        {#if suchbar && suchAktiv}
          <div class="suchteil">
            <h4 class="abschnitt tafelkopf">
              <svg viewBox={LOGOS.huggingface.vb} width="18" height="18" aria-hidden="true">{@html LOGOS.huggingface.html}</svg>
              {t('katalog.von_hf')}
            </h4>
            {#if sucht}
              <p class="leer">{t('modell.suche_laeuft')}</p>
            {:else if treffer?.length}
              {#each treffer as f (f.id)}
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="treffer" role="button" tabindex="0"
                     onclick={() => trefferOeffnen(f)}
                     onkeydown={(e) => { if (e.key === 'Enter') trefferOeffnen(f) }}>
                  <OwnerMark owner={f.anbieter} size={30} />
                  <div class="twer">
                    <div class="tname">{f.name}</div>
                    <div class="tunter">{f.anbieter}</div>
                  </div>
                  <span class="tzieh">{zahlKurz(f.ladungen)} ↓</span>
                  <span class="tpfeil" aria-hidden="true"><Hauszeichen zeichen="chevron_right" groesse="klein" /></span>
                </div>
              {/each}
            {:else if treffer}
              <p class="leer">{t('modell.keine_treffer')}</p>
            {/if}
          </div>
        {/if}
      {/if}
      </div>
     </div>
    {/snippet}
  </Menueseite>
</Seitenrahmen>

<style>
  /* The count of what runs and waits, blue: a download is in motion. */
  .dlzahl {
    font: 600 14px var(--schrift);
    font-variant-numeric: tabular-nums;
    color: var(--blau-text);
  }
  .titelblock {
    flex: 1 1 260px;
    min-width: 0;
  }
  .markenzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    color: var(--text);
  }
  /* The catalogue sign in a 40 px box of button glass, the page's mark. */
  .sign-box {
    width: 40px;
    height: 40px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    /* The glass of a button with its fine line, drawn inside the box. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .title {
    margin: 0;
    font-size: var(--schrift-seitentitel);
    font-weight: 400;
    line-height: 1.3;
  }
  /* Two columns in the page: the kinds at 300 px on the left, the chosen
     page on the right. Both are as high as the taller of the two; nothing
     stretches down to the foot of the window. */
  .two-columns {
    display: grid;
    grid-template-columns: 300px minmax(0, 1fr);
    gap: 24px;
    align-items: stretch;
  }
  /* Both columns are panels of card glass; the cards inside them step up.
     The panel of the kinds reaches as deep as the page beside it; its rows
     stay in view while the page scrolls. */
  .kinds {
    padding: 16px 10px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .kind-rows {
    display: flex;
    flex-direction: column;
    gap: 2px;
    position: sticky;
    top: 12px;
  }
  .divider {
    height: 1px;
    background: var(--linie);
    margin: 8px 0;
  }
  .page {
    min-width: 0;
    display: flex;
    flex-direction: column;
    padding: 16px 24px 24px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  /* Narrow window: the kinds stand over the page instead of beside it. */
  @media (max-width: 900px) {
    .two-columns { grid-template-columns: minmax(0, 1fr); gap: 16px; }
    .kind-rows { position: static; }
  }
  .zurueck {
    width: 30px;
    height: 30px;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 9px;
    /* Button glass with its fine edge, like every button on glass. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
  }
  .zurueck:hover {
    color: var(--text);
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  /* Memory figure and the way into the downloads, as one block at the far
     right — the panel drops from its right edge. */
  .kopfecke {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: none;
    position: relative;
  }
  .maschine {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: none;
  }
  .maschine .wort {
    font-size: 12px;
    color: var(--text-still);
  }
  .maschine .wert {
    font: 500 12px var(--schrift);
    font-variant-numeric: tabular-nums;
    color: var(--text-leise);
    white-space: nowrap;
  }
  /* As high as a row of the list beside it (40 px, its text in the middle) and
     starting at the same height, so the first row there and this head stand
     on one line; the hairline comes under that height. */
  .vorauswahl {
    box-sizing: content-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
    height: 40px;
    padding: 0 2px;
    margin-bottom: 14px;
    border-bottom: 1px solid var(--linie);
  }
  .kopfzeichen {
    display: flex;
    color: var(--text-still);
  }
  /* The magnifier sits inside the field, in front of the text. */
  .suchrahmen {
    position: relative;
    margin-bottom: 16px;
  }
  .lupe {
    position: absolute;
    left: 14px;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    color: var(--text-still);
    pointer-events: none;
  }
  .suchfeld {
    width: 100%;
    box-sizing: border-box;
    /* A field on glass: glass with the house's field outline. */
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 13.5px var(--schrift);
    padding: 12px 16px 12px 40px;
  }
  .suchfeld:focus {
    outline: 2px solid var(--linie-stark);
    outline-offset: -2px;
  }

  /* The columns follow the room the page really has, not the window: the
     sidebar beside the page can be wide or folded away, so the same window
     leaves very different widths. A card needs about 250px before its badge
     and its button run into each other. */
  .galerie {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
  }
  /* Every row is as high as the highest card: the cards of a row are one
     height, and nothing stretches below the last row. */
  .raster {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    grid-auto-rows: 1fr;
    gap: 14px;
    transition: opacity 0.16s;
  }
  /* Five cards of about 250px with their four gaps: 5 x 250 + 4 x 14. */
  @container (min-width: 1306px) {
    .raster { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  }
  @container (max-width: 780px) {
    .raster { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @container (max-width: 520px) {
    .raster { grid-template-columns: minmax(0, 1fr); }
  }
  /* The accessory kind: one column per sort, each a vertical stack. Where
     the page is narrower the columns wrap into fewer, then one. */
  .spaltenraster {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
    align-items: start;
  }
  /* A column is never narrower than the foot of an accessory card, which does
     not shrink: the widest one holds the kind pill "Vision (mmproj)" (the
     same word in both languages), the largest size and the download sign,
     224 px with the card's padding and line (measured in the browser). So
     five columns stand side by side from 5 x 224 + 4 x 12 = 1168 px, three
     from 696, two from 460, and one below. */
  @container (max-width: 1167px) {
    .spaltenraster { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }
  @container (max-width: 695px) {
    .spaltenraster { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @container (max-width: 459px) {
    .spaltenraster { grid-template-columns: minmax(0, 1fr); }
  }
  .zspalte {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .zkopf {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 2px 2px;
  }
  /* Text itself: global.css, .tafelkopf. Fills the row up to the folder
     button beside it. */
  .ztitel {
    flex: 1;
    min-width: 0;
  }
  .ordnerknopf {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text-leise);
    font: inherit;
    font-size: 12px;
    padding: 5px 10px;
    border-radius: 9px;
    cursor: pointer;
    white-space: nowrap;
  }
  .ordnerknopf:hover {
    color: var(--text);
    background: var(--glass-hover);
  }

  .suchteil {
    margin-top: 18px;
  }
  /* Text itself: global.css, .tafelkopf. */
  .abschnitt {
    margin: 0 0 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .treffer {
    display: flex;
    align-items: center;
    gap: 12px;
    border-radius: 9px;
    /* A card on the page: card glass with its fine line. The line is drawn
       inside the box, so the padding carries its pixel: 10 and 14 inside the
       line, 11 and 15 from the edge. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 11px 15px;
    margin-bottom: 4px;
    cursor: pointer;
  }
  .treffer:not(.datei):hover {
    background: color-mix(in srgb, var(--text) 8%, var(--glass-card));
  }
  .twer {
    flex: 1;
    min-width: 0;
  }
  .tname {
    font-size: 14px;
    font-weight: 500;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tunter {
    margin-top: 2px;
    font-size: 12px;
    color: var(--text-still);
  }
  .tzieh {
    flex: none;
    font-size: 12px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .tpfeil {
    display: flex;
    color: var(--text-still);
  }
  .leer {
    color: var(--text-still);
    font-size: 13px;
    padding: 6px 2px;
  }
  .knopf {
    flex: none;
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 500 12.5px var(--schrift);
    padding: 5px 12px;
    border-radius: 9px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.12s, opacity 0.12s;
  }
  .knopf:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .knopf:disabled {
    opacity: 0.5;
    cursor: default;
  }

  /* The token as one row over the downloads, in the house's row ground. */
  .hf-zeile {
    display: flex;
    align-items: center;
    gap: 12px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    /* Inside the line 10 and 14 (right 10); the line itself is drawn inside
       the box and takes no room, so the edge is one pixel further out. */
    padding: 11px 11px 11px 15px;
    margin-bottom: 8px;
  }
  .hf-marke {
    flex: none;
  }
  /* A sign button without a word: the bin that takes the token out, on the
     glass of a button with its fine line. */
  .sign-button {
    width: 32px;
    height: 32px;
    flex: none;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: pointer;
  }
  .sign-button:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .hf-name {
    flex: none;
    font: 500 13.5px var(--schrift);
    color: var(--text);
  }
  /* The field takes all the room the row has left after the name and the dot,
     up to the button at its end, as the masked token and as the empty field
     alike. */
  .feld {
    flex: 1 1 0;
    min-width: 0;
    height: 32px;
    box-sizing: border-box;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 12.5px var(--schrift);
    padding: 0 12px;
  }
  /* The set token: masking dots and its last four characters, not a field
     to type into. */
  .feld.maskiert {
    display: flex;
    align-items: center;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.04em;
    color: var(--text-leise);
  }
  .fussnote {
    margin-top: 10px;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-still);
  }
</style>
