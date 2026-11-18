// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { parsePage } from '../../pages'
import bridge from './index'
import { fakeContext } from './testkit'

const windDial = bridge.tiles?.find(({ type }) => type === 'wind-dial')
const WindDial = windDial!.Component

describe('wind-dial', () => {
  afterEach(cleanup)
  beforeEach(() => localStorage.clear())

  it('persists North up / Ship up per screen', () => {
    const ctx = fakeContext()
    const cfg = windDial!.validate({ type: 'wind-dial', speed: 'Avg1mPortTrueWindSpeed',
      direction: 'Avg1mPortTrueWindDir', heading: 'S330HeadingTrue' }, { file: 'bridge.yaml', tile: 1 })
    const first = render(<WindDial cfg={cfg} ctx={ctx} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ship up' }))
    expect(screen.getByRole('button', { name: 'Ship up' })).toHaveAttribute('aria-pressed', 'true')
    first.unmount()
    render(<WindDial cfg={cfg} ctx={ctx} />)
    expect(screen.getByRole('button', { name: 'Ship up' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('rotates the ship and from-wind arrow for the fake feed', () => {
    const ctx = fakeContext()
    const cfg = windDial!.validate({ type: 'wind-dial', speed: 'Avg1mPortTrueWindSpeed',
      direction: 'Avg1mPortTrueWindDir', heading: 'S330HeadingTrue' }, { file: 'bridge.yaml', tile: 1 })
    render(<WindDial cfg={cfg} ctx={ctx} />)
    expect(screen.getByTestId('ship')).toHaveAttribute('transform', 'rotate(249 100 100)')
    expect(screen.getByTestId('wind-arrow')).toHaveAttribute('transform', 'rotate(356 100 100)')
    fireEvent.click(screen.getByRole('button', { name: 'Ship up' }))
    expect(screen.getByTestId('ship')).toHaveAttribute('transform', 'rotate(0 100 100)')
    expect(screen.getByTestId('wind-arrow')).toHaveAttribute('transform', 'rotate(107 100 100)')
  })

  it('uses token colors only', () => {
    const source = windDial!.Component.toString()
    expect(source).not.toMatch(/#[0-9a-f]{3,8}|rgba?\(/i)
    expect(source).toContain('var(--')
  })

  it.each(['STALE', 'NO_DATA'] as const)('shows the reason instead of stale relative math for %s heading', (freshness) => {
    const ctx = fakeContext({ headingFreshness: freshness })
    const cfg = windDial!.validate({ type: 'wind-dial', speed: 'Avg1mPortTrueWindSpeed',
      direction: 'Avg1mPortTrueWindDir', heading: 'S330HeadingTrue' }, { file: 'bridge.yaml', tile: 1 })
    render(<WindDial cfg={cfg} ctx={ctx} />)
    expect(screen.getByText(`— (${freshness})`)).toBeInTheDocument()
  })
})

describe('bridge reading states', () => {
  afterEach(cleanup)
  beforeEach(() => localStorage.clear())
  const cfg = windDial!.validate({ type: 'wind-dial', speed: 'Avg1mPortTrueWindSpeed',
    direction: 'Avg1mPortTrueWindDir', heading: 'S330HeadingTrue', gust: 'gust',
    speed_fallback: 'PortTrueWindSpeed', direction_fallback: 'PortTrueWindDir',
    average_label: '1 min vector mean' }, { file: 'bridge.yaml', tile: 1 })

  it('labels fresh failed wind FAIL instead of OK', () => {
    const ctx = fakeContext()
    const get = ctx.store.get
    ctx.store.get = (field) => field === cfg.speed ? { ...get(field), quality: 'FAIL' } : get(field)
    render(<WindDial cfg={cfg} ctx={ctx} />)
    expect(screen.queryByText(/● OK/)).not.toBeInTheDocument()
    expect(screen.getByText(/FAIL/)).toBeInTheDocument()
  })

  it('marks stale heading, course, speed and gust and hides timed-out numbers', () => {
    const ctx = fakeContext()
    const get = ctx.store.get
    const values: Record<string, number> = { heading: 121, cog: 122, sog: 13.3, gust: 14.4 }
    ctx.store.get = (field) => field in values ? {
      ...get(field), field, value: values[field], quality: 'PASS',
      freshness: field === 'sog' ? 'NO_DATA' : 'STALE', ageS: field === 'sog' ? 400 : 12,
    } : get(field)
    const Nav = bridge.tiles!.find(({ type }) => type === 'nav')!.Component
    render(<><Nav cfg={{ type: 'nav', label: 'Navigation', heading: 'heading', cog: 'cog', sog: 'sog' }} ctx={ctx} />
      <WindDial cfg={cfg} ctx={ctx} /></>)
    expect(screen.queryByText(/13\.3/)).not.toBeInTheDocument()
    expect(screen.getByText(/NO DATA/)).toHaveTextContent('400 s')
    expect(screen.getAllByText(/STALE.*12 s/)).toHaveLength(3)
    expect(screen.getByText(/14\.4 kn/)).toBeInTheDocument()
  })

  it('omits the arrow when wind direction is missing', () => {
    const ctx = fakeContext()
    const get = ctx.store.get
    ctx.store.get = (field) => field === cfg.direction || field === cfg.direction_fallback
      ? { ...get(field), value: null, freshness: 'NO_DATA' } : get(field)
    render(<WindDial cfg={cfg} ctx={ctx} />)
    expect(screen.queryByTestId('wind-arrow')).not.toBeInTheDocument()
  })

  it('keeps the wind arrow north-referenced when ship-up heading is stale', () => {
    const ctx = fakeContext({ headingFreshness: 'STALE' })
    render(<WindDial cfg={cfg} ctx={ctx} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ship up' }))
    expect(screen.getByTestId('wind-arrow')).toHaveAttribute('transform', 'rotate(356 100 100)')
  })

  it('labels both fallback wind readings as instantaneous', () => {
    const ctx = fakeContext()
    const get = ctx.store.get
    ctx.store.get = (field) => field === cfg.speed || field === cfg.direction
      ? { ...get(field), freshness: 'NO_DATA' } : get(field)
    render(<WindDial cfg={cfg} ctx={ctx} />)
    expect(screen.queryByText('1 min vector mean')).not.toBeInTheDocument()
    expect(screen.getByText('Instantaneous wind')).toBeInTheDocument()
  })

  it('renders the shipped fallback wind speed in metres per second', () => {
    const preset = parsePage('bridge.yaml', bridge.presets![0].yaml).tiles.find(({ type }) => type === 'wind-dial')!
    const config = windDial!.validate(preset, { file: 'bridge.yaml', tile: 1 })
    const ctx = fakeContext()
    const get = ctx.store.get
    ctx.store.get = (field) => {
      const state = get(field)
      if (field === config.speed || field === config.direction) return { ...state, freshness: 'NO_DATA' }
      return field === config.speed_fallback ? { ...state, value: 10 } : state
    }
    render(<WindDial cfg={config} ctx={ctx} />)
    expect(screen.getByText('Instantaneous wind')).toBeInTheDocument()
    expect(screen.getByText('10.0', { exact: true })).toHaveTextContent('10.0 m/s')
  })
})
