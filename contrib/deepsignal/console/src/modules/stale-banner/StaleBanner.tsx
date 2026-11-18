/* oxlint-disable react/only-export-components -- module entrypoint intentionally exports the component and testable history */
import { useEffect, useState, type CSSProperties } from 'react'
import type { Alert, AlertTier, ConsoleContext, ConsoleModule, FieldState } from '../../contract'

type HistoryEntry = { alert: Alert; clearedAt?: number }
type Candidate = { field: string; logger: string; state: FieldState; tier: AlertTier; since: number; title: string }

const history: HistoryEntry[] = []
const serialLoggers = new Set(['flr1', 'knud1'])
const networkLoggers = new Set(['mwx1', 's330', 'true_winds', 'tsg1'])

export function getAlertHistory(): readonly HistoryEntry[] {
  return history
}

function remember(entry: HistoryEntry) {
  history.push(entry)
  if (history.length > 200) history.splice(0, history.length - 200)
}

function globMatches(glob: string, field: string) {
  const pattern = glob.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')
  return new RegExp(`^${pattern}$`).test(field)
}

function settings(ctx: ConsoleContext) {
  const raw = ctx.config.modules['stale-banner'] ?? {}
  const grace = raw.stale_grace_s
  return {
    grace: typeof grace === 'number' && Number.isFinite(grace) && grace >= 0 ? grace : 30,
    ignore: Array.isArray(raw.ignore) ? raw.ignore.filter((item): item is string => typeof item === 'string') : [],
  }
}

function actionFor(logger: string) {
  if (serialLoggers.has(logger)) return 'Check the cable and port.'
  if (networkLoggers.has(logger)) return 'Check the source host.'
  return 'Check the Health page.'
}

function utc(seconds: number) {
  return new Date(seconds * 1000).toISOString().replace('.000Z', 'Z')
}

function candidates(ctx: ConsoleContext, active?: ReadonlyMap<string, Alert>): Candidate[] {
  const now = ctx.clock.now()
  const { grace, ignore } = settings(ctx)
  return ctx.store.listFields().flatMap((field): Candidate[] => {
    if (ignore.some(glob => globMatches(glob, field))) return []
    const state = ctx.store.get(field)
    const logger = ctx.store.describe(field)?.logger ?? 'unassigned'
    const since = state.sourceTime ?? state.lastGood?.time
    if (state.health === 'FAILED') {
      const title = `${logger} logger failed`
      const previous = active?.get(`stale-alerts:${logger}`)
      const firstSeen = previous?.title === title ? previous.since : now
      return [{ field, logger, state, tier: 'A2', since: since ?? firstSeen, title }]
    }
    // The catalog also includes fields for which this console has no samples.
    if (since === undefined) return []
    if (state.freshness === 'NO_DATA') return [{ field, logger, state, tier: 'A2', since, title: `${field} no data since ${utc(since)}` }]
    const age = state.ageS ?? now - since
    if (state.freshness === 'STALE' && age > grace) {
      const label = ctx.store.describe(field)?.description || field
      return [{ field, logger, state, tier: 'A3', since, title: `${label} stale for ${Math.floor(age)} s` }]
    }
    return []
  })
}

function grouped(ctx: ConsoleContext, active?: ReadonlyMap<string, Alert>) {
  const groups = new Map<string, Candidate[]>()
  for (const candidate of candidates(ctx, active)) groups.set(candidate.logger, [...(groups.get(candidate.logger) ?? []), candidate])
  return groups
}

function makeAlert(group: Candidate[]): Alert {
  const primary = [...group].sort((a, b) => a.tier.localeCompare(b.tier) || a.since - b.since)[0]
  return {
    id: `stale-alerts:${primary.logger}`,
    tier: primary.tier,
    title: primary.title,
    source: 'stale-alerts',
    consequence: `${group.length} affected field${group.length === 1 ? '' : 's'}`,
    firstAction: actionFor(primary.logger),
    since: Math.min(...group.map(item => item.since)),
    groupKey: primary.logger,
  }
}

