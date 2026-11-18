export type LightingMode = 'day' | 'dusk' | 'night'
export type DayMode = Exclude<LightingMode, 'night'>
export type NightPalette = 'red' | 'neutral'

export interface Lighting {
  mode: LightingMode
  lastDay: DayMode
  dim: number
  palette?: NightPalette
  defaultPalette: NightPalette
}

// These two functions are also inlined into index.html, before the stylesheet.
export function readLighting(): Lighting {
  const fallback = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dusk' : 'day'
  let mode: string | null = null
  let lastDay: string | null = null
  let palette: string | null = null
  let defaultPalette: NightPalette = 'red'
  let dim = 0.8
  try {
    mode = window.localStorage.getItem('ds.mode')
    lastDay = window.localStorage.getItem('ds.daymode')
    palette = window.localStorage.getItem('ds.palette')
    if (window.localStorage.getItem('ds.defaultPalette') === 'neutral') defaultPalette = 'neutral'
    const stored = window.localStorage.getItem('ds.dim')
    if (stored !== null && Number.isFinite(Number(stored))) {
      dim = Math.max(0.15, Math.min(1, Number(stored)))
    }
  } catch {
    // Storage can be disabled on a shared display.
  }
  const day = lastDay === 'day' || lastDay === 'dusk' ? lastDay : fallback
  const active = mode === 'day' || mode === 'dusk' ? mode : day
  return {
    mode: mode === 'night' ? 'night' : active,
    lastDay: active,
    dim,
    palette: palette === 'red' || palette === 'neutral' ? palette : undefined,
    defaultPalette,
  }
}

export function paintLighting(root: HTMLElement, mode: LightingMode, dim: number, palette: NightPalette) {
  // Leave headroom for antialiasing at the edges of text and chart strokes.
  const redFg = [255, 38, 16]
  const redMuted = [150, 24, 10]
  const red = {
    bg: [0, 0, 0], panel: [5, 0, 0], panel2: [10, 0, 0], line: [70, 8, 4],
    fg: redFg, muted: redMuted, accent: redFg, ok: redFg, check: redFg,
    stale: redMuted, down: [255, 60, 30], chart: redFg, grid: [40, 4, 2],
    missing: redMuted, 'scroll-thumb': redMuted,
  }
  const neutralFg = [224, 224, 224]
  const neutral = {
    bg: [0, 0, 0], panel: [8, 8, 8], panel2: [17, 17, 17], line: [70, 70, 70],
    fg: neutralFg, muted: [184, 184, 184], accent: neutralFg, ok: [114, 180, 134],
    check: [255, 212, 90], stale: [160, 160, 160], down: [255, 90, 90],
    chart: neutralFg, grid: [40, 40, 40], missing: [141, 141, 141], 'scroll-thumb': [184, 184, 184],
  }
  const night = palette === 'neutral' ? neutral : red
  root.dataset.mode = mode
  root.dataset.nightPalette = palette
  root.style.colorScheme = mode === 'day' ? 'light' : 'dark'
  for (const [token, [r, g, b]] of Object.entries(night)) {
    if (mode !== 'night') {
      root.style.removeProperty('--' + token)
      continue
    }
    const scale = token === 'bg' || token === 'panel' || token === 'panel2' ? 1 : dim
    const redChannel = Math.round(r * scale)
    const ceiling = palette === 'red' ? Math.floor(0.075 * redChannel) : 255
    const green = Math.min(Math.round(g * scale), ceiling)
    const blue = Math.min(Math.round(b * scale), ceiling)
    root.style.setProperty('--' + token, 'rgb(' + redChannel + ',' + green + ',' + blue + ')')
  }
  const background = { day: '#e9eef0', dusk: '#081014', night: '#000000' }
  // Set the page background before external CSS has loaded.
  root.style.backgroundColor = background[mode]
}
