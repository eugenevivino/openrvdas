import type { ConsoleModule } from './contract'
import { isMapping, isText } from './settings'

const entries = import.meta.glob('./modules/*/index.ts', { eager: true })

const required = {
  tiles: { type: isText, validate: callable, fields: callable, Component: component },
  routes: { id: isText, title: isText, order: numeric, Component: component },
  presets: { id: isText, yaml: (value: unknown) => typeof value === 'string' },
  engines: { id: isText, start: callable },
  slots: { slot: (value: unknown) => value === 'banner' || value === 'topbar', order: numeric, Component: component },
  adapters: { id: isText, fields: callable, onValue: callable },
}

function callable(value: unknown) {
  return typeof value === 'function'
}

function component(value: unknown) {
  return callable(value) || (isMapping(value) &&
    ['react.memo', 'react.forward_ref', 'react.lazy'].some((kind) => value.$$typeof === Symbol.for(kind)))
}

function numeric(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value)
}

function validate(value: unknown, id: string): ConsoleModule {
  if (!isMapping(value) || value.id !== id) throw new Error(`Expected a default export with id "${id}".`)
  for (const [group, checks] of Object.entries(required)) {
    const definitions = value[group]
    if (definitions === undefined) continue
    if (!Array.isArray(definitions)) throw new Error(`Expected a list of ${group}.`)
    for (const definition of definitions) {
      if (!isMapping(definition)) throw new Error(`Expected a definition in ${group}.`)
      for (const [key, check] of Object.entries(checks)) {
        if (!check(definition[key])) throw new Error(`Invalid ${key} in ${group}.`)
      }
      if (group === 'routes' && definition.fields !== undefined && !callable(definition.fields)) {
        throw new Error('Invalid fields in routes.')
      }
    }
  }
  return value as unknown as ConsoleModule
}

export async function collectModules(glob: Record<string, unknown>) {
  const loaded = await Promise.all(Object.entries(glob).map(async ([path, entry]) => {
    const id = path.split('/').at(-2)!
    try {
      const namespace = isMapping(entry) && typeof entry.loadConsoleModule === 'function'
        ? await entry.loadConsoleModule() as unknown : await entry
      return { module: validate(isMapping(namespace) ? namespace.default : undefined, id) }
    } catch (error) {
      return { problem: `Module ${id}: ${error instanceof Error ? error.message : String(error)}` }
    }
  }))
  return {
    modules: loaded.flatMap(({ module }) => module ?? []),
    problems: loaded.flatMap(({ problem }) => problem ?? []),
  }
}

export const discoverModules = () => collectModules(entries)
