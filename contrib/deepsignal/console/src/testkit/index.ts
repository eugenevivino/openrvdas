import type { Snapshot } from '../cds'
import type { ConsoleConfig, FieldDescription } from '../contract'
import feedFixture from '../contract/fake-feed.json'
import { createConsoleContext } from '../context'
import { mergeFieldSamples, mergeReadings } from '../field-data'
import type { FieldSamples, Reading } from '../field-data'
import { ConsoleStore } from '../store'
import type { FieldRequest } from '../store'

interface FakeFeed {
  start_time: number
  fields: Record<string, FieldDescription>
  events: Array<{ t: number; field: string; value: unknown }>
}

interface FakeOptions {
  config?: Partial<ConsoleConfig>
  elapsedS?: number
  fields?: ReadonlyMap<string, FieldRequest>
}

export function makeFakeContext(feed: FakeFeed = feedFixture, opts: FakeOptions = {}) {
  const config: ConsoleConfig = {
    ship: 'R/V Test', shipTimezone: 'UTC', websocket: 'ws://test:8766', pages: [],
    historyS: 0, qcSuffix: '_QC', nightPalette: 'red', modules: {}, ...opts.config,
  }
  let elapsed = 0
  let currentEvent = 0
  const events = [...feed.events].sort((a, b) => a.t - b.t)
  const available = [...new Set([...Object.keys(feed.fields), ...events.map(({ field }) => field)])]
  const listeners = new Set<() => void>()
  const sampleFields = new Map<string, FieldSamples>()
  const history = new Map<string, Reading[]>()
  let snapshot: Snapshot = {
    connection: 'connected', fields: sampleFields, history, available, descriptions: new Map(Object.entries(feed.fields)),
  }
  const clock = { now: () => feed.start_time + elapsed }
  const store = new ConsoleStore(config, clock, {
    getSnapshot: () => snapshot,
    subscribe: (callback) => {
      listeners.add(callback)
      return () => listeners.delete(callback)
    },
    start() {},
    stop() {},
    setFields() {},
    refreshCatalog() {},
  })
  if (opts.fields) store.select(opts.fields)
  store.start()
  const ctx = createConsoleContext(config, store, clock)

  function stepClock(seconds: number) {
    if (!Number.isFinite(seconds) || seconds < 0) throw new RangeError('The fake clock can only step forward.')
    elapsed += seconds
    const batch = new Map<string, Reading[]>()
    while (currentEvent < events.length && events[currentEvent].t <= elapsed) {
      const { t, field, value } = events[currentEvent++]
      const readings = batch.get(field) ?? []
      const timestamp = feed.start_time + t
      readings.push({ timestamp, value, receivedAt: timestamp })
      batch.set(field, readings)
    }
    const suffix = config.qcSuffix
    const fields = new Set([...batch.keys(), ...[...batch.keys()]
      .filter((field) => field.endsWith(suffix)).map((field) => field.slice(0, -suffix.length))])
    for (const field of fields) {
      const readings = batch.get(field) ?? []
      const flags = batch.get(field + suffix) ?? []
      sampleFields.set(field, mergeFieldSamples(sampleFields.get(field), readings, flags))
      if (readings.length) history.set(field, mergeReadings(history.get(field) ?? [], readings))
    }
    snapshot = { ...snapshot, batch, lastMessage: [...batch.values()].reduce((last, readings) =>
      Math.max(last ?? -Infinity, readings.at(-1)!.timestamp), snapshot.lastMessage) }
    listeners.forEach((cb) => cb())
  }

  stepClock(opts.elapsedS ?? 0)
  return { ctx, stepClock }
}
