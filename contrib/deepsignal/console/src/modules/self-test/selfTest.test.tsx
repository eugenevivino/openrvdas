// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createPageRegistry } from '../../context'
import { loadConsole, parsePage } from '../../pages'
import module from './index'
import { makeContext } from './testkit'

const SelfTest = module.routes![0].Component
const reportValue = () => (screen.getByRole('textbox', { name: 'Plain-text self-test report' }) as HTMLTextAreaElement).value

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
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

it('reports a configured 404 even when another page file loads', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(
    url === './console.yaml' ? new Response('ship: Test\npages: [deck, missing]') :
      url === './pages/deck.yaml' ? new Response('title: Deck\ntiles: []') : new Response(null, { status: 404 }),
  )))
  const { config, files } = await loadConsole(new AbortController().signal)
  const pages = createPageRegistry(config.pages)
  for (const { page } of files) pages.register(page)
  render(<SelfTest ctx={{ ...makeContext(), config, pages }} />)
  expect(await screen.findByText('1 page loaded · Failed to load pages/missing.yaml')).toBeInTheDocument()
  expect(reportValue()).toContain('Page files: DOWN')
})

it('accepts configured presets and module routes alongside a loaded page file', async () => {
  const ctx = makeContext({ pages: [
    { ...parsePage('pages/deck.yaml', 'title: Deck\ntiles: []'), source: 'file:pages/deck.yaml' },
    { id: 'bridge', title: 'Bridge', source: 'preset:bridge', tiles: [{ type: 'nav' }] },
  ] })
  ctx.config.pages = ['deck', 'bridge', 'health']
  render(<SelfTest ctx={ctx} />)
  expect(await screen.findByText('1 page loaded')).toBeInTheDocument()
  expect(reportValue()).toContain('Page files: PASS')
})

it.each([
  { mwx1: null },
  { mwx1: { config: 'science', status: 'RUNNING' }, knud1: { status: 'RUNNING' } },
  { mwx1: { config: 'science', status: 'BROKEN' } },
])('reports DOWN for malformed logger entries (%j)', (loggerStatus) => {
  render(<SelfTest ctx={makeContext({ loggerStatus })} />)
  expect(reportValue()).toContain('Logger status: DOWN')
})
