import { useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties, MouseEvent as ReactMouseEvent } from 'react'
import { QARTOD_FLAG } from '../../contract/index.ts'
import type { ConsoleContext, ConsoleModule, FieldState, Freshness, PageProblem, PageWhere, Quality, TileConfig, TileDef } from '../../contract/index.ts'
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
  if (typeof value !== 'number' && !(typeof value === 'string' && value.trim())) return undefined
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

const freshnessShape = { LIVE: '●', AGING: '▲', STALE: '□', NO_DATA: '×' } as const
const qualityShape = { PASS: '●', NOT_EVALUATED: '◇', SUSPECT: '▲', FAIL: '×', MISSING: '□' } as const

function stateWords(quality: Quality, freshness: Freshness): string {
  return `${qualityShape[quality]} ${quality.replaceAll('_', ' ').toLowerCase()}, ${freshnessShape[freshness]} ${freshness.replace('_', ' ').toLowerCase()}`
}

function freshnessAt(age: number, period: number): Freshness {
  if (age <= 2 * period) return 'LIVE'
  if (age <= 5 * period) return 'AGING'
  return age <= Math.max(300, 60 * period) ? 'STALE' : 'NO_DATA'
}

type Samples = ReturnType<ConsoleContext['store']['history']>

function measurementHistory(samples: Samples, flags: Samples) {
  const byTime = new Map<number, { value: number | undefined; quality: Quality }>()
  let flagIndex = 0
  samples.forEach((sample, index) => {
    const nextTime = samples[index + 1]?.time ?? Infinity
    // Match the store: a later flag belongs to this reading until the next reading arrives.
    let flag: (typeof flags)[number] | undefined
    while (flagIndex < flags.length && flags[flagIndex].time < nextTime) flag = flags[flagIndex++]
    const quality = flag && flag.time >= sample.time && typeof flag.value === 'number'
      ? QARTOD_FLAG[flag.value] ?? 'NOT_EVALUATED' : 'NOT_EVALUATED'
    const value = quality === 'MISSING' ? undefined : numeric(sample.value)
    byTime.set(sample.time, { value, quality })
  })
  return byTime
}

function coordinateHistory(ctx: ConsoleContext, field: string, seconds: number): Samples {
  const readings = measurementHistory(ctx.store.history(field, seconds), ctx.store.history(field + ctx.config.qcSuffix, seconds))
  return Array.from(readings, ([time, { value, quality }]) => ({ time, value: quality === 'FAIL' ? undefined : value }))
}

function positionNotice(states: FieldState[], latest: TrackPoint | undefined, now: number) {
  const quality = states.some((state) => state.quality === 'FAIL') ? 'FAIL'
    : states.some((state) => state.quality === 'MISSING') ? 'MISSING'
      : states.some((state) => state.quality === 'SUSPECT') ? 'SUSPECT' : undefined
  const qualitySuffix = quality ? ` · ${quality}` : ''
  if (!latest) {
    const staleAges = states.flatMap(({ freshness, ageS }) =>
      ageS !== undefined && (freshness === 'STALE' || freshness === 'NO_DATA') ? [ageS] : [])
    const agingAges = states.flatMap(({ freshness, ageS }) =>
      ageS !== undefined && freshness === 'AGING' ? [ageS] : [])
    const coordinates = staleAges.length ? ` · Coordinates stale ${ageWords(Math.max(...staleAges))}`
      : agingAges.length ? ` · Coordinates aging ${ageWords(Math.max(...agingAges))}` : ''
    if (quality === 'FAIL') return `× Position FAIL${coordinates}`
    if (quality === 'MISSING') return `□ Position MISSING${coordinates}`
    if (states.some(({ sourceTime, value }) => sourceTime !== undefined && numeric(value) === undefined)) {
      return `□ Position MISSING${qualitySuffix}${coordinates}`
    }
    return `× Position NO DATA${qualitySuffix}${coordinates}`
  }
  const words = ageWords(Math.max(0, now - latest.time, ...states.map((state) => state.ageS ?? 0)))
  if (states.some((state) => state.freshness === 'NO_DATA')) return `× Position stale ${words} · NO DATA${qualitySuffix}`
  if (states.some((state) => state.freshness === 'STALE')) return `□ Position stale ${words}${qualitySuffix}`
  if (states.some((state) => state.freshness === 'AGING')) return `▲ Position aging ${words}${qualitySuffix}`
  if (quality === 'FAIL') return '× Position FAIL'
  if (quality === 'MISSING' || states.some((state) => numeric(state.value) === undefined)) return '□ Position MISSING'
  if (states.some((state) => state.sourceTime !== latest.time)) return `□ Waiting for a matched position · ${words}${qualitySuffix}`
  if (quality === 'SUSPECT') return '▲ Position SUSPECT'
  return undefined
}

