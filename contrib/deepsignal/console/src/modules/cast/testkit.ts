import fakeFeed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldDescription, FieldState } from '../../contract'

export interface CastTestContext {
  ctx: ConsoleContext
  set(field: string, value: unknown, options?: Partial<FieldState>): void
  step(seconds: number): void
}

export function makeCastContext(): CastTestContext {
  let now = fakeFeed.start_time
  const states = new Map<string, FieldState>()
  const histories = new Map<string, Array<{ time: number; value: unknown }>>()
  const subscribers = new Set<() => void>()
  const descriptions = fakeFeed.fields as Record<string, FieldDescription>
  const ctx = {
    config: {
      ship: 'Test ship', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 900,
      qcSuffix: '_QC', nightPalette: 'red' as const,
      modules: { cast: { wire_out: 'WireOut', wire_speed: 'WireSpeed', tension: 'Tension', ctd_depth: 'CtdDepth', altimeter: 'Altimeter', swl: 1000 } },
    },
    store: {
      connection: () => 'connected' as const,
      lastMessageAgeS: () => 0,
      listFields: () => [...states.keys()],
      describe: (field: string) => descriptions[field],
      get: (field: string) => states.get(field) ?? emptyState(field),
      history: (field: string, seconds: number) => (histories.get(field) ?? []).filter(sample => sample.time >= now - seconds),
      subscribe: (_fields: string[], cb: () => void) => { subscribers.add(cb); return () => subscribers.delete(cb) },
      setHealth: () => undefined,
    },
    pages: { register: () => undefined, list: () => [] },
    alerts: { raise: () => undefined, clear: () => undefined, ack: () => undefined, list: () => [], subscribe: () => () => undefined },
    lighting: { get: () => ({ mode: 'night' as const, dayMode: 'day' as const, nightPalette: 'red' as const, dim: 0.6 }), set: () => undefined, subscribe: () => () => undefined },
    clock: { now: () => now },
    route: { get: () => 'cast', go: () => undefined },
  } satisfies ConsoleContext
  return {
    ctx,
    set(field, value, options = {}) {
      const state: FieldState = { field, value, sourceTime: now, receiveTime: now, periodS: 1, ageS: 0, freshness: 'LIVE', quality: 'PASS', health: 'OK', ...options }
      states.set(field, state)
      histories.set(field, [...(histories.get(field) ?? []), { time: now, value }])
      subscribers.forEach(cb => cb())
    },
    step(seconds) { now += seconds },
  }
}

function emptyState(field: string): FieldState {
  return { field, value: undefined, freshness: 'NO_DATA', quality: 'MISSING', health: 'UNKNOWN' }
}