function start(ctx: ConsoleContext) {
  const active = new Map<string, Alert>()
  const evaluate = () => {
    const next = new Map<string, Alert>()
    for (const group of grouped(ctx, active).values()) {
      const alert = makeAlert(group)
      next.set(alert.id, alert)
      if (!active.has(alert.id)) remember({ alert })
      ctx.alerts.raise(alert)
    }
    for (const [id, alert] of active) {
      if (!next.has(id)) {
        ctx.alerts.clear(id)
        remember({ alert, clearedAt: ctx.clock.now() })
      }
    }
    active.clear()
    for (const item of next) active.set(item[0], item[1])
  }
  const timer = setInterval(evaluate, 1000)
  return () => clearInterval(timer)
}

const tierPresentation: Record<AlertTier, { word: string; shape: string; rank: number }> = {
  A1: { word: 'Emergency', shape: '●', rank: 1 },
  A2: { word: 'Warning', shape: '◆', rank: 2 },
  A3: { word: 'Caution', shape: '▲', rank: 3 },
  A4: { word: 'Notice', shape: '■', rank: 4 },
}

const rowStyle: CSSProperties = {
  background: 'var(--panel)', color: 'var(--fg)', border: '1px solid var(--line)',
  fontFamily: 'var(--f-body)', fontSize: '18px', padding: '8px 12px', minHeight: '44px',
}

function fieldsFor(ctx: ConsoleContext, logger: string) {
  return (grouped(ctx).get(logger) ?? []).map(item => item.field)
}

export function StaleBanner({ ctx }: { ctx: ConsoleContext }) {
  const [, redraw] = useState(0)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  useEffect(() => ctx.alerts.subscribe(() => redraw(value => value + 1)), [ctx])
  const alerts = ctx.alerts.list().filter(alert => alert.source === 'stale-alerts')
    .sort((a, b) => tierPresentation[a.tier].rank - tierPresentation[b.tier].rank || a.since - b.since)
  if (alerts.length === 0) return null
  const shown = alerts.slice(0, 3)
  return <section aria-label="Sensor alerts" style={{ background: 'var(--bg)', color: 'var(--fg)' }}>
    {shown.map(alert => {
      const logger = alert.groupKey ?? 'unassigned'
      const open = expanded.has(alert.id)
      const fields = fieldsFor(ctx, logger)
      return <div key={alert.id} data-testid={`alert-${logger}`} data-acked={String(Boolean(alert.acked))}
        style={{ ...rowStyle, opacity: alert.acked ? 0.65 : 1 }}>
        <button type="button" aria-expanded={open} onClick={() => setExpanded(old => {
          const next = new Set(old); if (next.has(alert.id)) next.delete(alert.id); else next.add(alert.id); return next
        })} style={{ minHeight: '44px', color: 'var(--fg)', background: 'var(--panel2)', border: '1px solid var(--line)', font: 'inherit' }}>
          <strong>{tierPresentation[alert.tier].word} {tierPresentation[alert.tier].shape}</strong>{' '}
          {alert.title} · {Math.max(0, Math.floor(ctx.clock.now() - alert.since))} s · {alert.firstAction}
          {fields.length > 1 ? ` · ${fields.length} fields` : ''}
        </button>
        {(alert.tier === 'A1' || alert.tier === 'A2') && !alert.acked &&
          <button type="button" onClick={() => ctx.alerts.ack(alert.id)} style={{ minWidth: '44px', minHeight: '44px', color: 'var(--fg)', background: 'var(--panel2)', border: '1px solid var(--line)', font: 'inherit' }}>Acknowledge</button>}
        {open && <ul>{fields.map(field => <li key={field}>{field}</li>)}</ul>}
      </div>
    })}
    {alerts.length > 3 && <div style={rowStyle}>{alerts.length - 3} more</div>}
  </section>
}

const staleBanner: ConsoleModule = {
  id: 'stale-banner',
  engines: [{ id: 'stale-alerts', start }],
  slots: [{ slot: 'banner', order: 10, Component: StaleBanner }],
}

export default staleBanner
