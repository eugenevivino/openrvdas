// @vitest-environment jsdom

import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import feed from '../../contract/fake-feed.json'
import { makeFakeContext } from '../../testkit'
import module from './index'

afterEach(cleanup)

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
