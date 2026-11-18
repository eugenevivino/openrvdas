import { useEffect, useEffectEvent, useMemo, useState, useSyncExternalStore } from 'react'
import { CdsClient, isStale } from './cds'
import type { Reading } from './cds'
import { LightingControls } from './LightingControls'
import { isShortcut } from './lighting'
import { loadConsole } from './pages'
import type { LoadedConsole, NumberTileConfig } from './pages'
import { Sparkline } from './Sparkline'

type State = 'OK' | 'Check' | 'Stale' | 'Down'
const emptyHistory: readonly Reading[] = []

function Status({ state, children }: { state: State; children?: string }) {
  return (
    <span className={'status status-' + state.toLowerCase()}>
      <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        {state === 'OK' && <circle cx="6" cy="6" r="5" fill="currentColor" />}
        {state === 'Check' && <path d="M6 1 11 11H1Z" fill="currentColor" />}
        {state === 'Stale' && <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="2" />}
        {state === 'Down' && <path d="M2 2l8 8m0-8-8 8" stroke="currentColor" strokeWidth="2.4" />}
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

function NumberTile({ tile, reading, history, now, connected }: {
  tile: NumberTileConfig
  reading?: Reading
  history: readonly Reading[]
  now: number
  connected: boolean
}) {
  const stale = reading && isStale(reading.timestamp, now, tile.stale_after)
  let state: State = 'Check'
  if (stale) state = 'Stale'
  else if (!connected) state = 'Down'
  else if (reading && reading.value !== null) state = 'OK'

  const value = reading?.value
  const observed = reading ? new Date(reading.timestamp * 1000).toISOString() : undefined
  return (
    <article className={tile.wide ? 'tile wide' : 'tile'}>
      <div className="tile-header">
        <h2>{tile.label}</h2>
        <Status state={state} />
      </div>
      <div className={state !== 'OK' && typeof value === 'number' ? 'value expired' : 'value'}>
        {typeof value === 'number' ? value.toFixed(tile.decimals) : '—'}
        <span className="unit"> {tile.unit}</span>
      </div>
      {tile.sparkline && <Sparkline history={history} now={now} minutes={tile.sparkline} staleAfter={tile.stale_after} />}
      <div className="tile-meta">
        <span>Source {tile.field}</span>
        {reading
          ? <span>
              {value === null && 'Bad reading. '}
              {state !== 'OK' && 'Last seen '}
              {age(reading.timestamp, now)} s ago
              {state !== 'OK' && <time dateTime={observed}> at {observed?.slice(11, 19)} UTC</time>}
            </span>
          : <span>Waiting for data</span>}
      </div>
    </article>
  )
}

function Header({ children, ship }: { children?: React.ReactNode; ship?: string }) {
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
      {children}
      <LightingControls />
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

  const last = (page?.tiles ?? []).reduce<number | undefined>((latest, tile) => {
    const reading = fields.get(tile.field)
    if (reading && reading.value !== null && !isStale(reading.timestamp, now, tile.stale_after)) {
      return Math.max(latest ?? 0, reading.timestamp)
    }
    return latest
  }, undefined)

  let pillState: State = 'Check'
  let pill = page ? 'Connecting' : 'Page unavailable'
  if (page && connection === 'reconnecting') {
    pillState = 'Down'
    pill = lastData === undefined ? 'Reconnecting, no data yet' : `Reconnecting, last data ${age(lastData, now)} s ago`
  } else if (page && connected && last !== undefined) {
    pillState = 'OK'
    pill = `Live ${age(last, now)} s`
  } else if (page && connected) {
    pill = 'Waiting for current data'
  }

  return (
    <>
      <Header ship={config.ship}>
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
            {page.tiles.map((tile, index) => (
              <NumberTile key={page.id + '/' + index} tile={tile} reading={fields.get(tile.field)}
                history={history.get(tile.field) ?? emptyHistory} now={now} connected={connected} />
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
