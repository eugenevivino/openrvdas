// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import type { ConsoleContext, ConsoleModule, Page } from './contract'
import { ConsoleStore } from './store'

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

const noon = Date.UTC(2026, 10, 20, 12) / 1000
const stockCachePoints = 8640

async function openSoundings(history: number) {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(noon * 1000)
  const { default: number } = await import('./modules/number')
  let context: ConsoleContext | undefined
  const onValue = vi.fn()
  const pages: ConsoleModule = {
    id: 'test-pages',
    presets: [
      { id: 'depth', yaml: `title: Soundings
tiles:
  - {type: number, field: Depth, label: Depth, unit: m, decimals: 0, period: 1}
` },
      { id: 'wind', yaml: `title: Weather
tiles:
  - {type: number, field: Wind, label: Wind, unit: m/s}
` },
    ],
    engines: [{ id: 'observe', start: (ctx) => {
      context = ctx
      if (!(ctx.store instanceof ConsoleStore)) throw new Error('Expected the production console store')
      return ctx.store.observeValues((field, reading) => {
        if (field === 'Depth') onValue(reading)
      })
    } }],
  }
  discover.mockResolvedValue({ modules: [number, pages], problems: [] })
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('console.yaml')
    ? new Response(`ship: Test\npages: [depth, wind]\nhistory: ${history}\n`)
    : new Response(null, { status: 404 })))
  window.history.replaceState(null, '', '#depth')
  const previousSocket = Socket.current
  render(<App />)
  await screen.findByRole('heading', { name: 'Depth' })
  await waitFor(() => expect(Socket.current).not.toBe(previousSocket))

  const socket = Socket.current
  const catalog = () => {
    socket.receive('fields', ['Depth', 'Depth_QC', 'Wind', 'Wind_QC'])
    socket.receive('describe', {})
  }
  const subscribe = (field: string) => {
    const options = history ? { seconds: history, back_records: 1 } : { seconds: -1 }
    expect(socket.sent.at(-1)).toEqual({ type: 'subscribe', fields: {
      [field]: options, [field + '_QC']: options,
    } })
    socket.receive('subscribe')
  }
  act(() => {
    socket.dispatchEvent(new Event('open'))
    catalog()
    subscribe('Depth')
  })
  const send = (data: object, offset?: number) => act(() => {
    if (offset !== undefined) vi.setSystemTime((noon + offset) * 1000)
    expect(socket.sent.at(-1)?.type).toBe('ready')
    socket.receive('data', data)
    if (socket.sent.at(-1)?.type === 'fields') catalog()
  })
  const navigate = async (page: string, field: string) => {
    const key = screen.getByRole('link', { name: page }).getAttribute('aria-keyshortcuts')!
    fireEvent.keyDown(window, { key })
    await screen.findByRole('heading', { name: field })
    send({}) // Complete the outstanding ready request for the previous page.
    act(() => subscribe(field))
  }
  return { store: context!.store, onValue, send, navigate }
}

it.each([
  { variation: 'two delayed FAILs after the stock 8640-point backfill', end: 8640,
    newer: [8617, 8618], revocations: [[8617, 8618]] },
  { variation: 'three delayed FAILs across batches after a shorter page-return backfill', end: 8643,
    newer: [8592, 8603, 8628], revocations: [[8592, 8603.5], [8628]] },
])('T-CON-14 keeps cached 18 m on page return with $variation', async ({ end, newer, revocations }) => {
  const history = 10_800
  const { store, send, navigate } = await openSoundings(history)
  const measurements = new Map([[0, 18], ...newer.map((offset, index) => [offset, 19 + index] as const)])
  const depths = Array.from({ length: end + 1 }, (_, offset) => [noon + offset, measurements.get(offset) ?? null])
  const pass = [[noon, 1]]
  send({ Depth: depths.slice(0, stockCachePoints), Depth_QC: pass }, stockCachePoints - 1)
  send({ Depth: depths.slice(stockCachePoints) }, end)

  await navigate('Weather', 'Wind')
  send({ Wind: [[noon + end, 5]] }, 9000)
  await navigate('Soundings', 'Depth')
  const backfill = depths.slice(-stockCachePoints)
  expect(backfill[0][0]).toBeGreaterThan(noon)
  send({ Depth: backfill, Depth_QC: pass })
  expect(store.history('Depth', history)[0]).toEqual({ time: noon, value: 18 })
  expect(store.history('Depth_QC', history)[0]).toEqual({ time: noon, value: 1 })
  expect(screen.getByRole('group', { name: 'Freshness' })).toHaveTextContent('NO DATA')
  expect(screen.getByText(new RegExp(`^Last: ${18 + newer.length} m at`))).toBeVisible()

  for (const batch of revocations) send({ Depth_QC: batch.map((offset) => [noon + offset, 4]) })
  expect(screen.getByText(/^Last: 18 m at/)).toHaveTextContent('Last: 18 m at 12:00:00Z')
})

