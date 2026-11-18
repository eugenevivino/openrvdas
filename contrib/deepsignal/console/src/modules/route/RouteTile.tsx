import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { ConsoleContext, FieldState, TileConfig } from '../../contract'
import { bearingDeg, courseDifferenceDeg, crossTrackM, distanceM, METRES_PER_NM, travelSeconds } from './geo'
import { coordinate, routeSource, type Station } from './source'
import './route.css'

type Status = 'ok' | 'check' | 'stale' | 'down'
function Notice({ state, children }: { state: Status; children: ReactNode }) {
  const shapes = { ok: '●', check: '▲', stale: '□', down: '×' }
  return <p className={`route-notice route-${state}`}><span aria-hidden="true">{shapes[state]} </span><span>{children}</span></p>
}

function nm(m: number) { return `${(m / METRES_PER_NM).toFixed(1)} nm` }

function Destination({ label, station, metres, bearing, now, speed }: {
  label: string; station: Station; metres: number; bearing: number; now: number; speed?: number
}) {
  const seconds = speed === undefined ? undefined : travelSeconds(metres, speed)
  const minutes = Math.floor((seconds ?? 0) / 60)
  return <section role="group" aria-label={label}>
    <h3>{label}</h3><p className="route-name">{station.name}</p>
    <dl>
      <dt>Distance</dt><dd>{nm(metres)}</dd>
      <dt>Bearing</dt><dd>{Math.round(bearing) % 360}° true</dd>
      {seconds !== undefined && <>
        <dt>Time to go</dt><dd>{Math.floor(minutes / 60)} h {String(minutes % 60).padStart(2, '0')} min</dd>
        <dt>ETA</dt><dd>{new Date((now + seconds) * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC</dd>
      </>}
    </dl>
  </section>
}

function current(field: FieldState) {
  return field.freshness === 'LIVE' || field.freshness === 'AGING'
}

function numeric(field: FieldState) {
  const value = field.value
  if (typeof value === 'number') return value
  if (typeof value === 'string' && value.trim()) return Number(value)
  return NaN
}

function age(field: FieldState, now: number) {
  return field.sourceTime === undefined ? field.ageS : now - field.sourceTime
}

function Navigation({ ctx, file, lat, lon, cog, sog }: {
  ctx: ConsoleContext; file: string; lat: string; lon: string; cog: string; sog: string
}) {
  const [view, setView] = useState<ReactNode>(<Notice state="check">Loading route</Notice>)

  useEffect(() => {
    let mounted = true
    let unsubscribe: (() => void) | undefined
    let awaySince: number | undefined
    const source = routeSource(ctx, file)
    const feedKey = JSON.stringify([lat, lon])
    function update(stations: Station[]) {
      const now = ctx.clock.now()
      let index = source.indices.get(feedKey) ?? 0
      if (index === stations.length) {
        setView(<Notice state="ok">Route complete</Notice>)
        return
      }
      const latitude = ctx.store.get(lat)
      const longitude = ctx.store.get(lon)
      const position = { lat: numeric(latitude), lon: numeric(longitude) }
      const positionFields = [latitude, longitude]
      if (positionFields.some(f => f.freshness === 'NO_DATA')
        || !coordinate(position.lat, 90) || !coordinate(position.lon, 180)) {
        awaySince = undefined
        setView(<Notice state="down">Position unavailable. No ETA.</Notice>)
        return
      }
      if (positionFields.some(f => f.freshness === 'STALE')) {
        awaySince = undefined
        const ages = positionFields.map(f => age(f, now)).filter((a): a is number => a !== undefined)
        const lastSeen = ages.length ? `last seen ${Math.round(Math.max(0, ...ages))} s ago` : 'age unknown'
        setView(<><Notice state="stale">Stale position, {lastSeen}. No ETA.</Notice>
          <s className="route-old">{position.lat}° latitude, {position.lon}° longitude</s></>)
        return
      }
      while (index < stations.length && distanceM(position, stations[index]) <= 0.1 * METRES_PER_NM) {
        index++
        awaySince = undefined
      }
      source.indices.set(feedKey, index)
      if (index === stations.length) {
        setView(<Notice state="ok">Route complete</Notice>)
        return
      }

      const next = stations[index]
      const end = stations[stations.length - 1]
      const metres = distanceM(position, next)
      const bearing = bearingDeg(position, next)
      const course = ctx.store.get(cog)
      const courseDeg = numeric(course)
      const hasCourse = current(course) && Number.isFinite(courseDeg)
      if (hasCourse && courseDifferenceDeg(bearing, courseDeg) > 45) {
        if (awaySince === undefined || now < awaySince) awaySince = now
      } else {
        awaySince = undefined
      }
      const offCourse = awaySince !== undefined && now - awaySince >= 60
      const velocity = ctx.store.get(sog)
      const knots = numeric(velocity)
      const speed = current(velocity) && Number.isFinite(knots) && knots >= 0 ? knots : undefined
      const etaSpeed = speed !== undefined && speed >= 0.5 ? speed : undefined
      const xt = index > 0 ? crossTrackM(stations[index - 1], next, position) : undefined
      const aging = positionFields.some(f => f.freshness === 'AGING')

      setView(<>
        {offCourse ? <Notice state="check">Check waypoint</Notice>
          : !hasCourse ? <Notice state="check">Course unavailable</Notice>
          : aging ? <Notice state="check">Position aging</Notice> : <Notice state="ok">Tracking waypoint</Notice>}
        {etaSpeed === undefined && <Notice state="check">{speed === undefined ? 'No ETA: speed unavailable' : 'No ETA: speed under 0.5 kn'}</Notice>}
        <Destination label="Next waypoint" station={next} metres={metres} bearing={bearing} now={now} speed={etaSpeed} />
        <dl><dt>Cross-track distance</dt><dd>{xt === undefined ? 'No leg before the first waypoint'
          : Math.abs(xt) < 1e-6 ? '0.0 nm on track' : `${nm(Math.abs(xt))} ${xt < 0 ? 'port' : 'starboard'}`}</dd></dl>
        <Destination label="Route end" station={end} metres={metres + next.remainingM}
          bearing={bearingDeg(position, end)} now={now} speed={etaSpeed} />
      </>)
    }

    source.stations.then(stations => {
      if (!mounted) return
      unsubscribe = ctx.store.subscribe([lat, lon, cog, sog], () => update(stations))
      update(stations)
    }, (error: Error) => {
      if (mounted) setView(<Notice state="down">{error.message}</Notice>)
    })
    return () => { mounted = false; unsubscribe?.() }
  }, [ctx, file, lat, lon, cog, sog])

  return <>{view}</>
}

export function RouteTile({ cfg, ctx }: { cfg: TileConfig; ctx: ConsoleContext }) {
  const settings = {
    file: String(cfg.route ?? 'routes.json'), lat: String(cfg.lat), lon: String(cfg.lon),
    cog: String(cfg.cog), sog: String(cfg.sog),
  }
  return <article className="route-tile">
    <h2>{cfg.label ?? 'Route'}</h2>
    <Navigation key={JSON.stringify(settings)} ctx={ctx} {...settings} />
  </article>
}
