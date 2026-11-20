import type { Connection, FieldDescription } from './contract'
import { mergeFieldSamples, mergeReadings } from './field-data'
import type { FieldSamples, Reading } from './field-data'

export interface Snapshot {
  connection: Connection
  fields: ReadonlyMap<string, FieldSamples>
  history: ReadonlyMap<string, readonly Reading[]>
  available: readonly string[]
  descriptions: ReadonlyMap<string, FieldDescription>
  batch?: ReadonlyMap<string, readonly Reading[]>
  lastMessage?: number
}

interface CdsOptions {
  now?: () => number
  qcSuffix?: string
  catalog?: boolean
}

const responseTimeout = 15_000
const catalogPeriod = 15
const maxHistoryPoints = 10_000

function isMapping(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function parseResponse(raw: string, isDataBatch: boolean): unknown {
  try {
    return JSON.parse(raw)
  } catch (error) {
    if (!isDataBatch) throw error
    // Stock CDS uses Python's json.dumps, which emits non-finite numbers as bare tokens.
    // Match quoted strings first so field names and text values are preserved verbatim.
    const normalized = raw.replace(/"(?:[^"\\]|\\[\s\S])*"|([:[,]\s*)(?:NaN|-?Infinity)(?=\s*[,}\]])/g,
      (token: string, prefix: string | undefined) => prefix === undefined ? token : prefix + 'null')
    return JSON.parse(normalized)
  }
}

function readBatch(batch: Record<string, unknown>, field: string, now: number): Reading[] {
  const samples = Object.hasOwn(batch, field) ? batch[field] : undefined
  if (!Array.isArray(samples)) return []
  const readings: Reading[] = []
  for (const sample of samples) {
    if (!Array.isArray(sample) || sample.length !== 2) continue
    const [timestamp, value] = sample as unknown[]
    if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0 || timestamp > now + 5) continue
    readings.push({ timestamp, value, receivedAt: now })
  }
  return readings.sort((a, b) => a.timestamp - b.timestamp)
}

function readDescription(value: unknown): FieldDescription | undefined {
  if (!isMapping(value)) return undefined
  const description: FieldDescription = {}
  for (const key of ['units', 'description', 'device', 'logger'] as const) {
    if (typeof value[key] === 'string') description[key] = value[key]
  }
  return description
}

function sameRequests(a: ReadonlyMap<string, number>, b: ReadonlyMap<string, number> | undefined) {
  return a.size === b?.size && [...a].every(([field, seconds]) => b.get(field) === seconds)
}

function sameReading(a: Reading, b: Reading) {
  if (a.timestamp !== b.timestamp) return false
  if (a.value === b.value) return true
  return typeof a.value === 'object' && typeof b.value === 'object' &&
    JSON.stringify(a.value) === JSON.stringify(b.value)
}

export class CdsClient {
  private readonly url: string
  private readonly now: () => number
  private readonly qcSuffix: string
  private readonly catalog: boolean
  private readonly listeners = new Set<() => void>()
  private snapshot: Snapshot = {
    connection: 'idle', fields: new Map(), history: new Map(), available: [], descriptions: new Map(),
  }
  private wanted = new Map<string, number>()
  private subscribed?: Map<string, number>
  private checkBackfill = false
  private phase: 'opening' | 'fields' | 'describe' | 'subscribe' | 'data' | 'idle' = 'idle'
  private socket?: WebSocket
  private retry?: ReturnType<typeof setTimeout>
  private watchdog?: ReturnType<typeof setTimeout>
  private failures = 0
  private catalogAt = -Infinity

  constructor(url: string, { now = () => Date.now() / 1000, qcSuffix = '_QC', catalog = false }: CdsOptions = {}) {
    this.url = url
    this.now = now
    this.qcSuffix = qcSuffix
    this.catalog = catalog
  }

  getSnapshot = () => this.snapshot

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  start() {
    if (!this.socket && this.retry === undefined) this.connect()
  }

