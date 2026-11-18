import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import type { ConsoleContext, FieldState, PageProblem, PageWhere, TileConfig, TileDef } from '../../contract'
import { compassPoint, relativeWind, wrapAngle } from './angles'

type WindConfig = TileConfig & { speed: string; direction: string; heading: string; gust?: string;
  speed_fallback?: string; direction_fallback?: string; unit: string; label: string; average_label?: string }
type NavConfig = TileConfig & { heading: string; cog: string; sog: string; label: string }

const panel: CSSProperties = { background: 'var(--panel)', color: 'var(--fg)', border: '1px solid var(--line)',
  borderRadius: 8, padding: 16, fontFamily: 'var(--f-body)', minWidth: 0 }
const button: CSSProperties = { minHeight: 44, minWidth: 88, border: '1px solid var(--line)', borderRadius: 6,
  color: 'var(--fg)', background: 'var(--panel2)', font: '600 16px var(--f-body)' }

function useUpdates(ctx: ConsoleContext, fields: string[]) {
  const [, update] = useState(0)
  useEffect(() => ctx.store.subscribe(fields, () => update((value) => value + 1)), [ctx, fields.join('|')])
  useEffect(() => ctx.lighting.subscribe(() => update((value) => value + 1)), [ctx])
}

function text(raw: Record<string, unknown>, key: string, where: PageWhere, optional = false): string | undefined {
  const value = raw[key]
  if (optional && value === undefined) return undefined
  if (typeof value === 'string' && value.trim()) return value
  const problem: PageProblem = { where, setting: key, saw: value === undefined ? 'nothing' : JSON.stringify(value),
    expected: 'non-empty text', example: `${key}: S330HeadingTrue` }
  throw problem
}

function chosen(ctx: ConsoleContext, primary: string, fallback?: string): FieldState {
  const value = ctx.store.get(primary)
  if (number(value) !== undefined || !fallback) return value
  const alternate = ctx.store.get(fallback)
  return number(alternate) === undefined ? value : alternate
}

function number(state: FieldState): number | undefined {
  if (state.freshness === 'NO_DATA' || state.quality === 'MISSING') return undefined
  return typeof state.value === 'number' && Number.isFinite(state.value) ? state.value : undefined
}

function readingIssue(state: FieldState): keyof typeof issueStyles | undefined {
  if (state.freshness !== 'LIVE') return state.freshness
  if (state.quality === 'FAIL' || state.quality === 'SUSPECT') return state.quality
  return number(state) === undefined ? 'MISSING' : undefined
}

const issueStyles = {
  AGING: ['▲', '--check'], STALE: ['□', '--stale'], NO_DATA: ['×', '--down'],
  FAIL: ['×', '--down'], SUSPECT: ['▲', '--check'], MISSING: ['□', '--down'],
} as const

function ReadingState({ state }: { state: FieldState }) {
  const issue = readingIssue(state)
  const qualityIssue = state.quality === 'FAIL' || state.quality === 'SUSPECT' || state.quality === 'MISSING'
    ? state.quality : undefined
  const badges = issue ? [issue] : []
  if (qualityIssue && qualityIssue !== issue) badges.push(qualityIssue)
  return badges.map((badge) => {
    const [shape, tone] = issueStyles[badge]
    const age = badge === state.freshness && state.ageS !== undefined ? ` · ${Math.floor(state.ageS)} s old` : ''
    return <span key={badge} style={{ color: `var(${tone})`, marginInlineStart: 8, font: '16px var(--f-mono)' }}>
      {`${shape} ${badge.replace('_', ' ')}${age}`}
    </span>
  })
}

function dialValue(state: FieldState) {
  return state.freshness === 'LIVE' && state.quality !== 'FAIL' ? number(state) : undefined
}

