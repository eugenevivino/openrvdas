/* oxlint-disable react/only-export-components -- this module exports the route definition, not a standalone page */
import { useEffect, useMemo, useState } from 'react'
import { load } from 'js-yaml'
import type { ConsoleContext, ConsoleModule, FieldState, Health } from '../../contract'
import { isMapping } from '../../settings'
import defaultHintsText from './hints.default.yaml?raw'
import { isStatuses, type LoggerEntry, type LoggerStatus } from './loggerStatus'
import './health.css'

type Hint = { logger?: RegExp; stderr?: RegExp; text: string }
type Runtime = { statuses: Record<string, LoggerEntry>; stderr: Map<string, string> }
const managerField = 'status:logger_status'
const cruiseField = 'status:cruise_mode'
const noStatuses: Record<string, LoggerEntry> = {}
const runtimes = new WeakMap<ConsoleContext, Runtime>()

function runtime(ctx: ConsoleContext): Runtime {
  let value = runtimes.get(ctx)
  if (!value) { value = { statuses: noStatuses, stderr: new Map() }; runtimes.set(ctx, value) }
  return value
}

function glob(pattern: string): RegExp {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replaceAll('*', '.*').replaceAll('?', '.')
  return new RegExp(`^${escaped}$`, 'i')
}

export function parseHints(text: string): Hint[] {
  const raw: unknown = load(text)
  if (!Array.isArray(raw)) throw new Error('expected a list of hints')
  return raw.map((item, index) => {
    if (!item || typeof item !== 'object') throw new Error(`hint ${index + 1} is not an object`)
    const record = item as Record<string, unknown>
    const match = record.match
    if (!match || typeof match !== 'object' || typeof record.hint !== 'string') {
      throw new Error(`hint ${index + 1} needs match and hint`)
    }
    const matcher = match as Record<string, unknown>
    if (matcher.logger !== undefined && typeof matcher.logger !== 'string') throw new Error(`hint ${index + 1} logger must be text`)
    if (matcher.stderr !== undefined && typeof matcher.stderr !== 'string') throw new Error(`hint ${index + 1} stderr must be text`)
    if (matcher.logger === undefined && matcher.stderr === undefined) throw new Error(`hint ${index + 1} has no matcher`)
    return {
      logger: typeof matcher.logger === 'string' ? glob(matcher.logger) : undefined,
      stderr: typeof matcher.stderr === 'string' ? new RegExp(matcher.stderr, 'i') : undefined,
      text: record.hint,
    }
  })
}

const defaultHints = parseHints(defaultHintsText)
export function resolveHint(hints: Hint[], logger: string, stderr: string): string | undefined {
  return hints.find((hint) => (!hint.logger || hint.logger.test(logger)) && (!hint.stderr || hint.stderr.test(stderr)))?.text
}

function expired(report: FieldState) {
  return report.freshness === 'STALE' || report.freshness === 'NO_DATA'
}

function usableQuality(report: FieldState) {
  return report.quality === 'PASS' || report.quality === 'NOT_EVALUATED'
}

const loggerHealth: Record<LoggerStatus, Health> = { RUNNING: 'OK', STARTING: 'DEGRADED', FAILED: 'FAILED', EXITED: 'UNKNOWN' }

function syncLoggerHealth(ctx: ConsoleContext) {
  const state = runtime(ctx)
  const report = ctx.store.get(managerField)
  const { value } = report
  const valid = isStatuses(value)
  const statuses = !expired(report) && usableQuality(report) && valid ? value : noStatuses
  const prior = state.statuses
  if (prior === statuses) return
  state.statuses = statuses
  const evidence = expired(report) ? 'Logger manager stopped reporting'
    : !usableQuality(report) ? `Logger manager report quality is ${report.quality}`
      : valid ? 'Logger omitted from the latest manager report' : 'Latest logger manager report is malformed'
  for (const logger of Object.keys(prior)) {
    if (!Object.hasOwn(statuses, logger)) ctx.store.setHealth({ logger }, 'UNKNOWN', evidence)
  }
  for (const [logger, entry] of Object.entries(statuses)) {
    const suffix = entry.status === 'EXITED' ? ' (Off)' : ''
    ctx.store.setHealth({ logger }, loggerHealth[entry.status], `Logger manager reports ${entry.status}${suffix}`)
  }
}

