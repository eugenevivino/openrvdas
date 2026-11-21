// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { DatasetPlot } from './DatasetPlot'

afterEach(cleanup)

it('plots only finite scalar observations while keeping nonfinite and missing classifications in the source', () => {
  const rows = Object.freeze([
    Object.freeze({ time: 5, value: 12, source_ref: 'record-5' }),
    Object.freeze({ time: 1, value: null, reason: 'missing' }),
    Object.freeze({ time: 2, value: NaN, reason: 'nonfinite' }),
    Object.freeze({ time: 3, value: Infinity, reason: 'nonfinite' }),
    Object.freeze({ time: 4, value: '12', reason: 'non-scalar' }),
    Object.freeze({ time: 0, value: 10, source_ref: 'record-0' }),
  ])
  render(<DatasetPlot datasetId="snapshot-1" rows={rows} unit="degC" start={0} end={6} cadenceS={1} timeBasis="seconds from fixture epoch" />)
  const chart = screen.getByRole('img')
  const points = chart.querySelectorAll('circle')
  expect(points).toHaveLength(2)
  expect(points[0].textContent).toBe('0: 10 degC · record-0')
  expect(points[1].textContent).toBe('5: 12 degC · record-5')
  expect(chart.querySelectorAll('path')).toHaveLength(0)
  expect(chart.outerHTML).not.toMatch(/(?:cx|cy)="(?:NaN|Infinity|-Infinity)"/)
  expect(screen.getByText(/Sorted by event time for presentation only/)).toBeInTheDocument()
  expect(rows.map((row) => row.time)).toEqual([5, 1, 2, 3, 4, 0])
  expect(rows[1].reason).toBe('missing')
  expect(Number.isNaN(rows[2].value)).toBe(true)
})

it('breaks a declared-cadence line at missing records and elapsed observation gaps', () => {
  render(<DatasetPlot datasetId="snapshot-gaps" rows={[
    { time: 0, value: 10 }, { time: 1, value: 11 },
    { time: 2, value: null, reason: 'missing' },
    { time: 3, value: 12 }, { time: 4, value: 13 },
    { time: 7, value: 14 }, { time: 8, value: 15 },
  ]} unit="degC" start={0} end={9} cadenceS={1} timeBasis="fixture seconds" />)
  const chart = screen.getByRole('img')
  const points = [...chart.querySelectorAll('circle')]
  const paths = [...chart.querySelectorAll('path')]
  expect(points).toHaveLength(6)
  expect(paths).toHaveLength(3)
  // Compare the displayed segment endpoints with their displayed observations:
  // no path may connect 1→3 across the missing value or 4→7 across the gap.
  const position = (point: Element) => `${point.getAttribute('cx')},${point.getAttribute('cy')}`
  expect(paths.map((path) => path.getAttribute('d'))).toEqual([
    `M${position(points[0])} L${position(points[1])}`,
    `M${position(points[2])} L${position(points[3])}`,
    `M${position(points[4])} L${position(points[5])}`,
  ])
  expect(screen.getByText(/declared 1 seconds/, { selector: 'p' })).toBeInTheDocument()
})

it('uses scatter points without invented continuity when cadence is unknown', () => {
  render(<DatasetPlot datasetId="snapshot-unknown" rows={[
    { time: 0, value: 10 }, { time: 1, value: 11 }, { time: 100, value: 12 },
  ]} unit={null} timeBasis="source UTC seconds" />)
  const chart = screen.getByRole('img')
  expect(chart.querySelectorAll('circle')).toHaveLength(3)
  expect(chart.querySelectorAll('path')).toHaveLength(0)
  expect(screen.getByText('Scatter plot only. No continuity or expected missing samples are inferred.')).toBeInTheDocument()
  expect(screen.getByText(/Value: unit unknown. Time: source UTC seconds/)).toBeInTheDocument()
})

it('keeps finite extreme values renderable and declines continuity for an invalid timestamp', () => {
  render(<DatasetPlot datasetId="snapshot-extremes" rows={[
    { time: 0, value: -1e308 }, { time: NaN, value: 2 }, { time: 1, value: 1e308 },
  ]} unit="declared scalar unit" cadenceS={1} />)
  const chart = screen.getByRole('img')
  expect(chart.querySelectorAll('circle')).toHaveLength(2)
  expect(chart.querySelectorAll('path')).toHaveLength(0)
  expect(chart.outerHTML).not.toMatch(/(?:cx|cy)="(?:NaN|Infinity|-Infinity)"/)
  expect(screen.getByText(/Invalid timestamps prevent continuity assessment/)).toBeInTheDocument()
})
