import type { Lighting } from './lighting-paint'

export { paintLighting, readLighting } from './lighting-paint'
export type { LightingMode } from './lighting-paint'

export function storeLighting(lighting: Lighting) {
  try {
    window.localStorage.setItem('ds.mode', lighting.mode)
    window.localStorage.setItem('ds.daymode', lighting.lastDay)
    window.localStorage.setItem('ds.dim', String(lighting.dim))
  } catch {
    // Keep the selected mode available for the current session.
  }
}

export function isShortcut(event: KeyboardEvent) {
  const target = event.target
  return !event.altKey && !event.ctrlKey && !event.metaKey && !event.repeat &&
    !(target instanceof HTMLElement && (
      target.isContentEditable || target.matches('input, textarea, select')
    ))
}
