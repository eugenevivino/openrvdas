import { useEffect, useState } from 'react'
import type { ConsoleContext, Freshness, Quality, TileConfig } from '../../contract'
import { Status } from '../../Status'
import { Sparkline } from './Sparkline'
import type { NumberTileConfig } from './validate'
import './number.css'

const statusStyles = {
  LIVE: ['circle', 'normal'], AGING: ['triangle', 'check'], STALE: ['square', 'stale'], NO_DATA: ['dash', 'missing'],
  PASS: ['circle', 'normal'], NOT_EVALUATED: ['diamond', 'normal'], SUSPECT: ['triangle', 'check'],
  FAIL: ['cross', 'down'], MISSING: ['square', 'missing'],
} as const satisfies Record<Freshness | Quality, readonly [string, string]>

const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

const emptyHistory: ReturnType<ConsoleContext['store']['history']> = []
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

function Badge({ state }: { state: Freshness | Quality }) {
  const [shape, tone] = statusStyles[state]
  return <Status shape={shape} tone={tone}>{state.replace('_', ' ')}</Status>
}

function Trend({ history, period, unit, decimals }: {
  history: typeof emptyHistory
  period: number
  unit: string
  decimals: number
}) {
  const first = history.find(({ value }) => isNumber(value))
  const last = history.findLast(({ value }) => isNumber(value))
  if (!first || !last || first.time >= last.time || !isNumber(first.value) || !isNumber(last.value)) return null
  const change = Number(((last.value - first.value) * period / (last.time - first.time)).toFixed(Math.max(3, decimals)))
  const label = change > 0 ? 'Rising' : change < 0 ? 'Falling' : 'Steady'
  const shape = change > 0 ? '↑' : change < 0 ? '↓' : '→'
  return <span className="number-trend"><span aria-hidden="true">{shape} </span>
    {label} {change > 0 ? '+' : ''}{change} {unit} / {period} s
  </span>
}

export function NumberTile({ cfg, ctx }: { cfg: TileConfig; ctx: ConsoleContext }) {
  const tile = cfg as NumberTileConfig
  const [, update] = useState(0)
  useEffect(() => ctx.store.subscribe([tile.field], () => update((current) => current + 1)), [ctx, tile.field])

  const { value, sourceTime, freshness, quality, lastGood, periodS, ageS } = ctx.store.get(tile.field)
  const now = ctx.clock.now()
  const noData = freshness === 'NO_DATA'
  const showValue = !noData && isNumber(value)
  const period = periodS ?? 1
  const observed = sourceTime === undefined ? undefined : new Date(sourceTime * 1000).toISOString()
  const lastGoodTime = lastGood && new Date(lastGood.time * 1000).toISOString()
  const history = tile.sparkline ? ctx.store.history(tile.field, tile.sparkline * 60) : emptyHistory
  const recent = tile.trend ? ctx.store.history(tile.field, tile.trend * 60) : emptyHistory

  return (
    <article className="tile number-tile">
      <div className="tile-header">
        <h2>{tile.label}</h2>
        <div className="tile-states">
          <span className="freshness" role="group" aria-label="Freshness"><Badge state={freshness} /></span>
          <span className="quality" role="group" aria-label="Data quality"><Badge state={quality} /></span>
        </div>
      </div>
      <div className="value">
        {showValue ? <>{value.toFixed(tile.decimals)}<span className="unit"> {tile.unit}</span>
          {tile.compass && <span className="unit"> {directions[((Math.round(value / 22.5) % 16) + 16) % 16]}</span>}
        </> : '—'}
      </div>
      {tile.trend && showValue && <Trend history={recent} period={period} unit={tile.unit} decimals={tile.decimals} />}
      {tile.sparkline && <Sparkline history={history} now={now} minutes={tile.sparkline} period={period} lighting={ctx.lighting} />}
      <div className="tile-meta">
        <span>Source {tile.field}</span>
        {ageS !== undefined
          ? <span className={freshness !== 'LIVE' || !isNumber(value) ? 'reading-exception' : undefined}>
              {!noData && !isNumber(value) && 'Bad reading. '}
              {Math.floor(ageS)} s old
              {freshness !== 'LIVE' && <time dateTime={observed}> · {observed?.slice(11, 19)}Z</time>}
            </span>
          : <span>Waiting for data</span>}
        {noData && lastGood && isNumber(lastGood.value) && (
          <span className="last-reading">Last: {lastGood.value.toFixed(tile.decimals)} {tile.unit} at{' '}
            <time dateTime={lastGoodTime}>{lastGoodTime?.slice(11, 19)}Z</time>
          </span>
        )}
      </div>
    </article>
  )
}
