import { useState, useSyncExternalStore } from 'react'
import type { ConsoleContext } from '../../contract'
import { call } from './client'
import type { Envelope } from './client'
import './workspace.css'

export type View = 'explorer' | 'configuration' | 'investigations' | 'connections'
type Row = { time: number; value: unknown; reason?: string; source_flag: unknown; source_ref: string }
type Dataset = { dataset_id: string; rows: Row[]; coverage: unknown; unit: string | null }
type Analysis = { artifact_id: string; count: number; finite_count: number; missing_count: number; nonfinite_count: number;
  min: number | null; max: number | null; mean: number | null; median: number | null; stddev: number | null;
  mean_convention: string; stddev_convention: string; unit: string | null }
type Configuration = { snapshot_id: string; source: unknown; loaded_state: string; runtime_state: string; supported_patterns: string[] }
type Draft = { draft_id: string; revision: number; source_diff: unknown; source: unknown }
type Validation = { artifact_id: string; checks: Array<{ level: string; status: string; message: string }> }
type Replay = { artifact_id: string; baseline_count: number; candidate_count: number; expected_count: number; passed: boolean; limitations: unknown }
type Investigation = { investigation_id: string; revision: number }
type Export = { artifact_id: string; report: string; manifest: unknown }
type Health = { assets: Array<{ id: string; name: string; activity: string; freshness: string; parsing: string; archive: string;
  age_s: number | null; last_value: unknown; unit: string | null; evidence: unknown }> }
type Asset = { id: string; name: string; kind: string; unit: string | null }
type Selection = { stream: string; start: number; end: number }
type State = {
  start: string; end: string; stream: string; busy: boolean; error?: string; warnings: string[]; evidence: string[]
  asOf?: string | number; resultStatus?: string; dataset?: Dataset; analysis?: Analysis; config?: Configuration
  draft?: Draft; validation?: Validation; replay?: Replay; investigation?: Investigation; exported?: Export
  system?: Record<string, unknown>; health?: Health; healthError?: string; healthAsOf?: string | number
  healthStatus?: string; healthWarnings?: string[]; assets?: Asset[]; selection?: string; datasetSelection?: Selection
  replayInput?: { datasetId: string; selection: string }
}

// A console runtime owns its selection and handles. Route changes keep them; a
// different runtime/deployment cannot inherit them. Tokens are never persisted.
const sessions = new WeakMap<ConsoleContext, ReturnType<typeof createSession>>()
function createSession() {
  let state: State = { start: '0', end: '6', stream: 'fixture-vessel/temperature', busy: false, warnings: [], evidence: [] }
  const listeners = new Set<() => void>()
  return {
    get: () => state,
    subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } },
    update: (patch: Partial<State>) => { state = { ...state, ...patch }; listeners.forEach((fn) => fn()) },
  }
}
function sessionFor(ctx: ConsoleContext) {
  let session = sessions.get(ctx)
  if (!session) { session = createSession(); sessions.set(ctx, session) }
  return session
}
const text = (value: unknown) => value === null || value === undefined ? 'Unknown / missing' :
  typeof value === 'string' ? value : JSON.stringify(value, null, 2)
const titles: Record<View, string> = {
  explorer: 'Data Explorer', configuration: 'Configuration Workbench', investigations: 'Investigations', connections: 'Connections and System',
}

function Evidence({ value, label }: { value: unknown; label: string }) {
  return <details><summary>{label}</summary><pre>{text(value)}</pre></details>
}