function WindDial({ cfg, ctx }: { cfg: TileConfig; ctx: ConsoleContext }) {
  const config = cfg as WindConfig
  const fields = [config.speed, config.direction, config.heading, config.gust,
    config.speed_fallback, config.direction_fallback].filter((value): value is string => Boolean(value))
  useUpdates(ctx, fields)
  const storageKey = `deepsignal.bridge.orientation.${ctx.route.get()}`
  const [orientation, setOrientation] = useState<'north' | 'ship'>(() =>
    localStorage.getItem(storageKey) === 'ship' ? 'ship' : 'north')
  const selectOrientation = (next: 'north' | 'ship') => {
    localStorage.setItem(storageKey, next)
    setOrientation(next)
  }
  const speedState = chosen(ctx, config.speed, config.speed_fallback)
  const directionState = chosen(ctx, config.direction, config.direction_fallback)
  const headingState = ctx.store.get(config.heading)
  const speed = number(speedState)
  const direction = number(directionState)
  const heading = dialValue(headingState)
  const windBearing = dialValue(directionState)
  const shipUp = orientation === 'ship' && heading !== undefined
  const northRotation = shipUp ? Math.round(wrapAngle(-heading)) : 0
  const shipRotation = shipUp ? 0 : Math.round(heading ?? 0)
  const arrowRotation = windBearing === undefined ? undefined : Math.round(wrapAngle(
    shipUp ? windBearing - heading : windBearing))
  const relative = windBearing !== undefined && heading !== undefined
    ? relativeWind(windBearing, heading, headingState.freshness) : undefined
  const relativeIssue = readingIssue(headingState) ?? readingIssue(directionState) ?? 'NO_DATA'
  const gustState = config.gust ? ctx.store.get(config.gust) : undefined
  const gust = gustState && number(gustState)
  const fallbackCount = Number(speedState.field !== config.speed) + Number(directionState.field !== config.direction)
  const windLabel = fallbackCount === 2 ? 'Instantaneous wind' : fallbackCount === 0 ? config.average_label : undefined
  return <article style={{ ...panel, display: 'grid', gridTemplateColumns: 'minmax(240px, 1fr) minmax(220px, 1fr)', gap: 12 }}>
    <div>
      <h2 style={{ margin: 0, fontSize: 18 }}>{config.label}</h2>
      <svg viewBox="0 0 200 200" role="img" aria-label={shipUp ? 'Wind direction dial, ship up' : 'Wind direction dial, north up'} style={{ width: '100%', maxHeight: 260 }}>
        <circle cx="100" cy="100" r="88" fill="var(--panel2)" stroke="var(--line)" strokeWidth="2" />
        <text x="100" y="22" transform={`rotate(${northRotation} 100 100)`} textAnchor="middle" fill="var(--muted)" fontSize="14">N</text>
        {heading !== undefined && <g data-testid="ship" transform={`rotate(${shipRotation} 100 100)`} fill="none" stroke="var(--fg)" strokeWidth="3">
          <path d="M100 52 L116 112 L100 142 L84 112 Z" />
          <path d="M100 52 V142" />
        </g>}
        {arrowRotation !== undefined && <g data-testid="wind-arrow" transform={`rotate(${arrowRotation} 100 100)`} stroke="var(--accent)" fill="var(--accent)" strokeWidth="5">
          <path d="M100 28 V91" /><path d="M88 76 L100 94 L112 76 Z" stroke="none" />
        </g>}
      </svg>
      <div role="group" aria-label="Dial orientation" style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
        <button style={button} aria-pressed={!shipUp} onClick={() => selectOrientation('north')}>North up</button>
        <button style={button} aria-pressed={shipUp} onClick={() => selectOrientation('ship')}>Ship up</button>
      </div>
    </div>
    <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 12 }}>
      <div style={{ font: '600 48px var(--f-number)', lineHeight: 1 }}>{speed?.toFixed(1) ?? '—'}
        <span style={{ fontSize: 22 }}> {config.unit}</span><ReadingState state={speedState} /></div>
      <div style={{ fontSize: 18 }}>From <strong>{direction === undefined ? '—' : `${Math.round(direction)}° ${compassPoint(direction)}`}</strong>
        <ReadingState state={directionState} /></div>
      <div style={{ fontSize: 18 }}>Relative to bow <strong>{relative && 'angle' in relative ?
        `${Math.round(relative.angle)}° ${relative.side}` : `— (${relativeIssue})`}</strong>
        <ReadingState state={headingState} /></div>
      {gustState && <div style={{ fontSize: 16 }}>Gust <span>{gust?.toFixed(1) ?? '—'} {config.unit}</span><ReadingState state={gustState} /></div>}
      {windLabel && <div style={{ color: 'var(--muted)', fontSize: 16 }}>{windLabel}</div>}
      <div style={{ color: 'var(--muted)', font: '16px var(--f-mono)' }}>Source {speedState.field} / {directionState.field}</div>
    </div>
  </article>
}

function Nav({ cfg, ctx }: { cfg: TileConfig; ctx: ConsoleContext }) {
  const config = cfg as NavConfig
  useUpdates(ctx, [config.heading, config.cog, config.sog])
  const headingState = ctx.store.get(config.heading)
  const cogState = ctx.store.get(config.cog)
  const sogState = ctx.store.get(config.sog)
  const heading = number(headingState)
  const cog = number(cogState)
  const sog = number(sogState)
  return <article style={panel}>
    <h2 style={{ margin: 0, fontSize: 18 }}>{config.label}</h2>
    <div style={{ font: '600 48px var(--f-number)' }}>{heading === undefined ? '—' : `${Math.round(heading)}° T`}
      <ReadingState state={headingState} /></div>
    <div style={{ display: 'flex', gap: 24, fontSize: 18 }}>
      <span>Course over ground <strong>{cog === undefined ? '—' : `${Math.round(cog)}° T`}</strong><ReadingState state={cogState} /></span>
      <span>Speed over ground <strong>{sog === undefined ? '—' : sog.toFixed(1)} kn</strong><ReadingState state={sogState} /></span>
    </div>
  </article>
}

export const windDial: TileDef = {
  type: 'wind-dial',
  validate(raw, where) {
    return { type: 'wind-dial', speed: text(raw, 'speed', where)!, direction: text(raw, 'direction', where)!,
      heading: text(raw, 'heading', where)!, gust: text(raw, 'gust', where, true),
      speed_fallback: text(raw, 'speed_fallback', where, true), direction_fallback: text(raw, 'direction_fallback', where, true),
      unit: text(raw, 'unit', where, true) ?? 'kn', label: text(raw, 'label', where, true) ?? 'Wind',
      average_label: text(raw, 'average_label', where, true), wide: raw.wide === true }
  },
  fields: (cfg) => { const c = cfg as WindConfig; return [c.speed, c.direction, c.heading, c.gust,
    c.speed_fallback, c.direction_fallback].filter((value): value is string => Boolean(value)) },
  Component: WindDial,
}

export const nav: TileDef = {
  type: 'nav',
  validate(raw, where) { return { type: 'nav', heading: text(raw, 'heading', where)!, cog: text(raw, 'cog', where)!,
    sog: text(raw, 'sog', where)!, label: text(raw, 'label', where, true) ?? 'Navigation', wide: raw.wide === true } },
  fields: (cfg) => { const c = cfg as NavConfig; return [c.heading, c.cog, c.sog] }, Component: Nav,
}
