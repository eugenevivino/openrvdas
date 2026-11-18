// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import mapModule, { colorDomain, fillTileTemplate, MapTile, pairTrack } from './index.ts'
import type { ConsoleContext } from '../../contract'
import { fakeContext } from './testkit.ts'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null)
})

describe('map tile', () => {
  it('exports the map console module', () => expect(mapModule.id).toBe('map'))

  it('builds the right number of track segments from the fake feed', () => {
    const ctx = fakeContext()
    const track = pairTrack(ctx.store.history('S330Latitude', 7200), ctx.store.history('S330Longitude', 7200))
    expect(track).toHaveLength(600)
    expect(track.filter((point) => point.segmentStart)).toHaveLength(1)
  })

  it('finds the color scale minimum and maximum', () => {
    expect(colorDomain([{ time: 1, value: 4 }, { time: 2, value: 9 }, { time: 3, value: 'bad' }])).toEqual([4, 9])
  })

  it('shows a tapped track value as text', () => {
    const ctx = fakeContext()
    render(<MapTile cfg={{ type: 'map', lat: 'S330Latitude', lon: 'S330Longitude', window: '2 h', color_by: 'TsgTemp' }} ctx={ctx} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ship track map' }), { clientX: 150, clientY: 100 })
    expect(screen.getByRole('status')).toHaveTextContent(/19\.\d+ degC/)
  })

  it('shows stale position with a hollow marker word and age', () => {
    const ctx = fakeContext({ stalePosition: true })
    render(<MapTile cfg={{ type: 'map', lat: 'S330Latitude', lon: 'S330Longitude', window: '2 h' }} ctx={ctx} />)
    expect(screen.getByText(/Position stale 2 min/)).toBeInTheDocument()
  })

  it('fills a tile URL template', () => {
    expect(fillTileTemplate('tiles/{z}/{x}/{y}.png', 8, 44, 101)).toBe('tiles/8/44/101.png')
  })

  it('handles a missing raster tile without reporting an error', async () => {
    class MissingImage {
      onerror: null | (() => void) = null
      set src(_url: string) { queueMicrotask(() => this.onerror?.()) }
    }
    vi.stubGlobal('Image', MissingImage)
    const ctx = fakeContext()
    render(<MapTile cfg={{ type: 'map', lat: 'S330Latitude', lon: 'S330Longitude', window: '2 h', tiles: 'tiles/{z}/{x}/{y}.png', zoom: 8 }} ctx={ctx} />)
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })
})

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const cfg = { type: 'map', lat: 'S330Latitude', lon: 'S330Longitude', window: '2 h', zoom: 8 }
const mapButton = () => screen.getByRole('button', { name: 'Ship track map' })
const canvasContext = () => ({
  scale: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
  stroke: vi.fn(), fillText: vi.fn(), strokeRect: vi.fn(), save: vi.fn(), restore: vi.fn(), translate: vi.fn(),
  rotate: vi.fn(), closePath: vi.fn(), fill: vi.fn(), drawImage: vi.fn(), arc: vi.fn(),
})

it('keeps null coordinates and measurements missing while accepting zero', () => {
  const samples = [{ time: 1, value: null }, { time: 2, value: 0 }, { time: 3, value: 5 }]
  expect.soft(pairTrack(samples, [{ time: 1, value: 4 }, { time: 2, value: 0 }, { time: 3, value: null }]))
    .toEqual([{ time: 2, lat: 0, lon: 0, segmentStart: true }])
  expect(colorDomain([{ value: null }, { value: 5 }, { value: 9 }])).toEqual([5, 9])
})

it('rebuilds the plotted track when the subscription delivers new positions', () => {
  const ctx = fakeContext()
  const now = ctx.clock.now()
  let notify = () => {}
  ctx.store.subscribe = (_fields, cb) => { notify = cb; return () => {} }
  const readings = [{ time: now - 1, value: 1 }]
  ctx.store.history = () => [...readings]
  render(<MapTile cfg={cfg} ctx={ctx} />)
  fireEvent.click(mapButton(), { clientX: 320, clientY: 180 })
  expect(screen.getByRole('status')).toHaveTextContent('1.00000°, 1.00000°')
  readings.push({ time: now, value: 2 })
  act(notify)
  fireEvent.click(mapButton(), { clientX: 320, clientY: 180 })
  expect(screen.getByRole('status')).toHaveTextContent('2.00000°, 2.00000°')
})

it('marks position stale when longitude alone stops updating', () => {
  const ctx = fakeContext()
  const get = ctx.store.get
  ctx.store.get = (field) => field === cfg.lon
    ? { ...get(field), sourceTime: ctx.clock.now() - 120, ageS: 120, freshness: 'STALE' } : get(field)
  render(<MapTile cfg={cfg} ctx={ctx} />)
  expect(screen.getByText(/Position stale 2 min/)).toBeInTheDocument()
})

it('excludes MISSING and FAIL historical coordinates using the configured QC suffix', () => {
  const ctx = fakeContext()
  const now = ctx.clock.now()
  const history: Record<string, ReturnType<ConsoleContext['store']['history']>> = {
    [cfg.lat]: [{ time: now - 6, value: 0.5 }, { time: now - 3, value: -0.5 }, { time: now, value: 0 }],
    [cfg.lon]: [{ time: now - 6, value: 0 }, { time: now - 3, value: 0 }, { time: now, value: 0 }],
    [`${cfg.lat}.flag`]: [{ time: now - 5, value: 9 }],
    [`${cfg.lon}.flag`]: [{ time: now - 2, value: 4 }],
  }
  ctx.config.qcSuffix = '.flag'
  ctx.store.history = (field) => history[field] ?? []
  expect.soft(mapModule.tiles![0].fields(cfg, ctx)).toEqual(expect.arrayContaining([`${cfg.lat}.flag`, `${cfg.lon}.flag`]))
  render(<MapTile cfg={cfg} ctx={ctx} />)
  fireEvent.click(mapButton(), { clientX: 320, clientY: 89 })
  expect.soft(screen.getByRole('status')).toHaveTextContent('0.00000°, 0.00000°')
  fireEvent.click(mapButton(), { clientX: 320, clientY: 271 })
  expect(screen.getByRole('status')).toHaveTextContent('0.00000°, 0.00000°')
})

it('marks a matched current position SUSPECT and draws it hollow', () => {
  const ctx = fakeContext()
  const get = ctx.store.get
  ctx.store.get = (field) => field === cfg.lon ? { ...get(field), quality: 'SUSPECT' } : get(field)
  const drawing = canvasContext()
  HTMLCanvasElement.prototype.getContext = vi.fn(() => drawing) as unknown as typeof HTMLCanvasElement.prototype.getContext
  render(<MapTile cfg={cfg} ctx={ctx} />)
  expect.soft(screen.queryByText('▲ Position SUSPECT')).toBeInTheDocument()
  expect(drawing.fill).not.toHaveBeenCalled()
})

it.each(['STALE', 'NO_DATA', 'MISSING', 'FAIL', 'SUSPECT'] as const)(
  'draws a position dot without a bearing for %s heading', (issue) => {
    const ctx = fakeContext()
    const get = ctx.store.get
    ctx.store.get = (field) => field !== 'S330HeadingTrue' ? get(field) : {
      ...get(field), value: 270, ...(issue === 'STALE' || issue === 'NO_DATA' ? { freshness: issue } : { quality: issue }),
    }
    const drawing = canvasContext()
    HTMLCanvasElement.prototype.getContext = vi.fn(() => drawing) as unknown as typeof HTMLCanvasElement.prototype.getContext
    render(<MapTile cfg={{ ...cfg, heading: 'S330HeadingTrue' }} ctx={ctx} />)
    expect.soft(drawing.rotate).not.toHaveBeenCalled()
    expect(drawing.arc).toHaveBeenCalled()
  },
)

it('picks the nearest plotted point in two dimensions and shows its historical states', () => {
  const ctx = fakeContext()
  const now = ctx.clock.now()
  const then = now - 120
  const history: Record<string, ReturnType<ConsoleContext['store']['history']>> = {
    [cfg.lat]: [{ time: then, value: 0.5 }, { time: now, value: 0 }],
    [cfg.lon]: [{ time: then, value: 0 }, { time: now, value: 0 }],
    TsgTemp: [{ time: then, value: 11 }, { time: now, value: 22 }],
    'TsgTemp.flag': [{ time: then, value: 4 }, { time: now, value: 1 }],
  }
  ctx.config.qcSuffix = '.flag'
  ctx.store.history = (field) => history[field] ?? []
  const map = mapModule.tiles![0]
  const colored = { ...cfg, color_by: 'TsgTemp' }
  expect.soft(map.fields(colored, ctx)).toContain('TsgTemp.flag')
  render(<MapTile cfg={colored} ctx={ctx} />)
  fireEvent.click(mapButton(), { clientX: 320, clientY: 89 })
  expect(screen.getByRole('status')).toHaveTextContent('0.50000°, 0.00000°')
  expect(screen.getByRole('status')).toHaveTextContent(/11\.00 degC.*fail.*stale/i)
  fireEvent.click(mapButton(), { clientX: 320, clientY: 180 })
  expect(screen.getByRole('status')).toHaveTextContent(/22\.00 degC.*pass.*live/i)
})

it('keeps delayed raster tiles below the track and zeros green and blue in Night red', () => {
  const images: TileImage[] = []
  class TileImage {
    onload?: () => void
    set src(_url: string) { images.push(this) }
  }
  vi.stubGlobal('Image', TileImage)
  const contexts = new Map<HTMLCanvasElement, ReturnType<typeof canvasContext>>()
  HTMLCanvasElement.prototype.getContext = vi.fn(function (this: HTMLCanvasElement) {
    const context = contexts.get(this) ?? canvasContext()
    contexts.set(this, context)
    return context
  }) as unknown as typeof HTMLCanvasElement.prototype.getContext
  const ctx = fakeContext()
  let mode: 'day' | 'night' = 'day'
  let relight = () => {}
  ctx.lighting.get = () => ({ mode, dayMode: 'day', nightPalette: 'red', dim: 0.8 })
  ctx.lighting.subscribe = (cb) => { relight = cb; return () => {} }
  const view = render(<MapTile cfg={{ ...cfg, tiles: 'tiles/{z}/{x}/{y}.png' }} ctx={ctx} />)
  expect(images.length).toBeGreaterThan(0)
  mode = 'night'
  act(relight)
  act(() => images.forEach((image) => image.onload?.()))
  const [raster, track] = view.container.querySelectorAll('canvas')
  expect.soft(contexts.get(raster)?.drawImage).toHaveBeenCalled()
  expect.soft(contexts.get(track)?.stroke).toHaveBeenCalled()
  expect.soft(contexts.get(track)?.drawImage).not.toHaveBeenCalled()
  const filter = view.container.querySelector('filter')
  expect.soft(filter?.id).toBeTruthy()
  expect.soft(raster.style.filter.replaceAll('"', '')).toBe(`url(#${filter?.id})`)
  const matrix = filter?.querySelector('feColorMatrix')?.getAttribute('values')?.trim().split(/\s+/).map(Number)
  expect(matrix?.slice(5, 15)).toEqual(Array(10).fill(0))
  expect(Number(raster.style.opacity)).toBeGreaterThan(0)
  expect(Number(raster.style.opacity)).toBeLessThan(0.8)
})
