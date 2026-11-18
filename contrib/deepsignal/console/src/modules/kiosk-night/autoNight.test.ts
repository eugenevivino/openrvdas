import { describe, expect, it } from 'vitest'
import { AutoNight } from './autoNight'
import { makeContext } from './testkit'

describe('automatic Night', () => {
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
})
