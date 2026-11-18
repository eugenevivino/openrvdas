import { vi } from 'vitest'
import type { ConsoleContext, FieldState, Lighting } from '../../contract'
import fakeFeed from '../../contract/fake-feed.json'

export function makeContext(moduleConfig: Record<string, unknown> = {}) {
  let now = fakeFeed.start_time
  const firstValue = (field: string) => fakeFeed.events.find((event) => event.field === field)?.value
  const fields: Record<string, FieldState> = {
    S330Latitude: { field: 'S330Latitude', value: firstValue('S330Latitude'), freshness: 'LIVE', quality: 'PASS', health: 'OK' },
    S330Longitude: { field: 'S330Longitude', value: firstValue('S330Longitude'), freshness: 'LIVE', quality: 'PASS', health: 'OK' },
  }
  const subscribers = new Set<() => void>()
  const lightingSubscribers = new Set<() => void>()
  const lightingState: Lighting = { mode: 'day', dayMode: 'day', nightPalette: 'red', dim: 0.6 }
  const lighting = {
    get mode() { return lightingState.mode },
    set: vi.fn((patch: Partial<Lighting>) => { Object.assign(lightingState, patch); lightingSubscribers.forEach((cb) => cb()) }),
    manualSet(patch: Partial<Lighting>) { Object.assign(lightingState, patch); lightingSubscribers.forEach((cb) => cb()) },
  }
  const store = {
    fields,
    subscribed: [] as string[],
    connection: () => 'connected' as const,
    lastMessageAgeS: () => 0,
    listFields: () => Object.keys(fields),
    describe: (field: string) => fakeFeed.fields[field as keyof typeof fakeFeed.fields],
    get: (field: string) => fields[field] ?? { field, freshness: 'NO_DATA', quality: 'NOT_EVALUATED', health: 'UNKNOWN' },
    history: () => [],
    subscribe: (names: string[], cb: () => void) => { store.subscribed = names; subscribers.add(cb); return () => subscribers.delete(cb) },
    setHealth: () => undefined,
  }
  const route = { get: vi.fn(() => 'bridge'), go: vi.fn() }
  const ctx = {
    config: { ship: 'Test', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 0, qcSuffix: '_QC', nightPalette: 'red', modules: { 'kiosk-night': moduleConfig } },
    store,
    pages: { register: () => undefined, list: () => [] },
    alerts: { raise: () => undefined, clear: () => undefined, ack: () => undefined, list: () => [], subscribe: () => () => undefined },
    lighting: { get: () => lightingState, set: lighting.set, subscribe: (cb: () => void) => { lightingSubscribers.add(cb); return () => lightingSubscribers.delete(cb) } },
    clock: { now: () => now }, route,
  } as ConsoleContext
  return { ctx, store, lighting, route, clock: { step: (seconds: number) => { now += seconds } } }
}