const loggerAdapter = {
  id: 'logger-status',
  fields(ctx: ConsoleContext) {
    return [managerField, cruiseField, ...ctx.store.listFields().filter((field) => field.startsWith('stderr:logger:'))]
  },
  onValue(field: string, value: unknown, _time: number, ctx: ConsoleContext) {
    if (field === managerField) {
      syncLoggerHealth(ctx)
    } else if (field.startsWith('stderr:logger:') && typeof value === 'string') {
      runtime(ctx).stderr.set(field.slice('stderr:logger:'.length), value)
    }
  },
}

const stateView = {
  RUNNING: { word: 'OK', shape: '●', rank: 3, className: 'ok' },
  STARTING: { word: 'Check', shape: '▲', rank: 1, className: 'check' },
  FAILED: { word: 'Failed', shape: '✕', rank: 0, className: 'failed' },
  EXITED: { word: 'Off', shape: '◇', rank: 2, className: 'off' },
} as const

function ageText(age: number): string {
  if (age < 60) return `${Math.max(0, Math.round(age))} s ago`
  return `${Math.round(age / 60)} min ago`
}

function utc(seconds: number): string { return new Date(seconds * 1000).toISOString().replace('T', ' ').replace('.000Z', ' UTC') }

function cruiseMode(ctx: ConsoleContext) {
  const report = ctx.store.get(cruiseField)
  if (report.sourceTime === undefined) return 'Unknown'
  const age = ageText(ctx.clock.now() - report.sourceTime)
  if (expired(report)) return `Unknown · ${report.freshness.replace('_', ' ')} · Last report ${age}`
  if (!usableQuality(report)) return `Unknown · ${report.quality} · Last report ${age}`
  const mode = isMapping(report.value) && typeof report.value.active_mode === 'string' && report.value.active_mode.trim()
  if (!mode) return 'Unknown'
  return report.freshness === 'AGING' ? `${mode} · AGING · ${age}` : mode
}

