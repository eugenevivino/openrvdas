/** Same-origin fixture service. The backend, not this UI, authorizes every call. */
export type Envelope<T> = {
  schema_version: number
  result_id: string
  deployment_id: string
  as_of: number | string
  status: 'success' | 'partial' | 'error'
  data: T
  warnings: string[]
  limits: Record<string, unknown>
  error?: { code: string; message: string }
}

export async function call<T>(method: string, args: Record<string, unknown>): Promise<Envelope<T>> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15_000)
  try {
    const session = await fetch('/api/workspace/session', {
      signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
    })
    if (!session.ok) throw new Error('Fixture workspace service is unavailable. Start the documented local demo server.')
    const credentials = await session.json() as { token?: unknown }
    if (typeof credentials.token !== 'string') throw new Error('The workspace service returned an invalid session.')
    const response = await fetch('/api/workspace/call', {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-DeepSignal-Token': credentials.token },
      body: JSON.stringify({ method, arguments: { ...args, deployment_id: 'fixture-vessel' } }),
    })
    const result = await response.json() as Envelope<T>
    if (!response.ok || result.status === 'error') {
      throw new Error(result.error ? `${result.error.code}: ${result.error.message}` : `Workspace request failed (${response.status}).`)
    }
    if (result.schema_version !== 1 || result.deployment_id !== 'fixture-vessel' ||
        !['success', 'partial'].includes(result.status) || !result.data) {
      throw new Error('The service returned an unsupported or mismatched result. No evidence was accepted.')
    }
    return result
  } catch (error) {
    if (controller.signal.aborted) throw new Error('The workspace request timed out. Its outcome is unknown; refresh evidence before retrying a change.')
    throw error
  } finally {
    clearTimeout(timeout)
  }
}
