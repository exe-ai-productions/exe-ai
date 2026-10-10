/*
  The languages a voice may be declared to speak.

  A closed list and not a text field, the same reason `diktatsprachen.js`
  gives for the dictation one: the code travels into a request the service
  builds, and a typed-in word would come back as a language nobody asked
  for. Smaller than that list on purpose — these are exactly the ten
  languages llama-tts documents for Qwen3-TTS, not every language the
  dictation side can transcribe.

  The same list the service holds (app/diktatsprachewahl.py,
  `STIMMSPRACHEN`). The names are not here: they live in the catalogues,
  keyed `sprache.name_<code>` — the same names the dictation picker already
  draws its entries from, since every one of these ten codes is also a
  dictation language.
*/

export const STIMMSPRACHEN = ['zh', 'en', 'de', 'it', 'pt', 'es', 'ja', 'ko', 'fr', 'ru']
