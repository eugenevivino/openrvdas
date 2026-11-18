import { describe, expect, it } from 'vitest'
import { sunElevation } from './sun'

describe('sunElevation', () => {
  it.each([
    ['San Diego solar noon', '2026-06-21T19:52:00Z', 32.7157, -117.1611, 80.7],
    ['San Diego sunset', '2026-06-22T02:59:00Z', 32.7157, -117.1611, -0.9],
    ['equator near the March equinox', '2026-03-20T12:07:00Z', 0, 0, 89.5],
    ['Tromso midnight sun', '2026-06-21T22:46:00Z', 69.6492, 18.9553, 3.1],
  ])('%s is within half a degree of the reference', (_name, iso, latitude, longitude, expected) => {
    expect(sunElevation(Date.parse(iso) / 1000, latitude, longitude)).toBeCloseTo(expected, 0)
  })
})