  setFields(fields: Record<string, number>) {
    const wanted = new Map(Object.entries(fields))
    if (sameRequests(wanted, this.wanted)) return

    this.wanted = wanted
    if (this.catalog) {
      const requested = this.requests()
      this.update({ fields: new Map([...this.snapshot.fields].filter(([field]) => requested.has(field))) })
      if (this.socket && this.phase === 'idle') this.requestNext()
      return
    }

    const requested = this.requests()
    this.update({
      fields: new Map([...this.snapshot.fields].filter(([field]) => wanted.has(field))),
      history: new Map([...this.snapshot.history].filter(([field]) => requested.has(field))),
    })
    if (!wanted.size) {
      this.disconnect()
      this.update({ connection: 'idle' })
    } else if (this.socket && this.phase === 'idle') {
      this.sendSubscription(this.requests())
    } else if (!this.socket && this.retry === undefined) {
      this.connect()
    }
  }

  refreshCatalog() {
    if (this.catalog && this.phase === 'idle' && this.socket && this.now() - this.catalogAt >= catalogPeriod) {
      this.requestCatalog()
    }
  }

  stop() {
    this.wanted.clear()
    this.disconnect()
    this.update({
      connection: 'idle', fields: new Map(), history: new Map(), available: [], descriptions: new Map(),
      lastMessage: undefined, batch: undefined,
    })
  }

