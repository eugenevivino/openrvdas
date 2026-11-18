import { describe, expect, it } from 'vitest'
import { latLonToPixel, pixelToLatLon, splitAtGaps } from './mercator.ts'

describe('Web Mercator', () => {
  it.each([3, 8, 12])('round-trips latitude and longitude at zoom %i', (zoom) => {
    const pixel = latLonToPixel(32.418, -118.062, zoom)
    const position = pixelToLatLon(pixel.x, pixel.y, zoom)
    expect(position.lat).toBeCloseTo(32.418, 8)
    expect(position.lon).toBeCloseTo(-118.062, 8)
  })

  it('wraps the antimeridian into adjacent world pixels', () => {
    const east = latLonToPixel(0, 179.9, 3)
    const west = latLonToPixel(0, -179.9, 3)
    const world = 256 * 2 ** 3
    expect(Math.min(Math.abs(east.x - west.x), world - Math.abs(east.x - west.x))).toBeCloseTo(1.1378, 3)
  })

  it('splits samples at gaps greater than three median intervals', () => {
    const samples = [0, 1, 2, 10, 11].map((time) => ({ time, value: time }))
    expect(splitAtGaps(samples).map((part) => part.map((sample) => sample.time))).toEqual([[0, 1, 2], [10, 11]])
  })
})
