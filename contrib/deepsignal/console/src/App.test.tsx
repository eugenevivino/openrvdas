// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import type { ConsoleModule } from './contract'

const { discover } = vi.hoisted(() => ({ discover: vi.fn() }))
vi.mock('./registry', () => ({ discoverModules: discover }))

class Socket extends EventTarget {
  static current: Socket
  sent: Array<{ type: string; fields?: Record<string, unknown> }> = []

  constructor() {
    super()
    Socket.current = this
  }

  send(message: string) { this.sent.push(JSON.parse(message)) }
  close() {}
  receive(type: string, data?: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type, status: 200, data }) }))
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

it('mounts slots and one engine, isolates a tile problem, and requests the active destination and adapter fields', async () => {
  const { default: number } = await import('./modules/number')
  const stop = vi.fn()
  const start = vi.fn(() => stop)
  const readStatus = vi.fn()
  const example: ConsoleModule = {
    id: 'example',
    presets: [{ id: 'example', yaml: `title: Weather
tiles:
  - {type: dial, fallback: number, field: Heading, unit: '°', label: Heading, dialScale: 360}
  - {type: unavailable}
` }],
    routes: [{ id: 'logs', title: 'Logs', order: 10, fields: () => ['LogText'],
      Component: () => <p>Log messages</p> }],
    adapters: [{ id: 'status', fields: () => ['status:*'], onValue: readStatus }],
    engines: [{ id: 'example', start }],
    slots: [
      { slot: 'banner', order: 10, Component: () => <p>Example banner</p> },
      { slot: 'topbar', order: 10, Component: () => <p>Example control</p> },
    ],
  }
  discover.mockResolvedValue({ modules: [number, example], problems: ['Module broken: Cannot start.'] })
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('console.yaml')
    ? new Response('ship: Test\npages: [example]\n')
    : new Response('<!doctype html>', { headers: { 'content-type': 'text/html' } })))

  const view = render(<App />)
  await screen.findByRole('heading', { name: 'Weather' })
  expect(screen.getByRole('heading', { name: 'Heading' })).toBeTruthy()
  expect(screen.getByText(/example.yaml, tile 2: type is "unavailable"/)).toBeTruthy()
  expect(screen.getByText('Module broken: Cannot start.')).toBeTruthy()
  expect(screen.getByRole('region', { name: 'Console banners' }).textContent).toBe('Example banner')
  expect(screen.getByRole('banner').textContent).toContain('Example control')
  expect(start).toHaveBeenCalledTimes(1)
  const socket = Socket.current

  const fields = ['Heading', 'LogText', 'status:logger_status', 'Unasked']
  act(() => {
    socket.dispatchEvent(new Event('open'))
    socket.receive('fields', fields)
    socket.receive('describe', {})
    socket.receive('subscribe')
    socket.receive('data', { 'status:logger_status': [[Date.now() / 1000, { logger: 'RUNNING' }]] })
  })
  expect(readStatus).toHaveBeenCalledTimes(1)
  expect(Object.keys(socket.sent.find(({ type }) => type === 'subscribe')!.fields!))
    .toEqual(['Heading', 'Heading_QC', 'status:logger_status'])
  const logs = screen.getByRole('link', { name: 'Logs' })
  fireEvent.click(logs)
  await screen.findByText('Log messages')
  act(() => socket.receive('data', {}))
  await waitFor(() => expect(Object.keys(socket.sent.at(-1)!.fields!))
    .toEqual(['LogText', 'LogText_QC', 'status:logger_status']))
  expect(start).toHaveBeenCalledTimes(1)
  view.unmount()
  expect(stop).toHaveBeenCalledTimes(1)
})
