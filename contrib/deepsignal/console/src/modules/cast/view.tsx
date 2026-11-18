import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import type { ConsoleContext, ConsoleModule, FieldState, PageProblem, TileConfig } from '../../contract'

type CastSettings = {
  wire_out: string
  wire_speed: string
  tension: string
  ctd_depth: string
  altimeter: string
  swl?: number
  warn_fraction: number
  alarm_fraction: number
  altimeter_warn: number
  altimeter_alarm: number
}

const fieldKeys = ['wire_out', 'wire_speed', 'tension', 'ctd_depth', 'altimeter'] as const
const defaults = { warn_fraction: 0.8, alarm_fraction: 0.95, altimeter_warn: 10, altimeter_alarm: 5 }

function settings(ctx: ConsoleContext, cfg?: TileConfig): CastSettings {
  const raw = { ...ctx.config.modules.cast, ...cfg }
  return {
    wire_out: String(raw.wire_out ?? 'wire_out'),
    wire_speed: String(raw.wire_speed ?? 'wire_speed'),
    tension: String(raw.tension ?? 'tension'),
    ctd_depth: String(raw.ctd_depth ?? 'ctd_depth'),
    altimeter: String(raw.altimeter ?? 'altimeter'),
    swl: finite(raw.swl),
    warn_fraction: finite(raw.warn_fraction) ?? defaults.warn_fraction,
    alarm_fraction: finite(raw.alarm_fraction) ?? defaults.alarm_fraction,
    altimeter_warn: finite(raw.altimeter_warn) ?? defaults.altimeter_warn,
    altimeter_alarm: finite(raw.altimeter_alarm) ?? defaults.altimeter_alarm,
  }
}

function finite(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function useStore(ctx: ConsoleContext, fields: string[]) {
  const [, render] = useState(0)
  const key = fields.join('\0')
  useEffect(() => ctx.store.subscribe(key.split('\0'), () => render(value => value + 1)), [ctx, key])
  useEffect(() => ctx.lighting.subscribe(() => render(value => value + 1)), [ctx])
}

const shell: CSSProperties = { background: 'var(--bg)', color: 'var(--fg)', fontFamily: 'var(--f-body)', minHeight: '100%', padding: 16 }
const grid: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }
const panel: CSSProperties = { background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 16, minWidth: 0 }
const label: CSSProperties = { color: 'var(--muted)', fontSize: 18, fontWeight: 600 }
const big: CSSProperties = { fontFamily: 'var(--f-number)', fontSize: 48, fontWeight: 600, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }
const meta: CSSProperties = { color: 'var(--muted)', fontFamily: 'var(--f-mono)', fontSize: 16, marginTop: 8 }

function CastView({ ctx, cfg }: { ctx: ConsoleContext; cfg?: TileConfig }) {
  const config = settings(ctx, cfg)
  const fields = fieldKeys.map(key => config[key])
  useStore(ctx, fields)
  const wire = ctx.store.get(config.wire_out)
  const speed = ctx.store.get(config.wire_speed)
  const tension = ctx.store.get(config.tension)
  const depth = ctx.store.get(config.ctd_depth)
  const altimeter = ctx.store.get(config.altimeter)
  const tensionValue = numberValue(tension)
  const wireValue = numberValue(wire)
  const maximum = useMaximumTension(wireValue, tensionValue)

  return <main style={shell} aria-label="Cast">
    <div style={grid}>
      <Readout label="Wire out" state={wire} value={format(numberValue(wire), unit(ctx, config.wire_out, 'm'))} />
      <Readout label="Payout speed" state={speed} value={speedText(numberValue(speed), unit(ctx, config.wire_speed, 'm/s'))} />
      <Readout label="CTD depth" state={depth} value={format(numberValue(depth), unit(ctx, config.ctd_depth, 'm'))} />
      <Altimeter state={altimeter} config={config} />
      <section style={{ ...panel, gridColumn: 'span 2' }}>
        <div style={label}>Tension</div>
        <div style={big}>{format(tensionValue, unit(ctx, config.tension, 'kg'))}</div>
        <TensionBar value={tensionValue} state={tension} config={config} />
        <div style={meta}>Maximum {format(maximum, unit(ctx, config.tension, 'kg'))}</div>
        <Freshness state={tension} />
      </section>
      <TensionChart ctx={ctx} field={config.tension} />
    </div>
  </main>
}

function useMaximumTension(wire: number | undefined, tension: number | undefined) {
  const [maximum, setMaximum] = useState<number | undefined>(tension)
  useEffect(() => {
    setMaximum(current => wire !== undefined && wire < 5 ? tension : tension === undefined ? current : Math.max(current ?? tension, tension))
  }, [wire, tension])
  return maximum
}

function Readout({ label: title, state, value }: { label: string; state: FieldState; value: string }) {
  return <section style={panel}><div style={label}>{title}</div><div style={big}>{value}</div><Freshness state={state} /></section>
}

function Freshness({ state }: { state: FieldState }) {
  const stale = state.freshness === 'STALE' || state.freshness === 'NO_DATA'
  const text = stale ? `Stale — last seen ${ageWords(state.ageS)} ago` : state.freshness === 'AGING' ? `Aging — ${ageWords(state.ageS)} old` : 'Live — just updated'
  return <div style={{ ...meta, opacity: stale ? 0.45 : 1, textDecoration: stale ? 'line-through' : 'none' }}>{text}</div>
}

