import { useEffect, useMemo, useRef, useState } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import './chart.css'
import type { ConsoleContext, ConsoleModule, PageProblem, PageWhere, Quality, TileConfig } from '../../contract'

interface ChartConfig extends TileConfig {
  field: string
  label: string
  unit: string
  decimals: number
  window: string
  windowS: number
  period?: number
  size: 'normal' | 'large'
}

interface Sample { time: number; value: unknown }
interface QualitySample { time: number; quality: Quality }

export interface ChartData {
  times: number[]
  values: Array<number | null>
  markerValues: Array<number | null>
  markers: number[]
  range: [number, number]
}

export function parseWindow(value: unknown): number | undefined {
  if (typeof value !== 'string') return undefined
  const match = /^(\d+(?:\.\d+)?)\s*(min|h)$/.exec(value.trim())
  if (!match) return undefined
  const seconds = Number(match[1]) * (match[2] === 'h' ? 3600 : 60)
  return seconds > 0 && seconds <= 21_600 ? seconds : undefined
}

function medianInterval(samples: Sample[]): number | undefined {
  if (samples.length < 2) return undefined
  // The store defines its inferred period from the most recent 20 intervals.
  // Keeping the same bounded sample also makes the six-hour redraw cost linear.
  const count = Math.min(samples.length - 1, 20)
  const intervals = new Array<number>(count)
  for (let offset = 0; offset < count; offset += 1) {
    const index = samples.length - count + offset
    intervals[offset] = samples[index].time - samples[index - 1].time
  }
  intervals.sort((a, b) => a - b)
  return intervals[Math.floor(intervals.length / 2)]
}

export function buildChartData(samples: Sample[], qualities: QualitySample[], period?: number): ChartData {
  const times = new Array<number>(samples.length)
  const values = new Array<number | null>(samples.length)
  const markerValues = new Array<number | null>(samples.length)
  const markers: number[] = []
  const interval = medianInterval(samples) ?? period
  let qualityIndex = 0
  let quality: Quality = 'NOT_EVALUATED'
  let minimum = Infinity
  let maximum = -Infinity
  let outputIndex = 0

  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index]
    const number = typeof sample.value === 'number' && Number.isFinite(sample.value) ? sample.value : null
    const previous = samples[index - 1]
    if (previous && interval !== undefined && sample.time - previous.time > 3 * interval) {
      times[outputIndex] = (previous.time + sample.time) / 2
      values[outputIndex] = null
      markerValues[outputIndex] = null
      outputIndex += 1
    }
    while (qualityIndex < qualities.length && qualities[qualityIndex].time <= sample.time) {
      quality = qualities[qualityIndex].quality
      qualityIndex += 1
    }
    times[outputIndex] = sample.time
    values[outputIndex] = number
    const affected = quality === 'SUSPECT' || quality === 'FAIL'
    markerValues[outputIndex] = affected ? number : null
    outputIndex += 1
    if (affected) markers.push(sample.time)
    if (number !== null) {
      minimum = Math.min(minimum, number)
      maximum = Math.max(maximum, number)
    }
  }
  if (!Number.isFinite(minimum)) return { times, values, markerValues, markers, range: [0, 1] }
  const span = maximum - minimum
  const margin = (span || Math.max(Math.abs(minimum), 1)) * 0.12
  return { times, values, markerValues, markers, range: [minimum - margin, maximum + margin] }
}

function problem(where: PageWhere, setting: string, saw: unknown, expected: string, example: string): never {
  throw { where, setting, saw: String(saw), expected, example } satisfies PageProblem
}

function validate(raw: Record<string, unknown>, where: PageWhere): ChartConfig {
  if (typeof raw.field !== 'string' || !raw.field.trim()) problem(where, 'field', raw.field, 'a field name', 'TsgTemp')
  const windowS = parseWindow(raw.window)
  if (windowS === undefined) problem(where, 'window', raw.window, 'a duration up to 6 h using min or h', '30 min')
  if (raw.period !== undefined && (typeof raw.period !== 'number' || raw.period <= 0)) problem(where, 'period', raw.period, 'a positive number of seconds', '1')
  if (raw.decimals !== undefined && (!Number.isInteger(raw.decimals) || Number(raw.decimals) < 0 || Number(raw.decimals) > 8)) problem(where, 'decimals', raw.decimals, 'an integer from 0 to 8', '2')
  if (raw.size !== undefined && raw.size !== 'normal' && raw.size !== 'large') problem(where, 'size', raw.size, 'normal or large', 'large')
  return {
    ...raw, type: 'chart', field: raw.field as string,
    label: typeof raw.label === 'string' ? raw.label : raw.field as string,
    unit: typeof raw.unit === 'string' ? raw.unit : '', decimals: raw.decimals === undefined ? 2 : Number(raw.decimals),
    window: raw.window as string, windowS, period: raw.period as number | undefined,
    size: raw.size === 'large' ? 'large' : 'normal', wide: raw.wide === true,
  }
}

