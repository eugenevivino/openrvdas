// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import type { ConsoleModule, Page } from './contract'

const { discover } = vi.hoisted(() => ({ discover: vi.fn() }))
vi.mock('./registry', () => ({ discoverModules: discover }))

class Socket extends EventTarget {
  static current: Socket
  sent: Array<{ type: string; fields?: Record<string, unknown> }> = []

  constructor() {
    super()
    Socket.current = this
  }

  send(message: string) { this.sent.push(JSON.parse(message)) }
  close() {}
  receive(type: string, data?: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, status: 200, data }) }))
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  window.history.replaceState(null, '', '/')
})

it('reports a malformed registered page and keeps valid pages available', async () => {
  const example: ConsoleModule = {
    id: 'example',
    engines: [{ id: 'example', start: (ctx) => {
      ctx.pages.register({ id: 'example', title: 'Weather', tiles: [] })
      ctx.pages.register({ id: 'example', title: 'Broken page', tiles: {} } as unknown as Page)
      return () => {}
    } }],
  }
  discover.mockResolvedValue({ modules: [example], problems: [] })
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('console.yaml')
    ? new Response('ship: Test\npages: [example]\n')
    : new Response(null, { status: 404 })))

  render(<App />)
  const problem = await screen.findByText('Module example: Page "example" must have a list of tiles.')
  expect(problem).toHaveAttribute('role', 'alert')
  expect(screen.getByRole('heading', { name: 'Weather' })).toBeTruthy()
})

it('shows the relay and UDP warning on Self-test even when the cache connects', async () => {
  const { default: selfTest } = await import('./modules/self-test')
  discover.mockResolvedValue({ modules: [selfTest], problems: [] })
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('console.yaml')
    ? new Response('ship: Test\npages: [self-test]\n')
    : new Response(null, { status: 404 })))
  render(<App />)
  await screen.findByText('Disconnected')
  const socket = Socket.current
  act(() => {
    socket.dispatchEvent(new Event('open'))
    socket.receive('fields', [])
    socket.receive('describe', {})
  })
  expect(screen.getByText('Connected')).toBeTruthy()
  const warning = screen.getByText(/read-only relay/i)
  expect(warning).toHaveTextContent(/Django and React/)
  expect(warning).toHaveTextContent(/UDP.*named interface/i)
  expect(warning).toHaveTextContent(/install\.sh --check/)
})

it('mounts slots and one engine, isolates a tile problem, and requests the active destination and adapter fields', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  const now = 1_005
  vi.setSystemTime(now * 1000)
  const { default: number } = await import('./modules/number')
  const stop = vi.fn()
  const start = vi.fn(() => stop)
  const readStatus = vi.fn()
  const example: ConsoleModule = {
    id: 'example',
    presets: [{ id: 'example', yaml: `title: Weather
tiles:
  - {type: dial, fallback: number, field: Heading, unit: '°', label: Heading, dialScale: 360}
  - {type: unavailable}
` }],
    routes: [{ id: 'logs', title: 'Logs', order: 10, fields: () => ['LogText'],
      Component: () => <p>Log messages</p> }],
    adapters: [{ id: 'status', fields: () => ['status:*'], onValue: readStatus }],
    engines: [{ id: 'example', start }],
    slots: [
      { slot: 'banner', order: 10, Component: () => <p>Example banner</p> },
      { slot: 'topbar', order: 10, Component: () => <p>Example control</p> },
    ],
  }
  discover.mockResolvedValue({ modules: [number, example], problems: ['Module broken: Cannot start.'] })
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('console.yaml')
    ? new Response('ship: Test\npages: [example]\n')
    : new Response('<!doctype html>', { headers: { 'content-type': 'text/html' } })))

  const view = render(<App />)
  await screen.findByRole('heading', { name: 'Weather' })
  expect(screen.getByRole('heading', { name: 'Heading' })).toBeTruthy()
  expect(screen.getByText(/example.yaml, tile 2: type is "unavailable"/)).toBeTruthy()
  expect(screen.getByText('Module broken: Cannot start.')).toBeTruthy()
  expect(screen.getByRole('region', { name: 'Console banners' }).textContent).toBe('Example banner')
  expect(screen.getByRole('banner').textContent).toContain('Example control')
  expect(start).toHaveBeenCalledTimes(1)
  const socket = Socket.current

  const fields = ['Heading', 'LogText', 'status:logger_status', 'Unasked']
  act(() => {
    socket.dispatchEvent(new Event('open'))
    socket.receive('fields', fields)
    socket.receive('describe', {})
    socket.receive('subscribe')
    socket.receive('data', { 'status:logger_status': [[now, { logger: 'RUNNING' }]] })
  })
  expect(readStatus).toHaveBeenCalledTimes(1)
  expect(Object.keys(socket.sent.find(({ type }) => type === 'subscribe')!.fields!))
    .toEqual(['Heading', 'Heading_QC', 'status:logger_status'])
  const logs = screen.getByRole('link', { name: 'Logs' })
  fireEvent.click(logs)
  await screen.findByText('Log messages')
  act(() => socket.receive('data', {}))
  expect(Object.keys(socket.sent.at(-1)!.fields!)).toEqual(['LogText', 'LogText_QC', 'status:logger_status'])
  expect(start).toHaveBeenCalledTimes(1)
  view.unmount()
  expect(stop).toHaveBeenCalledTimes(1)
})

