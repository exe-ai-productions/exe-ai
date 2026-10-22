# Where these sounds come from

The four notification sounds are made by a script of our own. Nothing in them
comes from a recording or from anybody else's library, so no licence of a
third party applies and none has to be named.

Each note is a sine wave with a second voice detuned by a fraction of a
percent and two weak overtones, started softly (35 ms), left to die away
exponentially and put into a small room with two quiet, low-passed echoes.
Mono, 48 kHz, 16 bit.

**The four signals**

| File | Meaning | Notes |
|---|---|---|
| `fertig.wav` | An answer is complete | G4 with B4, then C5 with E5, rising |
| `wartet.wav` | The program is waiting for the user | E5 twice, like a knock |
| `fehler.wav` | Something failed | E♭5 → C5 → A4, three soft steps down |
| `agent-cronjob.wav` | An agent or a cronjob ended well | C5 → E5 → G5 → C6, a major triad opening to the octave |

`agent-cronjob.wav` is deliberately its own file and not a replacement for
`fertig.wav`: one says "your answer is here", the other "something ran while
you were away", and those should not sound alike.

The window plays them only while it is in the background, unless that is
switched off (`frontend/src/lib/klaenge.svelte.js`). The service plays
`agent-cronjob.wav` and `fehler.wav` for a schedule's notification
(`app/cronmeldung.py`).
