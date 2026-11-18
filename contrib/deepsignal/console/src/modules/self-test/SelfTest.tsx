import { useEffect, useState } from 'react'
import type { ConsoleContext, FieldState, Page } from '../../contract'

type Result = { label: string; pass: boolean; detail: string }

function State({ pass }: { pass: boolean }) {
  const word = pass ? 'Pass' : 'Down'
  return (
    <span style={{ color: `var(--${pass ? 'ok' : 'down'})`, display: 'inline-flex', gap: 8, alignItems: 'center', fontWeight: 600 }}>
      <svg viewBox="0 0 14 14" width="14" height="14" role="img" aria-label={`${word} state`}>
        {pass
          ? <circle cx="7" cy="7" r="6" fill="currentColor" />
          : <path d="M2 2l10 10m0-10L2 12" stroke="currentColor" strokeWidth="2.5" />}
      </svg>
      {word}
    </span>
  )
}

function objectValue(value: unknown, key: string): unknown {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>)[key] : undefined
}

function isLive(state: FieldState) {
  return state.freshness === 'LIVE' && state.quality !== 'FAIL' && state.quality !== 'MISSING' && state.value != null
}

function loadedPage(page: Page) {
  // Core's parser includes order (possibly undefined), even for an empty page.
  // Its failed-file placeholder contains no order, and has the ID as its title.
  return page.tiles.length > 0 || Object.hasOwn(page, 'order') || page.title !== page.id
}

function results(ctx: ConsoleContext): Result[] {
  const fields = ctx.store.listFields()
  const logger = ctx.store.get('status:logger_status')
  const loggerValue = logger.value
  const loggerCount = loggerValue && typeof loggerValue === 'object' && !Array.isArray(loggerValue)
    ? Object.keys(loggerValue).length : 0
  const cruiseState = ctx.store.get('status:cruise_mode')
  const cruise = objectValue(cruiseState.value, 'active_mode')
  const hasMode = typeof cruise === 'string' && cruise.trim().length > 0
  const statusDetail = (state: FieldState) => state.freshness.replace('_', ' ')
  const newest = fields.reduce<FieldState | undefined>((latest, field) => {
    const record = ctx.store.get(field)
    return record.sourceTime !== undefined && (latest?.sourceTime === undefined || record.sourceTime > latest.sourceTime ||
      (record.sourceTime === latest.sourceTime && isLive(record))) ? record : latest
  }, undefined)
  const files = ctx.pages.list().filter((page) => page.source?.startsWith('file:'))
  const failed = files.filter((page) => !loadedPage(page))
  const pageCount = files.length - failed.length
  const pageDetail = pageCount > 0 ? `${pageCount} page${pageCount === 1 ? '' : 's'} loaded` : 'No page files loaded'
  return [
    {
      label: 'Cache connection', pass: ctx.store.connection() === 'connected',
      detail: ctx.store.connection() === 'connected' ? 'Connected' : 'Disconnected',
    },
    { label: 'Cache fields', pass: fields.length > 0, detail: `${fields.length} fields` },
    { label: 'Logger status', pass: isLive(logger) && loggerCount > 0,
      detail: `${loggerCount} loggers${logger.freshness !== 'LIVE' ? ` · ${statusDetail(logger)}` : ''}` },
    {
      label: 'Cruise mode', pass: isLive(cruiseState) && hasMode,
      detail: cruiseState.freshness !== 'LIVE' ? statusDetail(cruiseState) : hasMode ? cruise : 'No active cruise mode',
    },
    {
      label: 'Newest record', pass: newest !== undefined && isLive(newest),
      detail: newest?.sourceTime === undefined ? 'No records received'
        : `${Math.max(0, Math.floor(ctx.clock.now() - newest.sourceTime))} seconds${newest.freshness !== 'LIVE' ? ` · ${statusDetail(newest)}` : ''}`,
    },
    {
      label: 'Page files', pass: pageCount > 0 && failed.length === 0,
      detail: failed.length ? `${pageDetail} · Failed to load ${failed.map((page) => page.source!.slice(5)).join(', ')}` : pageDetail,
    },
  ]
}

function reportText(ctx: ConsoleContext, rows: Result[]): string {
  return [
    'DeepSignal Console self-test',
    `Ship: ${ctx.config.ship}`,
    ...rows.map((row) => `${row.label}: ${row.pass ? 'PASS' : 'DOWN'} — ${row.detail}`),
  ].join('\n')
}

export function SelfTest({ ctx }: { ctx: ConsoleContext }) {
  const [, redraw] = useState(0)
  const fields = JSON.stringify([...new Set([...ctx.store.listFields(), 'status:logger_status', 'status:cruise_mode'])])
  useEffect(() => ctx.store.subscribe(JSON.parse(fields) as string[], () => redraw((value) => value + 1)), [ctx, fields])
  useEffect(() => ctx.lighting.subscribe(() => redraw((value) => value + 1)), [ctx])
  const rows = results(ctx)
  const report = reportText(ctx, rows)
  const lighting = ctx.lighting.get()

  const copy = () => {
    if (navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(report)
      return
    }
    const output = document.querySelector<HTMLTextAreaElement>('#self-test-report')
    output?.focus()
    output?.select()
  }

  return (
    <main style={{ background: 'var(--bg)', color: 'var(--fg)', minHeight: '100%', padding: 24, fontFamily: 'var(--f-body)' }}>
      <h1 style={{ fontFamily: 'var(--f-number)', fontSize: 48, margin: '0 0 24px' }}>Self-test</h1>
      <section aria-label="Connection checks" style={{ background: 'var(--panel)', border: '1px solid var(--line)' }}>
        {rows.map((row) => (
          <div key={row.label} style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 1fr) minmax(90px, auto) minmax(220px, 2fr)', gap: 16, alignItems: 'center', minHeight: 56, padding: '8px 16px', borderBottom: '1px solid var(--line)', fontSize: 18 }}>
            <strong>{row.label}{row.label === 'Cache connection' && <small style={{ display: 'block', fontFamily: 'var(--f-mono)', fontSize: 16, fontWeight: 400 }}>{ctx.config.websocket}</small>}</strong><State pass={row.pass} />
            <span style={{ fontFamily: 'var(--f-mono)', fontSize: 16 }}>{row.detail}</span>
          </div>
        ))}
      </section>
      <section style={{ background: 'var(--panel2)', border: '1px solid var(--line)', marginTop: 24, padding: 16 }}>
        <h2 style={{ fontSize: 24, marginTop: 0 }}>Night palette check</h2>
        <p style={{ fontSize: 18 }}>Current mode: {lighting.mode}; palette: {lighting.nightPalette}; brightness: {Math.round(lighting.dim * 100)} percent.</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {['bg', 'panel', 'panel2', 'line', 'fg', 'muted', 'accent', 'ok', 'check', 'stale', 'down', 'chart', 'grid'].map((token) => (
            <span key={token} style={{ background: `var(--${token})`, color: 'var(--fg)', border: '1px solid var(--line)', padding: 8, fontFamily: 'var(--f-mono)', fontSize: 16 }}>--{token}</span>
          ))}
        </div>
      </section>
      <button type="button" onClick={copy} style={{ minHeight: 44, marginTop: 24, padding: '8px 18px', background: 'var(--accent)', color: 'var(--bg)', border: '2px solid var(--line)', font: '600 18px var(--f-body)' }}>Copy report</button>
      <textarea id="self-test-report" aria-label="Plain-text self-test report" readOnly value={report} style={{ position: 'absolute', left: -10000, background: 'var(--panel)', color: 'var(--fg)' }} />
    </main>
  )
}