function cssToken(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function Chart({ cfg, ctx }: { cfg: TileConfig; ctx: ConsoleContext }) {
  const config = cfg as ChartConfig
  const container = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  const [revision, setRevision] = useState(0)
  const state = ctx.store.get(config.field)
  const data = useMemo(() => {
    const qualityHistory = ctx.store.history(`${config.field}${ctx.config.qcSuffix}`, config.windowS)
      .map(({ time, value }) => ({ time, quality: value === 1 ? 'PASS' : value === 3 ? 'SUSPECT' : value === 4 ? 'FAIL' : 'NOT_EVALUATED' }) as QualitySample)
    return buildChartData(ctx.store.history(config.field, config.windowS), qualityHistory, config.period)
  }, [config.field, config.period, config.windowS, ctx, revision])

  useEffect(() => ctx.store.subscribe([config.field, `${config.field}${ctx.config.qcSuffix}`], () => setRevision((value) => value + 1)), [config.field, ctx])

  useEffect(() => {
    const element = container.current
    if (!element) return
    const instance = new uPlot({
      width: Math.max(element.clientWidth, 1), height: config.size === 'large' ? 260 : 190,
      legend: { show: false }, cursor: { show: false }, axes: [{ show: false }, { show: false }],
      scales: { x: { time: true }, y: { range: () => data.range } },
      series: [
        {},
        { stroke: () => cssToken('--chart'), width: 2, spanGaps: false, points: { show: false } },
        { stroke: () => cssToken('--check'), width: 0, spanGaps: false,
          points: { show: true, size: 7, width: 2, stroke: () => cssToken('--check'), fill: () => cssToken('--panel') } },
      ],
      padding: [8, 5, 8, 5],
    }, [data.times, data.values, data.markerValues], element)
    plot.current = instance
    const Resize = globalThis.ResizeObserver
    const resize = Resize ? new Resize(([entry]) => instance.setSize({ width: Math.max(1, Math.floor(entry.contentRect.width)), height: config.size === 'large' ? 260 : 190 })) : undefined
    resize?.observe(element)
    return () => { resize?.disconnect(); instance.destroy(); plot.current = null }
  }, [config.size])

  useEffect(() => {
    plot.current?.setData([data.times, data.values, data.markerValues], false)
    plot.current?.setScale('x', { min: ctx.clock.now() - config.windowS, max: ctx.clock.now() })
    plot.current?.setScale('y', { min: data.range[0], max: data.range[1] })
    plot.current?.redraw()
  }, [config.windowS, ctx, data])

  useEffect(() => ctx.lighting.subscribe(() => plot.current?.redraw()), [ctx])

  const noData = state.freshness === 'STALE' || state.freshness === 'NO_DATA'
  const current = typeof state.value === 'number' ? state.value.toFixed(config.decimals) : '—'
  return <section className={`chart-tile chart-tile--${config.size}${config.wide ? ' chart-tile--wide' : ''}`} aria-label={config.label}>
    <header><h2>{config.label}</h2><span className="chart-source">{config.field}</span></header>
    <div className="chart-current"><strong>{current}</strong> <span>{config.unit || 'unit not reported'}</span></div>
    <div className="chart-status"><span data-state={state.quality}>◇ {state.quality.replace('_', ' ')}</span><span>□ {state.freshness.replace('_', ' ')}</span></div>
    <div className="chart-plot-wrap">
      <div className="chart-range"><span>{data.range[1].toFixed(config.decimals)} {config.unit}</span><span>{data.range[0].toFixed(config.decimals)} {config.unit}</span></div>
      <div className="chart-plot" ref={container} aria-label={`${config.label} history`} />
      {noData && <span className="chart-no-data">NO DATA</span>}
    </div>
  </section>
}

const science = `title: Science
order: 20
tiles:
  - { type: chart, field: TsgTemp, label: Sea surface temperature, unit: degC, decimals: 2, window: 30 min, wide: true }
  - { type: chart, field: TsgSal, label: Salinity, unit: PSU, decimals: 3, window: 30 min, wide: true }
  - { type: chart, field: FlrChl, label: Fluorescence, unit: ug/L, decimals: 3, window: 30 min, wide: true }
  - { type: chart, field: Knud3Depth, label: Depth, unit: m, decimals: 1, window: 30 min, wide: true }
`

const module: ConsoleModule = {
  id: 'chart',
  tiles: [{ type: 'chart', validate, fields: (cfg, ctx) => [(cfg as ChartConfig).field, `${(cfg as ChartConfig).field}${ctx.config.qcSuffix}`], Component: Chart }],
  presets: [{ id: 'science', yaml: science }],
}

export default module
