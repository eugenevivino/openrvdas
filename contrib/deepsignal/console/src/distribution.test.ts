// @vitest-environment jsdom
/// <reference types="node" />

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

const dist = resolve('dist')

afterEach(() => {
  vi.unstubAllGlobals()
})

it('ships ASCII JavaScript in every production chunk', () => {
  const assets = resolve(dist, 'assets')
  const chunks = readdirSync(assets).filter((name) => name.endsWith('.js'))
  const nonAscii = chunks.filter((name) => readFileSync(resolve(assets, name)).some((byte) => byte > 127))

  expect(chunks.length).toBeGreaterThan(0)
  expect(nonAscii).toEqual([])
})

it('renders the production Bridge temperature in degrees and keeps the missing-value marker', async () => {
  const field = 'MwxAirTemp'
  const flag = field + '_QC'
  let ready = false
  let publish: (data: object) => void
  class CacheSocket extends EventTarget {
    constructor() {
      super()
      publish = (data) => {
        ready = false
        this.reply('data', data)
      }
      queueMicrotask(() => this.dispatchEvent(new Event('open')))
    }

    send(message: string) {
      const { type } = JSON.parse(message)
      switch (type) {
        case 'fields': this.reply(type, [field, flag]); break
        case 'describe': this.reply(type, {}); break
        case 'subscribe': this.reply(type); break
        case 'ready': ready = true; break
      }
    }

    reply(type: string, data?: object) {
      queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', {
        data: JSON.stringify({ type, status: 200, data }),
      })))
    }

    close() {}
  }

  vi.stubGlobal('WebSocket', CacheSocket)
  vi.stubGlobal('fetch', async (file: string) => {
    return file === './console.yaml'
      ? new Response('ship: R/V Example\npages: [bridge]\n')
      : new Response(null, { status: 404 })
  })

  const html = new DOMParser().parseFromString(readFileSync(resolve(dist, 'index.html'), 'utf8'), 'text/html')
  const script = html.querySelector<HTMLScriptElement>('script[type="module"]')!
  const entry = resolve(dist, script.getAttribute('src')!.replace(/^\/console\//, ''))
  document.body.innerHTML = html.body.innerHTML

  // jsdom does not load the stylesheet links that Vite preloads before importing a chunk.
  const styles = new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node instanceof HTMLLinkElement && node.rel === 'stylesheet') {
        const asset = resolve(dist, new URL(node.href).pathname.replace(/^\/console\//, ''))
        node.dispatchEvent(new Event(existsSync(asset) ? 'load' : 'error'))
      }
    }
  })
  styles.observe(document.head, { childList: true })
  try {
    await import(/* @vite-ignore */ entry)
    const tile = (await screen.findByRole('heading', { name: 'Air temperature' })).closest('article')!
    const value = tile.querySelector('.value')!
    const quality = within(tile).getByRole('group', { name: 'Data quality' })
    const now = Date.now() / 1000

    await waitFor(() => expect(ready).toBe(true))
    publish!({ [field]: [[now - 1, 19.06]], [flag]: [[now - 1, 1]] })
    await waitFor(() => expect(value.textContent).toBe('19.1 \u00B0C'))
    expect(quality.textContent).toBe('PASS')

    await waitFor(() => expect(ready).toBe(true))
    publish!({ [field]: [[now, 19.2]], [flag]: [[now, 9]] })
    await waitFor(() => expect(value.textContent).toBe('\u2014'))
    expect(quality.textContent).toBe('MISSING')
  } finally {
    styles.disconnect()
  }
})
