// @vitest-environment jsdom

import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import feed from '../../contract/fake-feed.json'
import { makeFakeContext } from '../../testkit'
import module from './index'

const { setData } = vi.hoisted(() => ({ setData: vi.fn() }))
vi.mock('uplot', () => ({ default: class {
  setData = setData
  setScale() {}
  destroy() {}
} }))

afterEach(() => {
  cleanup()
  setData.mockClear()
  vi.unstubAllGlobals()
})

const tile = module.tiles![0]

function show(cfg: Record<string, unknown>) {
  const { ctx, stepClock } = makeFakeContext(feed)
  const settings = tile.validate({ type: 'number', ...cfg }, { file: 'test.yaml', tile: 1 })
  const view = render(<tile.Component cfg={settings} ctx={ctx} />)
  return { advance: (seconds: number) => act(() => stepClock(seconds)), view }
}

it('shows LIVE and SUSPECT independently for tsg_suspect and gives each badge a shape', () => {
  const { advance } = show({ field: 'TsgTemp', label: 'Sea temperature', unit: '°C', decimals: 2 })
  expect(within(screen.getByRole('group', { name: 'Data quality' })).getByText('PASS')).toBeTruthy()
  advance(400)
  const freshness = screen.getByRole('group', { name: 'Freshness' })
  const quality = screen.getByRole('group', { name: 'Data quality' })
  expect(freshness.textContent).toBe('LIVE')
  expect(freshness.querySelector('circle')).toBeTruthy()
  expect(quality.textContent).toBe('SUSPECT')
  expect(quality.querySelector('path')).toBeTruthy()
})

it('steps through flr1_fails and shows the last good value and time after the timeout', () => {
  const { advance, view } = show({ field: 'FlrChl', label: 'Chlorophyll', unit: 'µg/L', decimals: 3 })
  advance(231)
  expect(screen.getByText('AGING')).toBeTruthy()
  advance(9)
  expect(screen.getByText('STALE')).toBeTruthy()
  advance(290)
  expect(screen.getByText('NO DATA')).toBeTruthy()
  expect(view.container.querySelector('.value')?.textContent).toBe('—')
  expect(screen.getByText(/^Last: 0.837 µg\/L at/).querySelector('time')?.textContent)
    .toBe(new Date((feed.start_time + 227) * 1000).toISOString().slice(11, 19) + 'Z')
})

it('adds a per-period trend and a 16-point compass direction when configured', () => {
  const trend = show({ field: 'MwxAirTemp', label: 'Air temperature', unit: '°C', decimals: 3, trend: 1 })
  trend.advance(60)
  expect(screen.getByText(/Rising.*°C \/ 1 s/)).toBeTruthy()
  trend.advance(340)
  expect(screen.getByText(/Falling.*°C \/ 1 s/)).toBeTruthy()
  trend.view.unmount()

  const compass = show({ field: 'PortTrueWindDir', label: 'Wind direction', unit: '°', compass: true })
  compass.advance(400)
  expect(screen.getByText('NNW')).toBeTruthy()
})

it('shows LIVE and MISSING with a dash and leaves gaps in sparkline history', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const { ctx, stepClock } = makeFakeContext({
    start_time: 100,
    fields: { Temperature: {} },
    events: [
      { t: 0, field: 'Temperature', value: 18 },
      { t: 1, field: 'Temperature', value: 999 },
      { t: 2, field: 'Temperature', value: 19 },
      { t: 3, field: 'Temperature', value: 999 },
      { t: 1, field: 'Temperature_QA', value: 9 },
      { t: 3, field: 'Temperature_QA', value: 9 },
    ],
  }, { elapsedS: 3, config: { qcSuffix: '_QA' } })
  const cfg = tile.validate({ type: 'number', field: 'Temperature', label: 'Temperature', unit: '°C', sparkline: 1, trend: 1 },
    { file: 'test.yaml', tile: 1 })
  const view = render(<tile.Component cfg={cfg} ctx={ctx} />)
  expect(screen.getByText('LIVE')).toBeTruthy()
  expect(screen.getByText('MISSING')).toBeTruthy()
  expect.soft(view.container.querySelector('.value')?.textContent).toBe('—')
  expect.soft(setData).toHaveBeenLastCalledWith([[100, 101, 102, 103], [18, null, 19, null]], false)
  expect(view.container.querySelector('.number-trend')).toBeNull()
  act(() => stepClock(301))
  expect(screen.getByText(/Last: 19\.0 °C/)).toBeTruthy()
})
