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

it.each<{ period: number; samples: number; replay: boolean; correction?: string; unseen?: boolean; batched?: boolean; cachedHistory?: boolean; accelerating?: boolean; cachedReplay?: boolean }>([{ period: 1, samples: 21, replay: true }, { period: 2, samples: 21, replay: true },
  { period: 1, samples: 2, replay: false }, { period: 2, samples: 2, replay: false },
  { period: 1, samples: 2, replay: true, correction: 'FAILED' },
  { period: 2, samples: 2, replay: true, correction: 'OFF' },
  { period: 1, samples: 2, replay: false, unseen: true },
  { period: 2, samples: 2, replay: false, unseen: true },
  { period: 1, samples: 2, replay: false, batched: true },
  { period: 2, samples: 2, replay: false, batched: true },
  { period: 1, samples: 21, replay: false, cachedHistory: true },
  { period: 2, samples: 21, replay: false, cachedHistory: true },
  { period: 1, samples: 2, replay: false, accelerating: true },
  { period: 2, samples: 2, replay: false, accelerating: true },
  { period: 1, samples: 2, replay: false, cachedReplay: true },
  { period: 2, samples: 2, replay: false, cachedReplay: true }])(
  'retains a learned $period-second cadence after a delayed report on page return with $samples samples',
  ({ period, samples, replay, correction, unseen, batched, cachedHistory, accelerating, cachedReplay }) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  let now = 1_000
  const store = new ConsoleStore({ websocket: 'ws://ship:8766', historyS: cachedHistory || accelerating || cachedReplay ? 300 : 0, qcSuffix: '_QC' }, { now: () => now })
  const field = 'ds_chain:science:sensor'
  const page = new Map([[field, {}]])
  store.select(page)
  store.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: [field, field + '_QC', 'Wind', 'Wind_QC'] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receive({ type: 'data', status: 200, data: {
      [field]: cachedHistory ? [...Array.from({ length: 19 }, (_, i) => [1_000 - (38 - i) * period, 'OK']), [1_000 - 10 * period, 'OK'], [1_000, 'OK']] :
        Array.from({ length: samples }, (_, i) => [1_000 - (samples - 1 - i) * period * (accelerating ? 10 : 1), 'OK']),
    } })
    expect(store.get(field)).toMatchObject({ periodS: accelerating ? 10 * period : period, freshness: 'LIVE' })
    store.select(new Map([['Wind', {}]]))
    socket.receive({ type: 'data', status: 200, data: {} })
    socket.receive({ type: 'subscribe', status: 200 })
    expect(store.get(field).sourceTime).toBeUndefined()
    now = accelerating ? 1_000 + 0.5 * period : cachedReplay ? 1_000 + 9 * period :
      cachedHistory ? 1_000 + 28 * period : 1_000 + 30 * period - 1
    store.select(page)
    socket.receive({ type: 'data', status: 200, data: { Wind: [[now, 5]] } })
    socket.receive({ type: 'subscribe', status: 200 })
    if (now >= 1_015) {
      expect(socket.sent.at(-1)).toMatchObject({ type: 'fields' })
      socket.receive({ type: 'fields', status: 200, data: [field, field + '_QC', 'Wind', 'Wind_QC'] })
      socket.receive({ type: 'describe', status: 200, data: {} })
    }
    expect(socket.sent.at(-1)).toMatchObject({ type: 'ready' })
    if (cachedReplay) {
      socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000 - period, 'OK'], [1_000, 'OK'], [1_000 + 2 * period, 'OK'], [1_000 + 8 * period, 'OK'], [1_000 + period, 'OK']] } })
      now = 1_000 + 14 * period
      socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000 + 2 * period, 'OK'], [1_000 + 8 * period, 'OK'], [now, 'OK']] } })
      now += 7 * period
      expect(store.get(field)).toMatchObject({ periodS: period, freshness: 'STALE' })
      return
    }
    if (accelerating) {
      socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000 - 10 * period, 'OK'], [1_000, 'OK']] } })
      for (let i = 1; i <= 3; i++) {
        now = 1_000 + i * period
        socket.receive({ type: 'data', status: 200, data: { [field]: [[now, 'OK']] } })
      }
      now += 10 * period
      expect(store.get(field)).toMatchObject({ periodS: period, freshness: 'STALE' })
      return
    }
    if (cachedHistory) {
      now = 1_000 + 28 * period
      socket.receive({ type: 'data', status: 200, data: { [field]: Array.from({ length: 18 }, (_, i) => [1_000 + (i + 1) * period, 'OK']) } })
      expect(store.get(field)).toMatchObject({ periodS: period, freshness: 'STALE', ageS: 10 * period })
      return
    }
    if (replay) socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000, correction ?? 'OK']] } })
    if (unseen) socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000 + period, 'OK']] } })
    now = 1_000 + 30 * period
    socket.receive({ type: 'data', status: 200, data: { [field]: [...(batched ? [[1_000 + period, 'OK']] : []), [now, 'OK']] } })
    now += 10 * period
    expect(store.get(field)).toMatchObject({ periodS: period, freshness: 'STALE', ageS: 10 * period })
  } finally {
    store.stop()
  }
})

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
    expect(client.getSnapshot().history.size).toBe(0)

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

