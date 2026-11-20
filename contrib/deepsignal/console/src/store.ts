import { CdsClient } from './cds'
import { realClock } from './context'
import type { Snapshot } from './cds'
import type { ConsoleConfig, ConsoleContext, FieldState, FieldStore, Health } from './contract'
import { fieldData } from './field-data'
import type { Reading } from './field-data'

export interface FieldRequest {
  period?: number
  logger?: string
}

type StoreConfig = Pick<ConsoleConfig, 'websocket' | 'historyS' | 'qcSuffix'>
type Clock = ConsoleContext['clock']
type Source = Pick<CdsClient, 'getSnapshot' | 'subscribe' | 'start' | 'stop' | 'setFields' | 'refreshCatalog'>
type HealthState = Pick<FieldState, 'health' | 'healthEvidence'>

const unknownHealth: HealthState = { health: 'UNKNOWN' }

function notifySubscriber<Args extends unknown[]>(listener: (...args: Args) => void, ...args: Args) {
  try {
    listener(...args)
  } catch (error) {
    console.error('Console store subscriber failed.', error)
  }
}

export class ConsoleStore implements FieldStore {
  private readonly source: Source
  private readonly clock: Clock
  private readonly config: StoreConfig
  private selected: ReadonlyMap<string, FieldRequest> = new Map()
  private readonly preferences = new Map<string, FieldRequest>()
  private readonly learnedPeriods = new Map<string, number>()
  private readonly windows = new Map<string, number>()
  private readonly health = new Map<string, HealthState>()
  private readonly listeners = new Set<() => void>()
  private readonly valueListeners = new Set<(field: string, reading: Reading) => void>()
  private unlisten?: () => void
  private historyPending = false

  constructor(config: StoreConfig, clock = realClock, source?: Source) {
    this.config = config
    this.clock = clock
    this.source = source ?? new CdsClient(config.websocket, {
      now: clock.now, qcSuffix: config.qcSuffix, catalog: true,
    })
  }

  start() {
    if (this.unlisten) return
    this.unlisten = this.source.subscribe(() => {
      const { batch, fields } = this.source.getSnapshot()
      for (const [field, { learnedPeriod }] of fields) {
        if (learnedPeriod !== undefined) this.learnedPeriods.set(field, learnedPeriod)
      }
      for (const [field, readings] of batch ?? []) {
        for (const reading of readings) this.valueListeners.forEach((listener) => notifySubscriber(listener, field, reading))
      }
      this.notify()
    })
    this.requestFields()
    this.source.start()
  }

  stop() {
    this.unlisten?.()
    this.unlisten = undefined
    this.source.stop()
    this.notify()
  }

  select(fields: ReadonlyMap<string, FieldRequest>) {
    if (fields.size === this.selected.size && [...fields].every(([field, request]) =>
      this.selected.has(field) && this.selected.get(field)?.period === request.period &&
      this.selected.get(field)?.logger === request.logger)) return
    this.selected = fields
    for (const [field, request] of fields) this.preferences.set(field, request)
    this.requestFields()
    this.notify()
  }

  tick() {
    this.source.refreshCatalog()
    this.notify()
  }

  observe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  observeValues(listener: (field: string, reading: Reading) => void) {
    this.valueListeners.add(listener)
    return () => { this.valueListeners.delete(listener) }
  }

  connection() {
    return this.source.getSnapshot().connection
  }

  lastMessageAgeS() {
    const lastMessage = this.source.getSnapshot().lastMessage
    return lastMessage === undefined ? undefined : Math.max(0, this.clock.now() - lastMessage)
  }

  listFields() {
    return [...this.source.getSnapshot().available]
  }

  describe(field: string) {
    const description = this.source.getSnapshot().descriptions.get(field)
    const logger = this.preferences.get(field)?.logger
    return logger ? { ...description, logger } : description
  }

