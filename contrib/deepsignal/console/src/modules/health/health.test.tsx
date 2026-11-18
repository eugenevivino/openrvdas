// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import feed from '../../contract/fake-feed.json'
import type {
  ConsoleContext,
  FieldDescription,
  FieldState,
  Health,
} from '../../contract'
import healthModule, { parseHints, resolveHint } from './index'

type FeedEvent = { t: number; field: string; value: unknown }

function fakeContext() {
  let now = feed.start_time
  const states = new Map<string, FieldState>()
  const descriptions = feed.fields as Record<string, FieldDescription>
  const health = new Map<string, { health: Health; evidence?: string }>()
  const listeners = new Set<() => void>()
  const ctx = {
    config: {
      ship: 'Test ship', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 600,
      qcSuffix: '_QC', nightPalette: 'red', modules: {},
    },
    store: {
      connection: () => 'connected' as const,
      lastMessageAgeS: () => 0,
      listFields: () => [...Object.keys(descriptions), ...states.keys()],
      describe: (field: string) => descriptions[field],
      get: (field: string) => states.get(field) ?? {
        field, value: undefined, freshness: 'NO_DATA', quality: 'NOT_EVALUATED', health: 'UNKNOWN',
      },
      history: () => [],
      subscribe: (_fields: string[], cb: () => void) => { listeners.add(cb); return () => listeners.delete(cb) },
      setHealth: ({ logger }: { logger: string }, value: Health, evidence?: string) => {
        health.set(logger, { health: value, evidence })
      },
    },
    pages: { register: vi.fn(), list: () => [] },
    alerts: { raise: vi.fn(), clear: vi.fn(), ack: vi.fn(), list: () => [], subscribe: () => () => {} },
    lighting: {
      get: () => ({ mode: 'day' as const, dayMode: 'day' as const, nightPalette: 'red' as const, dim: 1 }),
      set: vi.fn(), subscribe: () => () => {},
    },
    clock: { now: () => now },
    route: { get: () => 'health', go: vi.fn() },
  } satisfies ConsoleContext

  const adapter = healthModule.adapters![0]
  function send(event: FeedEvent) {
    now = feed.start_time + event.t
    states.set(event.field, {
      field: event.field, value: event.value, sourceTime: now, receiveTime: now,
      periodS: event.field.startsWith('status:') ? 5 : 1, ageS: 0,
      freshness: 'LIVE', quality: 'NOT_EVALUATED', health: 'UNKNOWN',
    })
    adapter.onValue(event.field, event.value, now, ctx)
    listeners.forEach((cb) => cb())
  }
  function at(t: number) {
    for (const event of feed.events as FeedEvent[]) if (event.t <= t) send(event)
    now = feed.start_time + t
  }
  function staleManager(t = 30) {
    now += t
    const old = states.get('status:logger_status')!
    states.set(old.field, { ...old, ageS: t, freshness: 'STALE' })
  }
  return { ctx, adapter, at, send, staleManager, health }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('health logger adapter and route', () => {
  const HealthPage = healthModule.routes![0].Component
  it('maps all logger statuses and expands stderr wildcard fields', () => {
    const f = fakeContext()
    f.send({ t: 0, field: 'stderr:logger:extra', value: 'line' })
    f.send({ t: 1, field: 'status:logger_status', value: {
      run: { config: 'run', status: 'RUNNING' }, start: { config: 'start', status: 'STARTING' },
      fail: { config: 'fail', status: 'FAILED' }, off: { config: 'off', status: 'EXITED' },
    } })
    expect(f.health).toEqual(new Map([
      ['run', { health: 'OK', evidence: 'Logger manager reports RUNNING' }],
      ['start', { health: 'DEGRADED', evidence: 'Logger manager reports STARTING' }],
      ['fail', { health: 'FAILED', evidence: 'Logger manager reports FAILED' }],
      ['off', { health: 'UNKNOWN', evidence: 'Logger manager reports EXITED (Off)' }],
    ]))
    expect(f.adapter.fields(f.ctx)).toContain('stderr:logger:extra')
  })

  it('sorts flr1 first, gives the serial hint, and does not count rad1 Off as a fault', () => {
    const f = fakeContext(); f.at(240)
    render(<HealthPage ctx={f.ctx} />)
    const rows = screen.getAllByTestId('logger-row')
    expect(within(rows[0]).getByText('flr1')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/serial port/i)).toBeInTheDocument()
    expect(within(screen.getByTestId('logger-rad1')).getByText(/Off/, { selector: '.health-state' })).toBeInTheDocument()
    expect(screen.getByTestId('summary-failed')).toHaveTextContent('Failed 1')
  })

  it('shows knud1 DEGRADED then OK after its restart', () => {
    const f = fakeContext(); f.at(305)
    const view = render(<HealthPage ctx={f.ctx} />)
    expect(within(screen.getByTestId('logger-knud1')).getByText(/Check/, { selector: '.health-state' })).toBeInTheDocument()
    act(() => f.at(335)); view.rerender(<HealthPage ctx={f.ctx} />)
    expect(within(screen.getByTestId('logger-knud1')).getByText(/OK/, { selector: '.health-state' })).toBeInTheDocument()
  })

  it('shows the manager stale time instead of logger states', () => {
    const f = fakeContext(); f.at(10); f.staleManager()
    render(<HealthPage ctx={f.ctx} />)
    expect(screen.getByText(/Logger manager not reporting since .*UTC/)).toBeInTheDocument()
    expect(screen.queryByTestId('logger-row')).not.toBeInTheDocument()
  })

  it('shows manager status as missing when the latest snapshot is malformed', () => {
    const f = fakeContext(); f.at(10)
    f.send({ t: 11, field: 'status:logger_status', value: { mwx1: { config: 'mwx', status: 'BROKEN' } } })
    render(<HealthPage ctx={f.ctx} />)
    expect(screen.getByText('Logger manager status missing from the latest report.')).toBeInTheDocument()
    expect(screen.queryByTestId('logger-row')).not.toBeInTheDocument()
    expect(screen.queryByText('No action needed.')).not.toBeInTheDocument()
  })

  it('uses first-match hint precedence and reports a bad override while using defaults', async () => {
    const hints = parseHints(`- match:\n    logger: "flr*"\n  hint: First\n- match:\n    stderr: "serial"\n  hint: Second\n`)
    expect(resolveHint(hints, 'flr1', 'serial stopped')).toBe('First')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, text: async () => 'not: [valid' }))
    const f = fakeContext(); f.at(240)
    render(<HealthPage ctx={f.ctx} />)
    expect(await screen.findByText(/Ship hint file is invalid.*defaults/i)).toBeInTheDocument()
    expect(screen.getByText(/serial port/i)).toBeInTheDocument()
  })

  it('renders stderr as literal text and reveals the full line on tap', async () => {
    const f = fakeContext(); f.at(0)
    const malicious = `<script>alert('no')</script>${'x'.repeat(140)}`
    act(() => f.send({ t: 1, field: 'stderr:logger:mwx1', value: malicious }))
    render(<HealthPage ctx={f.ctx} />)
    const button = within(screen.getByTestId('logger-mwx1')).getByRole('button')
    expect(button).toHaveTextContent('<script>')
    expect(document.querySelector('script')).toBeNull()
    act(() => button.click())
    expect(button).toHaveTextContent(malicious)
  })
})

it.each([
  ['malformed snapshot', { mwx1: { config: 'mwx', status: 'BROKEN' } }],
  ['omitted logger', { knud1: { config: 'science', status: 'STARTING' } }],
])('clears shared OK after a %s and restores it on a valid report', (_case, value) => {
  const f = fakeContext()
  const field = 'status:logger_status'
  const running = { mwx1: { config: 'mwx', status: 'RUNNING' } }
  f.send({ t: 1, field, value: running })
  expect(f.health.get('mwx1')?.health).toBe('OK')
  f.send({ t: 2, field, value })
  expect(f.health.get('mwx1')?.health).toBe('UNKNOWN')
  f.send({ t: 3, field, value: running })
  expect(f.health.get('mwx1')?.health).toBe('OK')
})
