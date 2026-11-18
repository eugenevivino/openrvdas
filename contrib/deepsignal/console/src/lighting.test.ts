// @vitest-environment jsdom

import { createElement } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { LightingControls } from './LightingControls'
import { paintLighting } from './lighting'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.documentElement.removeAttribute('style')
})

it.each([0.6, 1.0])('keeps every Night color red at brightness %s', (dim) => {
  const root = document.documentElement
  paintLighting(root, 'night', dim)
  for (const token of [
    'bg', 'panel', 'panel2', 'line', 'fg', 'muted', 'accent',
    'ok', 'check', 'stale', 'down', 'chart', 'grid', 'scroll-thumb',
  ]) {
    const channels = root.style.getPropertyValue('--' + token).match(/\d+/g)?.map(Number)
    expect(channels, token).toHaveLength(3)
    const [red, green, blue] = channels!
    expect(green, token).toBeLessThanOrEqual(0.15 * red)
    expect(blue, token).toBeLessThanOrEqual(0.15 * red)
  }
})

it('persists Night and brightness and restores Dusk when N toggles back', () => {
  const view = render(createElement(LightingControls))
  fireEvent.click(screen.getByRole('button', { name: 'Dusk' }))
  fireEvent.keyDown(window, { key: 'N' })
  expect(document.documentElement.dataset.mode).toBe('night')
  fireEvent.change(screen.getByRole('slider', { name: 'Night brightness' }), {
    target: { value: '80' },
  })
  view.unmount()
  render(createElement(LightingControls))
  expect(screen.getByRole('button', { name: 'Night' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole<HTMLInputElement>('slider', { name: 'Night brightness' }).value).toBe('80')
  fireEvent.keyDown(window, { key: 'n' })
  expect(screen.getByRole('button', { name: 'Dusk' }).getAttribute('aria-pressed')).toBe('true')
})
