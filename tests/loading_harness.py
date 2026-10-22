"""A page of the interface built as it ships and driven in a real Chrome.

Used by the tests that ask what a window does while its answers are on their
way: the service is not asked, every call of `api` is answered by the page
itself, after a time of its own where the test wants one. The build, the
browser and the result are the ones the other browser tests of the server
pages use.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from uuid import uuid4

from app import appfenster, prozessstopp
from tests.test_speech_server_projector_memory import (
    FRONTEND,
    PAGE,
    VITE_CONFIG,
    _free_port,
    _read_result,
)

# Every call answers with what `window.answers` holds under its name: a
# function is called (and may wait or throw), anything else is handed back as
# it is. The calls in flight per name are counted, the most at one time kept.
API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
export const api = new Proxy({}, {
  get: (_, name) => async (...args) => {
    const live = (window.inflight ||= {})
    const most = (window.mostAtOnce ||= {})
    live[name] = (live[name] || 0) + 1
    most[name] = Math.max(most[name] || 0, live[name])
    try {
      const answer = (window.answers || {})[name]
      if (typeof answer === 'function') return await answer(...args)
      return JSON.parse(JSON.stringify(answer === undefined ? {} : answer))
    } finally {
      live[name] -= 1
    }
  },
})
"""

PRELUDE = r"""
const report = { errors: [] }
window.addEventListener('error', (event) => report.errors.push(String(event.message)))
window.addEventListener('unhandledrejection', (event) => report.errors.push(String(event.reason && event.reason.message || event.reason)))
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const until = async (test, what, limit = 20000) => {
  const end = Date.now() + limit
  while (Date.now() < end) {
    try { if (test()) return true } catch (_) {}
    await wait(100)
  }
  throw new Error('timed out waiting for ' + what)
}
// An answer that comes after `ms`, with `value` — or a refusal with `value` as its sentence.
const later = (ms, value) => async () => { await wait(ms); return JSON.parse(JSON.stringify(value)) }
const refused = (ms, sentence) => async () => { await wait(ms); throw new window.ApiFehler(sentence) }
// Every notice that ever stood, by its number.
const seen = new Map()
setInterval(() => { for (const notice of window.meldungen.liste) seen.set(notice.id, notice.text) }, 40)
const noticesOf = (sentence) => [...seen.values()].filter((text) => text === sentence).length
"""


def run_page(shell: str, entry: str, cases: str, *, limit: float = 240.0) -> dict:
    """Builds `shell` with `entry`, runs `cases` in headless Chrome at
    1920 x 1080 and hands back what the page reported."""
    program = appfenster._programm() or __import__("pytest").skip("no Chrome on this machine")
    folder = FRONTEND / f".harness-loading-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(shell, encoding="utf-8")
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": PRELUDE + cases}, encoding="utf-8")
        port = _free_port()
        chrome = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port, limit=limit))
        finally:
            prozessstopp.beenden(chrome, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)