it('T-CON-14 keeps a matched FAIL across QC rollover and stops at the 10000-point measurement cap', () => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const start = 1000
  const count = 10_000
  const cap = 8640
  const failed = start + 1400
  const client = new CdsClient('ws://ship:8766', { now: () => start + count })
  client.setFields({ Depth: 10_800 })
  const [socket] = MockSocket.sockets
  const depths = Array.from({ length: count }, (_, i) => {
    const timestamp = start + i
    return [timestamp, i === 0 ? 18 : timestamp === failed ? 19 : null]
  })
  const flags = Array.from({ length: count }, (_, i) => [failed + 1 + i / 2, 1])
  const send = (data: object) => socket.receive({ type: 'data', status: 200, data })
  const subscribe = () => socket.receive({ type: 'subscribe', status: 200 })
  try {
    socket.open()
    subscribe()
    send({ Depth: depths.slice(0, cap), Depth_QC: [[start, 1], [failed, 4]] })
    send({ Depth: depths.slice(cap), Depth_QC: flags.slice(0, cap) })
    send({ Depth_QC: flags.slice(cap) })
    expect(client.getSnapshot().history.get('Depth')).toHaveLength(count)
    expect(client.getSnapshot().history.get('Depth_QC')?.[0].timestamp).toBeGreaterThan(failed)

    client.setFields({ Wind: -1 })
    send({})
    subscribe()
    expect(client.getSnapshot().fields.has('Depth')).toBe(false)
    client.setFields({ Depth: 10_800 })
    send({})
    subscribe()
    const returned = depths.slice(-cap)
    expect(returned).toContainEqual([failed, 19])
    send({ Depth: returned, Depth_QC: flags.slice(-cap) })
    expect(client.getSnapshot().fields.get('Depth')?.lastGood).toMatchObject({ timestamp: start, value: 18 })

    send({ Depth: [[start + count, null]] })
    expect(client.getSnapshot().fields.get('Depth')?.lastGood).toBeUndefined()
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


it.each([['timeout', 'port closed'], ['sync lost', 'reader stopped']])(
  'keeps latest logger error %s then %s across history replay', (first, last) => {
    vi.stubGlobal('WebSocket', MockSocket)
    vi.useFakeTimers()
    const field = 'stderr:logger:CTD'
    const store = new ConsoleStore({ websocket: 'ws://ship:8766', historyS: 300, qcSuffix: '_QC' }, { now: () => 1_001 })
    const values: unknown[] = []
    store.observeValues((name, reading) => { if (name === field) values.push(reading.value) })
    store.select(new Map([[field, {}]]))
    store.start()
    const socket = MockSocket.sockets[0]
    const batch = { [field]: [[1_000, first], [1_000, last]] }
    try {
      socket.open()
      socket.receive({ type: 'fields', status: 200, data: [field, 'Wind'] })
      socket.receive({ type: 'describe', status: 200, data: {} })
      socket.receive({ type: 'subscribe', status: 200 })
      socket.receive({ type: 'data', status: 200, data: batch })
      expect(values).toEqual([first, last])
      store.select(new Map([[field, {}], ['Wind', {}]]))
      socket.receive({ type: 'data', status: 200, data: {} })
      socket.receive({ type: 'subscribe', status: 200 })
      socket.receive({ type: 'data', status: 200, data: { ...batch, Wind: [[1_000, 5]] } })
      expect(store.get(field).value).toBe(last)
      expect(values).toEqual([first, last])
      socket.receive({ type: 'data', status: 200, data: batch })
      expect(values).toEqual([first, last, first, last])
    } finally {
      store.stop()
    }
  },
)


it.each([['timeout', 'port closed'], ['sync lost', 'reader stopped']])(
  'delivers new same-timestamp logger error after reconnect: %s then %s', (first, last) => {
    vi.stubGlobal('WebSocket', MockSocket)
    vi.useFakeTimers()
    const field = 'stderr:logger:CTD'
    const store = new ConsoleStore({ websocket: 'ws://ship:8766', historyS: 300, qcSuffix: '_QC' }, { now: () => 1_001 })
    const values: unknown[] = []
    store.observeValues((name, reading) => { if (name === field) values.push(reading.value) })
    store.select(new Map([[field, {}]]))
    store.start()
    const socket = MockSocket.sockets[0]
    try {
      socket.open()
      socket.receive({ type: 'fields', status: 200, data: [field, 'Wind'] })
      socket.receive({ type: 'describe', status: 200, data: {} })
      socket.receive({ type: 'subscribe', status: 200 })
      socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000, first]] } })
      store.select(new Map([[field, {}], ['Wind', {}]]))
      socket.receive({ type: 'data', status: 200, data: {} })
      socket.receive({ type: 'subscribe', status: 200 })
      socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000, first], [1_000, last]], Wind: [[1_000, 5]] } })
      expect(values).toEqual([first, last])
    } finally { store.stop() }
  },
)