it.each([
  { variation: 'two FAILs in one batch', revocations: [[1, 2]] },
  { variation: 'three FAILs across two batches', revocations: [[3], [1, 2.5]] },
])('T-CON-1 / T-CON-14 keeps 18 m on the NO DATA tile after $variation', async ({ revocations }) => {
  vi.useFakeTimers({ toFake: ['Date'] })
  const start = Date.UTC(2026, 10, 20, 12) / 1000
  vi.setSystemTime(start * 1000)
  const { default: number } = await import('./modules/number')
  discover.mockResolvedValue({ modules: [number, { id: 'depth', presets: [{ id: 'depth', yaml: `title: Soundings
tiles:
  - {type: number, field: Depth, label: Depth, unit: m, decimals: 0, period: 1}
` }] }], problems: [] })
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('console.yaml')
    ? new Response('ship: Test\npages: [depth]\nhistory: 600\n')
    : new Response(null, { status: 404 })))

  render(<App />)
  await screen.findByRole('heading', { name: 'Depth' })
  const socket = Socket.current
  const catalog = () => {
    socket.receive('fields', ['Depth', 'Depth_QC'])
    socket.receive('describe', {})
  }
  const send = (data: object) => {
    expect(socket.sent.at(-1)?.type).toBe('ready')
    socket.receive('data', data)
    if (socket.sent.at(-1)?.type === 'fields') catalog()
  }
  const values = revocations.flat().length + 1
  act(() => {
    socket.dispatchEvent(new Event('open'))
    catalog()
    expect(socket.sent.at(-1)).toEqual({ type: 'subscribe', fields: {
      Depth: { seconds: 600, back_records: 1 }, Depth_QC: { seconds: 600, back_records: 1 },
    } })
    socket.receive('subscribe')
    for (let offset = 0; offset <= values + 20; offset++) {
      vi.setSystemTime((start + offset) * 1000)
      send({ Depth: [[start + offset, offset < values ? 18 + offset : null]],
        ...(offset === 0 ? { Depth_QC: [[start, 1]] } : {}) })
    }
  })
  act(() => {
    vi.setSystemTime((start + 360) * 1000)
    send({})
  })
  const freshness = screen.getByRole('group', { name: 'Freshness' })
  expect(freshness).toHaveTextContent('NO DATA')
  expect(screen.getByText(new RegExp(`^Last: ${17 + values} m at`))).toBeVisible()

  for (const batch of revocations) act(() => send({ Depth_QC: batch.map((offset) => [start + offset, 4]) }))
  expect(freshness).toHaveTextContent('NO DATA')
  const last = screen.getByText(/^Last: 18 m at/)
  expect(last).toBeVisible()
  expect(last).toHaveTextContent('Last: 18 m at 12:00:00Z')

  act(() => send({ Depth_QC: [[start, 4]] }))
  expect(freshness).toHaveTextContent('NO DATA')
  expect(screen.queryByText(/^Last:/)).toBeNull()

  act(() => send({ Depth: [[start + 360, 22]], Depth_QC: [[start + 360, 1]] }))
  expect(freshness).toHaveTextContent('LIVE')
  expect(screen.getByText('22')).toBeVisible()
  expect(screen.getByRole('group', { name: 'Data quality' })).toHaveTextContent('PASS')
})
