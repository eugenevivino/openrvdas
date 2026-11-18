// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Alert, ConsoleContext, FieldState } from '../../contract'
import { createConsoleContext } from '../../context'
import { ConsoleStore } from '../../store'
import module, { StaleBanner } from './index'

type MutableState = FieldState

function context(states: Record<string, MutableState>, logger: Record<string, string | undefined> = {}, settings: Record<string, unknown> = {}) {
  let now = 1795000000
  let alerts: Alert[] = []
  const listeners = new Set<() => void>()
  const ctx = {
    config: { ship: 'test', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 600, qcSuffix: '_QC', nightPalette: 'red', modules: { 'stale-banner': settings } },
    store: {
      connection: () => 'connected' as const, lastMessageAgeS: () => 0,
      listFields: () => Object.keys(states), describe: (field: string) => ({ description: field === 'Knud3Depth' ? 'Depth' : undefined, logger: logger[field] }),
      get: (field: string) => states[field], history: () => [], subscribe: () => () => {}, setHealth: () => {},
    },
    pages: { register: () => {}, list: () => [] },
    alerts: {
      raise: (alert: Alert) => { const old = alerts.find(a => a.id === alert.id); alerts = [...alerts.filter(a => a.id !== alert.id), { ...alert, acked: old?.acked }]; listeners.forEach(fn => fn()) },
      clear: (id: string) => { alerts = alerts.filter(a => a.id !== id); listeners.forEach(fn => fn()) },
      ack: (id: string) => { alerts = alerts.map(a => a.id === id ? { ...a, acked: true } : a); listeners.forEach(fn => fn()) },
      list: () => alerts, subscribe: (fn: () => void) => (listeners.add(fn), () => listeners.delete(fn)),
    },
    lighting: { get: () => ({ mode: 'day' as const, dayMode: 'day' as const, nightPalette: 'red' as const, dim: 1 }), set: () => {}, subscribe: () => () => {} },
    clock: { now: () => now }, route: { get: () => '', go: () => {} },
  } satisfies ConsoleContext
  return { ctx, states, setNow: (value: number) => { now = value }, alerts: () => alerts }
}

function state(field: string, freshness: FieldState['freshness'], health: FieldState['health'] = 'OK', ageS = 0): FieldState {
  return { field, value: 1, freshness, health, quality: 'PASS', ageS, sourceTime: 1795000000 - ageS }
}

function start(ctx: ConsoleContext) { return module.engines![0].start(ctx) }

beforeEach(() => vi.useFakeTimers())
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe('stale-alerts', () => {
  it('flr1_fails gives one grouped A2 with failed logger and affected field', () => {
    const f = context({ FlrChl: state('FlrChl', 'STALE', 'FAILED', 12) }, { FlrChl: 'flr1' })
    const stop = start(f.ctx); act(() => vi.advanceTimersByTime(1000))
    expect(f.alerts()).toHaveLength(1)
    expect(f.alerts()[0]).toMatchObject({ tier: 'A2', groupKey: 'flr1', title: 'flr1 logger failed' })
    render(<StaleBanner ctx={f.ctx} />); fireEvent.click(screen.getByRole('button', { name: /flr1 logger failed/i }))
    expect(screen.getByText('FlrChl')).toBeInTheDocument(); stop()
  })

  it('knud1_restart raises an A3 after grace and clears after recovery', () => {
    const f = context({ Knud3Depth: state('Knud3Depth', 'STALE', 'OK', 31) }, { Knud3Depth: 'knud1' })
    const stop = start(f.ctx); act(() => vi.advanceTimersByTime(1000))
    expect(f.alerts()[0]).toMatchObject({ tier: 'A3', title: 'Depth stale for 31 s' })
    f.states.Knud3Depth.freshness = 'LIVE'; f.states.Knud3Depth.ageS = 0
    act(() => vi.advanceTimersByTime(1000)); expect(f.alerts()).toEqual([]); stop()
  })

  it('tsg_suspect quality alone raises nothing', () => {
    const s = state('TsgTemp', 'LIVE'); s.quality = 'SUSPECT'
    const f = context({ TsgTemp: s }, { TsgTemp: 'tsg1' }); const stop = start(f.ctx)
    act(() => vi.advanceTimersByTime(1000)); expect(f.alerts()).toEqual([]); stop()
  })

  it('honors ignore globs', () => {
    const f = context({ FlrChl: state('FlrChl', 'NO_DATA', 'OK', 400) }, { FlrChl: 'flr1' }, { ignore: ['Flr*'] })
    const stop = start(f.ctx); act(() => vi.advanceTimersByTime(1000)); expect(f.alerts()).toEqual([]); stop()
  })

  it('ack keeps an A2 row dimmed and readable', () => {
    const f = context({ FlrChl: state('FlrChl', 'NO_DATA', 'OK', 400) }, { FlrChl: 'flr1' }); const stop = start(f.ctx)
    act(() => vi.advanceTimersByTime(1000)); render(<StaleBanner ctx={f.ctx} />)
    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))
    expect(screen.getByText(/FlrChl no data since/)).toBeVisible()
    expect(screen.getByTestId('alert-flr1')).toHaveAttribute('data-acked', 'true'); stop()
  })

  it('renders text only and sorts warning before caution', () => {
    const f = context({ stale: state('stale', 'STALE', 'OK', 40), dead: state('dead', 'NO_DATA', 'OK', 400) }, { stale: 'one', dead: 'two' })
    const stop = start(f.ctx); act(() => vi.advanceTimersByTime(1000)); const { container } = render(<StaleBanner ctx={f.ctx} />)
    expect(container.querySelector('svg,canvas,img')).toBeNull()
    const rows = screen.getAllByTestId(/^alert-/); expect(rows[0]).toHaveTextContent('Warning ◆'); expect(rows[1]).toHaveTextContent('Caution ▲'); stop()
  })
})

