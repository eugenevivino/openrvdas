import feed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldState } from '../../contract'

export const fields = {
  lat: 'S330Latitude', lon: 'S330Longitude', cog: 'S330CourseTrue', sog: 'S330SpeedKt',
}

export function fakeFeed() {
  let time = feed.start_time
  const states = new Map<string, FieldState>()
  const listeners = new Set<() => void>()
  function record(field: string, value: unknown) {
    states.set(field, {
      field, value, freshness: 'LIVE', ageS: 0, sourceTime: time,
      quality: 'NOT_EVALUATED', health: 'UNKNOWN',
    })
  }
  for (const event of feed.events) {
    if (event.t === 0) record(event.field, event.value)
  }
  const ctx: ConsoleContext = {
    config: { ship: 'Test', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 600,
      qcSuffix: '_QC', nightPalette: 'red', modules: {} },
    pages: { register() {}, list: () => [] },
    alerts: { raise() {}, clear() {}, ack() {}, list: () => [], subscribe: () => () => {} },
    lighting: { get: () => ({ mode: 'night', dayMode: 'day', nightPalette: 'red', dim: 0.6 }),
      set() {}, subscribe: () => () => {} },
    route: { get: () => 'stations', go() {} },
    clock: { now: () => time },
    store: {
      connection: () => 'connected', lastMessageAgeS: () => 0,
      listFields: () => [...states.keys()], describe: field => Object.entries(feed.fields).find(([key]) => key === field)?.[1],
      history: () => [], setHealth() {},
      get: field => states.get(field) ?? { field, value: undefined, freshness: 'NO_DATA',
        quality: 'NOT_EVALUATED', health: 'UNKNOWN' },
      subscribe: (_: string[], cb: () => void) => {
        listeners.add(cb)
        return () => listeners.delete(cb)
      },
    },
  }

  return {
    ctx,
    step(seconds: number, values: Partial<Record<keyof typeof fields, number>> = {}) {
      time += seconds
      for (const key of Object.keys(values) as (keyof typeof fields)[]) record(fields[key], values[key])
      listeners.forEach(cb => cb())
    },
    stale(key: keyof typeof fields, ageS: number) {
      const state = states.get(fields[key])!
      states.set(fields[key], { ...state, freshness: 'STALE', ageS, sourceTime: time - ageS })
      listeners.forEach(cb => cb())
    },
  }
}
