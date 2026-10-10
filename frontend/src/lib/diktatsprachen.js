/*
  The languages a dictation may be declared to be in.

  A closed list and not a text field: the code travels into the request the
  service builds, and a typed-in word would come back as a transcription in a
  language nobody asked for.

  The same list the service holds (app/diktatsprachewahl.py). Two copies is
  one too many, and this one exists because the picker has to draw its
  entries before any request goes out — the service checks what it is sent,
  so a list that drifts costs a "not offered", never a wrong request. The
  names are not here: they live in the catalogues, keyed `sprache.name_<code>`.
*/

export const SPRACHEN = [
  'de', 'en', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'sv', 'tr',
  'ru', 'uk', 'ar', 'he', 'hi', 'zh', 'ja', 'ko',
]
