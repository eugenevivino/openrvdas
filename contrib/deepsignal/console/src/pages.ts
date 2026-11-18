import { JSON_SCHEMA, load } from 'js-yaml'
import type { NightPalette } from './lighting-paint'

export interface NumberTileConfig {
  type: 'number'
  label: string
  field: string
  unit: string
  decimals: number
  sparkline?: number
  period?: number
  wide: boolean
}

export interface Page {
  id: string
  title: string
  tiles: NumberTileConfig[]
}

export interface ConsoleConfig {
  ship: string
  ship_timezone: string
  websocket: string
  pages: string[]
  history: number
  night_palette: NightPalette
}

const pageIdPattern = /^[a-z0-9][a-z0-9-]*$/
const fieldPattern = /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/

function describe(value: unknown): string {
  if (value === undefined) return 'nothing'
  if (Array.isArray(value)) return 'a list'
  if (value !== null && typeof value === 'object') return 'a group of settings'
  const text = JSON.stringify(value)
  return text.length > 120 ? text.slice(0, 117) + '…' : text
}

function invalid(location: string, key: string, value: unknown, expected: string, example: string): never {
  throw new Error(`${location}, ${key}: saw ${describe(value)}. Expected ${expected}. Example: ${example}`)
}

function mapping(value: unknown, location: string, key: string, example: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return invalid(location, key, value, 'a group of settings', example)
  }
  return value as Record<string, unknown>
}

function exactKeys(settings: Record<string, unknown>, allowed: string[], location: string) {
  for (const key of Object.keys(settings)) {
    if (!allowed.includes(key)) {
      invalid(location, key, settings[key], `one of these setting names: ${allowed.join(', ')}`, allowed[0])
    }
  }
}

function yaml(text: string, file: string): unknown {
  try {
    return load(text, { schema: JSON_SCHEMA, filename: file })
  } catch (error) {
    const reason = error instanceof Error ? error.message.split('\n')[0] : 'unreadable settings'
    throw new Error(`${file}: saw ${reason}. Expected valid YAML. Example: title: Bridge`)
  }
}

function setting<T>(location: string, values: Record<string, unknown>, key: string,
  check: (value: unknown) => value is T, expected: string, example: string, fallback?: T): T {
  const value = Object.hasOwn(values, key) ? values[key] : undefined
  if (value === undefined && fallback !== undefined) return fallback
  if (check(value)) return value
  return invalid(location, key, value, expected, example)
}

const isText = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean'
const between = (min: number, max: number) =>
  (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) &&
    value >= min && value <= max

function parseTile(raw: unknown, location: string): NumberTileConfig {
  const values = mapping(raw, location, 'tile', 'type: number')
  const type = setting(location, values, 'type', (value): value is 'number' => value === 'number',
    '"number"', 'type: number')
  // Accept settings files deployed with v1. Freshness uses period in v2.
  exactKeys(values, ['type', 'label', 'field', 'unit', 'decimals', 'sparkline', 'period', 'wide', 'stale_after'], location)
  const label = setting(location, values, 'label', isText, 'a text label', 'label: Depth')
  const field = setting(location, values, 'field', (value): value is string => isText(value) && fieldPattern.test(value),
    'an exact field name using letters, numbers, underscores, periods or hyphens', 'field: DepthMeters')
  const unit = setting(location, values, 'unit', isText, 'a unit of measure', 'unit: m')
  const decimals = setting(location, values, 'decimals', between(0, 8), 'a whole number from 0 to 8', 'decimals: 1', 1)
  const sparkline = Object.hasOwn(values, 'sparkline')
    ? setting(location, values, 'sparkline', between(1, 1440), 'whole minutes from 1 to 1440', 'sparkline: 5')
    : undefined
  const period = Object.hasOwn(values, 'period')
    ? setting(location, values, 'period', (value): value is number =>
      typeof value === 'number' && Number.isFinite(value) && value > 0,
    'a positive period in seconds', 'period: 2')
    : undefined
  const wide = setting(location, values, 'wide', isBoolean, 'true or false', 'wide: true', false)
  return { type, label, field, unit, decimals, sparkline, period, wide }
}