it.each([
  { variation: 'three late FAILs after 24 nulls', step: 1, good: 4, nulls: 24, returnToPage: false },
  { variation: 'five late FAILs after 30 nulls and a live-only page return', step: 2, good: 6, nulls: 30,
    returnToPage: true },
])('T-CON-14 keeps the oldest usable reading with zero history and $variation', async ({
  step, good, nulls, returnToPage,
}) => {
  const { store, onValue, send, navigate } = await openSoundings(0)
  send({ Depth: [[noon, 18]], Depth_QC: [[noon, 1]] }, 0)
  // A previously rejected 19 m must stay rejected even if its flag is absent on return.
  if (returnToPage) {
    send({ Depth: [[noon + 1, 19]], Depth_QC: [[noon + 1, 4]] }, 1)
    expect(store.get('Depth').quality).toBe('FAIL')
  }
  for (let i = 1; i < good + nulls; i++) {
    const offset = i * step
    send({ Depth: [[noon + offset, i < good ? 20 + i : null]] }, offset)
  }
  const lastOffset = (good + nulls - 1) * step
  const staleOffset = lastOffset + 301
  const revoke = (i: number) => [noon + i * step + (step - 1) / 2, 4]
  send({ Depth_QC: [revoke(1)] }, staleOffset)
  expect(screen.getByRole('group', { name: 'Freshness' })).toHaveTextContent('NO DATA')
  expect(screen.getByText(new RegExp(`^Last: ${19 + good} m at`))).toBeVisible()

  if (returnToPage) {
    await navigate('Weather', 'Wind')
    send({ Wind: [[noon + staleOffset, 5]] })
    await navigate('Soundings', 'Depth')
    onValue.mockClear()
    send({ Depth_QC: [revoke(1)] })
    expect(store.get('Depth').sourceTime).toBeUndefined()
    expect(screen.getByRole('group', { name: 'Freshness' })).toHaveTextContent('NO DATA')
    send({ Depth: [[noon + lastOffset, null]] })
  }
  for (let i = 2; i < good; i++) send({ Depth_QC: [revoke(i)] })
  expect(screen.getByText(/^Last: 18 m at/)).toHaveTextContent('Last: 18 m at 12:00:00Z')
  if (returnToPage) expect(onValue).not.toHaveBeenCalled()
  expect(store.history('Depth', 0)).toEqual([])

  send({ Depth_QC: [[noon + 0.5, 4]] })
  expect(screen.getByRole('group', { name: 'Freshness' })).toHaveTextContent('NO DATA')
  expect(screen.queryByText(/^Last:/)).toBeNull()

  send({ Depth: [[noon + staleOffset, 42]], Depth_QC: [[noon + staleOffset, 1]] })
  expect(screen.getByRole('group', { name: 'Freshness' })).toHaveTextContent('LIVE')
  expect(screen.getByText('42')).toBeVisible()
  expect(screen.getByRole('group', { name: 'Data quality' })).toHaveTextContent('PASS')
  if (returnToPage) expect(onValue).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
    timestamp: noon + staleOffset, value: 42,
  }))
})
