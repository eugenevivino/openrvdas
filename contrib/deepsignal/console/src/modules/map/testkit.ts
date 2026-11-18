import feed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldState } from '../../contract/index.ts'

export function fakeContext(options: { stalePosition?: boolean } = {}): ConsoleContext {
  const now = feed.start_time + 599
  const byField = new Map<string, Array<{ time: number, value: unknown }>>()
  for (const event of feed.events) {
    const samples = byField.get(event.field) ?? []
    samples.push({ time: feed.start_time + event.t, value: event.value })
    byField.set(event.field, samples)
  }
  const state = (field: string): FieldState => {
    const samples = byField.get(field) ?? []
    const latest = samples.at(-1)
    const stale = options.stalePosition && (field === 'S330Latitude' || field === 'S330Longitude')
    return { field, value: latest?.value, sourceTime: stale ? now - 120 : latest?.time, receiveTime: latest?.time,
      periodS: 1, ageS: stale ? 120 : latest ? now - latest.time : undefined,
      freshness: stale ? 'STALE' : latest ? 'LIVE' : 'NO_DATA', quality: 'PASS', health: 'OK' }
  }
  return {
    config: { ship: 'Test ship', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 7200, qcSuffix: '_QC', nightPalette: 'red', modules: {} },
    store: { connection: () => 'connected', lastMessageAgeS: () => 0, listFields: () => [...byField.keys()],
      describe: (field) => feed.fields[field as keyof typeof feed.fields], get: state,
      history: (field, seconds) => (byField.get(field) ?? []).filter((sample) => sample.time >= now - seconds),
      subscribe: () => () => {}, setHealth: () => {} },
    pages: { register: () => {}, list: () => [] },
    alerts: { raise: () => {}, clear: () => {}, ack: () => {}, list: () => [], subscribe: () => () => {} },
    lighting: { get: () => ({ mode: 'day', dayMode: 'day', nightPalette: 'red', dim: 1 }), set: () => {}, subscribe: () => () => {} },
    clock: { now: () => now }, route: { get: () => 'test', go: () => {} },
  }
}
