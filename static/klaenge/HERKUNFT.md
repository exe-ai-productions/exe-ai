# Where these sounds come from

The three notification sounds are built from one recorded balafon note — a
wooden bar struck with a soft mallet. Pitch and rhythm were derived from that
single recording; nothing here is synthesised.

**Source:** Versilian Community Sample Library (VCSL), balafon, soft mallet.

**Licence:** CC0 1.0 — public domain dedication. No attribution is required
and the files may be shipped with this program. This note is kept anyway, so
that anybody asking where an audio file in an installer came from gets an
answer instead of a guess.

**The three signals**

| File | Meaning | Notes |
|---|---|---|
| `fertig.wav` | Response complete | D5 → G5, a rising fourth |
| `wartet.wav` | The program is waiting for the user | E5 twice, like a knock |
| `fehler.wav` | Something failed | G4 → F4 → E♭4, three steps down |
| `cron-fertig.wav` | A scheduled job finished | C5 → E5 → G5 → C6, a major triad up to the octave |

`cron-fertig.wav` was built later from the last note of `fehler.wav` — the
one that rings out freely — cut out and pitched. Nothing synthesised there
either: shifting the pitch takes the length with it, exactly as a shorter
wooden bar would. 115 ms between strikes. It is deliberately its own file
and not a replacement for `fertig.wav`: one says "your answer is here", the
other "something ran while you were away", and those should not sound alike.

Mono, 48 kHz, 16 bit. They are played only while the window is in the
background — see `frontend/src/lib/klaenge.js`.
