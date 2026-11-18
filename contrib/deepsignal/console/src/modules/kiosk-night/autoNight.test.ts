import { describe, expect, it } from 'vitest'
import { AutoNight } from './autoNight'
import kioskNight from './index'
import { makeContext } from './testkit'

describe('automatic Night', () => {
  it('requests the configured position fields from the data server', () => {
    const { ctx } = makeContext({ latitude_field: 'GpsLat', longitude_field: 'GpsLon' })
    expect(kioskNight.adapters?.[0]?.fields(ctx)).toEqual(['GpsLat', 'GpsLon'])
  })

  it('switches on crossings and applies half-degree hysteresis', () => {
    const { ctx, store, lighting } = makeContext({ auto_night: true })
    const auto = new AutoNight(ctx, () => -6.1)
    auto.start()
    expect(lighting.mode).toBe('night')
    auto.sample(() => -5.8)
    expect(lighting.mode).toBe('night')
    auto.sample(() => -5.4)
    expect(lighting.mode).toBe('day')
    expect(store.subscribed).toEqual(['S330Latitude', 'S330Longitude'])
  })

  it('lets a manual change win until the next crossing', () => {
    const { ctx, lighting } = makeContext({ auto_night: true })
    const auto = new AutoNight(ctx, () => -6.1)
    auto.start()
    lighting.manualSet({ mode: 'day' })
    auto.sample(() => -6.5)
    expect(lighting.mode).toBe('day')
    auto.sample(() => -5.4)
    expect(lighting.mode).toBe('day')
    auto.sample(() => -6.1)
    expect(lighting.mode).toBe('night')
  })

  it.each(['STALE', 'NO_DATA'] as const)('pauses for %s position data', (freshness) => {
    const { ctx, store, lighting } = makeContext({ auto_night: true })
    store.fields.S330Latitude.freshness = freshness
    const auto = new AutoNight(ctx, () => -20)
    auto.start()
    expect(lighting.set).not.toHaveBeenCalled()
    expect(auto.status()).toBe('Auto Night paused: position unavailable')
  })

  it.each([
    ['S330Latitude', 'MISSING'], ['S330Longitude', 'MISSING'],
    ['S330Latitude', 'FAIL'], ['S330Longitude', 'SUSPECT'],
  ] as const)('holds Night when %s has quality %s even with a fresh numeric reading', (field, quality) => {
    const { ctx, store, lighting } = makeContext({ auto_night: true })
    const auto = new AutoNight(ctx, () => -10)
    const stop = auto.start()
    expect(lighting.mode).toBe('night')
    store.fields[field].quality = quality
    auto.sample(() => 10)
    expect.soft(lighting.mode).toBe('night')
    expect.soft(auto.status()).toBe('Auto Night paused: position unavailable')
    store.fields[field].quality = 'PASS'
    auto.sample(() => 10)
    expect(lighting.mode).toBe('day')
    expect(auto.status()).toBe('')
    stop()
  })
})
