/*
  What a tap on "download" in the catalogue turns into.

  A file of the hub is rarely alone: a vision model comes with its
  projector, a picture model with its text encoders and its VAE. This turns
  one found file into the list of downloads that make it whole, in the order
  they are started, and the parts that lie in their folder already and only
  need tying to the model.

  No imports on purpose: a file in, a plan out, so it can be tried without a
  window around it.
*/

/** The last segment of a path — a file in a sub-folder of its repository
    lies flat in ours. */
export const flat = (path) => path.split('/').pop()

/** The name a file is kept under here: the service's word when it gave one. */
export const localName = (entry) => entry.local_name || flat(entry.datei ?? entry.name)

/** The local name of a projector: the model's own stem plus the projector's
    tail, so the server can tie the two together. */
export function visionTarget(modelFile, projectorFile) {
  const tail = projectorFile.slice(projectorFile.toLowerCase().indexOf('mmproj'))
  return `${flat(modelFile).replace(/\.gguf$/i, '')}-${tail}`
}

/** The plan for one found file.

    `present` is every file name that lies in a model folder, `partLists`
    the picture side's parts by sub-folder (or null before they were read).
    Returns `queue`, the downloads in the order they start, and `ties`, the
    parts that only need their bond to the model written. An empty queue
    means there is nothing left to fetch. */
export function planDownload({ repo, file, projector, present, partLists }) {
  const there = (entry) => !entry.collision && present.includes(localName(entry))
  const name = localName(file)
  const modelThere = there(file)
  const jobs = []
  const ties = []

  if (projector && !modelThere) {
    const target = visionTarget(name, projector.datei)
    if (!present.includes(target)) {
      jobs.push({ repo, datei: projector.datei, ziel: target, gehoert_zu: name, rolle: 'mmproj' })
    }
  }

  for (const part of file.bausatz?.teile ?? []) {
    if (part.rolle === 'modell') continue
    const job = {
      repo: part.repo,
      datei: part.datei,
      ziel: localName(part),
      unterordner: part.ordner,
      gehoert_zu: name,
      rolle: part.feld,
    }
    // The lists read just now decide what is there; the file list's own
    // answer only until those lists have been read once.
    const lying = part.collision
      ? false
      : partLists
        ? (partLists[part.ordner] ?? []).includes(localName(part))
        : part.da
    if (lying) ties.push(job)
    else jobs.push(job)
  }

  if (modelThere) return { queue: jobs, ties }
  const model = { repo, datei: file.datei, ziel: name === flat(file.datei) ? null : name }
  return { queue: [model, ...jobs], ties }
}

/** A size in bytes as gigabytes with one decimal. */
export const gigabytes = (bytes) => (bytes / 1e9).toFixed(1)

/** A count the short way: 12400 → "12k". */
export const shortCount = (n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))

/** What a curated card's build is right now, from the files that lie in the
    model folders and the download the service reports: `laedt` while the
    build's own file or one of its companions is being fetched, `bereit` when
    its file lies here, `neu` otherwise. A build names its local file with
    `ziel` where two repositories share a file name. */
export function buildState(build, present, stand) {
  const running = Boolean(stand) && !stand.fertig && !stand.fehler
  const fetching = (name) => running && Boolean(name) && stand.datei === name
  if (fetching(build.ziel ?? build.datei) || fetching(build.mmproj_ziel) || fetching(build.drafter_ziel) || fetching(build.partner?.ziel)) return 'laedt'
  const lies = present.includes(build.ziel ?? build.datei) && (!build.partner || present.includes(build.partner.ziel))
  return lies ? 'bereit' : 'neu'
}

/** How far the running download of a build is, and which part of it that is
    (`mmproj` the vision projector, `drafter` the speed module, `null` the
    model itself), or `null` while none of its files runs. */
export function buildProgress(build, stand) {
  if (!stand || stand.fertig || stand.fehler) return null
  const part =
    stand.datei && stand.datei === build.mmproj_ziel
      ? 'mmproj'
      : stand.datei && stand.datei === build.drafter_ziel
        ? 'drafter'
        : null
  const own = stand.datei === (build.ziel ?? build.datei)
  if (!part && !own) return null
  return { part, percent: Math.round((stand.anteil ?? 0) * 100), loaded: stand.geladen ?? 0, total: stand.gesamt ?? 0 }
}

/** The downloads that make one build of a card whole, in the order they
    start: the model, then its vision projector, then its speed module —
    leaving out what lies here already. `route` is where the card's files go
    (`art`, and for an accessory its folder and role); `targets` names the
    folders the two companions go to. Each job carries the model it belongs
    to and its role, so the service records the bond and the runner attaches
    the companion later without guessing. */
export function planBuild({ build, present, route, targets }) {
  const lies = (name) => present.includes(name)
  const companions = []
  if (build.mmproj) {
    companions.push({
      repo: build.id,
      datei: build.mmproj,
      ziel: build.mmproj_ziel,
      gehoert_zu: build.datei,
      rolle: 'mmproj',
      unterordner: targets.mmproj.unterordner,
    })
  }
  if (build.drafter) {
    companions.push({
      repo: build.drafter_repo ?? build.id,
      datei: build.drafter,
      ziel: build.drafter_ziel,
      gehoert_zu: build.datei,
      rolle: 'mtp',
      unterordner: targets.mtp.unterordner,
    })
  }
  const missing = companions.filter((job) => !lies(job.ziel))
  const own = build.ziel ?? build.datei
  const model = lies(own) ? [] : [{ repo: build.id, datei: build.datei, ziel: build.ziel ?? null }]
  const queue = [...model, ...missing].map((job) => ({
    ...job,
    rolle: job.rolle ?? route.rolle ?? null,
    unterordner: job.unterordner ?? route.unterordner ?? null,
  }))
  return { art: route.art, queue }
}
