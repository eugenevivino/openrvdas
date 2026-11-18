import type { Freshness } from '../../contract'

export function wrapAngle(degrees: number): number {
  return ((degrees % 360) + 360) % 360
}

/** Signed clockwise angle from the bow, in the range (-180, 180]. */
export function relativeAngle(direction: number, heading: number): number {
  const angle = wrapAngle(direction - heading)
  return angle > 180 ? angle - 360 : angle
}

const points = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'] as const

export function compassPoint(degrees: number): string {
  return points[Math.floor((wrapAngle(degrees) + 11.25) / 22.5) % points.length]
}

export type RelativeWind = { angle: number; side: 'port' | 'starboard' | 'ahead' | 'astern' } |
  { reason: 'STALE' | 'NO_DATA' }

export function relativeWind(direction: number, heading: number, freshness: Freshness): RelativeWind {
  if (freshness === 'STALE' || freshness === 'NO_DATA') return { reason: freshness }
  const signed = relativeAngle(direction, heading)
  const absolute = Math.abs(signed)
  if (absolute === 0) return { angle: 0, side: 'ahead' }
  if (absolute === 180) return { angle: 180, side: 'astern' }
  return { angle: absolute, side: signed < 0 ? 'port' : 'starboard' }
}