export function parsePage(file: string, text: string): Page {
  const values = mapping(yaml(text, file), file, 'page', 'title: Bridge')
  exactKeys(values, ['title', 'tiles'], file)
  const title = setting(file, values, 'title', isText, 'a page title', 'title: Bridge')
  const tiles = setting(file, values, 'tiles', (value): value is unknown[] => Array.isArray(value) && value.length > 0,
    'a list with at least one tile', 'tiles: [{type: number, label: Depth, field: DepthMeters, unit: m}]')
  return {
    id: file.split('/').at(-1)!.replace(/\.yaml$/, ''),
    title,
    tiles: tiles.map((tile, index) => parseTile(tile, `${file}, tile ${index + 1}`)),
  }
}

function isWebSocketUrl(value: unknown): value is string {
  if (!isText(value)) return false
  try {
    const url = new URL(value)
    return (url.protocol === 'ws:' || url.protocol === 'wss:') &&
      !url.username && !url.password && !url.href.includes('#')
  } catch {
    return false
  }
}

function isTimeZone(value: unknown): value is string {
  if (!isText(value)) return false
  try {
    new Intl.DateTimeFormat('en', { timeZone: value })
    return true
  } catch {
    return false
  }
}

export function parseConsole(text: string, host: string): ConsoleConfig {
  const file = 'console.yaml'
  const values = mapping(yaml(text, file), file, 'console', 'ship: R/V Example')
  exactKeys(values, ['ship', 'ship_timezone', 'websocket', 'pages', 'history', 'night_palette', 'stale_after'], file)
  return {
    ship: setting(file, values, 'ship', isText, 'a ship name', 'ship: R/V Example'),
    ship_timezone: setting(file, values, 'ship_timezone', isTimeZone,
      'a time zone such as UTC or America/Santiago', 'ship_timezone: UTC', 'UTC'),
    websocket: setting(file, values, 'websocket', isWebSocketUrl,
      'a ws:// or wss:// address', 'websocket: ws://localhost:8766', `ws://${host}:8766`),
    pages: setting(file, values, 'pages', (value): value is string[] =>
      Array.isArray(value) && value.length > 0 && new Set(value).size === value.length &&
      value.every((id) => typeof id === 'string' && pageIdPattern.test(id)),
    'a list of unique page IDs using lowercase letters, numbers or hyphens', 'pages: [example]'),
    history: setting(file, values, 'history', between(0, 86400),
      'whole seconds from 0 to 86400', 'history: 300', 0),
    night_palette: setting(file, values, 'night_palette',
      (value): value is NightPalette => value === 'red' || value === 'neutral',
      'red or neutral', 'night_palette: red', 'red'),
  }
}

async function fetchFile(file: string, signal: AbortSignal) {
  try {
    const response = await fetch('./' + file, { signal, cache: 'no-store' })
    if (!response.ok) throw new Error(`server response ${response.status}`)
    return await response.text()
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'could not load the file'
    throw new Error(`${file}: ${reason}. Check that the file is next to the console bundle.`)
  }
}

export async function loadConsole(signal: AbortSignal) {
  const config = parseConsole(await fetchFile('console.yaml', signal), window.location.hostname)
  const pages = await Promise.all(config.pages.map(async (id) => {
    const file = `pages/${id}.yaml`
    try {
      const page = parsePage(file, await fetchFile(file, signal))
      return { id, title: page.title, page }
    } catch (error) {
      return { id, title: id, error: error instanceof Error ? error.message : String(error) }
    }
  }))
  return { config, pages }
}

export type LoadedConsole = Awaited<ReturnType<typeof loadConsole>>
