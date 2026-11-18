// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import mapModule, { colorDomain, fillTileTemplate, MapTile, pairTrack } from './index.ts'
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
