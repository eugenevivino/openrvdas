// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import castModule from './index'
import { makeCastContext } from './testkit'

afterEach(cleanup)

function renderCast() {
  const test = makeCastContext()
  test.set('WireOut', 25)
  test.set('WireSpeed', 1.2)
  test.set('Tension', 500)
  test.set('CtdDepth', 24)
  test.set('Altimeter', 20)
  const Component = castModule.routes?.[0].Component
  if (!Component) throw new Error('Cast route missing')
  render(<Component ctx={test.ctx} />)
  return test
}

describe('Cast view', () => {
  it('uses the exact tension band thresholds and renders values as text', () => {
    const test = renderCast()
    expect(screen.getByText('500 kg')).toBeInTheDocument()
    act(() => test.set('Tension', 800))
    expect(screen.getByText('Near limit')).toBeInTheDocument()
    act(() => test.set('Tension', 950))
    expect(screen.getByText('Over limit')).toBeInTheDocument()
  })

  it('shows no bands when safe working load is not configured', () => {
    const test = makeCastContext()
    delete test.ctx.config.modules.cast.swl
    test.set('Tension', 500)
    const Component = castModule.tiles?.[0].Component
    if (!Component) throw new Error('Cast tile missing')
    render(<Component cfg={{ type: 'cast' }} ctx={test.ctx} />)
    expect(screen.getByText('SWL not set')).toBeInTheDocument()
    expect(screen.queryByTestId('tension-bands')).not.toBeInTheDocument()
  })

  it('spells out signed payout direction', () => {
    const test = renderCast()
    expect(screen.getByText('1.2 m/s down')).toBeInTheDocument()
    act(() => test.set('WireSpeed', -0.7))
    expect(screen.getByText('0.7 m/s up')).toBeInTheDocument()
  })

  it('handles altimeter no-bottom, warning, and alarm states', () => {
    const test = renderCast()
    act(() => test.set('Altimeter', 101))
    expect(screen.getByText('No bottom')).toBeInTheDocument()
    act(() => test.set('Altimeter', 10))
    expect(screen.getByText('Near bottom')).toBeInTheDocument()
    act(() => test.set('Altimeter', 5))
    expect(screen.getByText('Bottom alarm')).toBeInTheDocument()
  })

  it('tracks maximum tension and resets it when wire returns under 5 m', () => {
    const test = renderCast()
    act(() => test.set('Tension', 700))
    expect(screen.getByText('Maximum 700 kg')).toBeInTheDocument()
    act(() => test.set('WireOut', 4.9))
    act(() => test.set('Tension', 300))
    expect(screen.getByText('Maximum 300 kg')).toBeInTheDocument()
  })

  it('shows stale tension age and greys its bar', () => {
    const test = renderCast()
    test.step(90)
    act(() => test.set('Tension', 500, { freshness: 'STALE', ageS: 90, sourceTime: test.ctx.clock.now() - 90 }))
    expect(screen.getByText('Stale — last seen 1 minute 30 seconds ago')).toBeInTheDocument()
    expect(screen.getByTestId('tension-bar')).toHaveAttribute('data-stale', 'true')
  })
})
