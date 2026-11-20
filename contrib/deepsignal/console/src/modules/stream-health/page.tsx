/* oxlint-disable react/only-export-components, react-hooks/exhaustive-deps -- route helpers are public test seams; subscription identity follows the field-name key */
import { useEffect, useMemo, useState } from 'react'
import type { ConsoleContext, ConsoleModule, FieldState } from '../../contract'
import './stream-health.css'

export const stages = ['sensor', 'endpoint', 'raw_traffic', 'parser', 'time', 'calibration', 'derived', 'store'] as const
const states = ['OK', 'DEGRADED', 'FAILED', 'UNKNOWN', 'OFF'] as const

const prefix = 'ds_chain:'

function streamForField(field: string): string | undefined {
  if (!field.startsWith(prefix)) return undefined
  const rest = field.slice(prefix.length)
  const split = rest.lastIndexOf(':')
  if (split < 1) return undefined
  const member = rest.slice(split + 1)
  if (member === 'root' || stages.some((stage) => stage === member)) {
    return rest.slice(0, split)
  }
}

export function streamHealthFields(ctx: ConsoleContext): string[] {
  return ctx.store.listFields().filter((field) => streamForField(field) !== undefined).sort()
}

function stageLabel(value: unknown) {
  return states.find((state) => state === value)
}

function rootLabel(value: unknown) {
  return value === null ? 'None reported' : stages.find((stage) => stage === value)
}

function presentReport(report: FieldState, label: (value: unknown) => string | undefined, unknownLabel: string) {
  if (report.freshness === 'NO_DATA') return { value: unknownLabel, detail: 'Missing' }
  const qualityAccepted = report.quality === 'PASS' || report.quality === 'NOT_EVALUATED'
  const value = label(report.value)
  if (report.freshness === 'STALE') {
    const detail = ['Stale']
    if (!qualityAccepted) detail.push(report.quality)
    if (value !== undefined) detail.push(`Last reported: ${value}`)
    if (!qualityAccepted || value === undefined) {
      const lastUsable = label(report.lastGood?.value)
      if (lastUsable !== undefined) detail.push(`Last usable: ${lastUsable}`)
    }
    return { value: unknownLabel, detail: detail.join(' · ') }
  }
  if (!qualityAccepted) return { value: unknownLabel, detail: report.quality }
  if (value === undefined) return { value: unknownLabel, detail: 'Unusable value' }
  return { value, detail: report.freshness === 'AGING' ? 'Aging' : 'Current' }
}

function Root({ report }: { report: FieldState }) {
  const { value, detail } = presentReport(report, rootLabel, 'Unknown')
  return <div className="stream-root"><span>Reported root stage</span><strong>{value}</strong><small>{detail}</small></div>
}

function StreamHealthPage({ ctx }: { ctx: ConsoleContext }) {
  const [, redraw] = useState(0)
  const fields = streamHealthFields(ctx)
  const subscriptionKey = fields.join('\n')
  useEffect(() => ctx.store.subscribe(fields, () => redraw((value) => value + 1)), [ctx, subscriptionKey])
  const streams = useMemo(() => [...new Set(fields.map(streamForField).filter((stream) => stream !== undefined))]
    .sort((a, b) => a.localeCompare(b)), [subscriptionKey])

  if (!streams.length) return <section className="stream-health"><p className="stream-health-empty">No stream health data is available.</p></section>

  return <section className="stream-health" aria-label="Stream health">
    <div className="stream-list">
      {streams.map((stream) => <article className="stream-card" data-testid="stream-health-row" key={stream}>
        <header><h2>{stream}</h2><Root report={ctx.store.get(`${prefix}${stream}:root`)} /></header>
        <div className="stream-stages">
          {stages.map((stage) => {
            const report = ctx.store.get(`${prefix}${stream}:${stage}`)
            const { value, detail } = presentReport(report, stageLabel, 'UNKNOWN')
            return <div className="stream-stage" data-stage={stage} key={stage}>
              <span className="stream-stage-label">{stage}</span>
              <strong className={`stream-state stream-state-${value.toLowerCase()}`}>{value}</strong>
              <small>{detail}</small>
            </div>
          })}
        </div>
      </article>)}
    </div>
  </section>
}

const streamHealthModule: ConsoleModule = {
  id: 'stream-health',
  routes: [{
    id: 'stream-health', title: 'Stream Health', order: 31, Component: StreamHealthPage,
    fields: streamHealthFields,
  }],
}

export default streamHealthModule
