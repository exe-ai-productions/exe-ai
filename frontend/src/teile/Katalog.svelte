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
  import Seitenrahmen from './Seitenrahmen.svelte'
  import Menueseite from './Menueseite.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Menuezeile from './Menuezeile.svelte'
  import Schriftzug from './Schriftzug.svelte'
  import Modellkarte from './Modellkarte.svelte'
  import Modelldetail from './Modelldetail.svelte'
  import Downloadseite from './Downloadseite.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import {
    downloads, einreihen, fertigMerken, antreiben, anzahlAktiv,
  } from '../lib/downloads.svelte.js'
  import { api } from '../lib/api.js'
  import { weg, zurueckgehen } from '../lib/fensterweg.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'
  import {
    ARTEN, ZUBEHOER_ZIEL, SPALTEN_ZUBEHOER, ZUBEHOER_ORDNER, SUCHBARE_ARTEN,
    kartePasst, katalogFuer, passendeFassung, passt, brauchtMaschine,
    SORTE_FARBE, SORTE_LABEL,
  } from '../lib/modellempfehlungen.js'
  import { modellMarke } from '../lib/anbieterzeichen.js'
  import { LOGOS } from '../lib/logos.js'
  import { familyOf, loadImageFamilies } from '../lib/imageFamilies.svelte.js'

  let { offen = $bindable(false) } = $props()

  /* Which kind is open — Chat, Embedding, Speech, Picture, Accessories.
     Always one of them, always switchable back to Chat: the search below is
     scoped to this, and so is the curated gallery. */
  let art = $state('chat')
  /* Each kind's sign in the list: the speech bubble for chat models, the
     servers' own signs for embedding, speech and pictures, the puzzle piece
     for the add-ons a model reads beside it. */
  const ARTZEICHEN = {
    chat: 'sprechblase', einbettung: 'einbettung', sprache: 'sprache_welle',
    bild: 'bild', zubehoer: 'puzzle',
  }

  /* The heading each kind's page opens with. */
  const VORAUSWAHL = {
    chat: 'katalog.vorauswahl_chat', einbettung: 'katalog.vorauswahl_einbettung',
    sprache: 'katalog.vorauswahl_sprache', bild: 'katalog.vorauswahl_bild',
    zubehoer: 'katalog.vorauswahl_zubehoer',
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
  function artWaehlen(neu) {
    dlOffen = false
    if (neu === art) return
    art = neu
    detail = null
    trefferSeite = null
    // Leaving for a tab without a search: clear the field and its results,
    // or a stale term would keep the gallery dimmed on a tab that cannot search.
    if (!SUCHBARE_ARTEN.includes(neu)) {
      suchbegriff = ''
      treffer = null
      trefferSeite = null
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
      artWaehlen(zustand.katalogArtWunsch)
      zustand.katalogArtWunsch = null
    }
  })

  /* What the machine holds and what already lies in the folder — the two
     facts every card reads. Polled gently while the window is open, so a
     finished download lights up the right card without a reopen. */
  let maschineGb = $state(null)
  let vorhanden = $state([])
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
  const mbs = $derived(tempo > 50_000 ? (tempo / 1e6).toFixed(1) + ' MB/s' : '')

  const gb = (bytes) => (bytes / 1e9).toFixed(1)
  const istDa = (datei) => Boolean(datei) && vorhanden.includes(datei)
  /* The kit parts the picture side offers, by the sub-folder they belong
     in: a part is tied to its model without a download only when it is one
     of these. Null until the lists have been read once. */
  let partLists = $state(null)
  const wirdGeholt = (datei) => laedt && stand?.datei === datei

  function dran(f) {
    // An accessory keeps its local name in `ziel` (the remote file is named
    // the same across repositories); the progress and the presence check must
    // follow that name, not the remote one, or a renamed card never registers.
    return wirdGeholt(f.ziel ?? f.datei) || (f.mmproj_ziel && wirdGeholt(f.mmproj_ziel)) || (f.drafter_ziel && wirdGeholt(f.drafter_ziel))
  }
  function status(f) {
    if (dran(f)) return 'laedt'
    if (istDa(f.ziel ?? f.datei)) return 'bereit'
    return 'neu'
  }
  function fortschritt(f) {
    if (!dran(f) || !stand) return null
    const teil =
      stand.datei === f.mmproj_ziel ? t('modell.augen') + ' · '
      : stand.datei === f.drafter_ziel ? t('modell.feld_drafter') + ' · '
      : ''
    const anteil = Math.round((stand.anteil ?? 0) * 100)
    const text = `${teil}${gb(stand.geladen)} / ${gb(stand.gesamt)} GB · ${anteil} %${mbs ? ' · ' + mbs : ''}`
    const bytes = `${teil}${gb(stand.geladen)} / ${gb(stand.gesamt)} GB`
    return { anteil, text, bytes }
  }

  /* Fitting cards to the front — a fit is a fact worth surfacing. Ties keep
     the curated order. */
  const karten = $derived(
    [...katalogFuer(art)].sort((a, b) => Number(kartePasst(b, maschineGb)) - Number(kartePasst(a, maschineGb))),
  )

  $effect(() => {
    if (!offen) return
    const holen = async () => {
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
        if (art === 'zubehoer' || art === 'bild') {
          try {
            const bild = await api.bildmodelle()
            partLists = { vae: bild.vaes ?? [], text_encoders: bild.textversteher ?? [] }
            liste.push(
              ...(bild.modelle ?? []),
              ...(bild.vaes ?? []), ...(bild.loras ?? []), ...(bild.yolos ?? []),
              ...(bild.textversteher ?? []),
            )
          } catch {
            // No picture server yet — cards just show as not installed.
          }
        }
        // Embedding models land in the embedding server's own folder, which
        // the runner's list does not see either — same story as the picture
        // side, same fix, or a finished download keeps offering itself.
        if (art === 'einbettung') {
          try {
            const einbettung = await api.einbettungAuskunft()
            liste.push(...(einbettung.modelle ?? []).map((m) => m.name))
          } catch {
            // No embedding server yet — cards just show as not installed.
          }
        }
        // And speech models land in the speech server's own folder, with
        // their projectors beside them — same story again, same fix.
        if (art === 'sprache') {
          try {
            const sprache = await api.spracheAuskunft()
            liste.push(...(sprache.modelle ?? []).map((m) => m.name), ...(sprache.mmproj ?? []))
          } catch {
            // No speech server yet — cards just show as not installed.
          }
        }
        vorhanden = liste
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
      } catch {
        // A service that is not answering is not this window's problem yet.
      }
    }
    holen()
    const takt = setInterval(holen, 2000)
    return () => clearInterval(takt)
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
    if (karte?.zubehoer) return ZUBEHOER_ZIEL[karte.sorte] ?? { art }
    return { art }
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
    const ziel = routing(karte)
    const fehlend = begleiterJobs(f).filter((j) => !istDa(j.ziel))
    const lokal = f.ziel ?? f.datei
    if (!istDa(lokal)) {
      await starteJob({ repo: f.id, datei: f.datei, ziel: f.ziel ?? null }, fehlend, ziel)
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
      const antwort = await api.modellDateien(fund.id, art)
      // A slow answer for a page that was left in the meantime must not
      // write the files of the page that stands now.
      if (trefferSeite?.id !== fund.id) return
      dateien = antwort.dateien
      repoAugen = antwort.mmproj
      if (art === 'bild') readHeads(fund.id, antwort.dateien)
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
    if (art === 'bild') {
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
      if (!istDa(ziel)) jobs.push({ repo, datei: repoAugen.datei, ziel, gehoert_zu: modell, rolle: 'mmproj' })
    }
    for (const teil of d.bausatz?.teile ?? []) {
      if (teil.rolle === 'modell') continue
      const job = {
        repo: teil.repo, datei: teil.datei, ziel: localName(teil), unterordner: teil.ordner,
        gehoert_zu: modell, rolle: teil.feld,
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
    // A search hit downloads into the open tab's art (search runs only on the
    // searchable tabs); the routing argument is what starteJob now requires.
    if (modelThere) {
      const [erst, ...rest] = jobs
      if (erst) await starteJob(erst, rest, { art })
      return
    }
    await starteJob(
      { repo, datei: d.datei, ziel: modell === flach(d.datei) ? null : modell },
      jobs, { art },
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
  function suchDran(d) {
    const ziel = repoAugen ? augenZiel(localName(d), repoAugen.datei) : null
    return (
      wirdGeholt(localName(d)) || (ziel && wirdGeholt(ziel))
      // A kit's parts are shared by every file of its family: a part being
      // fetched completes the kit of each model that is here, and of no other.
      || (isThere(d) && (d.bausatz?.teile ?? []).some((teil) => wirdGeholt(localName(teil))))
    )
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
          const da = isThere(d) && (!ziel || istDa(ziel)) && (!teile || teile.every((teil) => teil.da))
          const dran = suchDran(d)
          return {
            bausatz: teile ? { ...d.bausatz, teile } : null,
            plakette: artPlakette(d),
            schluessel: d.datei,
            name: d.datei,
            gb: d.groesse_gb,
            teile: d.teile ?? 1,
            zustand: da ? 'bereit' : dran ? 'laedt' : 'neu',
            anteil: Math.round((stand?.anteil ?? 0) * 100),
            text: stand ? `${gb(stand.geladen)} / ${gb(stand.gesamt)} GB` : '',
            datei: d,
          }
        })
      : null,
  )
  const augenZielFuer = (d) => augenZiel(localName(d), repoAugen.datei)
  function kartenSatz(fassung, empfohlen) {
    if (passt(fassung, maschineGb)) {
      return empfohlen
        ? t('katalog.empfohlen_fuer', { gb: maschineGb })
        : t('katalog.passt_fuer', { gb: maschineGb })
    }
    return t('katalog.braucht_maschine', { gb: brauchtMaschine(fassung) })
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
        zustand: st === 'laedt' ? 'laedt' : st === 'bereit' ? 'bereit' : 'neu',
        anteil: fort?.anteil ?? 0,
        text: fort?.bytes ?? '',
        fassung: f,
      }
    })
  })
  const zahlKurz = (n) => (n >= 1000 ? Math.round(n / 1000) + 'k' : String(n))
