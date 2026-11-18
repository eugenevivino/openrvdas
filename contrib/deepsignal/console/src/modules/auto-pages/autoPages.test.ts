import { describe, expect, it } from 'vitest'
import feed from '../../contract/fake-feed.json'
import type { ConsoleContext, FieldDescription, Page } from '../../contract'
import autoPages, { recognizeFields } from './index'

function context(initial: Record<string, FieldDescription>, existing: Page[] = []) {
  let fields = { ...initial }
  let callback: (() => void) | undefined
  const registered: Page[] = []
  const ctx = {
    store: {
      listFields: () => Object.keys(fields),
      describe: (field: string) => fields[field],
      get: (field: string) => ({ field, value: undefined, freshness: 'NO_DATA', quality: 'NOT_EVALUATED', health: 'UNKNOWN' }),
      connection: () => 'connected', lastMessageAgeS: () => 0, history: () => [], setHealth: () => {},
      subscribe: (_subscribed: string[], cb: () => void) => { callback = cb; return () => { callback = undefined } },
    },
    pages: { register: (page: Page) => registered.push(page), list: () => [...existing, ...registered] },
    config: { ship: 'test', shipTimezone: 'UTC', websocket: '', pages: [], historyS: 300, qcSuffix: '_QC', nightPalette: 'red', modules: {} },
    alerts: { raise: () => {}, clear: () => {}, ack: () => {}, list: () => [], subscribe: () => () => {} },
    lighting: { get: () => ({ mode: 'day', dayMode: 'day', nightPalette: 'red', dim: 1 }), set: () => {}, subscribe: () => () => {} },
    clock: { now: () => 0 }, route: { get: () => '', go: () => {} },
  } as ConsoleContext
  return { ctx, registered, change(next: Record<string, FieldDescription>) { fields = next; callback?.() } }
}

const engine = autoPages.engines![0]

describe('auto-pages', () => {
  it('recognizes fake-feed roles and registers the expected pages', () => {
    const test = context(feed.fields)
    const roles = recognizeFields(test.ctx.store)
    expect(Object.keys(roles.byRole)).toEqual(expect.arrayContaining(['heading', 'course', 'speedOverGround', 'latitude', 'longitude', 'trueWindSpeed', 'trueWindDirection', 'averagedWind', 'airTemperature', 'humidity', 'barometer', 'seaTemperature', 'salinity', 'fluorescence', 'depth']))
    engine.start(test.ctx)
    expect(test.registered.map((page) => page.id)).toEqual(['bridge-auto', 'science-auto', 'all-fields'])
    expect(test.registered.every((page) => page.title.endsWith('(auto)'))).toBe(true)
    expect(test.registered.flatMap((page) => page.tiles).every((tile) => tile.fallback === 'number')).toBe(true)
  })

  it('does not register a bridge page without heading or wind', () => {
    const test = context({ TsgTemp: feed.fields.TsgTemp })
    engine.start(test.ctx)
    expect(test.registered.map((page) => page.id)).toEqual(['science-auto', 'all-fields'])
  })

  it('matches field names without regard to case', () => {
    expect(recognizeFields(context({ mIxEdHdG: { units: 'deg' } }).ctx.store).byRole.heading).toBe('mIxEdHdG')
  })

  it('caps all-fields at 200 numeric tiles and reports the remainder', () => {
    const fields = Object.fromEntries(Array.from({ length: 205 }, (_, index) => [`Numeric${index}`, { units: 'count', logger: index < 100 ? 'a' : 'b' }]))
    const test = context(fields)
    engine.start(test.ctx)
    const page = test.registered.find((item) => item.id === 'all-fields') as Page & { note: string }
    expect(page.tiles).toHaveLength(200)
    expect(page.note).toContain('and 5 more')
    expect(page.tiles[0].logger).toBe('a')
  })

  it('re-registers generated pages when the field list changes', () => {
    const test = context({ TsgTemp: feed.fields.TsgTemp })
    engine.start(test.ctx)
    const firstCount = test.registered.length
    test.change({ ...feed.fields })
    expect(test.registered.length).toBeGreaterThan(firstCount)
    expect(test.registered.slice(firstCount).some((page) => page.id === 'bridge-auto')).toBe(true)
  })

  it('does not register over an id supplied by a file', () => {
    const filePage: Page = { id: 'bridge-auto', title: 'My bridge', source: 'file:bridge-auto.yaml', tiles: [] }
    const test = context(feed.fields, [filePage])
    engine.start(test.ctx)
    expect(test.registered.some((page) => page.id === 'bridge-auto')).toBe(false)
  })
})
