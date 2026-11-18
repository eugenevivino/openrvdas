import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, MouseEvent as ReactMouseEvent } from 'react'
import type { ConsoleContext, ConsoleModule, FieldState, PageProblem, PageWhere, TileConfig, TileDef } from '../../contract/index.ts'
import { latLonToPixel, medianInterval, TILE_SIZE } from './mercator.ts'

interface MapConfig extends TileConfig {
  lat: string
  lon: string
  window: string
  color_by?: string
  events?: string[]
  heading?: string
  tiles?: string
  zoom?: number | 'auto'
}

export interface TrackPoint { time: number, lat: number, lon: number, segmentStart: boolean }

function numeric(value: unknown): number | undefined {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : undefined
}

export function pairTrack(latitudes: Array<{ time: number, value: unknown }>, longitudes: Array<{ time: number, value: unknown }>): TrackPoint[] {
  const longitudeByTime = new Map(longitudes.map((sample) => [sample.time, numeric(sample.value)]))
  const valid = latitudes.flatMap((sample) => {
    const lat = numeric(sample.value)
    const lon = longitudeByTime.get(sample.time)
    return lat === undefined || lon === undefined ? [] : [{ time: sample.time, lat, lon }]
  })
  const median = medianInterval(valid.map((point) => ({ time: point.time, value: point.lat })))
  return valid.map((point, index) => ({ ...point, segmentStart: index === 0 || (median !== undefined && point.time - valid[index - 1].time > 3 * median) }))
}

export function colorDomain<T extends { value: unknown }>(samples: T[]): [number, number] | undefined {
  const values = samples.map((sample) => numeric(sample.value)).filter((value): value is number => value !== undefined)
  return values.length ? [Math.min(...values), Math.max(...values)] : undefined
}

export function fillTileTemplate(template: string, zoom: number, x: number, y: number): string {
  return template.replaceAll('{z}', String(zoom)).replaceAll('{x}', String(x)).replaceAll('{y}', String(y))
}

