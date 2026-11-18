export type LightingMode = 'day' | 'dusk' | 'night'
export type DayMode = Exclude<LightingMode, 'night'>

export interface Lighting {
  mode: LightingMode
  lastDay: DayMode
  dim: number
}

// These two functions are also inlined into index.html, before the stylesheet.
export function readLighting(): Lighting {
  const fallback = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dusk' : 'day'
  let mode: string | null = null
  let lastDay: string | null = null
  let dim = 0.6
  try {
    mode = window.localStorage.getItem('ds.mode')
    lastDay = window.localStorage.getItem('ds.daymode')
    const stored = window.localStorage.getItem('ds.dim')
    if (stored !== null && Number.isFinite(Number(stored))) {
      dim = Math.max(0.15, Math.min(1, Number(stored)))
    }
  } catch {
    // Storage can be disabled on a shared display.
  }
  const day = lastDay === 'day' || lastDay === 'dusk' ? lastDay : fallback
  const active = mode === 'day' || mode === 'dusk' ? mode : day
  return { mode: mode === 'night' ? 'night' : active, lastDay: active, dim }
}

export function paintLighting(root: HTMLElement, mode: LightingMode, dim: number) {
  const fg = [255, 38, 16]
  const muted = [150, 24, 10]
  const night = {
    bg: [0, 0, 0], panel: [5, 0, 0], panel2: [10, 0, 0], line: [70, 8, 4],
    fg, muted, accent: fg, ok: fg, check: fg, stale: muted, down: [255, 60, 30],
    chart: fg, grid: [40, 4, 2], 'scroll-thumb': muted,
  }
  root.dataset.mode = mode
  root.style.colorScheme = mode === 'day' ? 'light' : 'dark'
  for (const [token, [r, g, b]] of Object.entries(night)) {
    if (mode !== 'night') {
      root.style.removeProperty('--' + token)
      continue
    }
    const scale = token === 'bg' || token === 'panel' || token === 'panel2' ? 1 : dim
    const red = Math.round(r * scale)
    const ceiling = Math.floor(0.15 * red)
    const green = Math.min(Math.round(g * scale), ceiling)
    const blue = Math.min(Math.round(b * scale), ceiling)
    root.style.setProperty('--' + token, 'rgb(' + red + ',' + green + ',' + blue + ')')
  }
  const background = { day: '#e9eef0', dusk: '#081014', night: '#000000' }
  // Set the page background before external CSS has loaded.
  root.style.backgroundColor = background[mode]
}
