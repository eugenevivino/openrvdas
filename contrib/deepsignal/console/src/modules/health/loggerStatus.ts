import { isMapping } from '../../settings'

const loggerStatuses = ['RUNNING', 'STARTING', 'FAILED', 'EXITED'] as const
export type LoggerStatus = typeof loggerStatuses[number]
export type LoggerEntry = { config: string; status: LoggerStatus }

export function isStatuses(value: unknown): value is Record<string, LoggerEntry> {
  return isMapping(value) && Object.values(value).every((entry) =>
    isMapping(entry) && typeof entry.config === 'string' && loggerStatuses.some(status => status === entry.status))
}
