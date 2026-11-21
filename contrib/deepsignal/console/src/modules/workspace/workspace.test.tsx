// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ConsoleContext } from '../../contract'
import { WorkspacePage } from './page'

function fixtureService(overrides: Record<string, unknown> = {}) {
  const clock = { asOf: 6 }
  const methods: string[] = []
  const calls: Array<{ method: string; arguments: Record<string, unknown> }> = []
  const responses: Record<string, unknown> = {
    ds_query_data: { dataset_id: 'dataset-1', rows: [
      { time: 0, value: 10, source_flag: 1, source_ref: 'record-0' },
      { time: 1, value: null, reason: 'missing', source_flag: 9, source_ref: 'record-1' },
    ], coverage: { completeness: 'partial', missing_times: [2, 3] }, unit: 'degC' },
    ds_analyze: { artifact_id: 'analysis-1', count: 2, finite_count: 1, missing_count: 1,
      nonfinite_count: 0, min: 10, max: 10, mean: 10, median: 10, stddev: 0,
      mean_convention: 'observation-weighted', stddev_convention: 'population', unit: 'degC' },
    ds_get_configuration: { snapshot_id: 'config-1', source: { parser: 'bad pattern' }, loaded_state: 'unknown',
      runtime_state: 'simulated', supported_patterns: ['old pattern', 'TEMP {temperature:f}'] },
    ds_create_draft: { draft_id: 'draft-1', revision: 1, source_diff: '-old pattern\n+TEMP {temperature:f}', source: { parser: 'TEMP {temperature:f}' } },
    ds_validate_draft: { artifact_id: 'validation-1', checks: [{ level: 'L1', status: 'passed', message: 'Syntax valid' },
      { level: 'L6', status: 'not-run', message: 'Site qualification unavailable' }] },
    ds_replay_draft: { artifact_id: 'replay-1', baseline_count: 0, candidate_count: 6, expected_count: 6,
      passed: true, limitations: ['Synthetic data; no device qualification'] },
    ds_create_investigation: { investigation_id: 'investigation-1', revision: 1 },
    ds_add_finding: { investigation_id: 'investigation-1', revision: 2 },
    ds_export_investigation: { artifact_id: 'export-1', report: 'Watch handoff: parser hypothesis remains a hypothesis.',
      manifest: { dataset_id: 'dataset-1', next_action: 'Review in isolated lab' } },
    ...overrides,
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/workspace/session') return { ok: true, status: 200, json: async () => ({ token: 'fixture-token' }) }
    expect(url).toBe('/api/workspace/call')
    expect(init?.headers).toMatchObject({ 'X-DeepSignal-Token': 'fixture-token' })
    const request = JSON.parse(String(init?.body)) as { method: string; arguments: Record<string, unknown> }
    expect(request.arguments.deployment_id).toBe('fixture-vessel')
    calls.push(request); methods.push(request.method)
    if (!(request.method in responses)) throw new Error(`Unexpected method ${request.method}`)
    const result = responses[request.method]
    if (result instanceof Error) throw result
    return { ok: true, status: 200, json: async () => ({ schema_version: 1, result_id: `result-${methods.length}`,
      deployment_id: 'fixture-vessel', as_of: clock.asOf, status: 'success', warnings: [], limits: { rows: 1000 }, data: result }) }
  }))
  return { methods, calls, responses, clock }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('keeps a frozen dataset through draft validation, replay, and an attributed portable handoff', async () => {
  const service = fixtureService()
  const ctx = {} as ConsoleContext
  const page = render(<WorkspacePage ctx={ctx} view="explorer" />)
  expect(screen.getByText('SIMULATED · Fixture vessel')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Load selected data' }))
  await screen.findByText(/fixture-vessel\/temperature \[0, 6\)/)
  expect(screen.getByText('Unknown / missing')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Analyze frozen dataset' }))
  await screen.findByRole('heading', { name: 'Deterministic analysis' })
  expect(screen.getByText('Mean: observation-weighted. Standard deviation: population. Unit: degC.')).toBeInTheDocument()

  page.rerender(<WorkspacePage ctx={ctx} view="configuration" />)
  fireEvent.click(screen.getByRole('button', { name: 'Load configuration snapshot' }))
  await screen.findByLabelText('Supported parser pattern')
  fireEvent.change(screen.getByLabelText('Supported parser pattern'), { target: { value: 'TEMP {temperature:f}' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create parser draft' }))
  await screen.findByRole('heading', { name: 'Draft 1' })
  expect(screen.getByRole('button', { name: 'Replay baseline and draft' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Validate draft' }))
  await screen.findByText('L6: not-run')
  fireEvent.click(screen.getByRole('button', { name: 'Replay baseline and draft' }))
  await screen.findByText('PASS for declared fixture checks')
  expect(service.calls.find((item) => item.method === 'ds_replay_draft')?.arguments).toMatchObject({
    draft_id: 'draft-1', revision: 1, dataset_id: 'dataset-1',
  })

  page.rerender(<WorkspacePage ctx={ctx} view="investigations" />)
  fireEvent.click(screen.getByRole('button', { name: 'Save investigation' }))
  await screen.findByRole('heading', { name: 'Investigation revision 1' })
  fireEvent.change(screen.getByLabelText('Finding'), { target: { value: 'Parser mapping may explain the missing output.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save attributed finding' }))
  await screen.findByRole('heading', { name: 'Investigation revision 2' })
  expect(service.calls.find((item) => item.method === 'ds_add_finding')?.arguments).toMatchObject({
    expected_revision: 1, kind: 'hypothesis', evidence_ids: ['dataset-1', 'analysis-1', 'config-1', 'validation-1', 'replay-1'],
  })
  fireEvent.click(screen.getByRole('button', { name: 'Prepare watch handoff' }))
  await screen.findByLabelText('Watch handoff report')
  expect(screen.getByLabelText('Watch handoff report')).toHaveTextContent('parser hypothesis remains a hypothesis')
  expect(screen.getByText(/Nothing has been published or sent/)).toBeInTheDocument()
  expect(service.methods).not.toContain('ds_execute_approved_change')
})

it('shows a service failure explicitly and retains the prior frozen observations', async () => {
  fixtureService()
  render(<WorkspacePage ctx={{} as ConsoleContext} view="explorer" />)
  fireEvent.click(screen.getByRole('button', { name: 'Load selected data' }))
  await screen.findByRole('heading', { name: 'Frozen dataset' })
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh health evidence' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('service is unavailable')
  expect(screen.getByRole('heading', { name: 'Frozen dataset' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Operational evidence' })).not.toBeInTheDocument()
})

it('keeps intentional inactivity, stale observations and unknown archival visibly separate', async () => {
  fixtureService({ ds_get_health: { assets: [
    { id: 'fixture-vessel/radiometer', name: 'Deck radiometer', activity: 'intentionally inactive', freshness: 'not expected',
      parsing: 'not evaluated', archive: 'unverified', age_s: null, last_value: null, unit: null, evidence: 'Night mode' },
    { id: 'fixture-vessel/temperature', name: 'Temperature', activity: 'running', freshness: 'stale', parsing: 'failed',
      archive: 'raw collection continues', age_s: 6, last_value: 10, unit: 'degC', evidence: 'Recorded fixture' },
  ] } })
  render(<WorkspacePage ctx={{} as ConsoleContext} view="explorer" />)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh health evidence' }))
  await waitFor(() => expect(screen.getByText('intentionally inactive')).toBeInTheDocument())
  expect(screen.getByText('stale · age 6 s')).toBeInTheDocument()
  expect(screen.getByText('raw collection continues')).toBeInTheDocument()
  expect(screen.getByText('unverified')).toBeInTheDocument()
  expect(screen.queryByText('globally healthy')).not.toBeInTheDocument()
})


it('preserves failed health freshness across unrelated success until health itself refreshes', async () => {
  const health = { assets: [{ id: 'fixture-vessel/temperature', name: 'Temperature', activity: 'running',
    freshness: 'fresh', parsing: 'passed', archive: 'unverified', age_s: 1, last_value: 10, unit: 'degC', evidence: 'snapshot' }] }
  const service = fixtureService({ ds_get_health: health })
  render(<WorkspacePage ctx={{} as ConsoleContext} view="explorer" />)
  fireEvent.click(screen.getByRole('button', { name: 'Refresh health evidence' }))
  await screen.findByText('Health observation as of 6 · success · Recorded fixture evidence')

  service.responses.ds_get_health = new Error('Health backend disconnected')
  fireEvent.click(screen.getByRole('button', { name: 'Refresh health evidence' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Health evidence refresh failed')
  service.clock.asOf = 100
  fireEvent.click(screen.getByRole('button', { name: 'Load selected data' }))
  await screen.findByRole('heading', { name: 'Frozen dataset' })
  expect(screen.getByText('Most recent workspace response as of 100 · success')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('Health backend disconnected')
  expect(screen.getByText('Health observation as of 6 · success · Historical evidence: refresh failed')).toBeInTheDocument()

  service.responses.ds_get_health = health
  service.clock.asOf = 101
  fireEvent.click(screen.getByRole('button', { name: 'Refresh health evidence' }))
  await screen.findByText('Health observation as of 101 · success · Recorded fixture evidence')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('labels a changed query as pending while replay remains bound to its original frozen interval', async () => {
  const service = fixtureService()
  const ctx = {} as ConsoleContext
  const page = render(<WorkspacePage ctx={ctx} view="explorer" />)
  fireEvent.click(screen.getByRole('button', { name: 'Load selected data' }))
  await screen.findByRole('heading', { name: 'Frozen dataset' })
  page.rerender(<WorkspacePage ctx={ctx} view="configuration" />)
  fireEvent.click(screen.getByRole('button', { name: 'Load configuration snapshot' }))
  await screen.findByLabelText('Supported parser pattern')
  fireEvent.change(screen.getByLabelText('Supported parser pattern'), { target: { value: 'TEMP {temperature:f}' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create parser draft' }))
  await screen.findByRole('heading', { name: 'Draft 1' })
  fireEvent.click(screen.getByRole('button', { name: 'Validate draft' }))
  await screen.findByText('L6: not-run')
  fireEvent.click(screen.getByRole('button', { name: 'Replay baseline and draft' }))
  await screen.findByText('PASS for declared fixture checks')

  page.rerender(<WorkspacePage ctx={ctx} view="explorer" />)
  fireEvent.change(screen.getByLabelText('End, exclusive (fixture seconds)'), { target: { value: '3' } })
  expect(screen.getByText(/The pending query differs from the frozen dataset/)).toBeInTheDocument()
  page.rerender(<WorkspacePage ctx={ctx} view="configuration" />)
  expect(screen.getByText('Pending query interval [0, 3) · seconds from fixture epoch')).toBeInTheDocument()
  expect(screen.getByLabelText('Replay input')).toHaveTextContent('dataset-1 · fixture-vessel/temperature [0, 6)')
  expect(screen.getByLabelText('Replay input')).not.toHaveTextContent('[0, 3)')
  expect(screen.getByText(/load the new selection to evaluate it/)).toBeInTheDocument()
  expect(service.methods.filter((method) => method === 'ds_query_data')).toHaveLength(1)
  expect(service.methods.filter((method) => method === 'ds_replay_draft')).toHaveLength(1)
})
