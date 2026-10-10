import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

/*
  The build writes straight into ../static/app/, where FastAPI serves it from.
  No second web server is needed: one process, one port.

  While developing (npm run dev) Vite runs on 5173 and forwards everything
  under /api to the running service. That gives instant reloads without
  touching the server.
*/
export default defineConfig({
  plugins: [svelte()],
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
