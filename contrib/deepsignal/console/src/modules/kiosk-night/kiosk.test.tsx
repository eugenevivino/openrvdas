// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseKioskHash } from './hash'
import { KioskSlot } from './kiosk'
import { makeContext } from './testkit'

afterEach(() => {
  cleanup()
  window.history.replaceState(null, '', '/')
  vi.unstubAllGlobals()
})

describe('kiosk mode', () => {
  it('parses only a kiosk hash suffix', () => {
    expect(parseKioskHash('#bridge-kiosk')).toBe('bridge')
    expect(parseKioskHash('#bridge')).toBeUndefined()
    expect(parseKioskHash('#-kiosk')).toBeUndefined()
  })

  it('hides tabs, ignores number keys, and exits after a two-second press', () => {
    const { ctx, clock, route } = makeContext({ kiosk_page: 'bridge' })
    render(<KioskSlot ctx={ctx} />)
    expect(document.querySelector('style')?.textContent).toContain('.tabs{display:none')
    fireEvent.keyDown(window, { key: '2' })
    expect(route.go).not.toHaveBeenCalled()
    fireEvent.pointerDown(screen.getByRole('button', { name: /exit kiosk/i }))
    clock.step(1.9)
    fireEvent.pointerUp(screen.getByRole('button', { name: /exit kiosk/i }))
    expect(route.go).not.toHaveBeenCalled()
    fireEvent.pointerDown(screen.getByRole('button', { name: /exit kiosk/i }))
    clock.step(2)
    fireEvent.pointerUp(screen.getByRole('button', { name: /exit kiosk/i }))
    expect(route.go).toHaveBeenCalledWith('bridge')
  })

  it('stays active after the router removes the kiosk hash suffix', () => {
    window.location.hash = '#bridge-kiosk'
    const { ctx } = makeContext()
    const view = render(<KioskSlot ctx={ctx} />)
    expect(document.querySelector('style')?.textContent).toContain('.tabs{display:none')

    window.location.hash = '#bridge'
    view.rerender(<KioskSlot ctx={ctx} />)

    expect(document.querySelector('style')?.textContent).toContain('.tabs{display:none')
    expect(screen.getByRole('button', { name: /exit kiosk/i })).toBeInTheDocument()
  })

  it('requests a wake lock and reports rejection', async () => {
    const request = vi.fn().mockRejectedValue(new Error('not allowed'))
    vi.stubGlobal('navigator', { wakeLock: { request } })
    const { ctx } = makeContext({ kiosk_page: 'bridge' })
    render(<KioskSlot ctx={ctx} />)
    await waitFor(() => expect(request).toHaveBeenCalledWith('screen'))
    expect(await screen.findByText('Screen may sleep')).toBeInTheDocument()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
  })
})
