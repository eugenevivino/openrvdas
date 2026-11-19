import { afterEach, expect, it, vi } from 'vitest'
import { CdsClient } from './cds'
import { ConsoleStore } from './store'

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
    this.receiveRaw(JSON.stringify(message))
  }

  receiveRaw(data: string) {
    this.dispatchEvent(new MessageEvent('message', { data }))
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

it('keeps readings and FAIL flags from a CDS batch containing non-finite numbers', () => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const client = new CdsClient('ws://ship:8766', { now: () => 1005 })
  client.setFields({ Depth: 60, Temperature: 60, Status: -1 })
  const [socket] = MockSocket.sockets
  try {
    socket.open()
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receiveRaw('{"type":"data","status":200,"data":{' +
      '"Depth":[[1004,20],[1005,21]],"Depth_QC":[[1005,4]],' +
      '"Temperature":[[1003,Infinity],[1004,-Infinity],[1005,NaN],[NaN,999]],' +
      '"Status":[[1005,{"NaN":"Keep [NaN], \\"Infinity\\" and -Infinity","nested":[NaN]}]]}}')
    const { fields, history } = client.getSnapshot()
    expect(fields.get('Depth')).toMatchObject({ quality: 'FAIL', lastGood: { value: 20, timestamp: 1004 } })
    expect(history.get('Temperature')?.map(({ value }) => value)).toEqual([null, null, null])
    expect(fields.get('Temperature')?.lastGood).toBeUndefined()
    expect(fields.get('Status')?.recent.at(-1)?.value).toEqual({
      NaN: 'Keep [NaN], "Infinity" and -Infinity', nested: [null],
    })
    expect(socket.sent.at(-1)).toEqual({ type: 'ready' })
  } finally {
    client.stop()
  }
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
    Depth: { seconds: 120, back_records: 1 }, Depth_QC: { seconds: 120, back_records: 1 },
    Wind: { seconds: -1 }, Wind_QC: { seconds: -1 },
  } }])
  socket.receive({ type: 'subscribe', status: 200 })
  socket.receive({ type: 'data', status: 200, data: {
    Depth: [[1003, 22], [1005, 24], [1004, 23]], Depth_QC: [[1005, 1]], OffPage: [[1005, 99]],
  } })
  expect(socket.sent.slice(1)).toEqual([{ type: 'ready' }, { type: 'ready' }])
  expect(client.getSnapshot().fields.get('Depth')?.recent.at(-1)).toEqual({ value: 24, timestamp: 1005, receivedAt: 1005 })
  expect(client.getSnapshot().fields.has('OffPage')).toBe(false)
  client.setFields({ Wind: -1 })
  socket.receive({ type: 'data', status: 200, data: { Depth: [[1005, 24]] } })
  expect(socket.sent.at(-1)).toEqual({ type: 'subscribe', fields: { Wind: { seconds: -1 }, Wind_QC: { seconds: -1 } } })
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
  expect(next.sent[0]).toEqual({ type: 'subscribe', fields: { Depth: { seconds: -1 }, Depth_QC: { seconds: -1 } } })
  client.stop()
  vi.runOnlyPendingTimers()
  expect(MockSocket.sockets).toHaveLength(3)
})

it('tries the latest value once when the initial history window is empty', () => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  vi.setSystemTime(1_005_000)
  const client = new CdsClient('ws://ship:8766')
  client.setFields({ Depth: 60 })
  const [socket] = MockSocket.sockets
  socket.open()
  socket.receive({ type: 'subscribe', status: 200 })
  socket.receive({ type: 'data', status: 200, data: {} })
  expect(socket.sent.at(-1)).toEqual({ type: 'subscribe', fields: {
    Depth: { seconds: -1 }, Depth_QC: { seconds: -1 },
  } })
  socket.receive({ type: 'subscribe', status: 200 })
  socket.receive({ type: 'data', status: 200, data: { Depth: [[900, 19]] } })
  expect(client.getSnapshot().fields.get('Depth')?.recent.at(-1)).toEqual({ value: 19, timestamp: 900, receivedAt: 1005 })
  socket.receive({ type: 'data', status: 200, data: {} })
  expect(socket.sent.at(-1)).toEqual({ type: 'ready' })
  expect(socket.sent.filter((request) => (request as { type: string }).type === 'subscribe')).toHaveLength(2)
  client.stop()
})

