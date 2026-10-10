"""The rule the interface page carries.

A Content-Security-Policy names, per kind of resource, where the browser may
load it from and where the page may talk to. Everything not named is
refused. The page can then be as compromised as you like: a script that
cannot reach a foreign address cannot hand anything to one.

The rule below is measured against the built interface, not guessed, and
every widening carries the reason it is there. Two of them are wide enough
to say out loud:

* ``'unsafe-inline'`` for scripts. The page learns this run's session key
  from a small script the service stitches into it (see app/main.py); that
  script is written fresh on every start, so a hash cannot cover it. A nonce
  could, but the preview frame beside the chat inherits this policy, and a
  document the model wrote can never know the nonce -- so a nonce would
  silently stop every preview from running its own scripts, which is the one
  thing that frame exists to allow.
* ``'unsafe-inline'`` for styles. The built bundle writes style attributes
  straight into its markup.

So this policy is not an answer to a script that already runs in the page.
What it does close is the way OUT, and that was the measured hole: no
foreign address may be called, no foreign picture, font or script loaded.
The preview frame inherits all of it, and having no origin of its own,
``'self'`` matches nothing there -- every source below that reads as an
allowance for the interface reads as a ban inside that frame.
"""

from __future__ import annotations

KOPFZEILE = "Content-Security-Policy"

# The rule goes on every page this service hands out, not only the interface.
# A same-origin document WITHOUT it is a way around it: only about:srcdoc,
# about:blank and blob: inherit a policy, so a page fetched by URL carries
# whatever its own answer said -- nothing. A script in the interface can open
# one and borrow its unrestricted context, which is exactly the way out this
# rule exists to close. Measured, not assumed: a foreign host received the
# session key through an iframe on a page that had no rule of its own.
REGEL = "; ".join(
    (
        "default-src 'self'",
        # Own bundle, the stitched key script, and blob: for the recording
        # worklet, which is handed to the audio engine as a blob URL.
        "script-src 'self' 'unsafe-inline' blob:",
        "worker-src 'self' blob:",
        "style-src 'self' 'unsafe-inline'",
        # blob: for the preview of a picture the user just attached, data:
        # for pictures a preview document carries inside itself.
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "media-src 'self' data: blob:",
        # The line that closes the way out: the answer stream and every API
        # call are our own address, and nothing else is allowed.
        "connect-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        # Nothing embeds this page.
        "frame-ancestors 'none'",
    )
)
