// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../../App'
import type { ConsoleContext, FieldState } from '../../contract'
import streamHealthModule, { stages, streamHealthFields } from './index'

const empty = (field: string): FieldState => ({
  field, value: undefined, freshness: 'NO_DATA', quality: 'NOT_EVALUATED', health: 'UNKNOWN',
})

function fakeContext(initial: Record<string, Partial<FieldState>> = {}) {
  const values = new Map<string, FieldState>()
  const listeners = new Set<() => void>()
  const unsubscribed = vi.fn()
  for (const [field, state] of Object.entries(initial)) values.set(field, {
    ...empty(field), sourceTime: 100, receiveTime: 100, freshness: 'LIVE', value: 'OK', ...state,
  })
  const ctx = {
    config: { ship: 'Test', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 0,
      qcSuffix: '_QC', nightPalette: 'red', modules: {} },
    store: {
      connection: () => 'connected' as const, lastMessageAgeS: () => 0,
      listFields: () => [...values.keys()], describe: () => undefined,
      get: (field: string) => values.get(field) ?? empty(field), history: () => [],
      subscribe: (_fields: string[], listener: () => void) => {
        listeners.add(listener)
        return () => { listeners.delete(listener); unsubscribed() }
      },
      setHealth: () => undefined,
    },
    pages: { register: () => undefined, list: () => [] },
    alerts: { raise: () => undefined, clear: () => undefined, ack: () => undefined,
      list: () => [], subscribe: () => () => undefined },
    lighting: { get: () => ({ mode: 'day' as const, dayMode: 'day' as const, nightPalette: 'red' as const, dim: 1 }),
      set: () => undefined, subscribe: () => () => undefined },
    clock: { now: () => 100 }, route: { get: () => 'stream-health', go: () => undefined },
  } satisfies ConsoleContext
  return {
    ctx, unsubscribed,
    set(field: string, state: Partial<FieldState>) {
      values.set(field, { ...(values.get(field) ?? empty(field)), ...state })
      listeners.forEach((listener) => listener())
    },
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  window.history.replaceState(null, '', '/')
})

it.each([
  { stream: 'CTD_QC_1', extra: [] }, { stream: 'lab_QC_secondary', extra: [] },
  { stream: 'CTD_QC_1', extra: ['ds_chain:CTD'] }, { stream: 'lab_QC_secondary', extra: ['ds_chain:lab'] },
])('retains QC rejection for valid stream name $stream with catalog $extra', async ({ stream, extra }) => {
  const field = `ds_chain:${stream}:sensor`
  await openStreamHealth(1_000, { [field]: [[1_000, 'OK']], [field + '_QC']: [[1_000, 4]] }, extra)
  const report = screen.getByTestId('stream-health-row').querySelector('[data-stage="sensor"]')!
  expect(report.querySelector('strong')).toHaveTextContent('UNKNOWN')
  expect(report.querySelector('small')).toHaveTextContent('FAIL')
  expect(report).not.toHaveTextContent('Current')
})

it.each([
  { member: 'sensor', before: 'OK', rejected: 'FAILED' },
  { member: 'root', before: 'parser', rejected: 'store' },
])('retains rejected $member history when navigating during a CDS outage', async ({ member, before, rejected }) => {
  const field = `ds_chain:science:${member}`
  const qc = field + '_QC'
  const batch = await openStreamHealth(1_000, { [field]: [[1_000, before]], [qc]: [[1_000, 1]] })
  vi.setSystemTime(1_001_000)
  batch({ [field]: [[1_001, rejected]], [qc]: [[1_001, 4]] })
  vi.setSystemTime(1_401_000)
  act(() => CatalogSocket.current.dispatchEvent(new Event('close')))
  fireEvent.click(screen.getByRole('link', { name: /^Health$/ }))
  await screen.findByText(/Waiting for the logger manager/)
  expect(screen.queryByTestId('stream-health-row')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('link', { name: 'Stream Health' }))
  await screen.findByRole('heading', { name: 'Stream Health' })
  const row = await screen.findByTestId('stream-health-row')
  const report = row.querySelector(member === 'root' ? '.stream-root' : `[data-stage="${member}"]`)!
  expect(report.querySelector('strong')).toHaveTextContent(/^unknown$/i)
  expect(report.querySelector('small')).toHaveTextContent(
    `No data · FAIL · Last reported: ${rejected} · Last usable: ${before}`,
  )
})

