import type { ConsoleConfig, ConsoleContext, FieldStore, Lighting, Page } from './contract'
import { paintLighting, readLighting, storeLighting } from './lighting'
import { isMapping, isText } from './settings'

function listeners(channel: string) {
  const callbacks = new Set<() => void>()
  return {
    subscribe(cb: () => void) {
      callbacks.add(cb)
      return () => { callbacks.delete(cb) }
    },
    notify() {
      for (const cb of callbacks) {
        try {
          cb()
        } catch (error) {
          console.error('Console ' + channel + ' subscriber failed.', error)
        }
      }
    },
  }
}

function priority(source: Page['source']) {
  if (source?.startsWith('file:')) return 2
  if (source?.startsWith('preset:')) return 1
  return 0
}

export function createPageRegistry(ids: string[]) {
  const pages = new Map<string, Page>()
  const { subscribe, notify } = listeners('pages')
  return {
    register(page: Page) {
      if (!isMapping(page) || !isText(page.id) || !isText(page.title)) {
        throw new Error('A registered page must have an ID and title.')
      }
      if (!Array.isArray(page.tiles)) throw new Error('Page "' + page.id + '" must have a list of tiles.')
      if (page.source !== undefined && typeof page.source !== 'string') {
        throw new Error('Page "' + page.id + '" must have a text source.')
      }
      if (page.order !== undefined && !Number.isFinite(page.order)) {
        throw new Error('Page "' + page.id + '" must have a numeric order.')
      }
      const previous = pages.get(page.id)
      if (previous && priority(previous.source) > priority(page.source)) return
      pages.set(page.id, page)
      notify()
    },
    list() {
      if (ids.length) return ids.flatMap((id) => pages.get(id) ?? [])
      return [...pages.values()].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    },
    subscribe,
  }
}

export function createAlerts(): ConsoleContext['alerts'] {
  const active = new Map<string, ReturnType<ConsoleContext['alerts']['list']>[number]>()
  const { subscribe, notify } = listeners('alerts')
  return {
    raise(alert) {
      const acked = active.get(alert.id)?.acked
      active.set(alert.id, acked && alert.acked === undefined ? { ...alert, acked } : { ...alert })
      notify()
    },
    clear(id) {
      if (active.delete(id)) notify()
    },
    ack(id) {
      const alert = active.get(id)
      if (!alert || alert.acked) return
      active.set(id, { ...alert, acked: true })
      notify()
    },
    list: () => [...active.values()],
    subscribe,
  }
}

export function createLighting(defaultPalette?: Lighting['nightPalette']) {
  const stored = readLighting()
  let selectedPalette = stored.palette
  const defaultNight = defaultPalette ?? stored.defaultPalette
  let state: Lighting = {
    mode: stored.mode, dayMode: stored.lastDay, nightPalette: selectedPalette ?? defaultNight, dim: stored.dim,
  }
  const { subscribe, notify } = listeners('lighting')
  const paint = () => {
    const { mode, dayMode, nightPalette, dim } = state
    paintLighting(document.documentElement, mode, dim, nightPalette)
    storeLighting({ mode, lastDay: dayMode, palette: selectedPalette, defaultPalette: defaultNight, dim }, defaultPalette)
  }

  return {
    get: () => state,
    set(update: Partial<Lighting>) {
      const mode = update.mode ?? state.mode
      const dayMode = update.dayMode ?? (update.mode && update.mode !== 'night' ? update.mode : state.dayMode)
      if (update.nightPalette) selectedPalette = update.nightPalette
      const nightPalette = selectedPalette ?? defaultNight
      const dim = update.dim !== undefined && Number.isFinite(update.dim)
        ? Math.max(0.15, Math.min(1, update.dim)) : state.dim
      const changed = mode !== state.mode || dayMode !== state.dayMode || nightPalette !== state.nightPalette ||
        dim !== state.dim
      if (changed) state = { mode, dayMode, nightPalette, dim }
      paint()
      if (changed) notify()
    },
    paint,
    subscribe,
  }
}

export const realClock: ConsoleContext['clock'] = { now: () => Date.now() / 1000 }

export function createConsoleContext(config: ConsoleConfig, store: FieldStore, clock = realClock) {
  return {
    config,
    store,
    clock,
    alerts: createAlerts(),
    pages: createPageRegistry(config.pages),
    lighting: createLighting(config.nightPalette),
    route: {
      get() {
        const id = window.location.hash.slice(1)
        try {
          return decodeURIComponent(id)
        } catch {
          return id
        }
      },
      go(id: string) { window.location.hash = encodeURIComponent(id) },
    },
  } satisfies ConsoleContext
}