function colorScale(context: CanvasRenderingContext2D) {
  const start = token('--chart')
  const end = token('--accent')
  if (start === end) return () => start
  const parse = (value: string) => value.startsWith('#') ? [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16)) : (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
  context.fillStyle = start
  const a = parse(context.fillStyle)
  context.fillStyle = end
  const b = parse(context.fillStyle)
  if (a.length < 3 || b.length < 3) return (amount: number) => amount < 0.5 ? start : end
  return (amount: number) => `rgb(${a.map((part, index) => Math.round(part + (b[index] - part) * amount)).join(' ')})`
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

function loadTiles(context: CanvasRenderingContext2D, cache: Map<string, HTMLImageElement>, template: string,
  zoom: number, center: { x: number, y: number }, width: number, height: number) {
  const firstX = Math.floor((center.x - width / 2) / TILE_SIZE)
  const firstY = Math.floor((center.y - height / 2) / TILE_SIZE)
  const lastX = Math.floor((center.x + width / 2) / TILE_SIZE)
  const lastY = Math.floor((center.y + height / 2) / TILE_SIZE)
  const visible = new Set<string>()
  for (let x = firstX; x <= lastX; x += 1) for (let y = firstY; y <= lastY; y += 1) {
    const key = `${zoom}/${x}/${y}/${template}`
    visible.add(key)
    const cached = cache.get(key)
    const image = cached ?? new Image()
    const draw = () => context.drawImage(image, x * TILE_SIZE - center.x + width / 2, y * TILE_SIZE - center.y + height / 2)
    if (cached && image.complete) {
      if (image.naturalWidth > 0) draw()
    } else {
      image.onload = draw
    }
    if (!cached) {
      cache.set(key, image)
      image.src = fillTileTemplate(template, zoom, x, y)
    }
  }
  for (const key of cache.keys()) if (!visible.has(key)) cache.delete(key)
  return () => { for (const image of cache.values()) image.onload = null }
}

function mapFields(config: MapConfig, ctx: ConsoleContext) {
  const flag = (field: string) => field + ctx.config.qcSuffix
  return [config.lat, flag(config.lat), config.lon, flag(config.lon), config.color_by,
    config.color_by && flag(config.color_by), config.heading, ...(config.events ?? [])]
    .filter((field): field is string => Boolean(field))
}

function canvasSize(canvas: HTMLCanvasElement) {
  return { width: canvas.clientWidth || 640, height: canvas.clientHeight || 360 }
}

const rasterRedMatrix = '0.2126 0.7152 0.0722 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0'

export function MapTile({ cfg, ctx }: { cfg: TileConfig, ctx: ConsoleContext }) {
  const config = cfg as MapConfig
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rasterRef = useRef<HTMLCanvasElement>(null)
  const rasterTiles = useRef(new Map<string, HTMLImageElement>())
  const rasterFilter = useId()
  const [, redraw] = useState(0)
  const [{ width, height }, setSize] = useState({ width: 640, height: 360 })
  const [selectedTime, setSelectedTime] = useState<number>()
  const seconds = windowSeconds(config.window)
  const now = ctx.clock.now()
  const track = pairTrack(coordinateHistory(ctx, config.lat, seconds), coordinateHistory(ctx, config.lon, seconds))
  const latest = track.at(-1)
  const zoom = config.zoom === undefined || config.zoom === 'auto' ? autoZoom(track) : config.zoom
  const center = latest ? latLonToPixel(latest.lat, latest.lon, zoom) : { x: 0, y: 0 }
  const colorSamples = config.color_by ? measurementHistory(ctx.store.history(config.color_by, seconds),
    ctx.store.history(config.color_by + ctx.config.qcSuffix, seconds)) : undefined
  const eventSamples = (config.events ?? []).flatMap((field) => ctx.store.history(field, seconds).map((sample) => ({ ...sample, field })))
  const domain = colorSamples && colorDomain([...colorSamples.values()])
  const positionState = positionNotice([ctx.store.get(config.lat), ctx.store.get(config.lon)], latest, now)
  const lighting = ctx.lighting.get()
  const night = lighting.mode === 'night'

  useEffect(() => ctx.store.subscribe(mapFields(config, ctx), () => redraw((value) => value + 1)), [config, ctx])
  useEffect(() => ctx.lighting.subscribe(() => redraw((value) => value + 1)), [ctx])
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const resize = () => setSize(canvasSize(canvas))
    resize()
    if (!globalThis.ResizeObserver) return
    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [])

  const { x: centerX, y: centerY } = center
  const hasTrack = latest !== undefined
  useEffect(() => {
    const canvas = rasterRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context || !config.tiles || !hasTrack) return
    canvas.width = width * devicePixelRatio
    canvas.height = height * devicePixelRatio
    context.scale(devicePixelRatio, devicePixelRatio)
    return loadTiles(context, rasterTiles.current, config.tiles, zoom, { x: centerX, y: centerY }, width, height)
  }, [config.tiles, zoom, centerX, centerY, hasTrack, width, height])

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    canvas.width = width * devicePixelRatio; canvas.height = height * devicePixelRatio
    context.scale(devicePixelRatio, devicePixelRatio)
    if (!config.tiles) drawGraticule(context, width, height, latest)
    const segmentColor = colorScale(context)
    track.forEach((point, index) => {
      if (!index || point.segmentStart) return
      const previous = track[index - 1]
      const a = latLonToPixel(previous.lat, previous.lon, zoom), b = latLonToPixel(point.lat, point.lon, zoom)
      const value = colorSamples?.get(point.time)?.value
      const ratio = value !== undefined && domain && domain[1] !== domain[0] ? (value - domain[0]) / (domain[1] - domain[0]) : 0
      context.strokeStyle = segmentColor(ratio); context.lineWidth = 3; context.beginPath()
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
      const headingState = config.heading ? ctx.store.get(config.heading) : undefined
      const heading = headingState?.freshness === 'LIVE' && (headingState.quality === 'PASS' || headingState.quality === 'NOT_EVALUATED')
        ? numeric(headingState.value) : undefined
      context.strokeStyle = token(positionState ? '--stale' : '--fg'); context.fillStyle = token('--fg'); context.lineWidth = 3
      context.beginPath()
      if (heading === undefined) {
        context.arc(0, 0, 7, 0, 2 * Math.PI)
      } else {
        context.rotate(heading * Math.PI / 180)
        context.moveTo(0, -15); context.lineTo(11, 12); context.lineTo(0, 7); context.lineTo(-11, 12); context.closePath()
      }
      if (positionState) context.stroke()
      else context.fill()
      context.restore()
    }
  })

  function showNearest(event: ReactMouseEvent<HTMLButtonElement>) {
    if (!latest) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - bounds.left + center.x - width / 2
    const y = event.clientY - bounds.top + center.y - height / 2
    let nearest = latest
    let distance = Infinity
    for (const point of track) {
      const pixel = latLonToPixel(point.lat, point.lon, zoom)
      const candidateDistance = (pixel.x - x) ** 2 + (pixel.y - y) ** 2
      if (candidateDistance < distance) {
        nearest = point
        distance = candidateDistance
      }
    }
    setSelectedTime(nearest.time)
  }
  const tooltip = track.find((point) => point.time === selectedTime)
  const selected = tooltip && colorSamples?.get(tooltip.time)
  const measurementPeriod = config.color_by ? ctx.store.get(config.color_by).periodS ?? 1 : 1
  const selectedEvents = tooltip ? eventSamples.filter((event) => Math.abs(event.time - tooltip.time) <= 1) : []
  const units = config.color_by ? ctx.store.describe(config.color_by)?.units ?? 'unit unknown' : undefined
  return <section style={styles.root}>
    {config.tiles && latest && <>
      <svg aria-hidden="true" width="0" height="0" style={{ position: 'absolute' }}>
        <filter id={rasterFilter} colorInterpolationFilters="sRGB"><feColorMatrix values={rasterRedMatrix} /></filter>
      </svg>
      <canvas ref={rasterRef} aria-hidden="true" style={{ ...styles.canvas, position: 'absolute', inset: 0,
        opacity: night ? 0.42 * lighting.dim : 1, filter: night && lighting.nightPalette === 'red' ? `url(#${rasterFilter})` : undefined }} />
    </>}
    <canvas ref={canvasRef} aria-hidden="true" style={styles.canvas} />
    <button type="button" aria-label="Ship track map" onClick={showNearest} style={styles.hitTarget} />
    {domain && config.color_by && <div style={styles.legend}>{domain[0].toFixed(2)}–{domain[1].toFixed(2)} {units}</div>}
    {positionState && <div style={styles.state}>{positionState}</div>}
    {tooltip && <div role="status" style={styles.tooltip}>
      <div>{new Date(tooltip.time * 1000).toISOString().replace('.000', '')}</div>
      <div>{tooltip.lat.toFixed(5)}°, {tooltip.lon.toFixed(5)}°</div>
      {config.color_by && <div>{selected?.value?.toFixed(2) ?? '—'} {units} · {stateWords(
        selected?.quality ?? 'MISSING', selected ? freshnessAt(now - tooltip.time, measurementPeriod) : 'NO_DATA')}</div>}
      {selectedEvents.map((event) => <div key={`${event.field}-${event.time}`}>□ {event.field}: {String(event.value)}</div>)}
    </div>}
  </section>
}

const styles: Record<string, CSSProperties> = {
  root: { position: 'relative', minHeight: 360, overflow: 'hidden', background: 'var(--panel)', color: 'var(--fg)', fontFamily: 'var(--f-body)' },
  canvas: { position: 'relative', width: '100%', height: 360, display: 'block' },
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
  fields: (cfg, ctx) => mapFields(cfg as MapConfig, ctx),
  Component: MapTile,
}

const mapModule: ConsoleModule = { id: 'map', tiles: [tile] }
export default mapModule