function windowSeconds(value: string): number {
  const match = /^\s*(\d+(?:\.\d+)?)\s*(s|m|h|d)\s*$/i.exec(value)
  if (!match) return 7200
  return Number(match[1]) * ({ s: 1, m: 60, h: 3600, d: 86400 }[match[2].toLowerCase()] ?? 1)
}

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function ageWords(seconds: number | undefined): string {
  if (seconds === undefined) return 'unknown age'
  if (seconds < 60) return `${Math.round(seconds)} sec`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${Math.round(seconds / 3600)} h`
}

function stateWords(state: FieldState): string {
  return `${state.quality.replaceAll('_', ' ').toLowerCase()}, ${state.freshness.toLowerCase()}`
}

function interpolateColor(start: string, end: string, amount: number): string {
  const canvas = document.createElement('canvas').getContext('2d')
  if (!canvas) return start
  canvas.fillStyle = start
  const first = canvas.fillStyle
  canvas.fillStyle = end
  const second = canvas.fillStyle
  const parse = (value: string) => value.startsWith('#') ? [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16)) : (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
  const a = parse(first), b = parse(second)
  if (a.length < 3 || b.length < 3) return amount < 0.5 ? start : end
  return `rgb(${a.map((part, index) => Math.round(part + (b[index] - part) * amount)).join(' ')})`
}

function autoZoom(track: TrackPoint[]): number {
  if (track.length < 2) return 8
  const latitudeSpan = Math.max(...track.map((point) => point.lat)) - Math.min(...track.map((point) => point.lat))
  const longitudeSpan = Math.max(...track.map((point) => point.lon)) - Math.min(...track.map((point) => point.lon))
  const span = Math.max(latitudeSpan, longitudeSpan, 0.001)
  return Math.max(1, Math.min(16, Math.floor(Math.log2(180 / span)) - 1))
}

function drawGraticule(context: CanvasRenderingContext2D, width: number, height: number, center: TrackPoint | undefined) {
  context.fillStyle = token('--panel')
  context.fillRect(0, 0, width, height)
  context.strokeStyle = token('--grid')
  context.fillStyle = token('--muted')
  context.font = `16px ${token('--f-mono')}`
  for (let x = 0; x <= width; x += width / 4) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke() }
  for (let y = 0; y <= height; y += height / 4) { context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke() }
  if (center) context.fillText(`${center.lat.toFixed(2)}°, ${center.lon.toFixed(2)}°`, 12, 24)
}

function loadTiles(context: CanvasRenderingContext2D, template: string, zoom: number, center: { x: number, y: number }, width: number, height: number, night: boolean) {
  const firstX = Math.floor((center.x - width / 2) / TILE_SIZE)
  const firstY = Math.floor((center.y - height / 2) / TILE_SIZE)
  const lastX = Math.floor((center.x + width / 2) / TILE_SIZE)
  const lastY = Math.floor((center.y + height / 2) / TILE_SIZE)
  for (let x = firstX; x <= lastX; x += 1) for (let y = firstY; y <= lastY; y += 1) {
    const image = new Image()
    image.onload = () => {
      context.drawImage(image, x * TILE_SIZE - center.x + width / 2, y * TILE_SIZE - center.y + height / 2)
      if (night) { context.globalAlpha = 0.58; context.fillStyle = token('--bg'); context.fillRect(0, 0, width, height); context.globalAlpha = 1 }
    }
    image.onerror = () => { /* A missing offline tile intentionally leaves the token background. */ }
    image.src = fillTileTemplate(template, zoom, x, y)
  }
}

export function MapTile({ cfg, ctx }: { cfg: TileConfig, ctx: ConsoleContext }) {
  const config = cfg as MapConfig
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [, redraw] = useState(0)
  const [tooltip, setTooltip] = useState<TrackPoint>()
  const seconds = windowSeconds(config.window)
  const track = useMemo(() => pairTrack(ctx.store.history(config.lat, seconds), ctx.store.history(config.lon, seconds)), [ctx, config.lat, config.lon, seconds])
  const colorSamples = config.color_by ? ctx.store.history(config.color_by, seconds) : []
  const eventSamples = (config.events ?? []).flatMap((field) => ctx.store.history(field, seconds).map((sample) => ({ ...sample, field })))
  const domain = colorDomain(colorSamples)
  const colorByTime = new Map(colorSamples.map((sample) => [sample.time, numeric(sample.value)]))
  const position = ctx.store.get(config.lat)
  const positionStale = position.freshness === 'STALE' || position.freshness === 'NO_DATA'

  useEffect(() => {
    const fields = [config.lat, config.lon, config.color_by, config.heading, ...(config.events ?? [])].filter((field): field is string => Boolean(field))
    return ctx.store.subscribe(fields, () => redraw((value) => value + 1))
  }, [config, ctx])
  useEffect(() => ctx.lighting.subscribe(() => redraw((value) => value + 1)), [ctx])

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    const width = canvas.clientWidth || 640, height = canvas.clientHeight || 360
    canvas.width = width * devicePixelRatio; canvas.height = height * devicePixelRatio
    context.scale(devicePixelRatio, devicePixelRatio)
    const latest = track.at(-1)
    const zoom = config.zoom === undefined || config.zoom === 'auto' ? autoZoom(track) : config.zoom
    const center = latest ? latLonToPixel(latest.lat, latest.lon, zoom) : { x: 0, y: 0 }
    drawGraticule(context, width, height, latest)
    if (config.tiles) loadTiles(context, config.tiles, zoom, center, width, height, ctx.lighting.get().mode === 'night')
    const start = token('--chart'), end = token('--accent')
    track.forEach((point, index) => {
      if (!index || point.segmentStart) return
      const previous = track[index - 1]
      const a = latLonToPixel(previous.lat, previous.lon, zoom), b = latLonToPixel(point.lat, point.lon, zoom)
      const value = colorByTime.get(point.time)
      const ratio = value !== undefined && domain && domain[1] !== domain[0] ? (value - domain[0]) / (domain[1] - domain[0]) : 0
      context.strokeStyle = interpolateColor(start, end, ratio); context.lineWidth = 3; context.beginPath()
      context.moveTo(a.x - center.x + width / 2, a.y - center.y + height / 2)
      context.lineTo(b.x - center.x + width / 2, b.y - center.y + height / 2); context.stroke()
    })
    for (const event of eventSamples) {
      const point = track.reduce<TrackPoint | undefined>((nearest, candidate) => !nearest || Math.abs(candidate.time - event.time) < Math.abs(nearest.time - event.time) ? candidate : nearest, undefined)
      if (!point) continue
      const pixel = latLonToPixel(point.lat, point.lon, zoom)
      context.strokeStyle = token('--accent'); context.lineWidth = 3
      context.strokeRect(pixel.x - center.x + width / 2 - 6, pixel.y - center.y + height / 2 - 6, 12, 12)
    }
    if (latest) {
      context.save(); context.translate(width / 2, height / 2)
      const heading = config.heading ? numeric(ctx.store.get(config.heading).value) ?? 0 : 0
      context.rotate(heading * Math.PI / 180); context.strokeStyle = token(positionStale ? '--stale' : '--fg'); context.fillStyle = token('--fg'); context.lineWidth = 3
      context.beginPath(); context.moveTo(0, -15); context.lineTo(11, 12); context.lineTo(0, 7); context.lineTo(-11, 12); context.closePath()
      if (positionStale) context.stroke()
      else context.fill()
      context.restore()
    }
  }, [track, colorSamples, domain, config, ctx, eventSamples, positionStale])

  function showNearest(event: ReactMouseEvent<HTMLButtonElement>) {
    if (!track.length) return
    const ratio = Math.max(0, Math.min(1, event.nativeEvent.offsetX / event.currentTarget.clientWidth))
    setTooltip(track[Math.round(ratio * (track.length - 1))])
  }
  const selectedValue = tooltip && config.color_by ? colorByTime.get(tooltip.time) : undefined
  const selectedState = config.color_by ? ctx.store.get(config.color_by) : undefined
  const selectedEvents = tooltip ? eventSamples.filter((event) => Math.abs(event.time - tooltip.time) <= 1) : []
  const units = config.color_by ? ctx.store.describe(config.color_by)?.units ?? 'unit unknown' : undefined
  return <section style={styles.root}>
    <canvas ref={canvasRef} aria-hidden="true" style={styles.canvas} />
    <button type="button" aria-label="Ship track map" onClick={showNearest} style={styles.hitTarget} />
    {domain && config.color_by && <div style={styles.legend}>{domain[0].toFixed(2)}–{domain[1].toFixed(2)} {units}</div>}
    {positionStale && <div style={styles.state}>□ Position stale {ageWords(position.ageS)}</div>}
    {tooltip && <div role="status" style={styles.tooltip}>
      <div>{new Date(tooltip.time * 1000).toISOString().replace('.000', '')}</div>
      <div>{tooltip.lat.toFixed(5)}°, {tooltip.lon.toFixed(5)}°</div>
      {selectedValue !== undefined && selectedState && <div>{selectedValue.toFixed(2)} {units} · {stateWords(selectedState)}</div>}
      {selectedEvents.map((event) => <div key={`${event.field}-${event.time}`}>□ {event.field}: {String(event.value)}</div>)}
    </div>}
  </section>
}

const styles: Record<string, CSSProperties> = {
  root: { position: 'relative', minHeight: 360, overflow: 'hidden', background: 'var(--panel)', color: 'var(--fg)', fontFamily: 'var(--f-body)' },
  canvas: { width: '100%', height: 360, display: 'block' },
  hitTarget: { position: 'absolute', inset: 0, width: '100%', height: '100%', border: 0, padding: 0, background: 'transparent', cursor: 'crosshair' },
  legend: { position: 'absolute', left: 12, bottom: 12, minHeight: 44, padding: '10px 14px', background: 'var(--panel2)', border: '2px solid var(--line)', fontFamily: 'var(--f-number)', fontSize: 18 },
  state: { position: 'absolute', right: 12, top: 12, minHeight: 44, padding: '10px 14px', background: 'var(--panel2)', border: '2px solid var(--stale)', fontSize: 18 },
  tooltip: { position: 'absolute', right: 12, bottom: 12, padding: 12, background: 'var(--panel2)', border: '2px solid var(--line)', fontFamily: 'var(--f-mono)', fontSize: 16, pointerEvents: 'none' },
}

function problem(where: PageWhere, setting: string, saw: unknown, expected: string, example: string): PageProblem {
  return { where, setting, saw: JSON.stringify(saw), expected, example }
}

function validate(raw: Record<string, unknown>, where: PageWhere): MapConfig {
  const cfg: Record<string, unknown> = { ...raw, type: 'map', lat: raw.lat ?? 'S330Latitude', lon: raw.lon ?? 'S330Longitude', window: raw.window ?? '2 h' }
  for (const key of ['lat', 'lon', 'window'] as const) if (typeof cfg[key] !== 'string') throw problem(where, key, cfg[key], 'a field name or duration string', key === 'window' ? '2 h' : 'S330Latitude')
  for (const key of ['color_by', 'heading', 'tiles'] as const) if (cfg[key] !== undefined && typeof cfg[key] !== 'string') throw problem(where, key, cfg[key], 'a string', 'TsgTemp')
  if (cfg.events !== undefined && (!Array.isArray(cfg.events) || cfg.events.some((field) => typeof field !== 'string'))) throw problem(where, 'events', cfg.events, 'a list of field names', '[event:log]')
  if (cfg.zoom !== undefined && cfg.zoom !== 'auto' && (typeof cfg.zoom !== 'number' || cfg.zoom < 0 || cfg.zoom > 22)) throw problem(where, 'zoom', cfg.zoom, 'auto or a number from 0 to 22', '8')
  return cfg as MapConfig
}

const tile: TileDef = {
  type: 'map', validate,
  fields: (raw) => { const cfg = raw as MapConfig; return [cfg.lat, cfg.lon, cfg.color_by, cfg.heading, ...(cfg.events ?? [])].filter((field): field is string => Boolean(field)) },
  Component: MapTile,
}

const mapModule: ConsoleModule = { id: 'map', tiles: [tile] }
export default mapModule
