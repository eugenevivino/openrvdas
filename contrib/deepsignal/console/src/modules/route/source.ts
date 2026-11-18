import type { ConsoleContext } from '../../contract'
import { distanceM, type Point } from './geo'

export interface Station extends Point { name: string; remainingM: number }

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function coordinate(value: unknown, limit: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= limit
}

function parse(data: unknown): Station[] {
  const geometry = object(data) && data.type === 'Feature' ? data.geometry : data
  let rows: unknown[] = []
  if (Array.isArray(data)) {
    rows = data
  } else if (object(geometry) && geometry.type === 'LineString'
    && Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2) {
    rows = geometry.coordinates.map((pair, i) => Array.isArray(pair)
      ? { name: `Waypoint ${i + 1}`, lon: pair[0], lat: pair[1] } : null)
  }
  if (!rows.length) throw new Error('Expected at least one waypoint.')
  const stations = rows.map(row => {
    if (!object(row) || typeof row.name !== 'string' || !row.name.trim()
      || !coordinate(row.lat, 90) || !coordinate(row.lon, 180)) {
      throw new Error('Check waypoint names, latitudes and longitudes.')
    }
    return { name: row.name, lat: row.lat, lon: row.lon, remainingM: 0 }
  })
  for (let i = stations.length - 2; i >= 0; i--) {
    stations[i].remainingM = distanceM(stations[i], stations[i + 1]) + stations[i + 1].remainingM
  }
  return stations
}

async function readFile(file: string) {
  const base = new URL('.', document.baseURI)
  const url = new URL(file, base)
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname)) {
    throw new Error('Choose a route file in the console directory.')
  }
  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw new Error(`Could not load ${file}. Check the file name and connection.`, { cause })
  }
  if (!response.ok) throw new Error(`Could not load ${file}. Check the file name.`)
  try {
    return parse(await response.json())
  } catch (cause) {
    throw new Error(`Invalid route in ${file}. Check the file format and coordinates.`, { cause })
  }
}

interface Source {
  stations: Promise<Station[]>
  // Preserve arrivals when the watch changes pages. Different position feeds track independently.
  indices: Map<string, number>
}

const sources = new WeakMap<ConsoleContext, Map<string, Source>>()

export function routeSource(ctx: ConsoleContext, file: string): Source {
  const files = sources.get(ctx) ?? new Map<string, Source>()
  sources.set(ctx, files)
  let source = files.get(file)
  if (!source) {
    source = { stations: readFile(file), indices: new Map() }
    files.set(file, source)
  }
  return source
}
