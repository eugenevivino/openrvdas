import { expect, it } from 'vitest'
import { parsePage } from './pages'

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
