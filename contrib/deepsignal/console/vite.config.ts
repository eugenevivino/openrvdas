import { existsSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'
import { paintLighting, readLighting } from './src/lighting-paint.ts'

// Keep the glob eager, but evaluate each module behind its own import boundary.
function isolateModules(): Plugin {
  const prefix = '\0console-module:'
  return {
    name: 'console-module-boundaries',
    enforce: 'pre',
    async resolveId(source, importer) {
      if (!importer?.endsWith('/src/registry.ts') || !/^\.\/modules\/[^/]+\/index\.ts$/.test(source)) return
      const entry = await this.resolve(source, importer, { skipSelf: true })
      if (entry) return prefix + entry.id
    },
    load(id) {
      if (!id.startsWith(prefix)) return
      return 'export const loadConsoleModule = () => import(' + JSON.stringify(id.slice(prefix.length)) + ')'
    },
  }
}

function pageManifest(): Plugin {
  let directory: string
  const file = 'pages/index.json'
  const generate = () => {
    if (!existsSync(directory)) return '[]'
    const ids = readdirSync(directory, { withFileTypes: true })
      .filter((entry) => entry.isFile() && /^[a-z0-9][a-z0-9-]*\.yaml$/.test(entry.name))
      .map((entry) => entry.name.slice(0, -5)).sort()
    return JSON.stringify(ids)
  }
  return {
    name: 'console-page-manifest',
    configResolved(config) {
      directory = resolve(config.publicDir, 'pages')
    },
    configureServer(server) {
      server.middlewares.use(server.config.base + file, (_request, response) => {
        response.setHeader('Content-Type', 'application/json')
        response.end(generate())
      })
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: file, source: generate() })
    },
  }
}

export default defineConfig({
  base: '/console/',
  build: {
    rolldownOptions: { output: { charset: 'ascii' } },
  },
  test: {
    setupFiles: ['./src/testkit/setup.ts'],
    // Let jsdom supply localStorage when Node exposes its own implementation.
    execArgv: process.allowedNodeEnvironmentFlags.has('--no-experimental-webstorage')
      ? ['--no-experimental-webstorage']
      : [],
  },
  plugins: [
    isolateModules(),
    pageManifest(),
    {
      name: 'console-first-paint',
      transformIndexHtml: {
        order: 'pre',
        handler(html) {
          return html.replace('/* console lighting boot */',
            `(() => {
              const { mode, dim, palette, defaultPalette } = (${readLighting.toString()})();
              (${paintLighting.toString()})(document.documentElement, mode, dim, palette ?? defaultPalette);
            })();`)
        },
      },
    },
    react(),
    tailwindcss(),
  ],
})
