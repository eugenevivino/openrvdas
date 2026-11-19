import type { PageWhere, TileConfig } from '../../contract'
import { parsePage as parseRawPage } from '../../pages'
import { between, exactKeys, isBoolean, isPositive, isText, setting } from '../../settings'

export interface NumberTileConfig extends TileConfig {
  type: 'number'
  label: string
  field: string
  unit: string
  decimals: number
  sparkline?: number
  period?: number
  logger?: string
  trend?: number
  compass: boolean
  wide: boolean
}

const fieldPattern = /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/

export function validateNumber(raw: Record<string, unknown>, where: PageWhere): NumberTileConfig {
  // A fallback receives the original tile's settings as well as its own.
  if (raw.fallback !== 'number') exactKeys(raw, ['type', 'field', 'label', 'unit', 'decimals', 'sparkline', 'period', 'wide', 'logger',
    'trend', 'compass', 'fallback', 'stale_after'], where)
  const type = setting(where, raw, 'type', (value): value is 'number' => value === 'number',
    '"number"', 'type: number')
  const label = setting(where, raw, 'label', isText, 'a text label', 'label: Depth')
  const field = setting(where, raw, 'field', (value): value is string => typeof value === 'string' && fieldPattern.test(value),
    'an exact field name using letters, numbers, underscores, periods or hyphens', 'field: DepthMeters')
  const unit = setting(where, raw, 'unit', isText, 'a unit of measure', 'unit: m')
  const decimals = setting(where, raw, 'decimals', between(0, 8), 'a whole number from 0 to 8', 'decimals: 1', 1)
  const sparkline = Object.hasOwn(raw, 'sparkline')
    ? setting(where, raw, 'sparkline', between(1, 1440), 'whole minutes from 1 to 1440', 'sparkline: 5')
    : undefined
  const period = Object.hasOwn(raw, 'period')
    ? setting(where, raw, 'period', isPositive, 'a positive period in seconds', 'period: 2')
    : undefined
  const logger = Object.hasOwn(raw, 'logger')
    ? setting(where, raw, 'logger', isText, 'the name of a logger', 'logger: knud1')
    : undefined
  const trend = Object.hasOwn(raw, 'trend')
    ? setting(where, raw, 'trend', between(1, 1440), 'whole minutes from 1 to 1440', 'trend: 5')
    : undefined
  const compass = setting(where, raw, 'compass', isBoolean, 'true or false', 'compass: true', false)
  const wide = setting(where, raw, 'wide', isBoolean, 'true or false', 'wide: true', false)
  return { type, label, field, unit, decimals, sparkline, period, logger, trend, compass, wide }
}

// Supports callers of the standalone number-page parser.
export function parseNumberPage(file: string, text: string) {
  const page = parseRawPage(file, text)
  return { ...page, tiles: page.tiles.map((tile, index) => validateNumber(tile, { file, tile: index + 1 })) }
}
