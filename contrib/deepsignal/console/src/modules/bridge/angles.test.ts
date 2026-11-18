import { describe, expect, it } from 'vitest'
import { compassPoint, relativeAngle, relativeWind } from './angles'

describe('relativeAngle', () => {
  it.each([
    [0, 0, 0], [90, 0, 90], [180, 0, 180], [270, 0, -90],
    [359, 1, -2], [1, 359, 2],
  ])('puts wind %s relative to heading %s at %s', (wind, heading, expected) => {
    expect(relativeAngle(wind, heading)).toBe(expected)
  })

  it('names port and starboard sides', () => {
    expect(relativeWind(270, 0, 'LIVE')).toEqual({ angle: 90, side: 'port' })
    expect(relativeWind(90, 0, 'LIVE')).toEqual({ angle: 90, side: 'starboard' })
  })

  it.each([
    [348.74, 'NNW'], [348.75, 'N'], [11.24, 'N'], [11.25, 'NNE'],
    [33.75, 'NE'], [78.75, 'E'], [168.75, 'S'], [258.75, 'W'], [359.9, 'N'],
  ])('maps %s degrees to %s', (degrees, expected) => {
    expect(compassPoint(degrees)).toBe(expected)
  })

  it.each(['STALE', 'NO_DATA'] as const)('does not compute with a %s heading', (freshness) => {
    expect(relativeWind(90, 45, freshness)).toEqual({ reason: freshness })
  })
})
