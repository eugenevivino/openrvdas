// @vitest-environment jsdom

import { createElement } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { LightingControls } from './LightingControls'
import { paintLighting, readLighting } from './lighting'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.documentElement.removeAttribute('style')
})

it.each([0.15, 0.6, 0.8, 1.0])('keeps every Night color red at brightness %s', (dim) => {
  const root = document.documentElement
  paintLighting(root, 'night', dim, 'red')
  for (const token of [
    'bg', 'panel', 'panel2', 'line', 'fg', 'muted', 'accent',
    'ok', 'check', 'stale', 'down', 'missing', 'chart', 'grid', 'scroll-thumb',
  ]) {
    const channels = root.style.getPropertyValue('--' + token).match(/\d+/g)?.map(Number)
    expect(channels, token).toHaveLength(3)
    const [red, green, blue] = channels!
    expect(green, token).toBeLessThanOrEqual(0.15 * red)
    expect(blue, token).toBeLessThanOrEqual(0.15 * red)
  }
})

it('starts at 80 percent and keeps alarms red against neutral Night text', () => {
  expect(readLighting().dim).toBe(0.8)
  const root = document.documentElement
  paintLighting(root, 'night', 1, 'neutral')
  expect(root.style.getPropertyValue('--fg')).toBe('rgb(224,224,224)')
  expect(root.style.getPropertyValue('--down')).toBe('rgb(255,90,90)')
  expect(root.style.backgroundColor).toBe('rgb(0, 0, 0)')
})

it('uses the configured palette until the operator selects a palette for this screen', () => {
  window.localStorage.setItem('ds.mode', 'night')
  const view = render(createElement(LightingControls, { defaultPalette: 'neutral' }))
  expect(screen.getByRole('button', { name: 'Neutral' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: 'Red' }))
  view.unmount()
  render(createElement(LightingControls, { defaultPalette: 'neutral' }))
  expect(screen.getByRole('button', { name: 'Red' }).getAttribute('aria-pressed')).toBe('true')
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
