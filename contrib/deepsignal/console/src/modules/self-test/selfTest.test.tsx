// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { parsePage } from '../../pages'
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

it('fails stale status, cruise mode and arbitrarily old records', () => {
  const ctx = makeContext()
  const get = ctx.store.get
  ctx.store.get = (field) => ({ ...get(field), freshness: 'STALE', sourceTime: ctx.clock.now() - 86_400 })
  render(<SelfTest ctx={ctx} />)
  const report = (screen.getByRole('textbox', { name: 'Plain-text self-test report' }) as HTMLTextAreaElement).value
  expect.soft(report).toContain('Logger status: DOWN')
  expect.soft(report).toContain('Cruise mode: DOWN')
  expect(report).toContain('Newest record: DOWN')
})

it('counts only successfully loaded page files', () => {
  const ctx = makeContext({ pages: [
    { id: 'bridge', title: 'Bridge', source: 'preset:bridge', tiles: [{ type: 'nav' }] },
    { id: 'auto', title: 'Auto', source: 'auto:test', tiles: [{ type: 'number' }] },
    { id: 'broken', title: 'broken', source: 'file:pages/broken.yaml', tiles: [] },
    { ...parsePage('pages/ship.yaml', 'title: ship\ntiles: []'), source: 'file:pages/ship.yaml' },
  ] })
  render(<SelfTest ctx={ctx} />)
  expect(screen.getByText(/^1 page loaded · Failed to load pages\/broken\.yaml$/)).toBeInTheDocument()
  expect((screen.getByRole('textbox', { name: 'Plain-text self-test report' }) as HTMLTextAreaElement).value)
    .toContain('Page files: DOWN')
})
