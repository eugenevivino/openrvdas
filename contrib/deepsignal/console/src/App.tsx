import { Component, useEffect, useEffectEvent, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { createConsoleContext, realClock } from './context'
import type { ConsoleContext, ConsoleModule, Page, RouteDef, TileConfig, TileDef } from './contract'
import { LightingControls } from './LightingControls'
import { isShortcut } from './lighting'
import { loadConsole, parsePage } from './pages'
import type { LoadedConsole } from './pages'
import { discoverModules } from './registry'
import { describeSetting, formatPageProblem, isMapping, isPageProblem, isPositive } from './settings'
import { Status } from './Status'
import { ConsoleStore } from './store'
import type { FieldRequest } from './store'

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function moduleProblem(id: string, error: unknown) {
  return `Module ${id}: ${message(error)}`
}

function Message({ children }: { children: ReactNode }) {
  return <p className="message" role="alert">{children}</p>
}

class ModuleBoundary extends Component<{ id: string; children: ReactNode }, { problem?: string }> {
  state: { problem?: string } = {}

  static getDerivedStateFromError(error: unknown) {
    return { problem: message(error) }
  }

  render() {
    const { problem } = this.state
    return problem === undefined ? this.props.children : <Message>{moduleProblem(this.props.id, problem)}</Message>
  }
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

function Header({ children, ctx }: { children?: ReactNode; ctx?: Runtime['ctx'] }) {
  return (
    <header className="bar">
      <div className="brand">
        <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="6" r="2.5" fill="currentColor" />
          <path d="M2 14c3-4 5-4 8 0s5 4 8 0 3-3 4-2M2 19c3-3 5-3 8 0s5 3 8 0" />
        </svg>
        <span>DeepSignal</span>
        {ctx && <span className="ship">{ctx.config.ship}</span>}
      </div>
      <span className="monitoring-label">Research system monitoring</span>
      {children}
      <LightingControls controller={ctx?.lighting} />
    </header>
  )
}

function definitions<K extends 'tiles' | 'routes' | 'engines' | 'adapters' | 'slots'>(modules: ConsoleModule[], key: K) {
  type Definition = NonNullable<ConsoleModule[K]>[number]
  return modules.flatMap((module) => ((module[key] ?? []) as Definition[])
    .map((def) => ({ owner: module.id, def })))
}

interface Plugin<T> {
  owner: string
  def: T
}

function index<T>(entries: Array<Plugin<T>>, key: (def: T) => string, problems: string[]) {
  const unique = new Map<string, Plugin<T>>()
  for (const plugin of entries) {
    const id = key(plugin.def)
    if (unique.has(id)) problems.push(moduleProblem(plugin.owner, `"${id}" is already provided by ${unique.get(id)!.owner}.`))
    else unique.set(id, plugin)
  }
  return unique
}

function initialize({ config, files, periods }: LoadedConsole, modules: ConsoleModule[], problems: string[]) {
  const store = new ConsoleStore(config, realClock)
  const ctx = createConsoleContext(config, store, realClock)
  const pageProblems = new Map<string, string>()
  for (const module of modules) {
    for (const preset of module.presets ?? []) {
      const file = preset.id + '.yaml'
      try {
        ctx.pages.register({ ...parsePage(file, preset.yaml), source: 'preset:' + module.id })
      } catch (error) {
        problems.push(moduleProblem(module.id, message(error)))
      }
    }
  }
  for (const { page, problem } of files) {
    ctx.pages.register(page)
    if (problem) pageProblems.set(page.id, problem)
  }
  const tiles = index(definitions(modules, 'tiles'), (tile) => tile.type, problems)
  const routes = index(definitions(modules, 'routes'), (route) => route.id, problems)
  const engines = definitions(modules, 'engines')
  const adapters = definitions(modules, 'adapters')
  const slots = definitions(modules, 'slots').sort((a, b) => a.def.order - b.def.order)
  return { ctx, store, periods, tiles, routes, engines, adapters, slots, problems, pageProblems }
}

type Runtime = ReturnType<typeof initialize>

interface Destination {
  id: string
  title: string
  order?: number
  page?: Page
  route?: Plugin<RouteDef>
  problem?: string
}

function destinations({ ctx, routes, pageProblems }: Runtime): Destination[] {
  const items = new Map<string, Destination>()
  for (const [id, route] of routes) items.set(id, { id, title: route.def.title, order: route.def.order, route })
  for (const page of ctx.pages.list()) items.set(page.id, {
    id: page.id, title: page.title, order: page.order, page, problem: pageProblems.get(page.id),
  })
  const order = ctx.config.pages
  const listed = order.map((id) => items.get(id) ?? {
    id, title: id, problem: `Page ${id} is unavailable. Expected pages/${id}.yaml or a module that provides ${id}.`,
  })
  const extra = [...items.values()].filter(({ id }) => !order.includes(id))
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  return [...listed, ...extra]
}

interface PreparedTile {
  wide: boolean
  plugin?: Plugin<TileDef>
  cfg?: TileConfig
  problem?: string
}

function prepareTiles(page: Page | undefined, tiles: Runtime['tiles']): PreparedTile[] {
  return (page?.tiles ?? []).map((raw, index) => {
    const where = { file: page?.source?.startsWith('file:') ? page.source.slice(5) : page!.id + '.yaml', tile: index + 1 }
    const input: Record<string, unknown> = isMapping(raw) ? raw : {}
    const type = typeof input.type === 'string' ? input.type : ''
    const fallback = typeof input.fallback === 'string' ? input.fallback : ''
    const plugin = tiles.get(type) ?? tiles.get(fallback)
    const wide = input.wide === true
    if (!plugin) {
      const types = [...tiles.keys()]
      return { wide, problem: formatPageProblem({
        where, setting: 'type', saw: describeSetting(input.type),
        expected: types.length ? 'an installed tile type (' + types.join(', ') + ')' : 'an installed tile type',
        example: 'type: ' + (types[0] ?? 'number'),
      }) }
    }
    try {
      const cfg = plugin.def.validate({ ...input, type: plugin.def.type }, where)
      if (!isMapping(cfg)) throw new Error('Tile validation must return settings.')
      return { wide: cfg.wide ?? wide, plugin, cfg }
    } catch (error) {
      return { wide, problem: isPageProblem(error) ? formatPageProblem(error) : moduleProblem(plugin.owner, error) }
    }
  })
}

function requestedFields(owner: string, read: () => string[], problems: string[], adapter = false) {
  try {
    const fields = read()
    if (!Array.isArray(fields) || fields.some((field) => typeof field !== 'string' || !field ||
      (field.includes('*') && !(adapter && field === 'status:*')))) throw new Error('Expected a list of cache fields.')
    return fields
  } catch (error) {
    problems.push(moduleProblem(owner, error))
    return []
  }
}

function demands(runtime: Runtime, selected: Destination | undefined, tiles: PreparedTile[], problems: string[]) {
  const { ctx, adapters, periods } = runtime
  const visible = new Set<string>()
  const fields = new Map<string, FieldRequest>()
  const add = (field: string, period?: number, logger?: string, raw = false) => {
    const previous = fields.get(field)
    fields.set(field, { period: previous?.period ?? period, logger: previous?.logger ?? logger,
      raw: previous ? previous.raw === true && raw : raw })
  }
  for (const { plugin, cfg } of tiles) {
    if (!plugin || !cfg) continue
    const logger = typeof cfg.logger === 'string' ? cfg.logger : undefined
    for (const field of requestedFields(plugin.owner, () => plugin.def.fields(cfg, ctx), problems)) {
      visible.add(field)
      add(field, isPositive(cfg.period) ? cfg.period : undefined, logger)
    }
  }
  const route = selected?.route
  if (route?.def.fields) {
    for (const field of requestedFields(route.owner, () => route.def.fields!(ctx), problems)) {
      visible.add(field)
      add(field, undefined, undefined, route.def.rawFields === true)
    }
  }
  const subscriptions = adapters.map((plugin) => {
    const names = requestedFields(plugin.owner, () => plugin.def.fields(ctx), problems, true)
    for (const name of names) add(name)
    return { ...plugin, fields: new Set(names) }
  })
  for (const [field, request] of fields) request.period ??= periods.get(field)
  return { visible, fields, subscriptions }
}

function ConnectionStatus({ store, visible }: { store: ConsoleStore; visible: Set<string> }) {
  const connection = store.connection()
  const age = store.lastMessageAgeS()
  let latest: number | undefined
  for (const field of visible) {
    const data = store.get(field)
    if (data.freshness === 'LIVE' && data.ageS !== undefined && data.value != null) {
      latest = Math.min(latest ?? Infinity, data.ageS)
    }
  }
  let label = 'Connecting'
  let shape: 'triangle' | 'circle' | 'cross' = 'triangle'
  let tone = 'check'
  if (connection === 'reconnecting') {
    label = age === undefined ? 'Reconnecting, no messages yet' : `Reconnecting, last message ${Math.floor(age)} s ago`
    shape = 'cross'
    tone = 'down'
  } else if (connection === 'connected' && latest !== undefined) {
    label = `Live ${Math.floor(latest)} s`
    shape = 'circle'
    tone = 'ok'
  } else if (connection === 'connected') {
    label = 'Waiting for current data'
  }
  return <div className="live" role="group" aria-label="Data connection">
    <Status shape={shape} tone={tone}>{label}</Status>
  </div>
}

function Slots({ runtime, slot }: { runtime: Runtime; slot: 'topbar' | 'banner' }) {
  return runtime.slots.filter(({ def }) => def.slot === slot).map(({ owner, def }, i) => (
    <ModuleBoundary id={owner} key={owner + '/' + i}><def.Component ctx={runtime.ctx} /></ModuleBoundary>
  ))
}

function PageView({ selected, prepared, ctx }: { selected?: Destination; prepared: PreparedTile[]; ctx: ConsoleContext }) {
  if (!selected) return <p className="message" role="status">No pages are available.</p>
  if (selected.problem) return <Message>{selected.problem}</Message>
  const route = selected.route
  if (route) return <ModuleBoundary id={route.owner} key={selected.id}><route.def.Component ctx={ctx} /></ModuleBoundary>
  return <div className="tiles">
    {prepared.map(({ plugin, cfg, problem, wide }, i) => (
      <div className={wide ? 'tile-frame wide' : 'tile-frame'} key={selected.id + '/' + i}>
        {plugin && cfg
          ? <ModuleBoundary id={plugin.owner} key={plugin.def.type}><plugin.def.Component cfg={cfg} ctx={ctx} /></ModuleBoundary>
          : <Message>{problem}</Message>}
      </div>
    ))}
  </div>
}

function Console({ runtime }: { runtime: Runtime }) {
  const { ctx, store, engines } = runtime
  const hash = ctx.route.get()
  const [, redraw] = useState(0)
  const [runtimeProblems, setRuntimeProblems] = useState<string[]>([])
  const pages = destinations(runtime)
  const selected = pages.find(({ id }) => id === hash) ?? pages[0]
  const prepared = useMemo(() => prepareTiles(selected?.page, runtime.tiles), [selected?.page, runtime.tiles])
  const fieldProblems: string[] = []
  const { fields, visible, subscriptions } = demands(runtime, selected, prepared, fieldProblems)

  function report(problem: string) {
    setRuntimeProblems((previous) => previous.includes(problem) ? previous : [...previous, problem])
  }

  const onValue = useEffectEvent((field: string, value: unknown, time: number) => {
    for (const { owner, def, fields } of subscriptions) {
      if (!fields.has(field) && !(field.startsWith('status:') && fields.has('status:*'))) continue
      try {
        def.onValue(field, value, time, ctx)
      } catch (error) {
        report(moduleProblem(owner, error))
      }
    }
  })

  const onShortcut = useEffectEvent((event: KeyboardEvent) => {
    if (!isShortcut(event) || !/^[1-9]$/.test(event.key)) return
    const target = pages[Number(event.key) - 1]
    if (target) ctx.route.go(target.id)
  })

  const selectedId = selected?.id
  useEffect(() => {
    if (selectedId && hash !== selectedId) {
      window.history.replaceState(null, '', '#' + encodeURIComponent(selectedId))
    }
  }, [hash, selectedId])

  useEffect(() => {
    const changed = () => redraw((value) => value + 1)
    const onKey = (event: KeyboardEvent) => onShortcut(event)
    const unsubscribeStore = store.observe(changed)
    const unsubscribePages = ctx.pages.subscribe(changed)
    const unsubscribeValues = store.observeValues((field, reading) => onValue(field, reading.value, reading.timestamp))
    const tick = window.setInterval(() => store.tick(), 1000)
    window.addEventListener('keydown', onKey)
    window.addEventListener('hashchange', changed)
    store.start()
    const stops = engines.flatMap(({ def, owner }) => {
      try {
        const stop = def.start(ctx)
        if (typeof stop !== 'function') throw new Error(`Engine ${def.id} must return a stop function.`)
        return [{ stop, owner }]
      } catch (error) {
        report(moduleProblem(owner, error))
        return []
      }
    })
    return () => {
      window.clearInterval(tick)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('hashchange', changed)
      unsubscribeStore()
      unsubscribePages()
      unsubscribeValues()
      for (const { stop, owner } of stops.reverse()) {
        try {
          stop()
        } catch (error) {
          console.error(moduleProblem(owner, error))
        }
      }
      store.stop()
    }
  }, [ctx, store, engines])

  useEffect(() => store.select(fields), [store, fields])

  const problems = new Set([...runtime.problems, ...runtimeProblems, ...fieldProblems])
  return (
    <>
      <Header ctx={ctx}>
        <nav className="tabs" aria-label="Pages">
          {pages.map(({ id, title }, index) => (
            <a href={'#' + encodeURIComponent(id)} key={id} aria-current={id === selected?.id ? 'page' : undefined}
              aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}>{title}</a>
          ))}
        </nav>
        <ConnectionStatus store={store} visible={visible} />
        <Clock now={ctx.clock.now()} timeZone={ctx.config.shipTimezone} />
        <Slots runtime={runtime} slot="topbar" />
      </Header>
      <div className="banners" role="region" aria-label="Console banners"><Slots runtime={runtime} slot="banner" /></div>
      <main>
        <h1>{selected?.title ?? 'Data console'}</h1>
        {[...problems].map((problem) => <Message key={problem}>{problem}</Message>)}
        {selected?.route?.owner === 'self-test' && <p className="message">
          Verify the read-only relay with <code>install.sh --check</code> on the ship server.
          Use the relay for <code>/cds-ws</code> in both Django and React nginx configurations.
          Bind the cache to loopback and any UDP feed (<code>--udp</code>) to a named interface.
          A feed bound to all interfaces (INADDR_ANY) accepts data from the whole network.
        </p>}
        <PageView selected={selected} prepared={prepared} ctx={ctx} />
      </main>
    </>
  )
}

export default function App() {
  const [result, setResult] = useState<{ runtime: Runtime } | { error: string }>()
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([loadConsole(controller.signal), discoverModules()])
      .then(([config, { modules, problems }]) => {
        if (!controller.signal.aborted) setResult({ runtime: initialize(config, modules, problems) })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setResult({ error: message(error) })
      })
    return () => controller.abort()
  }, [])

  if (result && 'runtime' in result) return <Console runtime={result.runtime} />
  return (
    <>
      <Header />
      <div className="banners" role="region" aria-label="Console banners" />
      <main>
        <h1>Data console</h1>
        {result
          ? <Message>{result.error} Reload this page after correcting the file.</Message>
          : <p className="message" role="status">Loading pages…</p>}
      </main>
    </>
  )
}
