import type { ConsoleContext, ConsoleModule, FieldStore, Page, TileConfig } from '../../contract'
import { ruleMatches, rules, type Role } from './rules'

const SOURCE = 'auto:auto-pages'
const NOTE = 'Built from the fields this ship publishes. To change it, save a page file with id'
const SCIENCE_ROLES: Role[] = ['airTemperature', 'humidity', 'barometer', 'seaTemperature', 'salinity', 'fluorescence', 'depth']
const BRIDGE_ROLES: Role[] = ['heading', 'course', 'speedOverGround', 'latitude', 'longitude', 'trueWindSpeed', 'trueWindDirection', 'averagedWind']

interface AutoPage extends Page { note: string }
export interface Recognition { byRole: Partial<Record<Role, string>>; numeric: string[] }

export function recognizeFields(store: FieldStore): Recognition {
  const byRole: Partial<Record<Role, string>> = {}
  const numeric: string[] = []
  for (const field of store.listFields()) {
    const details = store.describe(field) ?? {}
    for (const rule of rules) {
      if (!ruleMatches(rule, field, details)) continue
      if (rule.role === 'numeric') numeric.push(field)
      else byRole[rule.role] ??= field
    }
  }
  return { byRole, numeric }
}

function tile(field: string, type: string, ctx: ConsoleContext, extra: Record<string, unknown> = {}): TileConfig {
  const details = ctx.store.describe(field)
  return { type, fallback: 'number', field, label: details?.description ?? field, unit: details?.units ?? 'unknown', ...extra }
}

function page(id: string, title: string, order: number, tiles: TileConfig[], suffix = ''): AutoPage {
  return { id, title, order, source: SOURCE, tiles, note: `${NOTE} ${id}.${suffix}` }
}

function isBlocked(ctx: ConsoleContext, id: string): boolean {
  return ctx.pages.list().some((known) => known.id === id && known.source !== SOURCE)
}

function generate(ctx: ConsoleContext): string[] {
  const found = recognizeFields(ctx.store)
  const { byRole } = found
  const shownFields: string[] = []
  const heading = byRole.heading
  const windSpeed = byRole.trueWindSpeed ?? byRole.averagedWind
  const windDirection = byRole.trueWindDirection
  const hasWind = Boolean(windSpeed || windDirection || byRole.averagedWind)

  if ((heading || hasWind) && !isBlocked(ctx, 'bridge-auto')) {
    const used = new Set<string>()
    const tiles: TileConfig[] = []
    if (heading && windSpeed) {
      tiles.push(tile(windSpeed, 'wind-dial', ctx, { headingField: heading, directionField: windDirection ?? windSpeed }))
      used.add(heading); used.add(windSpeed)
      if (windDirection) used.add(windDirection)
    }
    for (const role of BRIDGE_ROLES) {
      const field = byRole[role]
      if (field && !used.has(field)) { tiles.push(tile(field, 'number', ctx)); used.add(field) }
    }
    ctx.pages.register(page('bridge-auto', 'Bridge (auto)', 11, tiles))
    shownFields.push(...tiles.flatMap((item) => [item.field, item.headingField, item.directionField].filter((value): value is string => typeof value === 'string')))
  }

  const scienceTiles = SCIENCE_ROLES.flatMap((role) => byRole[role] ? [tile(byRole[role], 'chart', ctx)] : [])
  if (scienceTiles.length && !isBlocked(ctx, 'science-auto')) {
    ctx.pages.register(page('science-auto', 'Science (auto)', 21, scienceTiles))
    shownFields.push(...scienceTiles.map((item) => String(item.field)))
  }

  const sorted = found.numeric.sort((left, right) => {
    const logger = (field: string) => ctx.store.describe(field)?.logger ?? 'Other'
    return logger(left).localeCompare(logger(right)) || left.localeCompare(right)
  })
  const visible = sorted.slice(0, 200)
  if (visible.length && !isBlocked(ctx, 'all-fields')) {
    const omitted = sorted.length - visible.length
    ctx.pages.register(page('all-fields', 'All fields (auto)', 90,
      visible.map((field) => tile(field, 'number', ctx, { logger: ctx.store.describe(field)?.logger ?? 'Other' })),
      omitted ? ` and ${omitted} more` : ''))
    shownFields.push(...visible)
  }
  return [...new Set(shownFields)]
}

const engine = {
  id: 'auto-pages',
  start(ctx: ConsoleContext) {
    let unsubscribe = () => {}
    const refresh = () => {
      unsubscribe()
      const shownFields = generate(ctx)
      unsubscribe = ctx.store.subscribe(shownFields, refresh)
    }
    refresh()
    return () => unsubscribe()
  },
}

const autoPages: ConsoleModule = { id: 'auto-pages', engines: [engine] }
export default autoPages
