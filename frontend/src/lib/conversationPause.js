/* How long the microphone must be silent before a spoken sentence of a
   conversation is sent: the user's own number of seconds, or the works one.

   The works number is the service's own (`conversation_pause_seconds` in
   app/diktatsprachewahl.py); a test holds the two equal. */

export const PAUSE_DEFAULT_SECONDS = 3.0

/* The silence, in milliseconds, for what is stored: any number above zero is
   a choice, anything else — nothing stored, zero, a negative number — is the
   works answer. */
export function pauseMs(seconds) {
  const ok = typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
  return Math.round((ok ? seconds : PAUSE_DEFAULT_SECONDS) * 1000)
}

/* Whether the silence heard so far ends the sentence. */
export function pauseElapsed(silenceMs, seconds) {
  return silenceMs >= pauseMs(seconds)
}
