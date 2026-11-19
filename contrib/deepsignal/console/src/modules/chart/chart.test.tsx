// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import feed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldState } from '../../contract'
import chart, { buildChartData, parseWindow } from './index'

const plots: Array<{ redraw: ReturnType<typeof vi.fn>; setData: ReturnType<typeof vi.fn> }> = []
vi.mock('uplot', () => ({ default: class {
  redraw = vi.fn()
  setData = vi.fn()
  setScale = vi.fn()
  setSize = vi.fn()
  destroy = vi.fn()
  constructor() { plots.push(this) }
} }))

const events = feed.events as Array<{ t: number; field: string; value: unknown }>
const samples = (field: string) => events.filter((event) => event.field === field)
  .sort((a, b) => a.t - b.t).map((event) => ({ time: feed.start_time + event.t, value: event.value }))

function context(field: string, state: Partial<FieldState> = {}) {
  let storeListener: () => void = () => undefined
  let lightingListener: () => void = () => undefined
  const ctx = {
    config: { ship: 'test', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 21_600,
      qcSuffix: '_QC', nightPalette: 'red', modules: {} },
    store: {
      connection: () => 'connected', lastMessageAgeS: () => 0, listFields: () => [field],
      describe: () => feed.fields[field as keyof typeof feed.fields],
      history: (name: string) => samples(name), subscribe: (_fields: string[], cb: () => void) => { storeListener = cb; return () => undefined },
      get: () => ({ field, value: 19.8, sourceTime: feed.start_time + 599, receiveTime: feed.start_time + 599,
        freshness: 'LIVE', quality: 'PASS', health: 'OK', ...state }), setHealth: () => undefined,
    },
    lighting: { get: () => ({ mode: 'day', dayMode: 'day', nightPalette: 'red', dim: 1 }),
      set: () => undefined, subscribe: (cb: () => void) => { lightingListener = cb; return () => undefined } },
    clock: { now: () => feed.start_time + 600 }, pages: { register: () => undefined, list: () => [] },
    alerts: { raise: () => undefined, clear: () => undefined, ack: () => undefined, list: () => [], subscribe: () => () => undefined },
    route: { get: () => '', go: () => undefined },
  } as unknown as ConsoleContext
  return { ctx, emit: () => storeListener(), relight: () => lightingListener() }
}

describe('chart data', () => {
  it('inserts a gap for the knud1_restart interval', () => {
    const data = buildChartData(samples('Knud3Depth'), [])
    expect(data.values.some((value) => value === null)).toBe(true)
    expect(data.times[data.values.indexOf(null)]).toBeGreaterThan(feed.start_time + 298)
  })

  it('marks SUSPECT tsg_suspect samples with hollow markers', () => {
    const quality = samples('TsgTemp_QC').map((sample) => ({ time: sample.time, quality: sample.value === 3 ? 'SUSPECT' as const : 'PASS' as const }))
    const data = buildChartData(samples('TsgTemp'), quality)
    expect(data.markers[0]).toBe(feed.start_time + 400)
    expect(data.markers.at(-1)).toBe(feed.start_time + 599)
  })

  it('prepares four six-hour charts under 16 ms', () => {
    const sixHours = Array.from({ length: 21_600 }, (_, time) => ({ time, value: Math.sin(time) }))
    const start = performance.now()
    for (let chartNumber = 0; chartNumber < 4; chartNumber += 1) buildChartData(sixHours, [])
    expect(performance.now() - start).toBeLessThan(16)
  })
})

describe('chart tile', () => {
  it('shows NO DATA after flr1_fails', () => {
    const { ctx } = context('FlrChl', { freshness: 'NO_DATA', value: undefined, lastGood: { value: 0.8369, time: feed.start_time + 227 } })
    const Component = chart.tiles![0].Component
    render(<Component cfg={{ type: 'chart', field: 'FlrChl', label: 'Fluorescence', unit: 'ug/L', decimals: 3, window: '30 min' }} ctx={ctx} />)
    expect(screen.getAllByText('NO DATA').length).toBeGreaterThan(0)
  })

  it('redraws when lighting changes', () => {
    const { ctx, relight } = context('TsgTemp')
    const Component = chart.tiles![0].Component
    render(<Component cfg={{ type: 'chart', field: 'TsgTemp', label: 'Temperature', unit: 'degC', decimals: 2, window: '30 min' }} ctx={ctx} />)
    act(relight)
    expect(plots.at(-1)?.redraw).toHaveBeenCalled()
  })

  it('throws a PageProblem for a bad window', () => {
    expect(() => chart.tiles![0].validate({ type: 'chart', field: 'x', window: 'soon' }, { file: 'science.yaml', tile: 1 }))
      .toThrow(expect.objectContaining({ where: { file: 'science.yaml', tile: 1 }, setting: 'window', saw: 'soon' }))
    expect(parseWindow('6 h')).toBe(21_600)
  })
})

it('plots historical QARTOD 9 as a gap and masks a retained value at timeout', () => {
  const { ctx, emit } = context('TsgTemp')
  const now = ctx.clock.now()
  ctx.store.history = (field) => field.endsWith('_QC') ? [
    { time: now - 2, value: 1 }, { time: now - 1, value: 9 },
  ] : [{ time: now - 2, value: 18 }, { time: now - 1, value: 999 }, { time: now, value: 20 }]
  const get = ctx.store.get
  let expired = false
  ctx.store.get = (field) => expired
    ? { ...get(field), freshness: 'NO_DATA', lastGood: { value: 19.8, time: now - 301 } } : get(field)
  const tile = chart.tiles![0]
  const cfg = tile.validate({ type: 'chart', field: 'TsgTemp', label: 'Temperature', unit: 'degC', window: '30 min' },
    { file: 'science.yaml', tile: 1 })
  const view = render(<tile.Component cfg={cfg} ctx={ctx} />)
  expect.soft(plots.at(-1)?.setData).toHaveBeenLastCalledWith(
    [[now - 2, now - 1, now], [18, null, 20], [null, null, null]], false)
  expired = true
  act(emit)
  expect(view.container.querySelector('.chart-current strong')).toHaveTextContent('—')
  expect(screen.getByText(/Last: 19\.80 degC/)).toBeInTheDocument()
})
