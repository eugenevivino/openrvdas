export interface Point { lat: number; lon: number }

export const METRES_PER_NM = 1852
const R = 6371008.8
const RAD = Math.PI / 180

export function distanceM(a: Point, b: Point) {
  const hav = Math.sin((b.lat - a.lat) * RAD / 2) ** 2
    + Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin((b.lon - a.lon) * RAD / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, hav)))
}

function bearingRad(a: Point, b: Point) {
  const phi1 = a.lat * RAD
  const phi2 = b.lat * RAD
  const delta = (b.lon - a.lon) * RAD
  return Math.atan2(Math.sin(delta) * Math.cos(phi2),
    Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(delta))
}

export function bearingDeg(a: Point, b: Point) {
  return (bearingRad(a, b) / RAD + 360) % 360
}

export function crossTrackM(start: Point, end: Point, position: Point) {
  const sine = Math.sin(distanceM(start, position) / R)
    * Math.sin(bearingRad(start, position) - bearingRad(start, end))
  return R * Math.asin(Math.max(-1, Math.min(1, sine)))
}

export function courseDifferenceDeg(bearing: number, course: number) {
  return Math.abs(((bearing - course % 360 + 540) % 360) - 180)
}

export function travelSeconds(metres: number, speedKnots: number) {
  return metres / (speedKnots * METRES_PER_NM / 3600)
}
