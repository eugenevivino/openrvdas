// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import module from './index'
import { makeContext } from './testkit'

const SelfTest = module.routes![0].Component

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('shows connected checks, field and logger counts, mode, age, and loaded pages', () => {
  render(<SelfTest ctx={makeContext()} />)
  expect(screen.getByText('Connected')).toBeTruthy()
  expect(screen.getByText('12 fields')).toBeTruthy()
  expect(screen.getByText('2 loggers')).toBeTruthy()
  expect(screen.getByText('science')).toBeTruthy()
  expect(screen.getByText('5 seconds')).toBeTruthy()
  expect(screen.getByText('1 page loaded')).toBeTruthy()
})

it('shows disconnected, zero loggers, and a page problem with word and shape states', () => {
  const ctx = makeContext({ connected: false, loggerStatus: {}, pages: [] })
  render(<SelfTest ctx={ctx} />)
  expect(screen.getByText('Disconnected')).toBeTruthy()
  expect(screen.getByText('0 loggers')).toBeTruthy()
  expect(screen.getByText('No page files loaded')).toBeTruthy()
  expect(screen.getAllByText('Down').length).toBeGreaterThan(0)
  expect(screen.getAllByLabelText('Down state').length).toBeGreaterThan(0)
})

it('copies a plain-text report', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  })
  render(<SelfTest ctx={makeContext()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Copy report' }))
  expect(writeText).toHaveBeenCalledOnce()
  expect(writeText.mock.calls[0][0]).toContain('Cache connection: PASS')
  expect(writeText.mock.calls[0][0]).toContain('Page files: PASS')
})