describe('stream health registered view', () => {
  const route = streamHealthModule.routes![0]
  const Page = route.Component

  it('registers normal navigation without replacing the logger Health route', () => {
    expect(streamHealthModule.id).toBe('stream-health')
    expect(route).toMatchObject({ id: 'stream-health', title: 'Stream Health', order: 31 })
    expect(route.id).not.toBe('health')
  })

  it('discovers independent streams and keeps producer order despite field arrival order', () => {
    const inputs: Record<string, Partial<FieldState>> = {}
    for (const stage of [...stages].reverse()) inputs[`ds_chain:zeta:${stage}`] = { value: stage === 'endpoint' ? 'OFF' : 'OK' }
    inputs['ds_chain:zeta:root'] = { value: 'endpoint' }
    inputs['unrelated:field'] = { value: 'OK' }
    inputs['ds_chain:alpha:store'] = { value: 'DEGRADED' }
    inputs['ds_chain:alpha:root'] = { value: 'store' }
    const f = fakeContext(inputs)
    expect(streamHealthFields(f.ctx)).not.toContain('unrelated:field')
    render(<Page ctx={f.ctx} />)
    const rows = screen.getAllByTestId('stream-health-row')
    expect(within(rows[0]).getByRole('heading')).toHaveTextContent('alpha')
    expect(within(rows[1]).getByRole('heading')).toHaveTextContent('zeta')
    expect([...rows[1].querySelectorAll('.stream-stage-label')].map((node) => node.textContent)).toEqual(stages)
    expect(within(rows[1]).getByText('OFF')).toBeInTheDocument()
    expect(within(rows[1]).getByText('endpoint', { selector: '.stream-root strong' })).toBeInTheDocument()
  })

  it('keeps explicit UNKNOWN distinct from OFF and qualifies stale, missing, bad-quality, and invalid evidence', () => {
    const f = fakeContext({
      'ds_chain:science:sensor': { value: 'OFF' },
      'ds_chain:science:endpoint': { value: 'UNKNOWN' },
      'ds_chain:science:raw_traffic': { value: 'OK', freshness: 'STALE' },
      'ds_chain:science:parser': { value: 'OK', quality: 'FAIL' },
      'ds_chain:science:time': { value: 'healthy' },
      'ds_chain:science:derived': { value: 'OK', freshness: 'STALE', quality: 'FAIL',
        lastGood: { value: 'DEGRADED', time: 99 } },
      'ds_chain:science:root': { value: 'parser', freshness: 'STALE' },
    })
    render(<Page ctx={f.ctx} />)
    const stage = (name: string) => document.querySelector(`[data-stage="${name}"]`)!
    expect(stage('sensor')).toHaveTextContent('OFFCurrent')
    expect(stage('endpoint')).toHaveTextContent('UNKNOWNCurrent')
    expect(stage('raw_traffic')).toHaveTextContent('UNKNOWNStale')
    expect(stage('raw_traffic')).toHaveTextContent('Last reported: OK')
    expect(stage('raw_traffic').querySelector('.stream-state')).toHaveClass('stream-state-unknown')
    expect(stage('parser')).toHaveTextContent('UNKNOWNFAIL')
    expect(stage('time')).toHaveTextContent('UNKNOWNUnusable value')
    expect(stage('calibration')).toHaveTextContent('UNKNOWNMissing')
    expect(stage('derived')).toHaveTextContent('UNKNOWNStale · FAIL · Last reported: OK · Last usable: DEGRADED')
    expect(document.querySelector('.stream-root')).toHaveTextContent('UnknownStale')
    expect(document.querySelector('.stream-root')).toHaveTextContent('Last reported: parser')
  })

  it('shows explicit null root, updates recovered evidence, and releases its subscription', () => {
    const field = 'ds_chain:science:root'
    const f = fakeContext({ [field]: { value: null }, 'ds_chain:science:sensor': { value: 'OK', freshness: 'STALE' } })
    const view = render(<Page ctx={f.ctx} />)
    expect(document.querySelector('.stream-root')).toHaveTextContent('None reportedCurrent')
    expect(document.querySelector('[data-stage="sensor"]')).toHaveTextContent('UNKNOWNStale')
    act(() => f.set('ds_chain:science:sensor', { value: 'DEGRADED', freshness: 'LIVE' }))
    expect(document.querySelector('[data-stage="sensor"]')).toHaveTextContent('DEGRADEDCurrent')
    view.unmount()
    expect(f.unsubscribed).toHaveBeenCalledOnce()
  })

  it('explains an empty field store', () => {
    render(<Page ctx={fakeContext().ctx} />)
    expect(screen.getByText('No stream health data is available.')).toBeInTheDocument()
  })
})