</script>

<Seitenrahmen {offen} beschriftung={t('menue.katalog')}>
  <!-- The page stays mounted under its frame while closed (Seitenrahmen
       hides it), so a chosen version and the gallery's scroll survive a
       look away. `offen` tells the frame whether its sections stand in
       the sidebar. -->
  <Menueseite offen={offen} beschriftung={t('menue.katalog')}>
    {#snippet liste()}
      <!-- The kinds of model, one row each — what the tab switch in the head
           used to hold. The downloads below them, and Hugging Face last: it
           is no kind of model but the account the downloads run under. -->
      {#each ARTEN as eintrag (eintrag)}
        <Menuezeile
          titel={t(`katalog.art_${eintrag}`)}
          gewaehlt={art === eintrag && !dlOffen}
          onclick={() => artWaehlen(eintrag)}
        >
          {#snippet zeichen()}<Hauszeichen zeichen={ARTZEICHEN[eintrag]} groesse="gross" />{/snippet}
        </Menuezeile>
      {/each}
      <Menuezeile
        titel={t('downloads.titel')}
        gewaehlt={dlOffen}
        onclick={() => { dlOffen = true; detail = null; trefferSeite = null }}
      >
        {#snippet zeichen()}<Hauszeichen zeichen="download" groesse="gross" />{/snippet}
        {#snippet rechts()}
          {#if anzahlAktiv()}<span class="dlzahl">{anzahlAktiv()}</span>{/if}
        {/snippet}
      </Menuezeile>
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
          <svg viewBox="0 0 100 100" width="36" height="36" fill="none" stroke="currentColor"
               stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="20" y="24" width="60" height="52" rx="11" />
            <path d="M35 40 h30 M35 50 h30 M35 60 h18" />
          </svg>
          <Schriftzug zug="katalog" hoehe={17} />
        </div>
      </div>
      <div class="kopfecke">
        {#if maschineGb}
          <div class="maschine">
            <span class="wort">{t('katalog.maschine')}:</span>
            <span class="wert">{maschineGb} GB</span>
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
      {#if dlOffen}
        {@render seitenkopf(t('downloads.titel'), 'download')}
        <!-- The Hugging Face token sits over the downloads it acts on: it
             lifts the rate limit and opens gated models. Once set it stands
             as masking dots with its last four characters, and "Remove"
             takes it out again (app/api/v1/hf_token.py). -->
        <div class="hf-zeile">
          <svg class="hf-marke" viewBox={LOGOS.huggingface.vb} width="20" height="20" aria-hidden="true">{@html LOGOS.huggingface.html}</svg>
          <span class="hf-name">{t('editor.quelle_hf')}</span>
          <Leuchtpunkt farbe={hfGesetzt ? 'gruen' : 'still'} groesse={11} />
          {#if hfGesetzt}
            <span class="feld maskiert" aria-label={t('modell.hf_token')}>••••••••••••{hfEnde}</span>
            <button class="knopf" onclick={hfEntfernen}>{t('editor.hf_entfernen')}</button>
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
          faehigkeiten={detail.zubehoer ? [] : (detail.faehigkeiten ?? [])}
          plaketten={detailPlaketten}
          {maschineGb}
          repo={erste?.id}
          satz={t(detail.langsatz ?? detail.satz)}
          zeilen={kartenZeilen}
          onZurueck={() => (detail = null)}
          onHolen={(z) => fassungHolen(z.fassung, detail)}
          onAbbrechen={abbrechen}
        />
      {:else if trefferSeite}
        <Modelldetail
          name={trefferSeite.name}
          unter={`${trefferSeite.anbieter} · ${zahlKurz(trefferSeite.ladungen)} ↓`}
          marke={modellMarke(trefferSeite.name, trefferSeite.anbieter)}
          buchstabe={String(trefferSeite.anbieter || '?').slice(0, 1).toUpperCase()}
          {maschineGb}
          repo={trefferSeite.id}
          zeilen={trefferZeilen}
          onZurueck={() => (trefferSeite = null)}
          onHolen={(z) => suchDateiHolen(trefferSeite.id, z.datei)}
          onAbbrechen={abbrechen}
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
            <h4 class="abschnitt tafelkopf">{t('katalog.von_hf')}</h4>
            {#if sucht}
              <p class="leer">{t('modell.suche_laeuft')}</p>
            {:else if treffer?.length}
              {#each treffer as f (f.id)}
                {@const marke = modellMarke(f.name, f.anbieter)}
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="treffer" role="button" tabindex="0"
                     onclick={() => trefferOeffnen(f)}
                     onkeydown={(e) => { if (e.key === 'Enter') trefferOeffnen(f) }}>
                  <div class="tmarke" class:echt={marke}>
                    {#if marke}
                      <svg viewBox={marke.vb} width="19" height="19" aria-hidden="true">{@html marke.html}</svg>
                    {:else}
                      {String(f.anbieter || '?').slice(0, 1).toUpperCase()}
                    {/if}
                  </div>
                  <div class="twer">
                    <div class="tname">{f.name}</div>
                    <div class="tunter">{f.anbieter}</div>
                  </div>
                  <span class="tzieh">{zahlKurz(f.ladungen)} ↓</span>
                  <span class="tpfeil" aria-hidden="true">▸</span>
                </div>
              {/each}
            {:else if treffer}
              <p class="leer">{t('modell.keine_treffer')}</p>
            {/if}
          </div>
        {/if}
      {/if}
    {/snippet}
  </Menueseite>
</Seitenrahmen>

<style>
  /* The count of what runs and waits, blue: a download is in motion. */
  .dlzahl {
    font: 600 14px var(--schrift);
    font-variant-numeric: tabular-nums;
    color: var(--blau);
  }
  .titelblock {
    flex: 1 1 260px;
    min-width: 0;
  }
  .markenzeile {
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text);
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
  .vorauswahl {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
    padding: 0 2px 6px;
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
  }
  .raster {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px;
    align-content: start;
    transition: opacity 0.16s;
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
  /* Five side by side only at the page's full content width — a column
     narrower than that runs the kind badge into the mark beside it. */
  @container (max-width: 799px) {
    .spaltenraster { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }
  @container (max-width: 519px) {
    .spaltenraster { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @container (max-width: 339px) {
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
  }
  .treffer {
    display: flex;
    align-items: center;
    gap: 10px;
    border-radius: 9px;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 10px 14px;
    margin-bottom: 4px;
    cursor: pointer;
  }
  .treffer:not(.datei):hover {
    background: color-mix(in srgb, var(--text) 8%, var(--glass-card));
  }
  /* The maker's mark in front of a hit — the same language as the cards:
     a real vector on a filled square, a letter until one exists. */
  .tmarke {
    width: 30px;
    height: 30px;
    flex: none;
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text-still);
    display: flex;
    align-items: center;
    justify-content: center;
    font: 700 11px var(--schrift);
  }
  .twer {
    flex: 1;
    min-width: 0;
  }
  .tname {
    font-size: 13.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tunter {
    font-size: 11.5px;
    color: var(--text-still);
  }
  .tzieh {
    flex: none;
    font-size: 11.5px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .tpfeil {
    color: var(--text-still);
    font-size: 11px;
    transition: transform 0.15s;
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
    gap: 10px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 10px 14px;
    margin-bottom: 8px;
  }
  .hf-marke {
    flex: none;
  }
  .hf-name {
    flex: none;
    font-size: 13px;
    color: var(--text);
    margin-right: 4px;
  }
  .feld {
    flex: 1;
    min-width: 0;
    height: 32px;
    box-sizing: border-box;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 13px var(--schrift);
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