export function WorkspacePage({ ctx, view }: { ctx: ConsoleContext; view: View }) {
  const session = sessionFor(ctx)
  const state = useSyncExternalStore(session.subscribe, session.get)
  const [pattern, setPattern] = useState('')
  const [title, setTitle] = useState('Simulated temperature parser investigation')
  const [finding, setFinding] = useState('')
  const [kind, setKind] = useState('hypothesis')

  async function perform<T>(method: string, args: Record<string, unknown>, accept: (value: T) => Partial<State>) {
    if (session.get().busy) return
    session.update({ busy: true, error: undefined, warnings: [] })
    try {
      const result: Envelope<T> = await call<T>(method, args)
      const value = result.data as T & { artifact_id?: string; dataset_id?: string; snapshot_id?: string }
      const id = value.artifact_id ?? value.dataset_id ?? value.snapshot_id
      session.update({ ...accept(result.data), ...(method === 'ds_get_health' ? { healthError: undefined, healthAsOf: result.as_of,
        healthStatus: result.status, healthWarnings: result.warnings ?? [] } : {}), asOf: result.as_of, resultStatus: result.status,
        warnings: result.warnings ?? [], evidence: id ? [...new Set([...session.get().evidence, id])] : session.get().evidence })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Workspace request failed. Existing evidence is retained.'
      session.update(method === 'ds_get_health' ? { healthError: message } : { error: message })
    } finally { session.update({ busy: false }) }
  }
  const queryChanged = state.datasetSelection !== undefined && (state.start.trim() === '' || state.end.trim() === '' ||
    state.datasetSelection.stream !== state.stream ||
    state.datasetSelection.start !== Number(state.start) || state.datasetSelection.end !== Number(state.end))
  const noDraft = state.busy || !state.draft
  const draftArgs = { draft_id: state.draft?.draft_id, revision: state.draft?.revision }
  const requestedPattern = pattern || state.config?.supported_patterns[0] || ''

  return <section className="workspace" aria-label={titles[view]}>
    <header className="workspace-context">
      <strong>SIMULATED · Fixture vessel</strong>
      <span>Pending query interval [{state.start}, {state.end}) · seconds from fixture epoch</span>
      {state.dataset && <span>Frozen dataset: {state.dataset.dataset_id}</span>}
      <span>Local drafts only. Live acquisition control is unavailable.</span>
      {state.asOf !== undefined && <small>Most recent workspace response as of {String(state.asOf)} · {state.resultStatus}</small>}
    </header>
    <nav aria-label="Investigation workflow" className="workspace-links">
      {(Object.keys(titles) as View[]).map((key) => <a key={key} href={`#workspace-${key}`} aria-current={key === view ? 'page' : undefined}>{titles[key]}</a>)}
    </nav>
    {state.busy && <p role="status">Loading or saving bounded fixture evidence…</p>}
    {state.healthError && <p role="alert" className="workspace-error">Health evidence refresh failed: {state.healthError} Retained health is historical; its status and ages have not been refreshed.</p>}
    {queryChanged && <p role="status">The pending query differs from the frozen dataset. Displayed analysis and replay apply only to the frozen input; load the new selection to evaluate it.</p>}
    {state.error && <p role="alert" className="workspace-error">{state.error} Previous results remain historical evidence.</p>}
    {state.warnings.length > 0 && <ul aria-label="Evidence limitations">{state.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}

    {view === 'explorer' && <>
      <div className="workspace-card">
        <h2>Inspect the selected observations</h2>
        <p>No gap filling, unit guessing, or scientific calculations happen in this browser. Results come from the same service used by CLI and MCP.</p>
        <div className="workspace-actions">
          <button disabled={state.busy} onClick={() => void perform<{ assets: Asset[] }>('ds_list_assets', {}, (value) => ({ assets: value.assets }))}>Discover fixture assets</button>
          <button disabled={state.busy} onClick={() => void perform<Health>('ds_get_health', {}, (health) => ({ health }))}>Refresh health evidence</button>
        </div>
        <div className="workspace-form">
          <label>Stream<select value={state.stream} onChange={(event) => session.update({ stream: event.target.value })}>
            <option value="fixture-vessel/temperature">Fixture temperature</option>
            {state.assets?.filter((asset) => asset.kind === 'stream' && asset.id !== 'fixture-vessel/temperature')
              .map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
          </select></label>
          <label>Start (fixture seconds)<input type="number" value={state.start} onChange={(event) => session.update({ start: event.target.value })} /></label>
          <label>End, exclusive (fixture seconds)<input type="number" value={state.end} onChange={(event) => session.update({ end: event.target.value })} /></label>
        </div>
        <button disabled={state.busy || state.start.trim() === '' || state.end.trim() === '' || !Number.isFinite(Number(state.start)) || !Number.isFinite(Number(state.end)) || Number(state.start) >= Number(state.end)}
          onClick={() => void perform<Dataset>('ds_query_data', { stream_id: state.stream, start: Number(state.start), end: Number(state.end) },
            (dataset) => ({ dataset, analysis: undefined, replay: undefined, replayInput: undefined,
              datasetSelection: { stream: state.stream, start: Number(state.start), end: Number(state.end) },
              selection: `${state.stream} [${state.start}, ${state.end})` }))}>Load selected data</button>
      </div>
      {state.health && <div className="workspace-card">
        <h2>Operational evidence</h2>
        <p>Health observation as of {String(state.healthAsOf)} · {state.healthStatus}{state.healthError ? ' · Historical evidence: refresh failed' : ' · Recorded fixture evidence'}</p>
        {state.healthWarnings?.map((warning, i) => <p key={i}>{warning}</p>)}
        <div className="workspace-table"><table><thead><tr><th>Asset</th><th>Activity</th><th>Freshness</th><th>Parsing</th><th>Archive</th><th>Last value</th></tr></thead>
          <tbody>{state.health.assets.map((asset) => <tr key={asset.id}><th scope="row">{asset.name}</th><td>{asset.activity}</td><td>{asset.freshness} · age {text(asset.age_s)} s</td><td>{asset.parsing}</td><td>{asset.archive}</td><td>{text(asset.last_value)} {asset.unit ?? '(unit unknown)'}</td></tr>)}</tbody></table></div>
        <Evidence value={state.health} label="Health rules and source evidence" />
      </div>}
      {state.dataset && <div className="workspace-card">
        <h2>Frozen dataset</h2><p>{state.selection} · Unit: {state.dataset.unit ?? 'unknown'} · {state.dataset.dataset_id}</p>
        <Evidence value={state.dataset.coverage} label="Requested and available coverage" />
        <div className="workspace-table"><table><thead><tr><th>Event time (s)</th><th>Value</th><th>Classification</th><th>Original flag</th><th>Source record</th></tr></thead>
          <tbody>{state.dataset.rows.map((row, i) => <tr key={i}><td>{row.time}</td><td>{text(row.value)}</td><td>{row.reason ?? 'Reported observation'}</td><td>{text(row.source_flag)}</td><td>{row.source_ref}</td></tr>)}</tbody></table></div>
        <button disabled={state.busy} onClick={() => void perform<Analysis>('ds_analyze', { dataset_id: state.dataset!.dataset_id }, (analysis) => ({ analysis }))}>Analyze frozen dataset</button>
      </div>}
      {state.analysis && <div className="workspace-card"><h2>Deterministic analysis</h2>
        <dl className="workspace-metrics">{(['count', 'finite_count', 'missing_count', 'nonfinite_count', 'min', 'max', 'mean', 'median', 'stddev'] as const).map((key) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{text(state.analysis![key])}</dd></div>)}</dl>
        <p>Mean: {state.analysis.mean_convention}. Standard deviation: {state.analysis.stddev_convention}. Unit: {state.analysis.unit ?? 'unknown'}.</p>
        <Evidence value={state.analysis} label="Analysis method and artifact" />
      </div>}
    </>}

    {view === 'configuration' && <>
      <div className="workspace-card"><h2>Inspect configuration evidence</h2>
        <button disabled={state.busy} onClick={() => void perform<Configuration>('ds_get_configuration', {}, (config) => ({ config }))}>Load configuration snapshot</button>
        {state.config && <>
          <p>Snapshot {state.config.snapshot_id} · Loaded: {state.config.loaded_state} · Runtime: {state.config.runtime_state}</p>
          <Evidence value={state.config.source} label="Configuration source" />
          <label>Supported parser pattern<select value={requestedPattern} onChange={(event) => setPattern(event.target.value)}>
            {state.config.supported_patterns.map((item) => <option key={item} value={item}>{item}</option>)}
          </select></label>
          <p>Changing this pattern creates a local immutable draft. It does not load or apply a configuration.</p>
          <button disabled={state.busy || !requestedPattern} onClick={() => void perform<Draft>('ds_create_draft',
            { base_snapshot_id: state.config!.snapshot_id, pattern: requestedPattern },
            (draft) => ({ draft, validation: undefined, replay: undefined, replayInput: undefined, exported: undefined }))}>Create parser draft</button>
        </>}
      </div>
      {state.draft && <div className="workspace-card"><h2>Draft {state.draft.revision}</h2><p>{state.draft.draft_id}</p>
        <Evidence value={state.draft.source_diff} label="Exact source diff" /><Evidence value={state.draft.source} label="Draft configuration" />
        <div className="workspace-actions">
          <button disabled={noDraft} onClick={() => void perform<Validation>('ds_validate_draft', draftArgs, (validation) => ({ validation }))}>Validate draft</button>
          <button disabled={noDraft || !state.dataset || !state.validation} onClick={() => void perform<Replay>('ds_replay_draft',
            { ...draftArgs, dataset_id: state.dataset!.dataset_id }, (replay) => ({ replay, replayInput: { datasetId: state.dataset!.dataset_id, selection: state.selection! } }))}>Replay baseline and draft</button>
        </div>
        {!state.dataset && <p>Load a frozen dataset in Data Explorer before replay.</p>}
        <p>Replay is a bounded fixture experiment, not vessel or instrument qualification.</p>
      </div>}
      {state.validation && <div className="workspace-card"><h2>Validation levels</h2><ul>{state.validation.checks.map((check, i) => <li key={i}><strong>{check.level}: {check.status}</strong> · {check.message}</li>)}</ul></div>}
      {state.replay && <div className="workspace-card"><h2>Replay comparison</h2>
        <p aria-label="Replay input">Frozen replay input: {state.replayInput?.datasetId} · {state.replayInput?.selection} · seconds from fixture epoch</p>
        <p>{state.replay.passed ? 'PASS for declared fixture checks' : 'FAIL: candidate did not meet declared checks'}</p>
        <p>Baseline: {state.replay.baseline_count}; candidate: {state.replay.candidate_count}; expected: {state.replay.expected_count} records.</p>
        <Evidence value={state.replay} label="Replay identities, results, and limitations" />
      </div>}
    </>}

    {view === 'investigations' && <>
      <div className="workspace-card"><h2>Preserve evidence for the next watch</h2>
        <p>Evidence handles collected in this workspace: {state.evidence.length}. Original observations remain unchanged.</p>
        <Evidence value={state.evidence} label="Selected evidence handles" />
        <label>Investigation title<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
        <button disabled={state.busy || !title.trim() || !state.evidence.length} onClick={() => void perform<Investigation>('ds_create_investigation',
          { title, evidence_ids: state.evidence }, (investigation) => ({ investigation, exported: undefined }))}>Save investigation</button>
      </div>
      {state.investigation && <div className="workspace-card"><h2>Investigation revision {state.investigation.revision}</h2><p>{state.investigation.investigation_id}</p>
        <label>Finding kind<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="observation">Observed fact</option><option value="hypothesis">Hypothesis, not established cause</option><option value="note">Operator note</option></select></label>
        <label>Finding<textarea rows={4} maxLength={2000} value={finding} onChange={(event) => setFinding(event.target.value)} /></label>
        <div className="workspace-actions">
          <button disabled={state.busy || !finding.trim()} onClick={() => void perform<Investigation>('ds_add_finding',
            { investigation_id: state.investigation!.investigation_id, expected_revision: state.investigation!.revision, kind, text: finding, evidence_ids: state.evidence },
            (investigation) => { setFinding(''); return { investigation, exported: undefined } })}>Save attributed finding</button>
          <button disabled={state.busy} onClick={() => void perform<Export>('ds_export_investigation',
            { investigation_id: state.investigation!.investigation_id }, (exported) => ({ exported }))}>Prepare watch handoff</button>
        </div>
      </div>}
      {state.exported && <div className="workspace-card"><h2>Portable watch handoff</h2>
        <p>Local artifact {state.exported.artifact_id}. Nothing has been published or sent.</p>
        <pre aria-label="Watch handoff report">{state.exported.report}</pre>
        <Evidence value={state.exported.manifest} label="Structured handoff manifest" />
        <button onClick={() => {
          const blob = new Blob([JSON.stringify({ report: state.exported!.report, manifest: state.exported!.manifest }, null, 2)], { type: 'application/json' })
          const url = URL.createObjectURL(blob); const link = document.createElement('a')
          link.href = url; link.download = 'deepsignal-fixture-handoff.json'; link.click(); URL.revokeObjectURL(url)
        }}>Download handoff JSON</button>
      </div>}
    </>}

    {view === 'connections' && <div className="workspace-card"><h2>Configured service and limits</h2>
      <p>This route calls only the same-origin fixture service. It cannot select arbitrary endpoints or connect to a vessel.</p>
      <button disabled={state.busy} onClick={() => void perform<Record<string, unknown>>('ds_get_system', {}, (system) => ({ system }))}>Inspect capabilities</button>
      {state.system && <pre aria-label="System capabilities">{text(state.system)}</pre>}
      <p>Unsupported capabilities remain unavailable. No approval or live execution control is exposed.</p>
    </div>}
  </section>
}