  private update(changes: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, batch: undefined, ...changes }
    this.listeners.forEach((listener) => listener())
  }

  private connect() {
    this.phase = 'opening'
    this.update({ connection: this.failures ? 'reconnecting' : 'connecting' })
    let socket: WebSocket
    try {
      socket = new WebSocket(this.url)
    } catch {
      this.reconnect()
      return
    }
    this.socket = socket
    const retry = () => {
      if (this.socket === socket) this.reconnect()
    }
    socket.addEventListener('open', () => {
      if (this.socket !== socket) return
      if (this.catalog) this.requestCatalog()
      else this.sendSubscription(this.requests())
    })
    socket.addEventListener('close', retry)
    socket.addEventListener('error', retry)
    socket.addEventListener('message', (event: MessageEvent<unknown>) => {
      if (this.socket === socket) this.receive(event.data)
    })
    this.waitForResponse()
  }

  private disconnect() {
    const socket = this.socket
    this.socket = undefined
    this.subscribed = undefined
    this.phase = 'idle'
    clearTimeout(this.retry)
    clearTimeout(this.watchdog)
    this.retry = undefined
    socket?.close()
  }

  private reconnect() {
    this.disconnect()
    this.update({ connection: 'reconnecting' })
    const delay = 1000 * 2 ** Math.min(this.failures++, 5)
    this.retry = setTimeout(() => {
      this.retry = undefined
      this.connect()
    }, Math.min(delay, 30_000))
  }

  private waitForResponse() {
    clearTimeout(this.watchdog)
    this.watchdog = setTimeout(() => this.reconnect(), responseTimeout)
  }

  private send(message: object) {
    try {
      this.socket?.send(JSON.stringify(message))
      this.waitForResponse()
    } catch {
      this.reconnect()
    }
  }

  private requestCatalog() {
    this.phase = 'fields'
    this.send({ type: 'fields' })
  }

  private requests() {
    const requested = new Map<string, number>()
    const set = (field: string, seconds: number) => requested.set(field, Math.max(requested.get(field) ?? -1, seconds))
    for (const [field, seconds] of this.wanted) {
      if (field === 'status:*') {
        for (const name of this.snapshot.available) {
          if (name.startsWith('status:')) set(name, seconds)
        }
        continue
      }
      set(field, seconds)
      if (this.catalog && (field.startsWith('status:') || field.startsWith('stderr:logger:') ||
        field.endsWith(this.qcSuffix) ||
        field.includes(this.qcSuffix + '_'))) continue
      const flag = field + this.qcSuffix
      set(flag, seconds)
      for (const name of this.snapshot.available) {
        if (name.startsWith(flag + '_')) set(name, seconds)
      }
    }
    return requested
  }

  private sendSubscription(requested: Map<string, number>, latest?: ReadonlySet<string>) {
    this.phase = 'subscribe'
    this.subscribed = requested
    this.checkBackfill = latest === undefined
    const fields = [...requested].map(([field, window]) => {
      const seconds = latest?.has(field) ? -1 : window
      return [field, seconds > 0 ? { seconds, back_records: 1 } : { seconds }]
    })
    this.send({ type: 'subscribe', fields: Object.fromEntries(fields) })
  }

  private requestNext() {
    const requested = this.requests()
    if (!requested.size) {
      this.phase = 'idle'
      clearTimeout(this.watchdog)
    } else if (!sameRequests(requested, this.subscribed)) {
      this.sendSubscription(requested)
    } else if (this.catalog && this.now() - this.catalogAt >= catalogPeriod) {
      this.requestCatalog()
    } else {
      this.phase = 'data'
      this.send({ type: 'ready' })
    }
  }

  private receive(raw: unknown) {
    const now = this.now()
    if (typeof raw !== 'string') return
    let message: unknown
    try {
      message = parseResponse(raw, this.phase === 'data')
    } catch (error) {
      // A bad batch has still consumed the outstanding ready request.
      console.warn('Cannot read a cache response.', error)
      this.update({ lastMessage: now })
      if (this.phase === 'data') this.requestNext()
      return
    }
    if (!isMapping(message)) return
    if (this.phase === 'fields' && message.type === 'fields') {
      if (message.status !== 200 || !Array.isArray(message.data)) return this.reconnect()
      this.phase = 'describe'
      this.update({ available: message.data.filter((field): field is string => typeof field === 'string'), lastMessage: now })
      this.send({ type: 'describe' })
    } else if (this.phase === 'describe' && message.type === 'describe') {
      if (message.status !== 200 || !isMapping(message.data)) return this.reconnect()
      const descriptions = new Map<string, FieldDescription>()
      for (const [field, raw] of Object.entries(message.data)) {
        const description = readDescription(raw)
        if (description) descriptions.set(field, description)
      }
      this.catalogAt = now
      this.failures = 0
      this.update({ descriptions, lastMessage: now, connection: 'connected' })
      this.requestNext()
    } else if (this.phase === 'subscribe' && message.type === 'subscribe') {
      if (message.status !== 200) return this.reconnect()
      this.update({ lastMessage: now })
      this.requestNext()
    } else if (this.phase === 'data' && message.type === 'data') {
      if (message.status !== 200 || !isMapping(message.data)) return this.reconnect()
      const requested = this.requests()
      // Finish the previous request before resubscribing on the same socket.
      // Discard the old batch if the operator has moved to another page.
      if (!sameRequests(requested, this.subscribed)) {
        this.update({ lastMessage: now })
        this.requestNext()
        return
      }
      const empty = this.accept(message.data, requested, now)
      if (empty.size && sameRequests(requested, this.requests())) this.sendSubscription(requested, empty)
      else this.requestNext()
    }
  }

  private accept(batch: Record<string, unknown>, requested: ReadonlyMap<string, number>, now: number) {
    const empty = new Set<string>()
    const fields = new Map(this.snapshot.fields)
    const history = new Map(this.snapshot.history)
    const readings = new Map<string, Reading[]>()
    const changed = new Map<string, Reading[]>()
    const wanted = this.catalog ? requested : this.wanted

    for (const [field, seconds] of requested) {
      const incoming = readBatch(batch, field, now)
      readings.set(field, incoming)
      if (seconds > 0 && incoming.length) {
        const cutoff = now - seconds
        const recent = mergeReadings(history.get(field) ?? [], incoming)
        history.set(field, recent.filter((point) => point.timestamp >= cutoff).slice(-maxHistoryPoints))
      }
    }

    for (const [field, seconds] of wanted) {
      const incoming = readings.get(field) ?? []
      const flag = field + this.qcSuffix
      const flags = readings.get(flag) ?? []
      const explicitlyRequested = this.wanted.has(field) || (field.startsWith('status:') && this.wanted.has('status:*'))
      if (this.checkBackfill && seconds > 0 && !incoming.length && explicitlyRequested) {
        empty.add(field)
        if (!flags.length && requested.has(flag)) empty.add(flag)
      }
      const previous = fields.get(field)
      if (incoming.length || flags.length) {
        const points = seconds > 0 && requested.has(flag) ? history.get(field) : undefined
        fields.set(field, mergeFieldSamples(previous, incoming, flags,
          points && { points, flags: history.get(flag) ?? [], cutoff: now - seconds }))
      }
      const latest = previous?.recent.at(-1)
      const fresh = latest ? incoming.filter((reading) =>
        reading.timestamp >= latest.timestamp && !sameReading(latest, reading)) : incoming
      if (fresh.length) changed.set(field, fresh)
    }
    this.failures = 0
    this.checkBackfill = false
    this.update({ connection: 'connected', fields, history, batch: changed, lastMessage: now })
    return empty
  }
}
