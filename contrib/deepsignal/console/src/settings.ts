import { JSON_SCHEMA, load } from 'js-yaml'
import type { PageProblem, PageWhere } from './contract'

export function describeSetting(value: unknown): string {
  if (value === undefined) return 'nothing'
  if (Array.isArray(value)) return 'a list'
  if (value !== null && typeof value === 'object') return 'a group of settings'
  const text = JSON.stringify(value) ?? String(value)
  return text.length > 120 ? text.slice(0, 117) + '…' : text
}

function location(where: PageWhere) {
  return where.tile === undefined ? where.file : `${where.file}, tile ${where.tile}`
}

class InvalidTile extends Error implements PageProblem {
  readonly where: PageWhere
  readonly setting: string
  readonly saw: string
  readonly expected: string
  readonly example: string

  constructor(problem: PageProblem) {
    super(`${location(problem.where)}, ${problem.setting}: saw ${problem.saw}. Expected ${problem.expected}. Example: ${problem.example}`)
    this.where = problem.where
    this.setting = problem.setting
    this.saw = problem.saw
    this.expected = problem.expected
    this.example = problem.example
  }
}

export function invalid(where: string | PageWhere, key: string, value: unknown, expected: string, example: string): never {
  const saw = describeSetting(value)
  if (typeof where === 'string') throw new Error(`${where}, ${key}: saw ${saw}. Expected ${expected}. Example: ${example}`)
  throw new InvalidTile({ where, setting: key, saw, expected, example })
}

export function formatPageProblem({ where, setting, saw, expected, example }: PageProblem) {
  return `${location(where)}: ${setting} is ${saw}. Expected ${expected}. Example: ${example}`
}

export function isPageProblem(value: unknown): value is PageProblem {
  if (!isMapping(value) || !isMapping(value.where) || typeof value.where.file !== 'string') return false
  return [value.setting, value.saw, value.expected, value.example].every((part) => typeof part === 'string')
}

export function isMapping(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function mapping(value: unknown, where: string | PageWhere, key: string, example: string) {
  if (isMapping(value)) return value
  return invalid(where, key, value, 'a group of settings', example)
}

export function exactKeys(settings: Record<string, unknown>, allowed: string[], where: string | PageWhere) {
  for (const key of Object.keys(settings)) {
    if (!allowed.includes(key)) {
      invalid(where, key, settings[key], `one of these setting names: ${allowed.join(', ')}`, allowed[0])
    }
  }
}

export function yaml(text: string, file: string): unknown {
  try {
    return load(text, { schema: JSON_SCHEMA, filename: file })
  } catch (error) {
    const reason = error instanceof Error ? error.message.split('\n')[0] : 'unreadable settings'
    throw new Error(`${file}: saw ${reason}. Expected valid YAML. Example: title: Bridge`, { cause: error })
  }
}

export function setting<T>(where: string | PageWhere, values: Record<string, unknown>, key: string,
  check: (value: unknown) => value is T, expected: string, example: string, fallback?: T): T {
  const value = Object.hasOwn(values, key) ? values[key] : undefined
  if (value === undefined && fallback !== undefined) return fallback
  if (check(value)) return value
  return invalid(where, key, value, expected, example)
}

export const isText = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
export const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean'
export const isPositive = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0
export const between = (min: number, max: number) =>
  (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max
