import type { ConsoleContext, LightingMode } from '../../contract'
import { sunElevation } from './sun'

type SolarZone = 'day' | 'night'
type Elevation = (time: number, latitude: number, longitude: number) => number

const statusByContext = new WeakMap<ConsoleContext, AutoNight>()
const statusListeners = new WeakMap<ConsoleContext, Set<() => void>>()

function setting(ctx: ConsoleContext, name: string, fallback: string): string {
  const value = ctx.config.modules['kiosk-night']?.[name]
  return typeof value === 'string' && value ? value : fallback
}

export class AutoNight {
  private readonly ctx: ConsoleContext
  private elevation: Elevation
  private zone?: SolarZone
  private manualOverride = false
  private applying = false
  private message = ''
  private observedMode: LightingMode
  private stopStore?: () => void
  private stopLighting?: () => void
  private timer?: ReturnType<typeof setInterval>

  constructor(ctx: ConsoleContext, elevation: Elevation = sunElevation) {
    this.ctx = ctx
    this.elevation = elevation
    this.observedMode = ctx.lighting.get().mode
  }

  start(): () => void {
    const latitude = setting(this.ctx, 'latitude_field', 'S330Latitude')
    const longitude = setting(this.ctx, 'longitude_field', 'S330Longitude')
    this.stopStore = this.ctx.store.subscribe([latitude, longitude], () => this.sample())
    this.stopLighting = this.ctx.lighting.subscribe(() => {
      const mode = this.ctx.lighting.get().mode
      if (!this.applying && mode !== this.observedMode) this.manualOverride = true
      this.observedMode = mode
    })
    statusByContext.set(this.ctx, this)
    this.sample()
    this.timer = setInterval(() => this.sample(), 60_000)
    return () => this.stop()
  }

  sample(nextElevation?: Elevation): void {
    const latitudeState = this.ctx.store.get(setting(this.ctx, 'latitude_field', 'S330Latitude'))
    const longitudeState = this.ctx.store.get(setting(this.ctx, 'longitude_field', 'S330Longitude'))
    if (latitudeState.freshness === 'STALE' || latitudeState.freshness === 'NO_DATA'
      || longitudeState.freshness === 'STALE' || longitudeState.freshness === 'NO_DATA'
      || typeof latitudeState.value !== 'number' || typeof longitudeState.value !== 'number') {
      this.setStatus('Auto Night paused: position unavailable')
      return
    }
    this.setStatus('')
    const elevation = (nextElevation ?? this.elevation)(this.ctx.clock.now(), latitudeState.value, longitudeState.value)
    let nextZone = this.zone
    if (elevation < -6) nextZone = 'night'
    else if (elevation > -5.5) nextZone = 'day'
    if (!nextZone) return
    const crossed = this.zone !== undefined && nextZone !== this.zone
    this.zone = nextZone
    if (crossed) this.manualOverride = false
    if (!this.manualOverride) this.setMode(nextZone)
  }

  status(): string { return this.message }

  private setMode(mode: LightingMode): void {
    if (this.ctx.lighting.get().mode === mode) return
    this.applying = true
    this.ctx.lighting.set({ mode })
    this.observedMode = mode
    this.applying = false
  }

  private setStatus(message: string): void {
    if (message === this.message) return
    this.message = message
    statusListeners.get(this.ctx)?.forEach((listener) => listener())
  }

  private stop(): void {
    this.stopStore?.()
    this.stopLighting?.()
    if (this.timer) clearInterval(this.timer)
    statusByContext.delete(this.ctx)
  }
}

export function autoNightStatus(ctx: ConsoleContext): string {
  return statusByContext.get(ctx)?.status() ?? ''
}

export function subscribeAutoNightStatus(ctx: ConsoleContext, listener: () => void): () => void {
  let listeners = statusListeners.get(ctx)
  if (!listeners) {
    listeners = new Set()
    statusListeners.set(ctx, listeners)
  }
  listeners.add(listener)
  return () => listeners?.delete(listener)
}

export function startAutoNight(ctx: ConsoleContext): () => void {
  if (ctx.config.modules['kiosk-night']?.auto_night !== true) return () => undefined
  return new AutoNight(ctx).start()
}