it.each(['status:logger_status', 'status:logger_manager'])('requests explicit manager QC for %s', (field) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const client = new CdsClient('ws://ship:8766', { now: () => 1_000, catalog: true })
  client.setFields({ [field]: 0 })
  client.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: [field, field + '_QC'] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe', fields: { [field + '_QC']: { seconds: 0 } } })
  } finally { client.stop() }
})

it.each([{ count: 70, suffix: '_QC' }, { count: 90, suffix: '_QC' },
  { count: 60, suffix: '_QC_range' }, { count: 60, suffix: '_QC_reason' }])(
  'keeps a $count-measurement catalog with $suffix within the existing gateway limit', ({ count, suffix }) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const fields = [...new Set(Array.from({ length: count }, (_, n) => `Sensor${n}`).flatMap((name) => [name, name + '_QC', name + suffix]))]
  fields.push('status:logger_status', 'status:logger_manager')
  const client = new CdsClient('ws://ship:8766', { now: () => 1_000, catalog: true })
  client.setFields(Object.fromEntries(fields.map((field) => [field, 0])), new Set(fields))
  client.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: fields })
    socket.receive({ type: 'describe', status: 200, data: {} })
    const request = socket.sent.at(-1) as { fields: Record<string, unknown> }
    expect(Object.keys(request.fields).length).toBeLessThanOrEqual(200)
    expect(Object.keys(request.fields)).toEqual(expect.arrayContaining(fields))
  } finally { client.stop() }
})


it.each(['time', 'store'])('requests new stage QC despite a stream-name prefix with suffix %s', (suffix) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const field = `ds_chain:run${suffix}_aux:${suffix}`
  const client = new CdsClient('ws://ship:8766', { now: () => 1_000, catalog: true, qcSuffix: suffix })
  client.setFields({ [field]: 0 })
  client.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: ['ds_chain:run', field] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe', fields: { [field + suffix]: { seconds: 0 } } })
  } finally { client.stop() }
})