  get(field: string): FieldState {
    const data = this.source.getSnapshot()
    const samples = data.fields.get(field)
    const period = this.preferences.get(field)?.period ?? samples?.learnedPeriod ?? this.learnedPeriods.get(field)
    const { value, timestamp, receivedAt, expectedPeriod, freshness, quality, age, lastGood, lastAccepted } =
      fieldData(samples, period, this.clock.now())
    const { qualityTests, qualityReason } = this.qualityDetails(data, field, timestamp)
    const reported = samples?.evidence.points.at(-1)
    const logger = this.describe(field)?.logger
    return {
      field, value: timestamp === undefined ? undefined : value,
      sourceTime: timestamp, receiveTime: receivedAt, periodS: expectedPeriod, ageS: age,
      freshness: freshness === 'NO DATA' ? 'NO_DATA' : freshness,
      lastGood: lastGood && { value: lastGood.value, time: lastGood.timestamp },
      lastAccepted: lastAccepted && { value: lastAccepted.value, time: lastAccepted.timestamp },
      lastReported: reported && { value: reported.value, time: reported.timestamp },
      quality: quality === 'NOT EVALUATED' ? 'NOT_EVALUATED' : quality, qualityTests, qualityReason,
      ...(this.health.get(logger ?? '') ?? unknownHealth),
    }
  }

  history(field: string, seconds: number) {
    if (!Number.isFinite(seconds) || seconds <= 0) return []
    if (seconds > Math.max(this.config.historyS, this.windows.get(field) ?? 0)) {
      this.windows.set(field, seconds)
      // History reads can occur during render. Update the cache request afterward.
      if (!this.historyPending) {
        this.historyPending = true
        queueMicrotask(() => {
          this.historyPending = false
          if (this.unlisten) this.requestFields()
        })
      }
    }
    const snapshot = this.source.getSnapshot()
    const start = this.clock.now() - seconds
    const readings = snapshot.history.get(field) ?? snapshot.fields.get(field)?.recent ?? []
    return readings.filter(({ timestamp }) => timestamp >= start).map(({ timestamp, value }) => ({ time: timestamp, value }))
  }

  subscribe(fields: string[], cb: () => void) {
    const stamp = () => fields.flatMap((field) => {
      const snapshot = this.source.getSnapshot()
      const state = this.get(field)
      return [snapshot.fields.get(field), snapshot.history.get(field), snapshot.descriptions.get(field),
        state.freshness, state.periodS, state.health, state.healthEvidence, state.qualityReason,
        ...Object.entries(state.qualityTests ?? {}).flat()]
    })
    let previous = stamp()
    return this.observe(() => {
      const next = stamp()
      if (previous.length === next.length && next.every((value, index) => Object.is(value, previous[index]))) return
      previous = next
      cb()
    })
  }

  setHealth({ logger }: { logger: string }, health: Health, healthEvidence?: string) {
    const previous = this.health.get(logger) ?? unknownHealth
    if (previous.health === health && previous.healthEvidence === healthEvidence) return
    this.health.set(logger, { health, healthEvidence })
    this.notify()
  }

  private notify() {
    this.listeners.forEach((listener) => notifySubscriber(listener))
  }

  private requestFields() {
    const fields = new Map<string, number>()
    for (const field of this.selected.keys()) {
      fields.set(field, Math.max(this.config.historyS, this.windows.get(field) ?? 0) || -1)
    }
    this.source.setFields(Object.fromEntries(fields))
  }

  private qualityDetails(snapshot: Snapshot, field: string, sourceTime: number | undefined) {
    const prefix = field + this.config.qcSuffix + '_'
    const tests: Array<[string, number]> = []
    let qualityReason: string | undefined
    for (const name of snapshot.available) {
      if (!name.startsWith(prefix)) continue
      const reading = snapshot.fields.get(name)?.recent.at(-1)
      if (!reading || (sourceTime !== undefined && reading.timestamp < sourceTime)) continue
      const key = name.slice(prefix.length)
      if (key === 'reason' && typeof reading.value === 'string') qualityReason = reading.value
      if (key !== 'reason' && typeof reading.value === 'number') tests.push([key, reading.value])
    }
    return { qualityTests: tests.length ? Object.fromEntries(tests) : undefined, qualityReason }
  }
}
