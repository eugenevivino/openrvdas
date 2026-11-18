import type { ConsoleConfig, Page, TileConfig } from './contract'
import { between, exactKeys, isMapping, isPositive, isText, mapping, setting, yaml } from './settings'

const pageIdPattern = /^[a-z0-9][a-z0-9-]*$/

export function parsePage(file: string, text: string): Page {
  const values = mapping(yaml(text, file), file, 'page', 'title: Bridge')
  exactKeys(values, ['title', 'order', 'tiles'], file)
  const title = setting(file, values, 'title', isText, 'a page title', 'title: Bridge')
  const order = Object.hasOwn(values, 'order')
    ? setting(file, values, 'order', (value): value is number => typeof value === 'number' && Number.isFinite(value),
      'a number', 'order: 10')
    : undefined
  const tiles = setting(file, values, 'tiles', (value): value is TileConfig[] => Array.isArray(value),
    'a list of tiles', 'tiles: [{type: number, label: Depth, field: DepthMeters, unit: m}]')
  return { id: file.split('/').at(-1)!.replace(/\.yaml$/, ''), title, order, tiles }
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

export function parseConsole(text: string, location: Pick<Location, 'protocol' | 'host'>) {
  const file = 'console.yaml'
  const values = mapping(yaml(text, file), file, 'console', 'ship: R/V Example')
  exactKeys(values, ['ship', 'ship_timezone', 'websocket', 'pages', 'history', 'night_palette', 'qc_suffix',
    'modules', 'period', 'stale_after'], file)
  return {
    ship: setting(file, values, 'ship', isText, 'a ship name', 'ship: R/V Example'),
    ship_timezone: setting(file, values, 'ship_timezone', isTimeZone,
      'a time zone such as UTC or America/Santiago', 'ship_timezone: UTC', 'UTC'),
    websocket: setting(file, values, 'websocket', isWebSocketUrl,
      'a ws:// or wss:// address', 'websocket: ws://localhost:8766',
      `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/cds-ws`),
    pages: setting(file, values, 'pages', (value): value is string[] =>
      Array.isArray(value) && new Set(value).size === value.length &&
      value.every((id) => typeof id === 'string' && pageIdPattern.test(id)),
    'a list of unique page IDs using lowercase letters, numbers or hyphens', 'pages: [example]', []),
    history: setting(file, values, 'history', between(0, 86400),
      'whole seconds from 0 to 86400', 'history: 300', 0),
    night_palette: setting(file, values, 'night_palette',
      (value): value is ConsoleConfig['nightPalette'] => value === 'red' || value === 'neutral',
      'red or neutral', 'night_palette: red', 'red'),
    qc_suffix: setting(file, values, 'qc_suffix',
      (value): value is string => isText(value) && /^[A-Za-z0-9_.-]+$/.test(value),
      'a suffix using letters, numbers, underscores, periods or hyphens', 'qc_suffix: _QC', '_QC'),
    modules: setting(file, values, 'modules', (value): value is ConsoleConfig['modules'] =>
      isMapping(value) && Object.values(value).every(isMapping),
    'module ids with a group of settings for each', 'modules: {example: {}}', {}),
    period: setting(file, values, 'period', (value): value is Record<string, number> =>
      isMapping(value) && Object.values(value).every(isPositive),
    'fields with positive periods in seconds', 'period: {DepthMeters: 2}', {}),
  }
}

async function fetchFile(file: string, signal: AbortSignal, optional = false) {
  try {
    const response = await fetch('./' + file, { signal, cache: 'no-store' })
    // A static server can send the shell HTML for a missing optional asset.
    if (optional && (response.status === 404 ||
      (response.ok && response.headers.get('content-type')?.startsWith('text/html')))) return undefined
    if (!response.ok) throw new Error(`server response ${response.status}`)
    return await response.text()
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'could not load the file'
    throw new Error(`${file}: ${reason}. Check that the file is next to the console bundle.`, { cause: error })
  }
}

async function pageIds(signal: AbortSignal) {
  const manifest = await fetchFile('pages/index.json', signal, true)
  if (manifest === undefined) return []
  const ids: unknown = JSON.parse(manifest)
  if (!Array.isArray(ids) || !ids.every((id) => typeof id === 'string' && pageIdPattern.test(id))) {
    throw new Error('pages/index.json: Expected a list of page IDs. Example: ["bridge"]')
  }
  return ids as string[]
}

export async function loadConsole(signal: AbortSignal) {
  const raw = parseConsole((await fetchFile('console.yaml', signal))!, window.location)
  const config: ConsoleConfig = {
    ship: raw.ship, shipTimezone: raw.ship_timezone, websocket: raw.websocket, pages: raw.pages,
    historyS: raw.history, qcSuffix: raw.qc_suffix, nightPalette: raw.night_palette, modules: raw.modules,
  }
  const files = await Promise.all((config.pages.length ? config.pages : await pageIds(signal)).map(async (id) => {
    const file = `pages/${id}.yaml`
    try {
      const text = await fetchFile(file, signal, true)
      if (text === undefined) return undefined
      return { page: { ...parsePage(file, text), source: 'file:' + file } }
    } catch (error) {
      return { page: { id, title: id, source: 'file:' + file, tiles: [] } as Page,
        problem: error instanceof Error ? error.message : String(error) }
    }
  }))
  return { config, files: files.filter((file) => file !== undefined), periods: new Map(Object.entries(raw.period)) }
}

export type LoadedConsole = Awaited<ReturnType<typeof loadConsole>>