it.each([1, 2])('replaces an interval split by a late reading at scale %s', (scale) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  let now = 1_000
  const field = 'ds_chain:science:sensor'
  const store = new ConsoleStore({ websocket: 'ws://ship:8766', historyS: 300, qcSuffix: '_QC' }, { now: () => now })
  store.select(new Map([[field, {}]])); store.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: [field] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000, 'OK'], [1_000 - 10 * scale, 'OK']] } })
    now += scale
    socket.receive({ type: 'data', status: 200, data: { [field]: [[1_000, 'OK'], [1_000 - scale, 'OK'], [now, 'OK']] } })
    now += 6 * scale
    expect(store.get(field)).toMatchObject({ periodS: scale, freshness: 'STALE' })
  } finally { store.stop() }
})

it.each(['Depth', 'Frequency'])('requests first QC for actual measurement LF%s beside LF', (suffix) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const field = 'LF' + suffix
  const client = new CdsClient('ws://ship:8766', { now: () => 1_000, catalog: true, qcSuffix: suffix })
  client.setFields({ [field]: 0 }); client.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: ['LF', field] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    expect(socket.sent.at(-1)).toMatchObject({ type: 'subscribe', fields: { [field + suffix]: { seconds: 0 } } })
  } finally { client.stop() }
})


it.each([false, true])('changes QC demand for the same fields when raw mode starts as %s', (raw) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  const client = new CdsClient('ws://ship:8766', { now: () => 1_000, catalog: true })
  client.setFields({ Depth: 0 }, raw ? new Set(['Depth']) : new Set()); client.start()
  const socket = MockSocket.sockets[0]
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: ['Depth', 'Depth_QC'] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    const request = () => socket.sent.at(-1) as { type: string; fields: Record<string, unknown> }
    expect(request().type).toBe('subscribe')
    expect(Object.hasOwn(request().fields, 'Depth_QC')).toBe(!raw)
    socket.receive({ type: 'subscribe', status: 200 })
    socket.receive({ type: 'data', status: 200, data: { Depth: [[1_000, 20]] } })
    client.setFields({ Depth: 0 }, raw ? new Set() : new Set(['Depth']))
    socket.receive({ type: 'data', status: 200, data: {} })
    expect(request().type).toBe('subscribe')
    expect(Object.hasOwn(request().fields, 'Depth_QC')).toBe(raw)
  } finally { client.stop() }
})


it.each(['sensor', 'store'])('preserves accepted %s history while Self-test reads raw fields', (member) => {
  vi.stubGlobal('WebSocket', MockSocket)
  vi.useFakeTimers()
  let now = 1_000
  const field = `ds_chain:science:${member}`
  const store = new ConsoleStore({ websocket: 'ws://ship:8766', historyS: 0, qcSuffix: '_QC' }, { now: () => now })
  store.select(new Map([[field, {}]])); store.start()
  const socket = MockSocket.sockets[0]
  const data = (values: Record<string, unknown>) => socket.receive({ type: 'data', status: 200, data: values })
  try {
    socket.open()
    socket.receive({ type: 'fields', status: 200, data: [field] })
    socket.receive({ type: 'describe', status: 200, data: {} })
    socket.receive({ type: 'subscribe', status: 200 })
    data({ [field]: [[now, 'OFF']] })
    store.select(new Map([[field, { raw: true }]]))
    data({}); socket.receive({ type: 'subscribe', status: 200 })
    data({ [field]: [[now, 'OFF']] })
    now++; data({ [field]: [[now, 'DEGRADED']] })
    now++; data({ [field]: [[now, 'OK']] })
    store.select(new Map([[field, {}]]))
    data({}); socket.receive({ type: 'subscribe', status: 200 })
    data({ [field]: [[now, 'OK']] })
    data({ [field + '_QC']: [[now, 4]] })
    now += 6
    expect(store.get(field)).toMatchObject({ quality: 'FAIL', freshness: 'STALE',
      lastReported: { value: 'OK', time: 1_002 }, lastAccepted: { value: 'DEGRADED', time: 1_001 } })
  } finally { store.stop() }
})
