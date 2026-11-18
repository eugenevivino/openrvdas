export const TILE_SIZE = 256
export const MAX_LATITUDE = 85.05112878

export interface TimedSample<T = unknown> { time: number, value: T }

export function latLonToPixel(lat: number, lon: number, zoom: number): { x: number, y: number } {
  const size = TILE_SIZE * 2 ** zoom
  const safeLat = Math.max(-MAX_LATITUDE, Math.min(MAX_LATITUDE, lat))
  const sin = Math.sin(safeLat * Math.PI / 180)
  return {
    x: ((lon + 180) / 360) * size,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size,
  }
}

export function pixelToLatLon(x: number, y: number, zoom: number): { lat: number, lon: number } {
  const size = TILE_SIZE * 2 ** zoom
  const n = Math.PI - 2 * Math.PI * y / size
  return { lat: 180 / Math.PI * Math.atan(Math.sinh(n)), lon: x / size * 360 - 180 }
}

export function medianInterval(samples: Array<TimedSample>): number | undefined {
  const intervals = samples.slice(1).map((sample, index) => sample.time - samples[index].time).filter((value) => value > 0).sort((a, b) => a - b)
  if (!intervals.length) return undefined
  const middle = Math.floor(intervals.length / 2)
  return intervals.length % 2 ? intervals[middle] : (intervals[middle - 1] + intervals[middle]) / 2
}

export function splitAtGaps<T extends TimedSample>(samples: T[]): T[][] {
  if (!samples.length) return []
  const median = medianInterval(samples)
  const groups: T[][] = [[samples[0]]]
  for (let index = 1; index < samples.length; index += 1) {
    if (median !== undefined && samples[index].time - samples[index - 1].time > 3 * median) groups.push([])
    groups.at(-1)?.push(samples[index])
  }
  return groups
}
