import { useId } from 'react'

export interface PlotObservation {
  time: number
  value: unknown
  reason?: string
  source_ref?: string
}

interface Props {
  datasetId: string
  rows: readonly PlotObservation[]
  unit: string | null
  start?: number
  end?: number
  cadenceS?: number | null
  timeBasis?: string
}

const MAX_POINTS = 1000
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const tick = (value: number) => Number(value.toPrecision(6)).toString()
const fraction = (value: number, low: number, high: number) => Number.isFinite(high - low)
  ? (value - low) / (high - low) : (value / 2 - low / 2) / (high / 2 - low / 2)

/** Rendering only: never replaces the frozen rows used by the analysis service. */
export function DatasetPlot({ datasetId, rows, unit, start, end, cadenceS, timeBasis }: Props) {
  const id = useId()
  // Keep missing/nonfinite rows in the ordered presentation: they break a line.
  // An unplaceable timestamp makes continuity unknown for the whole selection.
  const invalidTime = rows.some((row) => !finite(row.time))
  const ordered = rows.filter((row) => finite(row.time)).slice().sort((a, b) => a.time - b.time)
  const limited = ordered.slice(0, MAX_POINTS)
  const points = limited.filter((row): row is PlotObservation & { value: number } => finite(row.value))
  const knownCadence = finite(cadenceS) && cadenceS > 0
  const joinPoints = knownCadence && !invalidTime && rows.length <= MAX_POINTS
  const label = unit ?? 'unit unknown'
  const basis = timeBasis ?? 'time basis unknown; numeric source timestamps'
  const description = joinPoints
    ? `Lines join only consecutive finite records at positive intervals no greater than the declared ${cadenceS} seconds. Missing or nonfinite values and longer gaps break lines.`
    : 'Scatter plot only. No continuity or expected missing samples are inferred.'

  if (points.length === 0) return <figure className="workspace-plot">
    <figcaption>Frozen dataset {datasetId}. Value: {label}. Time: {basis}.</figcaption>
    <p>No finite scalar observations with valid timestamps are available to plot. Original rows and classifications remain in the table.</p>
  </figure>

  const times = points.map((row) => row.time)
  const values = points.map((row) => row.value)
  const first = Math.min(...times)
  const last = Math.max(...times)
  const xMin = finite(start) ? Math.min(start, first) : first
  const xMax = finite(end) ? Math.max(end, last) : last
  const low = Math.min(...values)
  const high = Math.max(...values)
  const left = 76, right = 696, top = 24, bottom = 194
  const x = (time: number) => xMax === xMin ? (left + right) / 2 : left + fraction(time, xMin, xMax) * (right - left)
  const y = (value: number) => high === low ? (top + bottom) / 2 : bottom - fraction(value, low, high) * (bottom - top)
  const paths: string[] = []
  let segment: Array<PlotObservation & { value: number }> = []
  function finishSegment() {
    if (segment.length >= 2) paths.push(segment.map((row, i) => `${i ? 'L' : 'M'}${x(row.time)},${y(row.value)}`).join(' '))
    segment = []
  }
  if (joinPoints) {
    for (const row of limited) {
      if (!finite(row.value)) { finishSegment(); continue }
      const previous = segment.at(-1)
      if (previous && (row.time <= previous.time || row.time - previous.time > cadenceS!)) finishSegment()
      segment.push({ ...row, value: row.value })
    }
    finishSegment()
  }

  return <figure className="workspace-plot">
    <svg viewBox="0 0 720 258" role="img" aria-labelledby={`${id}-title ${id}-description`}>
      <title id={`${id}-title`}>Frozen observations for {datasetId}</title>
      <desc id={`${id}-description`}>{description} Values in {label}; time in {basis}. The data table provides every original row.</desc>
      <g className="workspace-plot-grid" aria-hidden="true">
        <line x1={left} y1={top} x2={right} y2={top} />
        <line x1={left} y1={bottom} x2={right} y2={bottom} />
        <line x1={left} y1={top} x2={left} y2={bottom} />
      </g>
      <g className="workspace-plot-labels" aria-hidden="true">
        <text x={left - 8} y={high === low ? (top + bottom) / 2 + 5 : top + 5} textAnchor="end">{tick(high)}</text>
        {high !== low && <text x={left - 8} y={bottom + 5} textAnchor="end">{tick(low)}</text>}
        <text x={left} y={bottom + 24}>{tick(xMin)}</text>
        <text x={right} y={bottom + 24} textAnchor="end">{tick(xMax)}</text>
        <text x={(left + right) / 2} y={bottom + 49} textAnchor="middle">Source event time · {basis}</text>
        <text x={left} y={15}>Value · {label}</text>
      </g>
      {paths.map((path, i) => <path key={i} d={path} className="workspace-plot-segment" />)}
      {points.map((row, i) => <circle key={i} cx={x(row.time)} cy={y(row.value)} r="3.5" className="workspace-plot-point">
        <title>{row.time}: {row.value} {label}{row.source_ref ? ` · ${row.source_ref}` : ''}</title>
      </circle>)}
    </svg>
    <figcaption>
      <p>Frozen dataset {datasetId} · {points.length} finite scalar observations shown. Value: {label}. Time: {basis}.</p>
      <p>{description}</p>
      <p>Sorted by event time for presentation only. No interpolation, aggregation, or reduction enters analysis; calculations use the frozen source rows. The table is the accessible alternative.</p>
      {invalidTime && <p>Invalid timestamps prevent continuity assessment; those records are not placed on this plot.</p>}
      {rows.length > MAX_POINTS && <p>Plot limit reached: only the first {MAX_POINTS} timestamped rows in event-time order are shown. The selection is not represented in full; lines are disabled.</p>}
    </figcaption>
  </figure>
}
