// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import route from './index'
import { fakeFeed, fields } from './testkit'

const stations = [
  { name: 'Pier', lat: 0, lon: 0 }, { name: 'Station A', lat: 0, lon: 1 },
  { name: 'Station B', lat: 1, lon: 1 },
]
const tile = route.tiles![0]
const cfg = tile.validate({ type: 'route', ...fields }, { file: 'science.yaml', tile: 1 })

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function setup(data: unknown = stations, ok = true, file?: string) {
  window.history.replaceState(null, '', '/console/index.html')
  const feed = fakeFeed()
  const fetchFile = vi.fn().mockResolvedValue({ ok, json: async () => data })
  vi.stubGlobal('fetch', fetchFile)
  feed.step(0, { lat: 0, lon: 0, cog: 90, sog: 10 })
  const show = () => render(<tile.Component cfg={file ? { ...cfg, route: file } : cfg} ctx={feed.ctx} />)
  return { feed, fetchFile, show, view: show() }
}

it('subscribes to the configured navigation fields', () => {
  expect(route.id).toBe('route')
  expect(tile.type).toBe('route')
  expect(tile.fields(cfg, fakeFeed().ctx)).toEqual(Object.values(fields))
})

it('shows next and route-end distance, bearing, time to go and UTC ETA', async () => {
  setup()
  await screen.findByText('Station A')
  const next = within(screen.getByRole('group', { name: 'Next waypoint' }))
  const end = within(screen.getByRole('group', { name: 'Route end' }))
  expect(next.getByText('60.0 nm')).toBeTruthy()
  // Two perpendicular legs. A direct distance to Station B would be about 85 nm.
  expect(end.getByText('120.1 nm')).toBeTruthy()
  expect(end.getByText('45° true')).toBeTruthy()
  expect(next.getByText('90° true')).toBeTruthy()
  expect(next.getByText('6 h 00 min')).toBeTruthy()
  expect(end.getByText('12 h 00 min')).toBeTruthy()
  expect(next.getByText('2026-11-18 17:06 UTC')).toBeTruthy()
  expect(end.getByText('2026-11-18 23:07 UTC')).toBeTruthy()
})

it('advances only within 0.1 nm, never goes back, and completes the route', async () => {
  const { feed, view, show, fetchFile } = setup()
  await screen.findByText('Station A')
  const next = () => within(screen.getByRole('group', { name: 'Next waypoint' }))
  act(() => feed.step(1, { lon: 0.998 }))
  expect(next().getByText('Station A')).toBeTruthy()
  act(() => feed.step(1, { lon: 0.999 }))
  expect(next().getByText('Station B')).toBeTruthy()
  view.unmount()
  act(() => feed.step(1, { lon: 0 }))
  show()
  await screen.findByRole('group', { name: 'Next waypoint' })
  expect(next().getByText('Station B')).toBeTruthy()
  expect(fetchFile).toHaveBeenCalledTimes(1)
  act(() => feed.step(1, { lat: 1, lon: 1 }))
  expect(screen.getByText('Route complete')).toBeTruthy()
  act(() => feed.step(1, { lon: 0 }))
  expect(screen.getByText('Route complete')).toBeTruthy()
})

it('shows port and starboard on the active leg', async () => {
  const { feed } = setup()
  await screen.findByText('Station A')
  act(() => feed.step(1, { lat: 0.01, lon: 0.5 }))
  expect(screen.getByText('0.6 nm port')).toBeTruthy()
  act(() => feed.step(1, { lat: -0.01 }))
  expect(screen.getByText('0.6 nm starboard')).toBeTruthy()
})

it('suppresses both ETAs below 0.5 kn and restores them at the boundary', async () => {
  const { feed } = setup()
  await screen.findByText('Station A')
  act(() => feed.step(1, { sog: 0.49 }))
  expect(screen.getByText('No ETA: speed under 0.5 kn')).toBeTruthy()
  expect(screen.queryByText(/UTC$/)).toBeNull()
  act(() => feed.step(1, { sog: 0.5 }))
  expect(screen.getAllByText(/UTC$/)).toHaveLength(2)
})

it('warns at 60 s, not 59 s, and resets on a 45 degree course difference', async () => {
  const { feed } = setup()
  await screen.findByText('Station A')
  act(() => feed.step(0, { cog: 136 }))
  act(() => feed.step(59))
  expect(screen.queryByText('Check waypoint')).toBeNull()
  act(() => feed.step(1))
  expect(screen.getByText('Check waypoint')).toBeTruthy()
  act(() => feed.step(1, { cog: 135 }))
  expect(screen.queryByText('Check waypoint')).toBeNull()
  act(() => feed.step(1, { cog: 136 }))
  act(() => feed.step(59))
  expect(screen.queryByText('Check waypoint')).toBeNull()
})

it('reads a named GeoJSON LineString in longitude-latitude order and wraps course across north', async () => {
  const { feed, fetchFile } = setup({ type: 'LineString', coordinates: [[0, 0], [0, 1]] }, true, 'survey.json')
  await screen.findByRole('group', { name: 'Next waypoint' })
  expect(fetchFile.mock.calls[0][0].toString()).toMatch(/\/console\/survey\.json$/)
  expect(screen.getAllByText('0° true').length).toBeGreaterThan(0)
  act(() => feed.step(1, { cog: 359 }))
  act(() => feed.step(61))
  expect(screen.queryByText('Check waypoint')).toBeNull()
})

it('shows the stale position age and withholds both ETAs and arrival', async () => {
  const { feed } = setup()
  await screen.findByText('Station A')
  act(() => feed.stale('lat', 75))
  act(() => feed.step(0, { lon: 1 }))
  expect(screen.getByText(/last seen 75 s ago/i)).toBeTruthy()
  expect(screen.queryByText(/UTC$/)).toBeNull()
  act(() => feed.step(1, { lon: 0, lat: 0 }))
  expect(screen.getByText('Station A')).toBeTruthy()
})

it('explains a missing default routes file', async () => {
  const { fetchFile } = setup(null, false)
  await screen.findByText(/could not load routes\.json/i)
  expect(fetchFile.mock.calls[0][0].toString()).toMatch(/\/console\/routes\.json$/)
})

it('explains invalid coordinates without showing a partial route', async () => {
  setup([...stations, { name: 'Bad', lat: 91, lon: 2 }])
  await screen.findByText(/invalid route in routes\.json/i)
  expect(screen.queryByText(/UTC$/)).toBeNull()
})
