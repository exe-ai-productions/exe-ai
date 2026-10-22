/*
  The rule that travels with a document the model wrote.

  The preview frame runs that document with scripts allowed and without a
  shared origin (see ModulVorschau.svelte). The sandbox already keeps it out
  of this program: it cannot read the chats, the session key, or the page
  around it. What the sandbox does NOT stop is the document reaching the
  network. A script in there can post what it was given to a foreign address,
  and a single image pulled from one is enough to report "this document was
  opened just now".

  So the document gets a policy of its own, and the policy is cut to what a
  self-contained document actually needs. It may run its own scripts — a page
  that cannot run is not a preview of that page — and that includes the ways
  a script runs code it builds itself: `eval`, a WebAssembly module, and a
  worker started from a `blob:` the document made. None of the three can reach
  the network on its own: the line that closes the way out below holds for
  the worker as well, and a worker started from a `blob:` inherits the policy
  of the document that started it. The document may also style itself and
  carry its own pictures, as long as those pictures are IN the document
  (`data:`) or made by it (`blob:`). Nothing may travel outward: no fetch, no
  XHR, no WebSocket, no foreign picture, no foreign font, no foreign script.

  `'self'` appears nowhere on purpose. Without a shared origin the frame has
  no origin to match, so `'self'` would match nothing at all — writing it
  would read like an allowance and act like a ban.

  A document is free to bring a policy of its own; two policies are both
  enforced and the stricter one wins, so it can only ever narrow this one.
*/

const REGEL = [
  "default-src 'none'",
  // `'unsafe-eval'` for `eval` and `new Function`, `'wasm-unsafe-eval'` for a
  // WebAssembly module (the first one covers it too in some browsers; naming
  // both keeps the rule the same in all of them).
  "script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'",
  // Without its own line a worker would fall back to `default-src 'none'`.
  "worker-src blob:",
  "style-src 'unsafe-inline'",
  'img-src data: blob:',
  'font-src data:',
  'media-src data: blob:',
  // Already covered by default-src; spelled out because this is the line
  // that closes the way out.
  "connect-src 'none'",
  // Neither of these falls back to default-src.
  "form-action 'none'",
  "base-uri 'none'",
].join('; ')

const MARKE = `<meta http-equiv="Content-Security-Policy" content="${REGEL}">`

/* The frame is a document of its own, so the house rule of rolling without a
   bar on show (stil/global.css) does not reach into it. This brings it in:
   the universal selector has no weight, so a document that states its own
   `scrollbar-width` anywhere keeps it. It goes straight after the policy. */
const STIL = '<style>*{scrollbar-width:none}</style>'

/* A policy in a meta element governs whatever is parsed AFTER it, so it goes
   first — but never ahead of a doctype, which only counts as one when it is
   the very first thing in the document. Put in front of it, the document
   would silently switch to quirks mode and lay itself out differently.

   Only what goes into the frame is wrapped. The source view, the download
   and the save-to-folder button all keep handing out the document the model
   actually wrote, without a line nobody typed (neither the policy nor the
   rule for the bars). */
export function mitSchutzregel(inhalt) {
  const text = String(inhalt ?? '')
  const doctyp = text.match(/^\s*<!doctype[^>]*>/i)
  if (!doctyp) return MARKE + STIL + text
  return text.slice(0, doctyp[0].length) + MARKE + STIL + text.slice(doctyp[0].length)
}
