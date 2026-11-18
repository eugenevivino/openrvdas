// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
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
