import { mergeFieldSamples } from './field-data'
import type { FieldSamples, Reading } from './field-data'

type Connection = 'idle' | 'connecting' | 'connected' | 'reconnecting'

interface Snapshot {
  connection: Connection
  fields: ReadonlyMap<string, FieldSamples>
  history: ReadonlyMap<string, readonly Reading[]>
  lastData?: number
}

const responseTimeout = 15_000
const maxHistoryPoints = 10_000

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function readBatch(batch: Record<string, unknown>, field: string, now: number): Reading[] {
  const samples = Object.hasOwn(batch, field) ? batch[field] : undefined
  if (!Array.isArray(samples)) return []
  const readings: Reading[] = []
  for (const sample of samples) {
    if (!Array.isArray(sample) || sample.length !== 2) continue
    const [timestamp, rawValue] = sample as unknown[]
    if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0 || timestamp > now + 5) continue
    const value = typeof rawValue === 'number' && Number.isFinite(rawValue) ? rawValue : null
    readings.push({ timestamp, value, receivedAt: now })
  }
  return readings
}

export class CdsClient {
  private readonly url: string
  private readonly listeners = new Set<() => void>()
  private snapshot: Snapshot = { connection: 'idle', fields: new Map(), history: new Map() }
  private wanted = new Map<string, number>()
  private subscribed?: Map<string, number>
  private checkBackfill = false
  private phase: 'opening' | 'subscribe' | 'data' | 'idle' = 'idle'
  private socket?: WebSocket
  private retry?: ReturnType<typeof setTimeout>
  private watchdog?: ReturnType<typeof setTimeout>
  private failures = 0

  constructor(url: string) {
    this.url = url
  }

  getSnapshot = () => this.snapshot

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  setFields(fields: Record<string, number>) {
    const wanted = new Map(Object.entries(fields))
    if (wanted.size === this.wanted.size &&
        [...wanted].every(([field, seconds]) => this.wanted.get(field) === seconds)) return

    this.wanted = wanted
    this.update({
      fields: new Map([...this.snapshot.fields].filter(([field]) => wanted.has(field))),
      history: new Map([...this.snapshot.history].filter(([field]) => wanted.has(field))),
    })

    if (!wanted.size) {
      this.disconnect()
      this.update({ connection: 'idle' })
    } else if (this.socket && this.phase === 'idle') {
      this.sendSubscription()
    } else if (!this.socket && this.retry === undefined) {
      this.connect()
    }
  }

  stop() {
    this.wanted.clear()
    this.disconnect()
    this.update({ connection: 'idle', fields: new Map(), history: new Map(), lastData: undefined })
  }

  private update(changes: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, ...changes }
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
      if (this.socket === socket) this.sendSubscription()
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

  private sendSubscription(latest?: ReadonlySet<string>) {
    this.phase = 'subscribe'
    this.subscribed = this.wanted
    this.checkBackfill = latest === undefined
    const requested = new Map(this.wanted)
    for (const [field, seconds] of this.wanted) {
      const flag = field + '_QC'
      requested.set(flag, Math.max(requested.get(flag) ?? -1, seconds))
    }
    for (const field of latest ?? []) requested.set(field, -1)
    const fields = [...requested].map(([field, seconds]) => [field,
      seconds > 0 ? { seconds, back_records: 1 } : { seconds },
    ])
    this.send({ type: 'subscribe', fields: Object.fromEntries(fields) })
  }

  private requestNext() {
    if (this.wanted !== this.subscribed) {
      this.sendSubscription()
    } else {
      this.phase = 'data'
      this.send({ type: 'ready' })
    }
  }

  private receive(raw: unknown) {
    if (typeof raw !== 'string') return
    let message: unknown
    try {
      message = JSON.parse(raw)
    } catch {
      // This batch has been consumed. Some CDS versions emit non-JSON NaN values.
      if (this.phase === 'data') this.requestNext()
      return
    }
    if (!object(message)) return
    if (this.phase === 'subscribe' && message.type === 'subscribe') {
      if (message.status === 200) this.requestNext()
      else this.reconnect()
    } else if (this.phase === 'data' && message.type === 'data') {
      if (message.status !== 200 || !object(message.data)) {
        this.reconnect()
        return
      }
      const empty = this.accept(message.data)
      if (empty.size && this.wanted === this.subscribed) this.sendSubscription(empty)
      else this.requestNext()
    }
  }

  private accept(batch: Record<string, unknown>) {
    // Finish the previous request before subscribing on the same socket.
    // Discard its batch if the operator has moved to another page.
    const empty = new Set<string>()
    if (this.wanted !== this.subscribed) return empty
    const fields = new Map(this.snapshot.fields)
    const history = new Map(this.snapshot.history)
    const now = Date.now() / 1000
    let { lastData } = this.snapshot
    this.failures = 0
    for (const [field, seconds] of this.wanted) {
      const flags = readBatch(batch, field + '_QC', now)
      const readings = readBatch(batch, field, now)
      if (this.checkBackfill && seconds > 0 && !readings.length) {
        empty.add(field)
        if (!flags.length) empty.add(field + '_QC')
      }
      if (readings.length || flags.length) fields.set(field, mergeFieldSamples(fields.get(field), readings, flags))
      if (seconds > 0 && readings.length) {
        const recent = new Map((history.get(field) ?? []).map((point) => [point.timestamp, point]))
        for (const reading of readings) recent.set(reading.timestamp, reading)
        history.set(field, [...recent.values()].filter((point) => point.timestamp >= now - seconds)
          .sort((a, b) => a.timestamp - b.timestamp).slice(-maxHistoryPoints))
      }
      for (const { timestamp } of readings) lastData = Math.max(lastData ?? 0, timestamp)
    }
    this.checkBackfill = false
    this.update({ connection: 'connected', fields, history, lastData })
    return empty
  }
}
