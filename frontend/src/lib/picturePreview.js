/*
  The picture of a message that has not reached the service yet, and after
  it has.

  A picture the person attached is a file until the message goes: the upload
  happens when it is sent. Its waiting bubble shows the file itself, by an
  address of its own (`blob:`). When the message goes, the service names the
  upload, and the sent bubble would read the picture by that name — a second
  fetch, a second decode, and for a moment the frame stands empty and the
  bubble is shorter by its picture. So the name is tied to the address the
  waiting bubble already drew: the sent bubble shows the very same picture,
  from the same address, and nothing moves.

  The message leaves the line before its upload is done, so an address cannot
  be let go of when the message leaves. The newest ones are kept instead, and
  the oldest let go of; a name whose address is gone is read from the service
  as any other.

  No imports on purpose: files and names in, addresses out, so it can be
  tried without a window around it.
*/

const MAX_KEPT = 24

/* The address made for each file; the newest used last. */
const addresses = new Map()
/* The upload's name → the address of the file it came from. */
const byName = new Map()

/** The address a file is shown by: made once per file. A name that is already
 *  an address or a name of an upload passes through. */
export function previewOf(file) {
  if (typeof file === 'string') return file
  let address = addresses.get(file)
  if (address) {
    addresses.delete(file)
  } else {
    address = URL.createObjectURL(file)
  }
  addresses.set(file, address)
  while (addresses.size > MAX_KEPT) {
    const [oldest, old] = addresses.entries().next().value
    addresses.delete(oldest)
    URL.revokeObjectURL(old)
    for (const [name, held] of byName) if (held === old) byName.delete(name)
  }
  return address
}

/** The service named the upload of this file: the sent bubble shows it by the
 *  address the waiting one showed. */
export function nameUpload(name, file) {
  if (!name || typeof file === 'string') return
  byName.set(name, previewOf(file))
}

/** The address a named upload is shown by, or null when there is none and the
 *  service's own address is the one to read. */
export function addressOf(name) {
  return byName.get(name) ?? null
}
