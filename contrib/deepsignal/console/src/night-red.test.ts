// @vitest-environment jsdom

import { afterEach, expect, it } from 'vitest'
import { paintLighting, readLighting } from './lighting-paint'

afterEach(() => document.documentElement.removeAttribute('style'))

it.each([0.15, 0.8, 1])('keeps every red token in range at dim %s and muted text legible at the default', (dim) => {
  expect(readLighting().dim).toBe(0.8)
  paintLighting(document.documentElement, 'night', dim, 'red')
  const { style } = document.documentElement
  for (const token of ['bg', 'panel', 'panel2', 'line', 'fg', 'muted', 'accent', 'ok', 'check',
    'stale', 'down', 'missing', 'chart', 'grid', 'scroll-thumb']) {
    const [r, g, b] = style.getPropertyValue('--' + token).match(/\d+/g)!.map(Number)
    expect(g, token).toBeLessThanOrEqual(0.15 * r)
    expect(b, token).toBeLessThanOrEqual(0.15 * r)
    if (token === 'muted' && dim === 0.8) expect(r).toBeGreaterThanOrEqual(150)
  }
})
