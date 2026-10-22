import { cpSync } from 'node:fs'
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

/*
  The data folders of pdf.js (predefined CMaps, the standard fonts, the
  decoders that come as plain JavaScript where WebAssembly is not allowed,
  the ICC profiles) are files the library fetches while it draws a PDF
  (src/lib/pdfDocument.js). They are copied beside the build, with the
  licence file each folder carries. What only runs scripts inside a PDF
  (the QuickJS files of the wasm folder) is left out: the program shows a
  PDF, it does not run it.
*/
const PDFJS_DATA = ['cmaps', 'standard_fonts', 'wasm', 'iccs']
function pdfjsData() {
  return {
    name: 'pdfjs-data',
    apply: 'build',
    closeBundle() {
      for (const folder of PDFJS_DATA) {
        cpSync(
          new URL(`./node_modules/pdfjs-dist/${folder}`, import.meta.url),
          new URL(`../static/app/pdfjs/${folder}`, import.meta.url),
          { recursive: true, filter: (from) => !/quickjs/.test(from) },
        )
      }
    },
  }
}

/*
  The build writes straight into ../static/app/, where FastAPI serves it from.
  No second web server is needed: one process, one port.

  While developing (npm run dev) Vite runs on 5173 and forwards everything
  under /api to the running service. That gives instant reloads without
  touching the server.
*/
export default defineConfig({
  plugins: [svelte(), pdfjsData()],
  base: '/app/',
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
    // Kept for local development only — the map is never shipped
    // (deploy/exe-ai-terminal.spec excludes .map from the package, because
    // it unpacks to the full source of every file it maps). The bundle
    // still ends in a sourceMappingURL comment pointing at a file nobody
    // ships; a user who opens devtools sees one 404 there. Accepted on
    // purpose — sourcemap: 'hidden' would drop that comment, but it would
    // also stop the local browser from finding the map on its own, and
    // that costs more than the 404 only a developer ever sees.
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8090',
      '/favicon.svg': 'http://127.0.0.1:8090',
      '/icons': 'http://127.0.0.1:8090',
    },
  },
})
