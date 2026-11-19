// DeepSignal Console plugin contract (types only, no logic).
// Owned by console-core. Module tasks import from here and never edit it.
// See ../../CONTRACT.md for the rules that go with these types.
import type { FC } from 'react'

// ---------- data from the CachedDataServer ----------
export type Freshness = 'LIVE' | 'AGING' | 'STALE' | 'NO_DATA'
export type Quality = 'PASS' | 'NOT_EVALUATED' | 'SUSPECT' | 'FAIL' | 'MISSING'
export type Health = 'OK' | 'DEGRADED' | 'FAILED' | 'UNKNOWN'
export type Connection = 'idle' | 'connecting' | 'connected' | 'reconnecting'

/** QARTOD primary flag values as published in <field><qc_suffix>. */
export const QARTOD_FLAG: Readonly<Record<number, Quality>> = {
  1: 'PASS',
  2: 'NOT_EVALUATED',
  3: 'SUSPECT',
  4: 'FAIL',
  9: 'MISSING',
}

export interface FieldDescription {
  units?: string
  description?: string
  device?: string
  /** Logger that produces the field, when the cache or page file says so. */
  logger?: string
}

export interface FieldState {
  field: string
  /** Latest value as received. undefined when nothing was ever received. */
  value: unknown
  /** Timestamp carried by the record (seconds since epoch). */
  sourceTime?: number
  /** When the console received it (seconds since epoch). */
  receiveTime?: number
  /** Expected update period T in seconds (page file `period`, else median of last 20 intervals). */
  periodS?: number
  /** now - sourceTime, seconds. */
  ageS?: number
  freshness: Freshness
  /** Last valid value; always kept for STALE and NO_DATA. */
  lastGood?: { value: unknown; time: number }
  quality: Quality
  /** Per-test flags from <field><qc_suffix>_<test>. */
  qualityTests?: Record<string, number>
  /** Text from <field><qc_suffix>_reason. */
  qualityReason?: string
  health: Health
  healthEvidence?: string
}

export interface FieldStore {
  connection(): Connection
  /** Seconds since the last message of any kind from the cache, or undefined. */
  lastMessageAgeS(): number | undefined
  /** All field names the cache reports (the 'fields' request). */
  listFields(): string[]
  describe(field: string): FieldDescription | undefined
  get(field: string): FieldState
  /** Recent samples, oldest first, for charts. */
  history(field: string, seconds: number): Array<{ time: number; value: unknown }>
  /** Calls cb whenever any of the fields changes or freshness moves. Returns unsubscribe. */
  subscribe(fields: string[], cb: () => void): () => void
  /** Adapters set health for every field of a logger. */
  setHealth(selector: { logger: string }, health: Health, evidence?: string): void
}

// ---------- pages ----------
export interface PageWhere {
  /** Page file name, e.g. "bridge.yaml". */
  file: string
  /** 1-based tile number, when the problem is in a tile. */
  tile?: number
}

/** Thrown by TileDef.validate. Core turns it into the plain message format in CONTRACT.md. */
export interface PageProblem {
  where: PageWhere
  setting: string
  saw: string
  expected: string
  example: string
}

export interface TileConfig {
  type: string
  label?: string
  wide?: boolean
  [key: string]: unknown
}

export interface Page {
  id: string
  title: string
  /** Lower comes first in the tab bar. */
  order?: number
  /** Where it came from: 'file:<name>', 'preset:<module>', 'auto:<module>'. */
  source?: string
  tiles: TileConfig[]
}

// ---------- configuration and lighting ----------
export interface ConsoleConfig {
  ship: string
  shipTimezone: string
  websocket: string
  /** Page ids to show, in order; empty means all known pages. */
  pages: string[]
  historyS: number
  qcSuffix: string
  nightPalette: 'red' | 'neutral'
  /** Free-form settings for modules, keyed by module id. */
  modules: Record<string, Record<string, unknown>>
}

export type LightingMode = 'day' | 'dusk' | 'night'
export interface Lighting {
  mode: LightingMode
  /** Day mode to return to when Night is turned off. */
  dayMode: 'day' | 'dusk'
  nightPalette: 'red' | 'neutral'
  /** 0.15 to 1.0 */
  dim: number
}

// ---------- alerts ----------
export type AlertTier = 'A1' | 'A2' | 'A3' | 'A4'
export interface Alert {
  id: string
  tier: AlertTier
  title: string
  source: string
  consequence: string
  firstAction: string
  /** Seconds since epoch. */
  since: number
  acked?: boolean
  /** Alerts with the same groupKey show as one row with a count. */
  groupKey?: string
}

// ---------- the context every module receives ----------
export interface ConsoleContext {
  config: ConsoleConfig
  store: FieldStore
  pages: { register(page: Page): void; list(): Page[] }
  alerts: {
    raise(a: Alert): void
    clear(id: string): void
    ack(id: string): void
    list(): Alert[]
    subscribe(cb: () => void): () => void
  }
  lighting: { get(): Lighting; set(p: Partial<Lighting>): void; subscribe(cb: () => void): () => void }
  /** Seconds since epoch. Tests inject a fake. Never use Date.now() in modules. */
  clock: { now(): number }
  /** Current route id (page id or route id). */
  route: { get(): string; go(id: string): void }
}

// ---------- plugin interfaces ----------
export interface TileDef {
  type: string
  /** Throws a PageProblem when the raw tile is wrong. */
  validate(raw: Record<string, unknown>, where: PageWhere): TileConfig
  fields(cfg: TileConfig, ctx: ConsoleContext): string[]
  Component: FC<{ cfg: TileConfig; ctx: ConsoleContext }>
}
export interface RouteDef {
  id: string
  title: string
  order: number
  Component: FC<{ ctx: ConsoleContext }>
  fields?(ctx: ConsoleContext): string[]
}
export interface PresetDef {
  id: string
  /** Page file text (YAML), usually imported with ?raw. */
  yaml: string
}
export interface EngineDef {
  id: string
  /** Start background work; return a stop function. */
  start(ctx: ConsoleContext): () => void
}
export interface SlotDef {
  slot: 'topbar' | 'banner'
  order: number
  Component: FC<{ ctx: ConsoleContext }>
}
export interface AdapterDef {
  id: string
  /** Extra cache fields this adapter needs subscribed (e.g. 'status:logger_status'). */
  fields(ctx: ConsoleContext): string[]
  onValue(field: string, value: unknown, time: number, ctx: ConsoleContext): void
}

/** Default export of src/modules/<id>/index.ts */
export interface ConsoleModule {
  id: string
  tiles?: TileDef[]
  routes?: RouteDef[]
  presets?: PresetDef[]
  engines?: EngineDef[]
  slots?: SlotDef[]
  adapters?: AdapterDef[]
}
