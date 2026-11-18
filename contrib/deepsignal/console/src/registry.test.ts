// @vitest-environment jsdom

import { expect, it } from 'vitest'
import { collectModules, discoverModules } from './registry'

it('collects both default exports and leaves working modules available after import and shape errors', async () => {
  const result = await collectModules({
    './modules/first/index.ts': { default: { id: 'first' } },
    './modules/second/index.ts': { default: { id: 'second', presets: [{ id: 'weather', yaml: 'title: Weather' }] } },
    './modules/throwing/index.ts': Promise.resolve().then(() => { throw new Error('Cannot read settings') }),
    './modules/malformed/index.ts': { default: { id: 'malformed', tiles: [{ type: 'gauge' }] } },
  })
  expect(result.modules.map(({ id }) => id)).toEqual(['first', 'second'])
  expect(result.problems).toEqual([
    expect.stringMatching(/throwing.*Cannot read settings/),
    expect.stringMatching(/malformed.*tiles/),
  ])
})

it('discovers the bundled number and example modules through the registry', async () => {
  const { modules, problems } = await discoverModules()
  expect(modules.map(({ id }) => id)).toEqual(expect.arrayContaining(['number', 'example']))
  expect(problems).toEqual([])
})

it('discovers the Science preset and the stale alert engine and banner from the shipped registry', async () => {
  const { modules, problems } = await discoverModules()
  expect(modules.find(({ id }) => id === 'chart')?.presets).toEqual([
    expect.objectContaining({ id: 'science' }),
  ])
  const stale = modules.find(({ id }) => id === 'stale-banner')
  expect(stale?.engines).toEqual([expect.objectContaining({ id: 'stale-alerts' })])
  expect(stale?.slots).toEqual([expect.objectContaining({ slot: 'banner' })])
  expect(problems).toEqual([])
})
