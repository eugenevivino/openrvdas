import { expect, it } from 'vitest'
import { fieldData, mergeFieldSamples, qualityFromFlag } from './field-data'

it.each([
  [1, 'PASS'], [2, 'NOT EVALUATED'], [3, 'SUSPECT'], [4, 'FAIL'],
  [9, 'MISSING'], [undefined, 'NOT EVALUATED'], [7, 'NOT EVALUATED'],
])('maps quality flag %s to %s', (flag, expected) => {
  expect(qualityFromFlag(flag)).toBe(expected)
})

it('reports quality independently of freshness and annotates an asynchronously flagged reading', () => {
  const pass = mergeFieldSamples(undefined, [{ value: 12, timestamp: 100, receivedAt: 101 }],
    [{ value: 1, timestamp: 100, receivedAt: 101 }])
  expect(fieldData(pass, 1, 106)).toMatchObject({ quality: 'PASS', freshness: 'STALE', health: 'UNKNOWN', ai: 'NONE' })
  const suspect = mergeFieldSamples(pass, [{ value: 13, timestamp: 110, receivedAt: 111 }],
    [{ value: 3, timestamp: 111, receivedAt: 111 }])
  expect(fieldData(suspect, 1, 111)).toMatchObject({ quality: 'SUSPECT', freshness: 'LIVE', value: 13 })
  const unflagged = mergeFieldSamples(suspect, [{ value: 14, timestamp: 112, receivedAt: 112 }], [])
  expect(fieldData(unflagged, 1, 112).quality).toBe('NOT EVALUATED')
})

it('reports a missing quality flag even when the cache supplies no measurement', () => {
  const series = mergeFieldSamples(undefined, [], [{ value: 9, timestamp: 100, receivedAt: 101 }])
  expect(fieldData(series, 1, 101)).toMatchObject({ quality: 'MISSING', freshness: 'NO DATA' })
})

it('drops an expired last good reading when a FAIL arrives for its exact timestamp', () => {
  const good = { value: 12, timestamp: 100, receivedAt: 100 }
  const later = Array.from({ length: 22 }, (_, index) => ({
    value: null, timestamp: 101 + index, receivedAt: 101 + index,
  }))
  const original = mergeFieldSamples(undefined, [good, ...later], [])
  expect(original.recent).not.toContain(good)
  const unrelated = mergeFieldSamples(original, [], [{ value: 4, timestamp: 101, receivedAt: 130 }])
  expect(fieldData(unrelated, 1, 500).lastGood).toEqual(good)
  const failed = mergeFieldSamples(unrelated, [], [{ value: 4, timestamp: 100, receivedAt: 140 }])
  expect(fieldData(failed, 1, 500)).toMatchObject({ freshness: 'NO DATA', lastGood: undefined })
})
