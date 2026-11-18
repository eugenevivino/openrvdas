import feed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldState, Page } from '../../contract'

export function makeContext(options: {
  connected?: boolean
  loggerStatus?: Record<string, unknown>
  pages?: Page[]
} = {}): ConsoleContext {
  const now = feed.start_time + 600
  const names = Object.keys(feed.fields).slice(0, 9)
  const loggerStatus = options.loggerStatus ?? {
    knud1: { config: 'science', status: 'RUNNING' },
    tsg1: { config: 'science', status: 'RUNNING' },
  }
  const values = new Map<string, FieldState>()
  for (const field of names) {
    values.set(field, {
      field, value: 1, sourceTime: now - 5, receiveTime: now - 5,
      freshness: 'LIVE', quality: 'PASS', health: 'OK',
    })
  }
  values.set('status:logger_status', {
    field: 'status:logger_status', value: loggerStatus, sourceTime: now - 5,
    freshness: 'LIVE', quality: 'NOT_EVALUATED', health: 'UNKNOWN',
  })
  values.set('status:cruise_mode', {
    field: 'status:cruise_mode', value: { active_mode: 'science' }, sourceTime: now - 5,
    freshness: 'LIVE', quality: 'NOT_EVALUATED', health: 'UNKNOWN',
  })
  values.set('extra', {
    field: 'extra', value: 1, sourceTime: now - 5,
    freshness: 'LIVE', quality: 'PASS', health: 'OK',
  })
  const pages = options.pages ?? [{ id: 'bridge', title: 'Bridge', tiles: [] }]
  return {
    config: {
      ship: 'Test ship', shipTimezone: 'UTC', websocket: 'ws://ship:8766', pages: [],
      historyS: 3600, qcSuffix: '_QC', nightPalette: 'red', modules: {},
    },
    store: {
      connection: () => options.connected === false ? 'reconnecting' : 'connected',
      lastMessageAgeS: () => 5,
      listFields: () => [...values.keys()],
      describe: () => undefined,
      get: (field) => values.get(field) ?? {
        field, value: undefined, freshness: 'NO_DATA',
        quality: 'NOT_EVALUATED', health: 'UNKNOWN',
      },
      history: () => [], subscribe: () => () => {}, setHealth: () => {},
    },
    pages: { register: () => {}, list: () => pages },
    alerts: {
      raise: () => {}, clear: () => {}, ack: () => {}, list: () => [],
      subscribe: () => () => {},
    },
    lighting: {
      get: () => ({ mode: 'night', dayMode: 'dusk', nightPalette: 'red', dim: 0.6 }),
      set: () => {}, subscribe: () => () => {},
    },
    clock: { now: () => now },
    route: { get: () => 'self-test', go: () => {} },
  }
}