class CatalogSocket extends EventTarget {
  static current: CatalogSocket
  sent: Array<{ type: string; fields?: Record<string, unknown> }> = []

  constructor() {
    super()
    CatalogSocket.current = this
  }

  send(message: string) { this.sent.push(JSON.parse(message)) }
  close() {}
  receive(type: string, data?: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, status: 200, data }) }))
  }
}

async function openStreamHealth(now: number, firstBatch: Record<string, unknown>, extraFields: string[] = [], qcSuffix = '_QC') {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(now * 1_000)
  vi.stubGlobal('WebSocket', CatalogSocket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('console.yaml')) return new Response(`ship: Test\npages: [health]\nhistory: 300\nqc_suffix: ${qcSuffix}\n`)
    return new Response(null, { status: 404 })
  }))

  render(<App />)
  fireEvent.click(await screen.findByRole('link', { name: 'Stream Health' }))
  await screen.findByRole('heading', { name: 'Stream Health' })
  expect(screen.getByRole('link', { name: /^Health$/ })).toBeInTheDocument()
  expect(screen.getByText('No stream health data is available.')).toBeInTheDocument()
  const socket = CatalogSocket.current
  act(() => {
    socket.dispatchEvent(new Event('open'))
    socket.receive('fields', [...Object.keys(firstBatch), ...extraFields])
    socket.receive('describe', {})
  })
  expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe' })
  const batch = (data: Record<string, unknown>) => act(() => socket.receive('data', data))
  const acknowledge = () => {
    act(() => socket.receive('subscribe'))
    expect(socket.sent.at(-1)?.type).toBe('ready')
  }
  // The app acknowledges its in-flight background subscription before sending the route request.
  act(() => socket.receive('subscribe'))
  expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe' })
  expect(Object.keys(socket.sent.at(-1)?.fields ?? {})).toEqual(expect.arrayContaining(Object.keys(firstBatch)))
  acknowledge()
  batch(firstBatch)
  // Empty background history causes a second subscription before normal streaming.
  expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe' })
  acknowledge()

  return batch
}