it('ignores never-observed catalog entries and preserves the outage time of an observed field', () => {
  const latent: FieldState = { field: 'latent', value: undefined, freshness: 'NO_DATA',
    health: 'UNKNOWN', quality: 'NOT_EVALUATED' }
  const f = context({ latent, gone: state('gone', 'NO_DATA', 'OK', 400) },
    { latent: 'quiet', gone: 'one' })
  const stop = start(f.ctx)
  act(() => vi.advanceTimersByTime(1000))
  const outage = f.alerts().find(({ groupKey }) => groupKey === 'one')
  expect.soft(f.alerts().map(({ groupKey }) => groupKey)).toEqual(['one'])
  f.setNow(f.ctx.clock.now() + 60)
  act(() => vi.advanceTimersByTime(1000))
  expect(f.alerts()).toEqual([outage])
  stop()
})

it('raises an outage only for a silent field still subscribed after a page switch', () => {
  const socket = new class extends EventTarget {
    send = vi.fn<(message: string) => void>()
    close() {}
    receive(type: string, data?: unknown) {
      this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, status: 200, data }) }))
    }
  }()
  vi.stubGlobal('WebSocket', function () { return socket })
  let now = 1795000000
  const clock = { now: () => now }
  const config = { ...context({}).ctx.config, websocket: 'ws://test:8766' }
  const store = new ConsoleStore(config, clock)
  const ctx = createConsoleContext(config, store, clock)
  const stop = start(ctx)
  try {
    store.select(new Map([['Knud3Depth', { period: 1 }], ['TsgTemp', { period: 1 }]]))
    store.start()
    socket.dispatchEvent(new Event('open'))
    socket.receive('fields', ['Knud3Depth', 'TsgTemp'])
    socket.receive('describe', { Knud3Depth: { description: 'Depth', logger: 'knud1' }, TsgTemp: { logger: 'tsg1' } })
    socket.receive('subscribe')
    socket.receive('data', { Knud3Depth: [[now, 20]], TsgTemp: [[now, 10]] })
    expect(store.get('Knud3Depth').value).toBe(20)
    act(() => vi.advanceTimersByTime(1000))
    expect(ctx.alerts.list()).toEqual([])

    store.select(new Map([['TsgTemp', { period: 1 }]]))
    socket.receive('data', { Knud3Depth: [[now, 21]] })
    expect(JSON.parse(socket.send.mock.lastCall![0])).toMatchObject({ type: 'subscribe', fields: { TsgTemp: expect.any(Object) } })
    socket.receive('subscribe')
    socket.receive('data', {})
    expect(store.listFields()).toContain('Knud3Depth')

    now += 301
    act(() => vi.advanceTimersByTime(1000))
    expect(ctx.alerts.list()).toMatchObject([{ tier: 'A2', groupKey: 'tsg1', title: expect.stringMatching(/^TsgTemp no data/) }])
  } finally {
    stop()
    store.stop()
  }
})

it('warns about a known failed logger before its first sample and preserves the failure time', () => {
  const failed: FieldState = { field: 'FlrChl', value: undefined, freshness: 'NO_DATA',
    health: 'FAILED', quality: 'NOT_EVALUATED' }
  const f = context({ FlrChl: failed }, { FlrChl: 'flr1' })
  const firstSeen = f.ctx.clock.now()
  const stop = start(f.ctx)
  act(() => vi.advanceTimersByTime(1000))
  expect(f.alerts()).toMatchObject([{ tier: 'A2', title: 'flr1 logger failed', since: firstSeen }])
  f.setNow(firstSeen + 60)
  act(() => vi.advanceTimersByTime(1000))
  expect(f.alerts()).toMatchObject([{ since: firstSeen }])
  failed.health = 'OK'
  act(() => vi.advanceTimersByTime(1000))
  expect(f.alerts()).toEqual([])
  stop()
})
