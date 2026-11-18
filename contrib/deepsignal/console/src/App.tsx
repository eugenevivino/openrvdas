import { useEffect, useEffectEvent, useMemo, useState, useSyncExternalStore } from 'react'
import { CdsClient } from './cds'
import { fieldData } from './field-data'
import type { Freshness, Quality, Reading } from './field-data'
import { LightingControls } from './LightingControls'
import { isShortcut } from './lighting'
import type { NightPalette } from './lighting'
import { loadConsole } from './pages'
import type { LoadedConsole, NumberTileConfig } from './pages'
import { Sparkline } from './Sparkline'

const emptyHistory: readonly Reading[] = []

const statusStyles = {
  ok: ['circle', 'ok'], check: ['triangle', 'check'], down: ['cross', 'down'],
  LIVE: ['circle', 'normal'], AGING: ['triangle', 'check'], STALE: ['square', 'stale'], 'NO DATA': ['dash', 'missing'],
  PASS: ['circle', 'normal'], 'NOT EVALUATED': ['diamond', 'normal'], SUSPECT: ['triangle', 'check'],
  FAIL: ['cross', 'down'], MISSING: ['square', 'missing'],
} satisfies Record<Freshness | Quality | 'ok' | 'check' | 'down', readonly [string, string]>

type State = keyof typeof statusStyles

function Status({ state, children }: { state: State; children?: string }) {
  const [shape, color] = statusStyles[state]
  return (
    <span className={'status status-' + color}>
      <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        {shape === 'circle' && <circle cx="6" cy="6" r="5" fill="currentColor" />}
        {shape === 'triangle' && <path d="M6 1 11 11H1Z" fill="currentColor" />}
        {shape === 'square' && <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="2" />}
        {shape === 'cross' && <path d="M2 2l8 8m0-8-8 8" stroke="currentColor" strokeWidth="2.4" />}
        {shape === 'diamond' && <path d="m6 1 5 5-5 5-5-5Z" fill="none" stroke="currentColor" strokeWidth="1.5" />}
        {shape === 'dash' && <path d="M1 6h10" stroke="currentColor" strokeWidth="2" />}
      </svg>
      {children ?? state}
    </span>
  )
}

function age(timestamp: number, now: number) {
  return Math.max(0, Math.floor(now - timestamp))
}

function Clock({ now, timeZone }: { now: number; timeZone: string }) {
  const clock = useMemo(() => new Intl.DateTimeFormat('en-GB', {
    hourCycle: 'h23', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone,
  }), [timeZone])
  const iso = new Date(now * 1000).toISOString()
  return (
    <div className="clock">
      <div><time dateTime={iso}>{iso.slice(11, 19)}</time> UTC</div>
      <div><time dateTime={iso}>{clock.format(now * 1000)}</time> ship</div>
    </div>
  )
}

function NumberTile({ tile, data, history, now }: {
  tile: NumberTileConfig
  data: ReturnType<typeof fieldData>
  history: readonly Reading[]
  now: number
}) {
  const { value, timestamp, freshness, quality, lastGood, expectedPeriod, age: secondsOld } = data
  const noData = freshness === 'NO DATA'
  const showValue = !noData && value !== null
  const observed = timestamp === undefined ? undefined : new Date(timestamp * 1000).toISOString()
  const lastGoodTime = lastGood && new Date(lastGood.timestamp * 1000).toISOString()
  return (
    <article className={tile.wide ? 'tile wide' : 'tile'}>
      <div className="tile-header">
        <h2>{tile.label}</h2>
        <div className="tile-states">
          <span className="freshness" role="group" aria-label="Freshness"><Status state={freshness} /></span>
          <span className="quality" role="group" aria-label="Data quality"><Status state={quality} /></span>
        </div>
      </div>
      <div className="value">
        {showValue ? <>{value.toFixed(tile.decimals)}<span className="unit"> {tile.unit}</span></> : '—'}
      </div>
      {tile.sparkline && <Sparkline history={history} now={now} minutes={tile.sparkline} period={expectedPeriod} />}
      <div className="tile-meta">
        <span>Source {tile.field}</span>
        {secondsOld !== undefined
          ? <span className={freshness !== 'LIVE' || value === null ? 'reading-exception' : undefined}>
              {!noData && value === null && 'Bad reading. '}
              {Math.floor(secondsOld)} s old
              {freshness !== 'LIVE' && <time dateTime={observed}> · {observed?.slice(11, 19)}Z</time>}
            </span>
          : <span>Waiting for data</span>}
        {noData && lastGood?.value != null && (
          <span className="last-reading">Last: {lastGood.value.toFixed(tile.decimals)} {tile.unit} at{' '}
            <time dateTime={lastGoodTime}>{lastGoodTime?.slice(11, 19)}Z</time>
          </span>
        )}
      </div>
    </article>
  )
}

