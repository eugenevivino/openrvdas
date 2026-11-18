import feed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldState, Freshness } from '../../contract'

export function fakeContext(options: { headingFreshness?: Freshness } = {}): ConsoleContext {
  const now = feed.start_time + 599
  const states = new Map<string, FieldState>()
  for (const [field, description] of Object.entries(feed.fields)) {
    const event = feed.events.findLast((item) => item.field === field && item.t <= 599)
    const freshness = field === 'S330HeadingTrue' ? (options.headingFreshness ?? 'LIVE') : 'LIVE'
    states.set(field, { field, value: event?.value, sourceTime: event ? feed.start_time + event.t : undefined,
      receiveTime: event ? feed.start_time + event.t : undefined, freshness, quality: 'NOT_EVALUATED',
      health: 'OK', lastGood: event ? { value: event.value, time: feed.start_time + event.t } : undefined })
    void description
  }
  const empty = (field: string): FieldState => ({ field, value: undefined, freshness: 'NO_DATA',
    quality: 'MISSING', health: 'UNKNOWN' })
  return {
    config: { ship: 'Test vessel', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 600,
      qcSuffix: '_QC', nightPalette: 'red', modules: {} },
    store: { connection: () => 'connected', lastMessageAgeS: () => 0,
      listFields: () => [...states.keys()], describe: (field) => feed.fields[field as keyof typeof feed.fields],
      get: (field) => states.get(field) ?? empty(field), history: () => [], subscribe: () => () => {},
      setHealth: () => {} },
    pages: { register: () => {}, list: () => [] },
    alerts: { raise: () => {}, clear: () => {}, ack: () => {}, list: () => [], subscribe: () => () => {} },
    lighting: { get: () => ({ mode: 'day', dayMode: 'day', nightPalette: 'red', dim: 1 }),
      set: () => {}, subscribe: () => () => {} },
    clock: { now: () => now }, route: { get: () => 'bridge', go: () => {} },
  }
}
