// @vitest-environment jsdom

import { afterEach, expect, it, vi } from 'vitest'
import { createAlerts, createLighting, createPageRegistry } from './context'

afterEach(() => {
  window.localStorage.clear()
  document.documentElement.removeAttribute('style')
})

it('uses file over preset over auto and follows configured page order', () => {
  const pages = createPageRegistry(['weather', 'bridge'])
  const register = (id: string, title: string, source: string) => pages.register({ id, title, source, tiles: [] })
  register('bridge', 'Auto bridge', 'auto:standard')
  register('bridge', 'Preset bridge', 'preset:standard')
  register('weather', 'Ship weather', 'file:weather.yaml')
  register('weather', 'Preset weather', 'preset:standard')
  register('extra', 'Extra', 'file:extra.yaml')
  register('bridge', 'Ship bridge', 'file:bridge.yaml')
  register('bridge', 'Refreshed auto bridge', 'auto:standard')
  expect(pages.list().map(({ title }) => title)).toEqual(['Ship weather', 'Ship bridge'])
})

it('lists all pages in page order when the configured list is empty', () => {
  const pages = createPageRegistry([])
  pages.register({ id: 'later', title: 'Later', order: 20, tiles: [] })
  pages.register({ id: 'first', title: 'First', order: 10, tiles: [] })
  expect(pages.list().map(({ id }) => id)).toEqual(['first', 'later'])
})

it('raises, acknowledges, clears, and notifies alert subscribers', () => {
  const alerts = createAlerts()
  const changed = vi.fn()
  const unsubscribe = alerts.subscribe(changed)
  const alert = { id: 'feed', tier: 'A2' as const, title: 'Feed stopped', source: 'Depth', consequence: 'No updates',
    firstAction: 'Check the logger', since: 3 }
  alerts.raise(alert)
  expect(alerts.list()).toEqual([alert])
  alerts.ack(alert.id)
  expect(alerts.list()).toEqual([{ ...alert, acked: true }])
  alerts.clear(alert.id)
  expect(alerts.list()).toEqual([])
  expect(changed).toHaveBeenCalledTimes(3)
  unsubscribe()
  alerts.raise(alert)
  expect(changed).toHaveBeenCalledTimes(3)
})

it('persists lighting, notifies after painting, and keeps neutral alarms distinct', () => {
  const lighting = createLighting('red')
  const changed = vi.fn()
  lighting.subscribe(changed)
  lighting.set({ mode: 'dusk' })
  lighting.set({ mode: 'night', nightPalette: 'neutral', dim: 0.5 })
  expect(createLighting('red').get()).toEqual({ mode: 'night', dayMode: 'dusk', nightPalette: 'neutral', dim: 0.5 })
  expect(changed).toHaveBeenCalledTimes(2)
  const { style } = document.documentElement
  expect(style.getPropertyValue('--down')).toBe('rgb(128,45,45)')
  expect(style.getPropertyValue('--fg')).toBe('rgb(112,112,112)')
  lighting.set({ nightPalette: 'red', dim: 0 })
  expect(lighting.get()).toMatchObject({ nightPalette: 'red', dim: 0.15 })
})
