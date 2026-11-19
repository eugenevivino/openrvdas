// @vitest-environment jsdom

import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ConsoleStore } from './store'

class MockSocket extends EventTarget {
  static current: MockSocket
  sent: Array<{ type: string; fields?: Record<string, unknown> }> = []

  constructor() {
    super()
    MockSocket.current = this
  }

  send(text: string) {
    this.sent.push(JSON.parse(text))
  }

  receive(type: string, data?: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, status: 200, data }) }))
  }

  close() {}
}

let now: number
let store: ConsoleStore | undefined

beforeEach(() => {
  now = 110
  vi.stubGlobal('WebSocket', MockSocket)
})

afterEach(() => {
  store?.stop()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function connect(qcSuffix = '_QC', fields = ['Depth', 'Depth' + qcSuffix]) {
  const result = store = new ConsoleStore({ websocket: 'ws://test:8766', historyS: 60, qcSuffix }, { now: () => now })
  result.select(new Map([['Depth', {}], ['Temp', { logger: 'tsg1' }], ['status:logger_status', {}]]))
  result.start()
  const socket = MockSocket.current
  socket.dispatchEvent(new Event('open'))
  expect(socket.sent.at(-1)).toEqual({ type: 'fields' })
  socket.receive('fields', fields)
  expect(socket.sent.at(-1)).toEqual({ type: 'describe' })
  socket.receive('describe', { Depth: { units: 'm', logger: 'knud1' } })
  socket.receive('subscribe')
  return { store: result, socket }
}

it('learns T, notifies at 2T and 5T, and keeps last good through the hard timeout', () => {
  const { store, socket } = connect()
  socket.receive('data', { Depth: [[100, 10], [105, 11], [110, 12]], Depth_QC: [[105, 1], [110, 4]] })
  expect(store.get('Depth')).toMatchObject({ periodS: 5, lastGood: { time: 105, value: 11 }, quality: 'FAIL' })
  expect(store.history('Depth', 6)).toEqual([{ time: 105, value: 11 }, { time: 110, value: 12 }])
  const changed = vi.fn()
  const unsubscribe = store.subscribe(['Depth'], changed)
  for (const [age, freshness] of [
    [10, 'LIVE'], [10.001, 'AGING'], [25, 'AGING'], [25.001, 'STALE'], [300, 'STALE'], [300.001, 'NO_DATA'],
  ] as const) {
    now = 110 + age
    store.tick()
    expect(store.get('Depth').freshness).toBe(freshness)
  }
  expect(changed).toHaveBeenCalled()
  expect(store.get('Depth').lastGood).toEqual({ time: 105, value: 11 })
  unsubscribe()
})

it('maps absent and custom quality flags, with per-test evidence independent of freshness', () => {
  const { store, socket } = connect('_flag', ['Depth', 'Depth_flag', 'Depth_flag_rate', 'Depth_flag_reason', 'Unasked'])
  expect(socket.sent.find(({ type }) => type === 'subscribe')?.fields).toEqual({
    Depth: { seconds: 60, back_records: 1 },
    Temp: { seconds: 60, back_records: 1 },
    Depth_flag: { seconds: 60, back_records: 1 },
    Depth_flag_rate: { seconds: 60, back_records: 1 },
    Depth_flag_reason: { seconds: 60, back_records: 1 },
    Temp_flag: { seconds: 60, back_records: 1 },
    'status:logger_status': { seconds: 60, back_records: 1 },
  })
  socket.receive('data', { Depth: [[108, 2]], Depth_flag: [[108, 1]], Temp: [[110, 5]], 'status:logger_status': [[110, {}]], Unasked: [[110, 8]] })
  now = 114
  expect(store.get('Depth')).toMatchObject({ freshness: 'STALE', quality: 'PASS' })
  expect(store.get('Temp').quality).toBe('NOT_EVALUATED')
  expect(store.get('Unasked').sourceTime).toBeUndefined()
  now = 120
  socket.receive('data', {
    Depth: [[120, 3]], Depth_flag: [[120, 3]], Depth_flag_rate: [[120, 4]], Depth_flag_reason: [[120, 'Rate of change']],
  })
  expect(store.get('Depth')).toMatchObject({
    freshness: 'LIVE', quality: 'SUSPECT', qualityTests: { rate: 4 }, qualityReason: 'Rate of change',
  })
  now = 132
  socket.receive('data', { Depth: [[132, 4]] })
  expect(store.get('Depth')).toMatchObject({ freshness: 'LIVE', quality: 'NOT_EVALUATED' })
  expect(store.get('Depth').qualityReason).toBeUndefined()
})

it('sets independent logger health from metadata or a tile logger', () => {
  const { store, socket } = connect()
  socket.receive('data', { Depth: [[110, 12]], Temp: [[110, 6]] })
  expect(store.listFields()).toContain('Depth')
  expect(store.describe('Depth')).toEqual({ units: 'm', logger: 'knud1' })
  expect(store.get('Depth').health).toBe('UNKNOWN')
  store.setHealth({ logger: 'knud1' }, 'FAILED', 'Exited')
  store.setHealth({ logger: 'tsg1' }, 'DEGRADED')
  expect(store.get('Depth')).toMatchObject({ health: 'FAILED', healthEvidence: 'Exited', quality: 'NOT_EVALUATED' })
  expect(store.get('Temp').health).toBe('DEGRADED')
})

it('requests the latest reading once after an empty first backfill', () => {
  const { store, socket } = connect()
  socket.receive('data', { Temp: [[110, 6]], 'status:logger_status': [[110, { knud1: { status: 'FAILED' } }]] })
  expect(socket.sent.at(-1)?.fields?.Depth).toEqual({ seconds: -1 })
  socket.receive('subscribe')
  socket.receive('data', { Depth: [[40, 12]] })
  expect(store.get('Depth')).toMatchObject({ value: 12, sourceTime: 40, receiveTime: 110, freshness: 'STALE' })
  expect(store.get('status:logger_status').value).toEqual({ knud1: { status: 'FAILED' } })
  expect(store.lastMessageAgeS()).toBe(0)
  expect(socket.sent.filter(({ type }) => type === 'subscribe')).toHaveLength(2)
})

it.each(['field', 'value'] as const)('isolates a throwing %s subscriber and requests the next CDS batch', (kind) => {
  const { store, socket } = connect()
  const error = new Error('Subscriber failed')
  const reported = vi.spyOn(console, 'error').mockImplementation(() => {})
  const failing = () => { throw error }
  const healthy = vi.fn()
  const subscribe = kind === 'field' ? (listener: () => void) => store.subscribe(['Depth'], listener)
    : (listener: () => void) => store.observeValues(listener)
  const unsubscribe = subscribe(failing)
  subscribe(healthy)

  try {
    const batches = socket.sent.length
    socket.receive('data', { Depth: [[110, 12]], Temp: [[110, 6]], 'status:logger_status': [[110, {}]] })
    expect(healthy).toHaveBeenCalledTimes(kind === 'field' ? 1 : 3)
    expect(reported).toHaveBeenCalledWith(expect.any(String), error)
    expect(socket.sent.slice(batches)).toEqual([{ type: 'ready' }])
    socket.receive('data', { Depth: [[111, 13]] })
    expect(store.get('Depth').value).toBe(13)
  } finally {
    unsubscribe()
  }
})

it('requests and applies quality flags for namespaced measurements', () => {
  const field = 'gnss:Latitude'
  const flag = `${field}_flag`
  const status = 'status:logger_status'
  const stderr = 'stderr:logger:gnss'
  store = new ConsoleStore({ websocket: 'ws://test:8766', historyS: 0, qcSuffix: '_flag' }, { now: () => now })
  store.select(new Map([[field, {}], [status, {}], [stderr, {}]]))
  store.start()
  const socket = MockSocket.current
  socket.dispatchEvent(new Event('open'))
  socket.receive('fields', [field, flag, flag + '_range', flag + '_reason', status, stderr])
  socket.receive('describe', {})
  expect(socket.sent.at(-1)?.fields).toEqual(Object.fromEntries(
    [field, flag, flag + '_range', flag + '_reason', status, stderr].map((name) => [name, { seconds: -1 }]),
  ))
  socket.receive('subscribe')
  socket.receive('data', { [field]: [[110, 40]], [flag]: [[110, 4]],
    [flag + '_range']: [[110, 4]], [flag + '_reason']: [[110, 'Out of range']] })
  expect(store.get(field)).toMatchObject({ value: 40, quality: 'FAIL', qualityTests: { range: 4 }, qualityReason: 'Out of range' })
})
