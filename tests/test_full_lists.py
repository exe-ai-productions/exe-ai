"""The sidebar's lists hold every row, not only the newest hundred.

The chat list, the archive and the job list are read from routes that answer
one page at a time (100 rows by default, 500 at most). A window that asked
once lost every older row: an old chat of a project, the tail of the archive,
a waiting agent's question behind many newer jobs. ``api.chats``,
``api.archivedChats`` and ``api.auftraege`` now ask page after page.

Driven the way tests/test_stromende.py drives api.js: the module as a plain
script, a stubbed ``window`` and a ``fetch`` that serves the rows of the
scenario with the service's own ``limit`` and ``offset`` rules.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.conftest import node_script

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "frontend/src/lib/api.js"

# A service that serves ``globalThis.__rows[route]`` newest first, refuses a
# limit above 500 the way the chat route does, and notes every request.
ENVIRONMENT = """
globalThis.window = { __SITZUNGSSCHLUESSEL__: 'key', location: { reload() {} } }
globalThis.__rows = {}
globalThis.__ignoreOffset = false
globalThis.__requests = []
globalThis.fetch = async (url) => {
  const address = new URL(url, 'http://service')
  const route = address.pathname.replace('/api/v1', '')
  const limit = Number(address.searchParams.get('limit') ?? 100)
  const offset = Number(address.searchParams.get('offset') ?? 0)
  globalThis.__requests.push({ route, search: address.search, limit, offset })
  if (limit > 500) return { ok: false, status: 422, json: async () => ({ detail: 'limit too large' }) }
  let rows = globalThis.__rows[route + (address.searchParams.get('archived') ? '?archived' : '')] ?? []
  const word = address.searchParams.get('suche')
  if (word) rows = rows.filter((row) => row.title.includes(word))
  const page = globalThis.__ignoreOffset ? rows.slice(0, limit) : rows.slice(offset, offset + limit)
  return { ok: true, status: 200, json: async () => page }
}
const make = (count, prefix, extra = {}) =>
  Array.from({ length: count }, (_, i) => ({ id: `${prefix}${i}`, title: `${prefix} ${i}`, ...extra }))
"""


def _module() -> str:
    """api.js as a plain script: the exports become declarations."""
    source = API.read_text(encoding="utf-8")
    return re.sub(
        r"^export (?=(?:async )?(?:function\*?|const|let|class) )", "", source, flags=re.M
    )


def _run(scenario: str) -> dict:
    script = f"""
{ENVIRONMENT}
{_module()}
const result = await (async () => {{
{scenario}
}})()
console.log(JSON.stringify(result))
"""
    done = node_script(script)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_chat_list_over_a_hundred_loses_no_old_chat():
    result = _run(
        """
        __rows['/chats'] = make(1201, 'chat')
        const chats = await api.chats()
        return {
          count: chats.length,
          oldest: chats.at(-1).id,
          order: chats.slice(0, 3).map((c) => c.id),
          offsets: __requests.map((r) => r.offset),
          limits: [...new Set(__requests.map((r) => r.limit))],
        }
        """
    )
    assert result["count"] == 1201
    assert result["oldest"] == "chat1200"
    assert result["order"] == ["chat0", "chat1", "chat2"]
    assert result["offsets"] == [0, 500, 1000]
    assert result["limits"] == [500]


def test_the_archive_holds_every_archived_chat():
    result = _run(
        """
        __rows['/chats?archived'] = make(101, 'old')
        const chats = await api.archivedChats()
        return {
          count: chats.length,
          oldest: chats.at(-1).id,
          archived: [...new Set(__requests.map((r) => new URLSearchParams(r.search).get('archived')))],
        }
        """
    )
    assert result["count"] == 101
    assert result["oldest"] == "old100"
    assert result["archived"] == ["true"]


def test_a_search_asks_page_after_page_with_its_word():
    result = _run(
        """
        __rows['/chats'] = make(700, 'match')
        const chats = await api.chats('match')
        return {
          count: chats.length,
          words: [...new Set(__requests.map((r) => new URLSearchParams(r.search).get('suche')))],
        }
        """
    )
    assert result["count"] == 700
    assert result["words"] == ["match"]


def test_a_waiting_agent_behind_many_newer_jobs_stays_in_the_list():
    result = _run(
        """
        __rows['/jobs'] = [
          ...make(101, 'newer', { state: 'finished' }),
          { id: 'agent', title: 'agent', state: 'waiting', question: 'Which file?' },
        ]
        const jobs = await api.auftraege()
        const waiting = jobs.find((job) => job.id === 'agent')
        return { count: jobs.length, question: waiting?.question ?? null }
        """
    )
    assert result["count"] == 102
    assert result["question"] == "Which file?"


def test_a_short_list_is_one_request_in_the_same_order():
    result = _run(
        """
        __rows['/chats'] = make(40, 'chat')
        const chats = await api.chats()
        return {
          ids: chats.map((c) => c.id),
          expected: make(40, 'chat').map((c) => c.id),
          requests: __requests.length,
        }
        """
    )
    assert result["ids"] == result["expected"]
    assert result["requests"] == 1


def test_a_list_of_exactly_one_page_ends_after_the_empty_next_page():
    result = _run(
        """
        __rows['/jobs'] = make(500, 'job')
        const jobs = await api.auftraege()
        return { count: jobs.length, requests: __requests.length }
        """
    )
    assert result == {"count": 500, "requests": 2}


def test_a_row_that_moves_between_pages_shows_up_once():
    result = _run(
        """
        const rows = make(750, 'chat')
        __rows['/chats'] = rows
        let first = true
        const inner = globalThis.fetch
        globalThis.fetch = async (url) => {
          const answer = await inner(url)
          if (first) {
            first = false
            // A chat is touched after the first page: it moves to the front,
            // so the second page starts with the row the first one ended on.
            __rows['/chats'] = [{ id: 'fresh', title: 'fresh' }, ...rows]
          }
          return answer
        }
        const chats = await api.chats()
        const ids = chats.map((c) => c.id)
        return { count: chats.length, unique: new Set(ids).size, oldest: ids.at(-1) }
        """
    )
    assert result["count"] == result["unique"] == 750
    assert result["oldest"] == "chat749"


def test_a_page_that_fails_fails_the_whole_load():
    result = _run(
        """
        __rows['/chats'] = make(900, 'chat')
        const inner = globalThis.fetch
        globalThis.fetch = async (url) => {
          if (new URL(url, 'http://service').searchParams.get('offset') === '500')
            return { ok: false, status: 500, json: async () => ({ detail: 'broken' }) }
          return inner(url)
        }
        try {
          await api.chats()
          return { failed: false }
        } catch {
          return { failed: true }
        }
        """
    )
    assert result == {"failed": True}


def test_a_service_that_ignores_the_offset_does_not_ask_for_ever():
    result = _run(
        """
        __ignoreOffset = true
        __rows['/chats'] = make(900, 'chat')
        const chats = await api.chats()
        return { count: chats.length, requests: __requests.length }
        """
    )
    assert result == {"count": 500, "requests": 2}
