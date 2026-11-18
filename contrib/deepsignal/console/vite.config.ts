import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'
import { paintLighting, readLighting } from './src/lighting-paint.ts'

export default defineConfig({
  base: '/console/',
  test: {
    // Let jsdom supply localStorage when Node exposes its own implementation.
    execArgv: process.allowedNodeEnvironmentFlags.has('--no-experimental-webstorage')
      ? ['--no-experimental-webstorage']
      : [],
  },
  plugins: [
    {
      name: 'console-first-paint',
      transformIndexHtml: {
        order: 'pre',
        handler(html) {
          return html.replace('/* console lighting boot */',
            `(() => {
              const { mode, dim } = (${readLighting.toString()})();
              (${paintLighting.toString()})(document.documentElement, mode, dim);
            })();`)
        },
      },
    },
    react(),
    tailwindcss(),
  ],
})
