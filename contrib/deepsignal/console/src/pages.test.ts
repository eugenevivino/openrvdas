import { expect, it } from 'vitest'
import { parseConsole } from './pages'
import { parseNumberPage as parsePage } from './modules/number/validate'

const tile = `title: Bridge
tiles:
  - type: number
    label: Depth
    field: DepthMeters
    unit: m
`

it('explains an invalid field name in the page file', () => {
  expect(() => parsePage('pages/bridge.yaml', tile.replace('DepthMeters', 'Depth *')))
    .toThrow('pages/bridge.yaml, tile 1, field: saw "Depth *". Expected an exact field name using letters, numbers, underscores, periods or hyphens. Example: field: DepthMeters')
})

it('explains an unsupported tile type in the page file', () => {
  expect(() => parsePage('pages/bridge.yaml', tile.replace('type: number', 'type: gauge')))
    .toThrow('pages/bridge.yaml, tile 1, type: saw "gauge". Expected "number". Example: type: number')
})

it('reads a fractional sample period and explains an invalid period', () => {
  expect(parsePage('pages/bridge.yaml', tile + '    period: 0.5\n').tiles[0].period).toBe(0.5)
  expect(() => parsePage('pages/bridge.yaml', tile + '    period: 0\n'))
    .toThrow('pages/bridge.yaml, tile 1, period: saw 0. Expected a positive period in seconds. Example: period: 2')
})

it('defaults to Night red and accepts the Night neutral configuration', () => {
  const settings = 'ship: Example\npages: [bridge]\n'
  expect(parseConsole(settings, 'ship').night_palette).toBe('red')
  expect(parseConsole(settings + 'night_palette: neutral\n', 'ship').night_palette).toBe('neutral')
})
