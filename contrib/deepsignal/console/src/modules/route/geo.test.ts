// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { bearingDeg, crossTrackM, distanceM } from './geo'

describe('spherical route geometry', () => {
  it.each([
    ['equator', 0, 0, 0, 1, '111195.08', '90.0000'],
    ['Cornwall to Scotland', 50.0359, -5.4253, 58.3838, -3.0412, '940948.93', '8.5220'],
    ['Pacific crossing', 32.7, -117.2, 21.3, -157.9, '4198112.76', '262.8775'],
    ['antimeridian', 10, 179.5, 10, -179.5, '109505.74', '89.9132'],
  ] as const)('%s distance and initial bearing', (_, lat1, lon1, lat2, lon2, distance, bearing) => {
    const start = { lat: lat1, lon: lon1 }
    const end = { lat: lat2, lon: lon2 }
    expect(distanceM(start, end).toFixed(2)).toBe(distance)
    expect(bearingDeg(start, end).toFixed(4)).toBe(bearing)
  })

  it('normalizes north and west bearings', () => {
    const start = { lat: 0, lon: 0 }
    expect(bearingDeg(start, { lat: 1, lon: 0 })).toBe(0)
    expect(bearingDeg(start, { lat: 0, lon: -1 })).toBe(270)
  })

  it.each([['port', 0.01, '-1111.95'], ['starboard', -0.01, '1111.95']] as const)(
    'signs %s cross-track distance', (_, lat, expected) => {
      expect(crossTrackM({ lat: 0, lon: 0 }, { lat: 0, lon: 1 }, { lat, lon: 0.5 })
        .toFixed(2)).toBe(expected)
    })
})
