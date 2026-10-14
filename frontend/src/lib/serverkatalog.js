/*
  The shipped tool servers: what we offer to connect, and under which name.

  Its own module because two windows ask the same question. The connections
  gallery needs the address and the kind of sign-in; the tools window needs
  only the proper name — `notion` is what the file calls it, `Notion` is what
  it is called. Capitalising the id would work for exactly that one and turn
  SearXNG into Searxng.

  `vorauswahl` is the vetted allowlist per provider. `null` means "offer
  everything" for now — the lists come into being as the providers are tested
  one by one. Short lists on purpose: twenty tool descriptions ruin the hit
  rate of a small local model.
*/

export const SERVERKATALOG = [
  /* The search that ships with the program. `anmeldung: 'keine'` is the
     honest entry for a server that runs here: there is nothing to sign in
     to, no address to reach, no key to set — it is simply on. The name in
     the file is a plain id; the title is the product it belongs to. */
  { name: 'websuche', titel: 'Exe Web Search', url: null, anmeldung: 'keine', vorauswahl: null },
  /* The search of one's own instance. Nothing ships for it: there is no
     address of ours to put in, so the card asks for one and writes the entry
     only with it. `command` and `args` are the program that starts here;
     `address_env` is the variable it reads the address from — by it the
     sheet knows to ask. */
  {
    name: 'searxng',
    titel: 'SearXNG',
    url: null,
    anmeldung: 'keine',
    command: '.venv/bin/python',
    args: ['mcp/searxng_server.py'],
    address_env: 'SEARXNG_URL',
    vorauswahl: null,
  },
  /* Recraft preselection, set while testing: generate, image-to-image,
     background removal — and inpainting, because the second wish after every
     first image is "change the sunglasses". The rest stays selectable. */
  {
    name: 'recraft',
    titel: 'Recraft',
    url: 'https://mcp.recraft.ai/mcp',
    anmeldung: 'oauth',
    vorauswahl: ['generate_image', 'image_to_image', 'remove_background', 'inpaint_image'],
  },
  { name: 'notion', titel: 'Notion', url: 'https://mcp.notion.com/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'github', titel: 'GitHub', url: 'https://api.githubcopilot.com/mcp/', anmeldung: 'schluessel', api_key_env: 'GITHUB_TOKEN', vorauswahl: null },
  { name: 'figma', titel: 'Figma', url: 'https://mcp.figma.com/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'gmail', titel: 'Gmail', url: 'https://gmailmcp.googleapis.com/mcp/v1', anmeldung: 'oauth_kennung', vorauswahl: null },
  { name: 'huggingface', titel: 'Hugging Face', url: 'https://huggingface.co/mcp', anmeldung: 'schluessel', api_key_env: 'HF_TOKEN', vorauswahl: null },
  /* `oauth` where the provider's sign-in server registers a client by
     itself, `oauth_kennung` where it does not and a client id made by hand
     at the provider is the only way in. The two Google servers answer
     without a sign-in and want a token per call, the same as Gmail. */
  { name: 'calendar', titel: 'Google Calendar', url: 'https://calendarmcp.googleapis.com/mcp/v1', anmeldung: 'oauth_kennung', vorauswahl: null },
  { name: 'drive', titel: 'Google Drive', url: 'https://drivemcp.googleapis.com/mcp/v1', anmeldung: 'oauth_kennung', vorauswahl: null },
  { name: 'slack', titel: 'Slack', url: 'https://mcp.slack.com/mcp', anmeldung: 'oauth_kennung', vorauswahl: null },
  { name: 'canva', titel: 'Canva', url: 'https://mcp.canva.com/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'todoist', titel: 'Todoist', url: 'https://ai.todoist.net/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'spotify', titel: 'Spotify', url: 'https://mcp-gateway-external-pilot.spotify.net/mcp', anmeldung: 'oauth_kennung', vorauswahl: null },
  { name: 'trello', titel: 'Trello', url: 'https://mcp.trello.com/v1', anmeldung: 'oauth', vorauswahl: null },
  { name: 'asana', titel: 'Asana', url: 'https://mcp.asana.com/v2/mcp', anmeldung: 'oauth_kennung', vorauswahl: null },
  { name: 'linear', titel: 'Linear', url: 'https://mcp.linear.app/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'clickup', titel: 'ClickUp', url: 'https://mcp.clickup.com/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'airtable', titel: 'Airtable', url: 'https://mcp.airtable.com/mcp', anmeldung: 'oauth', vorauswahl: null },
  { name: 'vercel', titel: 'Vercel', url: 'https://mcp.vercel.com/', anmeldung: 'oauth', vorauswahl: null },
  { name: 'sentry', titel: 'Sentry', url: 'https://mcp.sentry.dev/mcp', anmeldung: 'oauth', vorauswahl: null },
]

/** The proper name of a server — its own id if we do not know one. Asked
    for the table's OWN entries only: an id may be any word, also one every
    object answers to. */
export function serverTitel(name) {
  return SERVERKATALOG.find((k) => k.name === name)?.titel || name
}

/** Whether a server entry on file is the shipped server `katalog`. The name
    has to match, and a shipped server that has an address also needs the
    entry to reach that same address (the string the card writes itself): a
    server of one's own that carries a shipped name but points elsewhere is
    another server. A shipped server without an address — the one that runs
    here — is its entry's name alone. */
export function gehoertZurKachel(katalog, eintrag) {
  if (katalog.name !== eintrag.name) return false
  return !katalog.url || eintrag.url === katalog.url
}