it('keeps historical producer reports and recovers both roots on the real console route', async () => {
  const now = 1_000
  const firstBatch = {
    'ds_chain:weather:root': [[now, 'endpoint']],
    'ds_chain:science:store': [[now, 'OK']],
    'ds_chain:science:time': [[now - 400, 'OK']],
    'ds_chain:weather:endpoint': [[now, 'DEGRADED']],
    'ds_chain:science:root': [[now, 'parser']],
    'ds_chain:science:parser': [[now, 'FAILED']],
  }
  const batch = await openStreamHealth(now, firstBatch)
  const [science, weather] = screen.getAllByTestId('stream-health-row')
  const root = (row: HTMLElement) => row.querySelector('.stream-root')
  const stage = (row: HTMLElement, name: string) => row.querySelector(`[data-stage="${name}"]`)
  expect(root(science)).toHaveTextContent('parserCurrent')
  expect(stage(science, 'parser')).toHaveTextContent('FAILEDCurrent')
  expect(stage(science, 'time')).toHaveTextContent('UNKNOWNNo data · Last reported: OK')
  expect(stage(science, 'sensor')).toHaveTextContent('UNKNOWNMissing')
  expect(root(weather)).toHaveTextContent('endpointCurrent')

  const later = now + 10
  vi.setSystemTime(later * 1_000)
  batch({})
  expect(stage(science, 'parser')).toHaveTextContent('UNKNOWNStale · Last reported: FAILED')
  expect(stage(science, 'store')?.querySelector('.stream-state')).toHaveTextContent('UNKNOWN')
  expect(stage(science, 'store')).toHaveTextContent('Last reported: OK')
  expect(root(science)).toHaveTextContent('UnknownStale · Last reported: parser')
  expect(root(weather)).toHaveTextContent('UnknownStale · Last reported: endpoint')
  expect(stage(weather, 'endpoint')).toHaveTextContent('UNKNOWNStale · Last reported: DEGRADED')

  batch({
    'ds_chain:science:root': [[later, 'store']],
    'ds_chain:science:store': [[later, 'DEGRADED']],
    'ds_chain:weather:root': [[later, null]],
    'ds_chain:weather:endpoint': [[later, 'OFF']],
  })
  expect(root(science)).toHaveTextContent('storeCurrent')
  expect(stage(science, 'store')).toHaveTextContent('DEGRADEDCurrent')
  expect(root(weather)).toHaveTextContent('None reportedCurrent')
  expect(stage(weather, 'endpoint')).toHaveTextContent('OFFCurrent')

  batch({ 'ds_chain:weather:root_QC': [[later, 4]], 'ds_chain:weather:endpoint_QC': [[later, 3]] })
  expect(root(weather)).toHaveTextContent('UnknownFAIL')
  expect(stage(weather, 'endpoint')).toHaveTextContent('UNKNOWNSUSPECT')
})

it.each([
  { member: 'derived', earlier: 'OK', latest: 'FAILED', separateFlag: false },
  { member: 'root', earlier: 'parser', latest: 'store', separateFlag: true },
])('shows stale QC and the latest report for $member on the real Console route', async ({
  member, earlier, latest, separateFlag,
}) => {
  const now = 100
  const field = `ds_chain:science:${member}`
  const qc = field + '_QC'
  const batch = await openStreamHealth(now, { [field]: [[now, earlier]], [qc]: [[now, 1]] })
  const row = screen.getByTestId('stream-health-row')
  const report = member === 'root' ? row.querySelector('.stream-root') : row.querySelector(`[data-stage="${member}"]`)
  expect(report?.querySelector('strong')).toHaveTextContent(earlier)

  vi.setSystemTime((now + 1) * 1_000)
  const failure = { [qc]: [[now + 1, 4]] }
  batch({ [field]: [[now + 1, latest]], ...(separateFlag ? {} : failure) })
  if (separateFlag) batch(failure)
  expect(report?.querySelector('strong')).toHaveTextContent(/^unknown$/i)
  expect(report?.querySelector('small')).toHaveTextContent('FAIL')

  vi.setSystemTime((now + 7) * 1_000)
  batch({})
  expect(report?.querySelector('strong')).toHaveTextContent(/^unknown$/i)
  expect(report?.querySelector('small')).toHaveTextContent(
    `Stale · FAIL · Last reported: ${latest} · Last usable: ${earlier}`,
  )
})