function HealthPage({ ctx }: { ctx: ConsoleContext }) {
  const [, refresh] = useState(0)
  const [hints, setHints] = useState(defaultHints)
  const [overrideError, setOverrideError] = useState('')
  const fields = ctx.store.listFields()
  useEffect(() => ctx.store.subscribe(loggerAdapter.fields(ctx), () => refresh((n) => n + 1)), [ctx])
  useEffect(() => {
    let current = true
    fetch('hints.yaml').then(async (response) => {
      if (!response.ok || !current) return
      try { const parsed = parseHints(await response.text()); if (current) setHints(parsed) }
      catch (error) { if (current) setOverrideError(`Ship hint file is invalid; using defaults. ${error instanceof Error ? error.message : String(error)}`) }
    }).catch((error: unknown) => {
      // A missing optional file is normal; only unexpected non-network failures are actionable.
      if (current && !(error instanceof TypeError)) setOverrideError(`Could not read ship hint file; using defaults. ${String(error)}`)
    })
    return () => { current = false }
  }, [])
  const state = runtime(ctx)
  const manager = ctx.store.get(managerField)
  const loggerRows = useMemo(() => Object.entries(state.statuses).sort(([nameA, a], [nameB, b]) =>
    stateView[a.status].rank - stateView[b.status].rank || nameA.localeCompare(nameB)), [state.statuses])

  if (manager.value === undefined && manager.sourceTime === undefined) return <main className="health-page"><h1>Health</h1><p className="health-message">Waiting for the logger manager. If this lasts over a minute, check that logger_manager is running (supervisorctl status).</p></main>
  if (expired(manager)) {
    const since = manager.receiveTime ?? manager.sourceTime ?? ctx.clock.now()
    return <main className="health-page"><h1>Health</h1><p className="health-message">Logger manager not reporting since {utc(since)}</p></main>
  }
  if (!usableQuality(manager)) {
    return <main className="health-page"><h1>Health</h1><p className="health-message">Logger manager report quality is {manager.quality}.</p></main>
  }
  if (!isStatuses(manager.value)) {
    return <main className="health-page"><h1>Health</h1><p className="health-message">Logger manager status missing from the latest report.</p></main>
  }
  const counts = { RUNNING: 0, STARTING: 0, FAILED: 0, EXITED: 0 }
  for (const [, entry] of loggerRows) counts[entry.status]++
  return <main className="health-page">
    <h1>Health</h1>
    <div className="health-mode"><strong>Cruise mode:</strong> {cruiseMode(ctx)}</div>
    {overrideError && <p className="health-override">{overrideError}</p>}
    <div className="health-summary" aria-label="Logger state summary">
      <span>● OK {counts.RUNNING}</span><span>▲ Check {counts.STARTING}</span>
      <span data-testid="summary-failed">✕ Failed {counts.FAILED}</span><span>◇ Off {counts.EXITED}</span>
    </div>
    <div className="health-table">
      {loggerRows.map(([logger, entry]) => {
        const view = stateView[entry.status]
        const loggerFields = fields.filter((field) => ctx.store.describe(field)?.logger === logger)
        const newest = loggerFields.map((field) => ctx.store.get(field)).filter((field) => field.sourceTime !== undefined)
          .sort((a, b) => (b.sourceTime ?? 0) - (a.sourceTime ?? 0))[0]
        const age = newest?.sourceTime === undefined ? undefined : ctx.clock.now() - newest.sourceTime
        const stderr = state.stderr.get(logger) ?? ''
        const hint = entry.status === 'RUNNING' ? 'No action needed.' : entry.status === 'EXITED'
          ? 'This logger is configured Off; no fault action is needed.'
          : resolveHint(hints, logger, stderr) ?? 'Check the latest error, logger configuration, and connected instrument.'
        return <section className="health-row" data-testid="logger-row" id={`logger-${logger}`} key={logger}>
          <div data-testid={`logger-${logger}`} className="health-row-contents">
          <div className="health-cell"><span className="health-label">State</span><span className={`health-state health-state-${view.className}`}>{view.shape} {view.word}</span></div>
          <div className="health-cell health-mono"><span className="health-label">Logger</span>{logger}</div>
          <div className="health-cell health-mono"><span className="health-label">Config</span>{entry.config}</div>
          <div className="health-cell"><span className="health-label">Newest field</span>{newest ? <><span className="health-mono">{newest.field}</span><br />{newest.freshness}, {ageText(age ?? 0)}</> : 'No mapped fields'}</div>
          <div className="health-cell"><span className="health-label">Latest error</span>{stderr ? <ExpandableText text={stderr} /> : 'No error reported'}</div>
          <div className="health-hint"><strong>What to try:</strong> {hint}</div>
          </div>
        </section>
      })}
    </div>
  </main>
}

function ExpandableText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const shortened = text.length > 120 ? `${text.slice(0, 117)}…` : text
  return <button className="health-stderr" type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>{expanded ? text : shortened}</button>
}

const healthModule: ConsoleModule = {
  id: 'health', adapters: [loggerAdapter],
  engines: [{ id: 'logger-health-expiry', start(ctx) {
    const sync = () => syncLoggerHealth(ctx)
    sync()
    return ctx.store.subscribe([managerField], sync)
  } }],
  routes: [{ id: 'health', title: 'Health', order: 30, Component: HealthPage, fields: (ctx) => loggerAdapter.fields(ctx) }],
}
export default healthModule
