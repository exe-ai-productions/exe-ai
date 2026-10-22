/* How long a conversation waits: the silence that ends a spoken sentence,
   the time one round waits for the user to start speaking, and how many
   rounds in a row may pass unspoken. Each is the user's own number, or the
   works one.

   The works numbers are the service's own (`conversation_pause_seconds`,
   `conversation_wait_seconds` and `conversation_silent_rounds` in
   app/diktatsprachewahl.py); a test holds them equal. */

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

export const WAIT_DEFAULT_SECONDS = 15.0
export const ROUNDS_DEFAULT = 3

/* The time one round waits for the first word, in milliseconds, by the same
   rule as the pause. */
export function roundMs(seconds) {
  const ok = typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
  return Math.round((ok ? seconds : WAIT_DEFAULT_SECONDS) * 1000)
}

/* How many rounds without a word end the conversation: a whole number of at
   least one is a choice, anything else is the works answer. */
export function silentRounds(rounds) {
  return Number.isInteger(rounds) && rounds >= 1 ? rounds : ROUNDS_DEFAULT
}
