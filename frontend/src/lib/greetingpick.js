/*
  The sentence that follows the greeting of the empty chat.

  One of three, picked once when the page starts and kept until the next
  start, so the greeting does not change under the user's eyes while the
  chat stays empty. A plain module without runes, so the pick can be run
  by itself.
*/

export const GREETING_KEYS = ['greeting.ask_today', 'greeting.ask_help', 'greeting.lets_start']

/** One key of the three; `random` returns a number from 0 up to, not including, 1. */
export function pickGreeting(random = Math.random) {
  const at = Math.floor(random() * GREETING_KEYS.length)
  return GREETING_KEYS[Math.min(GREETING_KEYS.length - 1, Math.max(0, at))]
}

/** The key of this start. */
export const greetingKey = pickGreeting()