it.each([
  { member: 'sensor', reported: 'FAILED' },
  { member: 'store', reported: 'OFF' },
  { member: 'root', reported: 'parser' },
  { member: 'root', reported: null },
])('retains expired $member observation $reported without presenting it as current', async ({ member, reported }) => {
  const now = 1_000
  const field = `ds_chain:science:${member}`
  const batch = await openStreamHealth(now, { [field]: [[now, reported]] })
  vi.setSystemTime((now + 400) * 1_000)
  batch({})
  const row = screen.getByTestId('stream-health-row')
  const target = row.querySelector(member === 'root' ? '.stream-root' : `[data-stage="${member}"]`)
  expect(target?.querySelector('strong')).toHaveTextContent(member === 'root' ? 'Unknown' : 'UNKNOWN')
  expect(target?.querySelector('small')).toHaveTextContent(`No data · Last reported: ${reported === null ? 'None reported' : reported}`)
  expect(row.querySelector('[data-stage="endpoint"] small')).toHaveTextContent('Missing')
  // Expiry crosses the real client's catalog-refresh interval. Complete that
  // protocol exchange before sending the next data response.
  const socket = CatalogSocket.current
  expect(socket.sent.at(-1)?.type).toBe('fields')
  act(() => {
    socket.receive('fields', [field])
    socket.receive('describe', {})
  })
  expect(socket.sent.at(-1)?.type).toBe('ready')
  const recovered = member === 'root' ? 'store' : 'OK'
  batch({ [field]: [[now + 400, recovered]] })
  expect(target?.querySelector('strong')).toHaveTextContent(recovered)
  expect(target?.querySelector('small')).toHaveTextContent('Current')
})


it.each([{ member: 'sensor', earlierFail: false }, { member: 'store', earlierFail: false },
  { member: 'sensor', earlierFail: true }, { member: 'store', earlierFail: true }])(
  'retains correctly qualified $member history after a QC-only response (older FAIL: $earlierFail)', async ({ member, earlierFail }) => {
  const field = `ds_chain:science:${member}`
  const qc = field + '_QC'
  const flagTime = earlierFail ? 999 : 1_000
  const batch = await openStreamHealth(1_000, {
    [field]: earlierFail ? [[999, 'FAILED'], [1_000, 'OK']] : [[1_000, 'FAILED']], [qc]: [[flagTime, 4]],
  })
  const socket = CatalogSocket.current
  fireEvent.click(screen.getByRole('link', { name: /^Health$/ }))
  await screen.findByText(/Waiting for the logger manager/)
  batch({})
  expect(socket.sent.at(-1)?.type).toBe('subscribe')
  act(() => socket.receive('subscribe'))
  vi.setSystemTime(1_400_000)
  fireEvent.click(screen.getByRole('link', { name: 'Stream Health' }))
  await screen.findByTestId('stream-health-row')
  batch({})
  expect(socket.sent.at(-1)?.type).toBe('subscribe')
  act(() => socket.receive('subscribe'))
  expect(socket.sent.at(-1)?.type).toBe('fields')
  act(() => {
    socket.receive('fields', [field, qc])
    socket.receive('describe', {})
  })
  expect(socket.sent.at(-1)?.type).toBe('ready')
  batch({ [qc]: [[flagTime, 4]] })
  const report = screen.getByTestId('stream-health-row').querySelector(`[data-stage="${member}"]`)!
  expect(report.querySelector('strong')).toHaveTextContent('UNKNOWN')
  expect(report.querySelector('small')).toHaveTextContent(earlierFail
    ? 'No data · Last reported: OK' : 'No data · FAIL · Last reported: FAILED')
  if (earlierFail) expect(report.querySelector('small')).not.toHaveTextContent('FAIL')
  expect(report).not.toHaveTextContent('Current')
})


it.each(['time', 'store'])('requests stage QC when configured suffix is %s', async (suffix) => {
  const field = `ds_chain:CTD:${suffix}`
  await openStreamHealth(1_000, { [field]: [[1_000, 'OK']], [field + suffix]: [[1_000, 4]] }, [], suffix)
  const report = screen.getByTestId('stream-health-row').querySelector(`[data-stage="${suffix}"]`)!
  expect(report.querySelector('strong')).toHaveTextContent('UNKNOWN')
  expect(report.querySelector('small')).toHaveTextContent('FAIL')
})
