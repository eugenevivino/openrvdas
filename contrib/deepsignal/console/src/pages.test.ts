import { expect, it, vi } from 'vitest'
import { loadConsole, parseConsole } from './pages'
import { parseNumberPage as parsePage } from './modules/number/validate'

const tile = `title: Bridge
tiles:
  - type: number
    label: Depth
    field: DepthMeters
    unit: m
`

it('explains an invalid field name in the page file', () => {
  expect(() => parsePage('pages/bridge.yaml', tile.replace('DepthMeters', 'Depth *')))
    .toThrow('pages/bridge.yaml, tile 1, field: saw "Depth *". Expected an exact field name using letters, numbers, underscores, periods or hyphens. Example: field: DepthMeters')
})

it('explains an unsupported tile type in the page file', () => {
  expect(() => parsePage('pages/bridge.yaml', tile.replace('type: number', 'type: gauge')))
    .toThrow('pages/bridge.yaml, tile 1, type: saw "gauge". Expected "number". Example: type: number')
})

it('reads a fractional sample period and explains an invalid period', () => {
  expect(parsePage('pages/bridge.yaml', tile + '    period: 0.5\n').tiles[0].period).toBe(0.5)
  expect(() => parsePage('pages/bridge.yaml', tile + '    period: 0\n'))
    .toThrow('pages/bridge.yaml, tile 1, period: saw 0. Expected a positive period in seconds. Example: period: 2')
})

it('defaults to Night red and accepts the Night neutral configuration', () => {
  const settings = 'ship: Example\npages: [bridge]\n'
  const location = { protocol: 'https:', host: 'ship.example' }
  expect(parseConsole(settings, location).night_palette).toBe('red')
  expect(parseConsole(settings + 'night_palette: neutral\n', location).night_palette).toBe('neutral')
})

it('uses the same-origin CDS endpoint unless websocket is configured', () => {
  const settings = 'ship: Example\n'
  const https = parseConsole(settings, { protocol: 'https:', host: 'ship.example' }).websocket
  const http = parseConsole(settings, { protocol: 'http:', host: 'bridge.local:8080' }).websocket
  const explicit = parseConsole(settings + 'websocket: wss://cds.example/live\n',
    { protocol: 'https:', host: 'ship.example' }).websocket

  expect(https).toBe('wss://ship.example/cds-ws')
  expect(http).toBe('ws://bridge.local:8080/cds-ws')
  expect(explicit).toBe('wss://cds.example/live')
  expect(https).not.toContain(':8766')
  expect(http).not.toContain(':8766')
})

it.each(['ws://ship.example:8766', 'wss://other.example/cds-ws', 'wss://ship.example/raw']) (
  'refuses a browser CDS URL outside the same-origin relay: %s', async (url) => {
    vi.stubGlobal('window', { location: { protocol: 'https:', host: 'ship.example' } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(`ship: Example\nwebsocket: ${url}\n`)))
    try {
      await expect(loadConsole(new AbortController().signal)).rejects.toThrow('same-origin /cds-ws')
    } finally {
      vi.unstubAllGlobals()
    }
  },
)