function TensionBar({ value, state, config }: { value?: number; state: FieldState; config: CastSettings }) {
  const stale = state.freshness === 'STALE' || state.freshness === 'NO_DATA'
  if (config.swl === undefined) return <div style={meta}>SWL not set</div>
  const fraction = (value ?? 0) / config.swl
  const condition = fraction >= config.alarm_fraction ? { word: 'Over limit', shape: '✕', token: '--down' } : fraction >= config.warn_fraction ? { word: 'Near limit', shape: '▲', token: '--check' } : { word: 'OK', shape: '●', token: '--ok' }
  return <div data-testid="tension-bar" data-stale={String(stale)} style={{ opacity: stale ? 0.45 : 1 }}>
    <div data-testid="tension-bands" style={{ position: 'relative', height: 44, background: 'var(--panel2)', border: '1px solid var(--line)', marginTop: 12 }}>
      <span style={{ position: 'absolute', left: `${config.warn_fraction * 100}%`, height: '100%', borderLeft: '3px solid var(--check)' }} />
      <span style={{ position: 'absolute', left: `${config.alarm_fraction * 100}%`, height: '100%', borderLeft: '3px solid var(--down)' }} />
      <span style={{ display: 'block', width: `${Math.min(100, Math.max(0, fraction * 100))}%`, height: '100%', background: `var(${stale ? '--stale' : condition.token})` }} />
    </div>
    <div style={{ ...meta, color: `var(${stale ? '--stale' : condition.token})` }}>{condition.shape} <span>{condition.word}</span> · SWL {format(config.swl, 'kg')}</div>
  </div>
}

function Altimeter({ state, config }: { state: FieldState; config: CastSettings }) {
  const value = numberValue(state)
  const noBottom = value === undefined || value < 0 || value > 100
  const condition = !noBottom && value <= config.altimeter_alarm ? ['✕', 'Bottom alarm', '--down'] : !noBottom && value <= config.altimeter_warn ? ['▲', 'Near bottom', '--check'] : ['●', 'OK', '--ok']
  return <section style={panel}><div style={label}>Altimeter</div><div style={big}>{noBottom ? 'No bottom' : `Bottom in ${format(value, 'm')}`}</div><div style={{ ...meta, color: `var(${condition[2]})` }}>{condition[0]} <span>{condition[1]}</span></div><Freshness state={state} /></section>
}

function TensionChart({ ctx, field }: { ctx: ConsoleContext; field: string }) {
  const samples = ctx.store.history(field, 15 * 60).map(sample => ({ time: sample.time, value: finite(sample.value) })).filter((sample): sample is { time: number; value: number } => sample.value !== undefined)
  const max = Math.max(1, ...samples.map(sample => sample.value))
  const now = ctx.clock.now()
  const points = samples.map(sample => `${((sample.time - (now - 900)) / 900) * 100},${100 - sample.value / max * 100}`).join(' ')
  return <section style={{ ...panel, gridColumn: '1 / -1' }}><div style={label}>Tension, last 15 minutes</div><svg viewBox="0 0 100 100" role="img" aria-label="Tension strip chart" style={{ width: '100%', height: 160, background: 'var(--panel2)' }}><polyline points={points} fill="none" stroke="var(--chart)" strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg></section>
}

function numberValue(state: FieldState): number | undefined { return finite(state.value) }
function unit(ctx: ConsoleContext, field: string, fallback: string) { return ctx.store.describe(field)?.units ?? fallback }
function format(value: number | undefined, units: string) { return value === undefined ? `— ${units}` : `${Number.isInteger(value) ? value : value.toFixed(1)} ${units}` }
function speedText(value: number | undefined, units: string) { return value === undefined ? `— ${units}` : `${Math.abs(value).toFixed(1)} ${units} ${value >= 0 ? 'down' : 'up'}` }
function ageWords(age: number | undefined) {
  if (age === undefined) return 'an unknown time'
  const seconds = Math.max(0, Math.round(age)); const minutes = Math.floor(seconds / 60); const remainder = seconds % 60
  return [minutes ? `${minutes} minute${minutes === 1 ? '' : 's'}` : '', remainder || !minutes ? `${remainder} second${remainder === 1 ? '' : 's'}` : ''].filter(Boolean).join(' ')
}

function validate(raw: Record<string, unknown>, where: { file: string; tile?: number }): TileConfig {
  for (const key of fieldKeys) if (raw[key] !== undefined && typeof raw[key] !== 'string') throw { where, setting: key, saw: typeof raw[key], expected: 'a field name', example: `${key}: WinchField` } satisfies PageProblem
  return { ...raw, type: 'cast' } as TileConfig
}

const castModule: ConsoleModule = {
  id: 'cast',
  tiles: [{ type: 'cast', validate, fields: (cfg, ctx) => { const config = settings(ctx, cfg); return fieldKeys.map(key => config[key]) }, Component: CastView }],
  routes: [{ id: 'cast', title: 'Cast', order: 40, fields: ctx => { const config = settings(ctx); return fieldKeys.map(key => config[key]) }, Component: CastView }],
}

export default castModule
