import { afterEach, expect, it, vi } from 'vitest'
import { CdsClient, isStale } from './cds'

class MockSocket extends EventTarget {
  static sockets: MockSocket[] = []
  sent: unknown[] = []
  readonly url: string

  constructor(url: string) {
    super()
    this.url = url
    MockSocket.sockets.push(this)
  }

  send(message: string) {
    this.sent.push(JSON.parse(message))
  }

  open() {
    this.dispatchEvent(new Event('open'))
  }

  receive(message: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }))
  }

  close() {
    this.dispatchEvent(new Event('close'))
  }
}

afterEach(() => {
  MockSocket.sockets = []
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

it('requests visible fields and history, then acknowledges each batch', () => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  vi.setSystemTime(1_005_000)
  const client = new CdsClient('ws://ship:8766')
  client.setFields({ Depth: 120, Wind: -1 })
  const [socket] = MockSocket.sockets
  socket.open()
  expect(socket.url).toBe('ws://ship:8766')
  expect(socket.sent).toEqual([{ type: 'subscribe', fields: {
    Depth: { seconds: 120, back_records: 1 }, Wind: { seconds: -1 },
  } }])
  socket.receive({ type: 'subscribe', status: 200 })
  socket.receive({ type: 'data', status: 200, data: {
    Depth: [[1003, 22], [1005, 24], [1004, 23]], OffPage: [[1005, 99]],
  } })
  expect(socket.sent.slice(1)).toEqual([{ type: 'ready' }, { type: 'ready' }])
  expect(client.getSnapshot().fields.get('Depth')).toEqual({ value: 24, timestamp: 1005 })
  expect(client.getSnapshot().fields.has('OffPage')).toBe(false)
  client.setFields({ Wind: -1 })
  socket.receive({ type: 'data', status: 200, data: { Depth: [[1005, 24]] } })
  expect(socket.sent.at(-1)).toEqual({ type: 'subscribe', fields: { Wind: { seconds: -1 } } })
  expect(client.getSnapshot().fields.has('Depth')).toBe(false)
  expect(MockSocket.sockets).toHaveLength(1)
  client.stop()
})

it('reconnects with backoff and resubscribes the current page', () => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const client = new CdsClient('ws://ship:8766')
  client.setFields({ Depth: -1 })
  MockSocket.sockets[0].close()
  expect(client.getSnapshot().connection).toBe('reconnecting')
  vi.advanceTimersByTime(1000)
  MockSocket.sockets[1].close()
  vi.advanceTimersByTime(1000)
  expect(MockSocket.sockets).toHaveLength(2)
  vi.advanceTimersByTime(1000)
  const next = MockSocket.sockets[2]
  next.open()
  expect(next.sent[0]).toEqual({ type: 'subscribe', fields: { Depth: { seconds: -1 } } })
  client.stop()
  vi.runOnlyPendingTimers()
  expect(MockSocket.sockets).toHaveLength(3)
})

it('marks a field stale strictly after 30 seconds by default', () => {
  expect(isStale(100, 130)).toBe(false)
  expect(isStale(100, 130.001)).toBe(true)
  expect(isStale(100, 106, 5)).toBe(true)
})