function Header({ children, ship, defaultPalette }: {
  children?: React.ReactNode
  ship?: string
  defaultPalette?: NightPalette
}) {
  return (
    <header className="bar">
      <div className="brand">
        <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="6" r="2.5" fill="currentColor" />
          <path d="M2 14c3-4 5-4 8 0s5 4 8 0 3-3 4-2M2 19c3-3 5-3 8 0s5 3 8 0" />
        </svg>
        <span>DeepSignal</span>
        {ship && <span className="ship">{ship}</span>}
      </div>
      <span className="monitoring-label">Research system monitoring</span>
      {children}
      <LightingControls defaultPalette={defaultPalette} />
    </header>
  )
}

function Console({ config, pages }: LoadedConsole) {
  const [route, setRoute] = useState(() => window.location.hash.slice(1))
  const selected = pages.find(({ id }) => id === route) ?? pages[0]
  const page = selected.page
  const [now, setNow] = useState(() => Date.now() / 1000)
  const client = useMemo(() => new CdsClient(config.websocket), [config.websocket])
  const { connection, fields, history, lastData } = useSyncExternalStore(client.subscribe, client.getSnapshot)
  const connected = connection === 'connected'

  const onShortcut = useEffectEvent((event: KeyboardEvent) => {
    if (!isShortcut(event) || !/^[1-9]$/.test(event.key)) return
    const target = pages[Number(event.key) - 1]
    if (target) window.location.hash = target.id
  })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => onShortcut(event)
    const onHash = () => setRoute(window.location.hash.slice(1))
    const tick = window.setInterval(() => setNow(Date.now() / 1000), 1000)
    window.addEventListener('keydown', onKey)
    window.addEventListener('hashchange', onHash)
    return () => {
      window.clearInterval(tick)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('hashchange', onHash)
    }
  }, [])

  useEffect(() => {
    if (route !== selected.id) window.history.replaceState(null, '', '#' + selected.id)
  }, [route, selected.id])

  useEffect(() => () => client.stop(), [client])

  useEffect(() => {
    const wanted = new Map<string, number>()
    for (const tile of page?.tiles ?? []) {
      const seconds = Math.max(config.history, (tile.sparkline ?? 0) * 60)
      wanted.set(tile.field, Math.max(wanted.get(tile.field) ?? -1, seconds || -1))
    }
    client.setFields(Object.fromEntries(wanted))
  }, [client, page, config.history])

  const tiles = (page?.tiles ?? []).map((tile) => ({ tile, data: fieldData(fields.get(tile.field), tile.period, now) }))
  const last = tiles.reduce<number | undefined>((latest, { data }) => {
    if (data.timestamp !== undefined && data.value !== null && data.freshness === 'LIVE') {
      return Math.max(latest ?? 0, data.timestamp)
    }
    return latest
  }, undefined)

  let pillState: State = 'check'
  let pill = page ? 'Connecting' : 'Page unavailable'
  if (page && connection === 'reconnecting') {
    pillState = 'down'
    pill = lastData === undefined ? 'Reconnecting, no data yet' : `Reconnecting, last data ${age(lastData, now)} s ago`
  } else if (page && connected && last !== undefined) {
    pillState = 'ok'
    pill = `Live ${age(last, now)} s`
  } else if (page && connected) {
    pill = 'Waiting for current data'
  }

  return (
    <>
      <Header ship={config.ship} defaultPalette={config.night_palette}>
        <nav className="tabs" aria-label="Pages">
          {pages.map(({ id, title }, index) => (
            <a href={'#' + id} key={id} aria-current={id === selected.id ? 'page' : undefined}
              aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}>{title}</a>
          ))}
        </nav>
        <div className="live" role="group" aria-label="Data connection"><Status state={pillState}>{pill}</Status></div>
        <Clock now={now} timeZone={config.ship_timezone} />
      </Header>
      <main>
        <h1>{page?.title ?? selected.title}</h1>
        {page ? (
          <div className="tiles">
            {tiles.map(({ tile, data }, index) => (
              <NumberTile key={page.id + '/' + index} tile={tile} data={data}
                history={history.get(tile.field) ?? emptyHistory} now={now} />
            ))}
          </div>
        ) : <p className="message" role="alert">{selected.error} Reload this page after correcting the file.</p>}
      </main>
    </>
  )
}

export default function App() {
  const [result, setResult] = useState<{ data: LoadedConsole } | { error: string }>()
  useEffect(() => {
    const controller = new AbortController()
    loadConsole(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ data }) },
      (error: Error) => { if (!controller.signal.aborted) setResult({ error: error.message }) },
    )
    return () => controller.abort()
  }, [])

  if (result && 'data' in result) return <Console {...result.data} />
  return (
    <>
      <Header />
      <main>
        <h1>Data console</h1>
        {result
          ? <p className="message" role="alert">{result.error} Reload this page after correcting the file.</p>
          : <p className="message" role="status">Loading pages…</p>}
      </main>
    </>
  )
}
