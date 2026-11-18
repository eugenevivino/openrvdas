const radians = Math.PI / 180

/** NOAA fractional-year solar position, accurate to about 0.5 degrees. */
export function sunElevation(epochSeconds: number, latitude: number, longitude: number): number {
  const date = new Date(epochSeconds * 1000)
  const start = Date.UTC(date.getUTCFullYear(), 0, 0)
  const day = Math.floor((Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) - start) / 86_400_000)
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600
  const gamma = 2 * Math.PI / 365 * (day - 1 + (hour - 12) / 24)
  const equationOfTime = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
    - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma))
  const declination = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma)
    - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma)
    - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma)
  const solarMinutes = hour * 60 + equationOfTime + 4 * longitude
  const hourAngle = (solarMinutes / 4 - 180) * radians
  const latitudeRadians = latitude * radians
  const cosineZenith = Math.sin(latitudeRadians) * Math.sin(declination)
    + Math.cos(latitudeRadians) * Math.cos(declination) * Math.cos(hourAngle)
  return 90 - Math.acos(Math.max(-1, Math.min(1, cosineZenith))) / radians
}