it.each([21, 25])('T-CON-1 keeps the prior usable reading after a late FAIL and %i newer samples', (count) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const client = new CdsClient('ws://ship:8766', { now: () => 1030 })
  client.setFields({ Depth: -1 })
  const [socket] = MockSocket.sockets
  try {
    socket.open()
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receive({ type: 'data', status: 200, data: {
      Depth: [[999, 19], [1000, 20]], Depth_QC: [[999, 1], [1000, 1]],
    } })
    for (let offset = 1; offset <= count; offset++) {
      socket.receive({ type: 'data', status: 200, data: { Depth: [[1000 + offset, null]] } })
    }
    const before = client.getSnapshot().fields.get('Depth')
    expect(before?.recent[0].timestamp).toBeGreaterThan(1000)
    expect(before?.lastGood).toMatchObject({ timestamp: 1000, value: 20 })

    const failTime = count === 21 ? 1000 : 1000.5
    socket.receive({ type: 'data', status: 200, data: { Depth_QC: [[failTime, 4]] } })

    expect(client.getSnapshot().fields.get('Depth')).toMatchObject({
      lastGood: { timestamp: 999, value: 19 }, quality: 'NOT EVALUATED',
    })
    socket.receive({ type: 'data', status: 200, data: { Depth: [[999.25, 19.5]] } })
    expect(client.getSnapshot().fields.get('Depth')?.lastGood).toMatchObject({ timestamp: 999.25, value: 19.5 })

    socket.receive({ type: 'data', status: 200, data: { Depth: [[1026, 22]], Depth_QC: [[999, 4], [1026, 1]] } })
    expect(client.getSnapshot().fields.get('Depth')).toMatchObject({
      lastGood: { timestamp: 1026, value: 22 }, quality: 'PASS',
    })
  } finally {
    client.stop()
  }
})

it.each([
  { period: 30, age: 20 },
  { period: 60, age: 35 },
])('T-CON-2 restores a learned $period-second cadence on page return', ({ period, age }) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  let now = 1100
  const sourceTime = now - age
  const store = new ConsoleStore({ websocket: 'ws://ship:8766', historyS: 0, qcSuffix: '_QC' }, { now: () => now })
  const depthPage = new Map([['Depth', {}]])
  store.select(depthPage)
  store.start()
  const [socket] = MockSocket.sockets
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: ['Depth', 'Depth_QC', 'Wind', 'Wind_QC'] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receive({ type: 'data', status: 200, data: { Depth: [[sourceTime - period, 19], [sourceTime, 20]] } })
    expect(store.get('Depth')).toMatchObject({ periodS: period, ageS: age, freshness: 'LIVE' })

    store.select(new Map([['Wind', {}]]))
    socket.receive({ type: 'data', status: 200, data: {} })
    expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe', fields: { Wind: { seconds: -1 } } })
    socket.receive({ type: 'subscribe', status: 200 })
    expect(store.get('Depth').sourceTime).toBeUndefined()

    store.select(depthPage)
    socket.receive({ type: 'data', status: 200, data: { Wind: [[now, 5]] } })
    expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe', fields: { Depth: { seconds: -1 } } })
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receive({ type: 'data', status: 200, data: { Depth: [[sourceTime, 20]] } })

    expect(store.get('Depth')).toMatchObject({ value: 20, sourceTime, ageS: age, periodS: period, freshness: 'LIVE' })
    now = sourceTime + period * 3
    expect(store.get('Depth')).toMatchObject({ ageS: period * 3, freshness: 'AGING' })
    now = sourceTime + period * 6
    expect(store.get('Depth')).toMatchObject({ ageS: period * 6, freshness: 'STALE' })
    now = sourceTime + period * 61
    expect(store.get('Depth')).toMatchObject({ ageS: period * 61, freshness: 'NO_DATA' })
  } finally {
    store.stop()
  }
})
