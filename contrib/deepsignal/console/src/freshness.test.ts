import { expect, it } from 'vitest'
import { fieldData, mergeFieldSamples } from './field-data'

const reading = (timestamp: number, value: number | null = 12) => ({ timestamp, receivedAt: 140, value })

it('learns the median of the last 20 distinct source intervals', () => {
  const samples = [reading(10), ...Array.from({ length: 21 }, (_, i) => reading(100 + i * 2))]
  samples.push(reading(140, 13))
  const series = mergeFieldSamples(undefined, samples.reverse(), [])
  expect(fieldData(series, undefined, 141)).toMatchObject({
    expectedPeriod: 2, timestamp: 140, receivedAt: 140, freshness: 'LIVE',
  })
  expect(fieldData(series, 10, 160).expectedPeriod).toBe(10)
})

it('uses inclusive 2T and 5T boundaries and a hard timeout of at least 5 minutes', () => {
  const series = mergeFieldSamples(undefined, [reading(100)], [])
  for (const [period, now, freshness] of [
    [3, 106, 'LIVE'], [3, 106.001, 'AGING'], [3, 115, 'AGING'], [3, 115.001, 'STALE'],
    [3, 400, 'STALE'], [3, 400.001, 'NO DATA'], [10, 700, 'STALE'], [10, 700.001, 'NO DATA'],
  ] as const) {
    expect(fieldData(series, period, now).freshness).toBe(freshness)
  }
  expect(fieldData(undefined, 3, 100).freshness).toBe('NO DATA')
})

it('keeps the last good reading after a failure, missing values and the hard timeout', () => {
  const series = mergeFieldSamples(undefined, [reading(100), reading(101, 99)], [reading(101, 4)])
  const later = mergeFieldSamples(series, Array.from({ length: 25 }, (_, i) => reading(102 + i, null)), [])
  const afterMoreMissing = mergeFieldSamples(later, [reading(127, null)], [])
  expect(fieldData(afterMoreMissing, 1, 500)).toMatchObject({
    value: null, freshness: 'NO DATA', lastGood: reading(100),
  })
})
