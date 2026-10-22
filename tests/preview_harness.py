"""A web page of the real preview components, drawn in headless Chrome.

The frontend's own build tool builds an entry of the test as shipped, a small
web server of the test serves it with a few files, and Chrome reports what
the page drew (the page writes a JSON text into `#ergebnis`, read over the
debugging port). Several browser tests of the preview share it.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  base: './',
  // A library build keeps `process.env.NODE_ENV` as written; the app's build replaces it.
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'error',
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; } #wurzel { width: 1280px; height: 1000px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      %(cases)s
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
</body></html>
"""

class _Handler(http.server.SimpleHTTPRequestHandler):
    """The harness folder, with the service's file address mapped onto it."""

    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0]
        if path.startswith("/api/v1/"):
            path = path[len("/api/v1"):]
        return super().translate_path(path)

    def log_message(self, *args) -> None:
        pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 150.0) -> dict:
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + limit
    address = None
    while time.monotonic() < end and address is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                for page in json.load(response):
                    if page.get("type") == "page" and "measure.html" in page.get("url", ""):
                        address = page["webSocketDebuggerUrl"]
        except OSError:
            pass
        if address is None:
            await asyncio.sleep(0.2)
    assert address, "Chrome did not open the page"
    async with websockets.connect(address, max_size=32 * 1024 * 1024) as connection:
        number = 0

        async def value_of(expression: str):
            nonlocal number
            number += 1
            await connection.send(
                json.dumps({"id": number, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}})
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {}).get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def run_page(shell: str, entry: str, cases: str, assets: dict[str, bytes], limit: float = 150.0) -> dict:
    """Build `shell` and `entry`, serve them with `assets` (file name to
    bytes), run the JavaScript `cases` in the page and return its report."""
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-preview-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(shell, encoding="utf-8")
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        (folder / "measure.html").write_text(PAGE % {"cases": cases, "links": links}, encoding="utf-8")
        for name, data in assets.items():
            (folder / name).write_bytes(data)
        web_port = _free_port()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port), functools.partial(_Handler, directory=str(folder))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking", "--mute-audio",
                "--use-mock-keychain", "--password-store=basic",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", f"http://127.0.0.1:{web_port}/measure.html",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port, limit))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        if server:
            server.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


