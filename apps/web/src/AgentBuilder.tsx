import { FormEvent, useEffect, useState } from 'react'
import { apiFetch } from './auth'

type Options = { models: { alias: string }[]; tools: { stable_name: string; schema_version: string }[] }
type Limits = { max_iterations: number; max_tool_calls_per_step: number; max_tool_argument_bytes: number; max_tool_result_bytes: number; max_output_tokens: number }
type Manifest = { agent: { id: string; version: string; name: string; description: string }; instructions: string; model: { alias: string }; tools: string[]; limits: Limits }
type Draft = { id: string; state: string; current_revision: number; manifest: Manifest; validation?: { digest?: string } | null }

const initial = {
  slug: 'portal-assistant', version: '1.0.0', name: 'Portal Assistant',
  description: 'A declarative agent created in the portal.',
  instructions: 'Answer clearly. Use reviewed read-only tools only when needed.',
  model_alias: 'default', tools: [] as string[],
  limits: { max_iterations: 4, max_tool_calls_per_step: 2, max_tool_argument_bytes: 4096, max_tool_result_bytes: 32768, max_output_tokens: 2048 },
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body.detail
    throw new Error(detail?.message ?? detail?.code ?? detail ?? `Request failed (${response.status})`)
  }
  return body as T
}

function fields(draft: Draft) {
  const manifest = draft.manifest
  return { slug: manifest.agent.id, version: manifest.agent.version, name: manifest.agent.name, description: manifest.agent.description, instructions: manifest.instructions, model_alias: manifest.model.alias, tools: manifest.tools, limits: manifest.limits }
}

export function AgentBuilder({ canPublish, onCatalogChanged }: { canPublish: boolean; onCatalogChanged: () => void }) {
  const [options, setOptions] = useState<Options>({ models: [], tools: [] })
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [active, setActive] = useState<Draft | null>(null)
  const [form, setForm] = useState(initial)
  const [testId, setTestId] = useState('')
  const [testPrompt, setTestPrompt] = useState('What time is it in UTC?')
  const [tested, setTested] = useState(false)
  const [published, setPublished] = useState<{ agent_id: string; version: string } | null>(null)
  const [status, setStatus] = useState('Create or select a draft.')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    const [available, items] = await Promise.all([json<Options>('/api/v1/agent-authoring/options'), json<Draft[]>('/api/v1/agent-drafts')])
    setOptions(available); setDrafts(items)
  }
  useEffect(() => { refresh().catch((error: Error) => setStatus(error.message)) }, [])

  function selectDraft(item: Draft) {
    setActive(item); setForm(fields(item)); setTestId(''); setTested(false); setPublished(null)
    setStatus(`Editing revision ${item.current_revision}.`)
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true)
    try {
      const next = await json<Draft>(active ? `/api/v1/agent-drafts/${active.id}` : '/api/v1/agent-drafts', { method: active ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(active ? { ...form, expected_revision: active.current_revision } : form) })
      setActive(next); setTestId(''); setTested(false); setStatus(`Saved immutable revision ${next.current_revision}.`); await refresh()
    } catch (error) { setStatus((error as Error).message) } finally { setBusy(false) }
  }

  async function validate() {
    if (!active) return; setBusy(true)
    try {
      const report = await json<{ digest: string }>(`/api/v1/agent-drafts/${active.id}/revisions/${active.current_revision}/validate`, { method: 'POST' })
      setActive({ ...active, state: 'validated', validation: report }); setStatus(`Validated ${report.digest}.`)
    } catch (error) { setStatus((error as Error).message) } finally { setBusy(false) }
  }

  async function createTest() {
    if (!active) return; setBusy(true)
    try {
      const test = await json<{ id: string }>(`/api/v1/agent-drafts/${active.id}/revisions/${active.current_revision}/tests`, { method: 'POST' })
      setTestId(test.id); setTested(false); setStatus('Private test session is pinned and ready.')
    } catch (error) { setStatus((error as Error).message) } finally { setBusy(false) }
  }

  async function runTest() {
    if (!testId) return; setBusy(true)
    try {
      const turn = await json<{ turn_id: string }>(`/api/v1/agent-draft-tests/${testId}/turns`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: testPrompt, idempotency_key: crypto.randomUUID() }) })
      setStatus('Draft test is running through the generic workflow…')
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
        const current = await json<{ state: string; error_code?: string }>(`/api/v1/turns/${turn.turn_id}`)
        if (current.state === 'completed') { setTested(true); setStatus('Draft test completed successfully for this revision.'); return }
        if (['failed', 'cancelled'].includes(current.state)) throw new Error(current.error_code ?? `Test ${current.state}`)
      }
      throw new Error('Test is still running; check it again shortly.')
    } catch (error) { setStatus((error as Error).message) } finally { setBusy(false) }
  }

  async function publish() {
    if (!active) return; setBusy(true)
    try {
      const release = await json<{ agent_id: string; version: string }>(`/api/v1/agent-drafts/${active.id}/revisions/${active.current_revision}/publish`, { method: 'POST' })
      setPublished(release); setActive({ ...active, state: 'published' }); setStatus(`Published ${release.agent_id}:${release.version}.`); onCatalogChanged()
    } catch (error) { setStatus((error as Error).message) } finally { setBusy(false) }
  }

  async function deprecate() {
    if (!published) return; setBusy(true)
    try {
      await json(`/api/v1/agents/${published.agent_id}/versions/${published.version}/deprecate`, { method: 'POST' })
      setStatus(`Deprecated ${published.agent_id}:${published.version}; existing runs remain pinned.`); onCatalogChanged()
    } catch (error) { setStatus((error as Error).message) } finally { setBusy(false) }
  }

  return <section className="builder">
    <header><div><small>DECLARATIVE AGENTS</small><h1>Agent builder</h1></div><p role="status">{status}</p></header>
    <div className="builder-grid">
      <nav aria-label="Agent drafts"><button onClick={() => { setActive(null); setForm(initial); setStatus('Creating a new draft.') }}>＋ New draft</button>{drafts.map((item) => <button className={active?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => selectDraft(item)}>{item.manifest.agent.name}<small>{item.manifest.agent.version} · r{item.current_revision} · {item.state}</small></button>)}</nav>
      <form onSubmit={save}>
        <fieldset disabled={busy || active?.state === 'published'}><legend>Identity</legend><label>Slug<input value={form.slug} pattern="[a-z][a-z0-9-]{1,62}" onChange={(e) => setForm({ ...form, slug: e.target.value })} /></label><label>Version<input value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} /></label><label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>Description<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label></fieldset>
        <fieldset disabled={busy || active?.state === 'published'}><legend>Behavior</legend><label>System instructions<textarea rows={8} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} /></label><label>Model<select value={form.model_alias} onChange={(e) => setForm({ ...form, model_alias: e.target.value })}>{options.models.map((model) => <option key={model.alias}>{model.alias}</option>)}</select></label><div className="tool-options"><span>Reviewed read-only tools</span>{options.tools.map((tool) => <label key={tool.stable_name}><input type="checkbox" checked={form.tools.includes(tool.stable_name)} onChange={(e) => setForm({ ...form, tools: e.target.checked ? [...form.tools, tool.stable_name] : form.tools.filter((name) => name !== tool.stable_name) })} />{tool.stable_name} <small>schema {tool.schema_version}</small></label>)}</div></fieldset>
        <div className="builder-actions"><button className="primary" type="submit" disabled={busy}>Save revision</button><button type="button" disabled={!active || busy || active.state === 'published'} onClick={validate}>Validate</button><button type="button" disabled={!active?.validation || busy} onClick={createTest}>Create private test</button></div>
        {testId && <div className="test-panel"><label>Test prompt<input value={testPrompt} onChange={(e) => setTestPrompt(e.target.value)} /></label><button type="button" disabled={busy} onClick={runTest}>Run test</button></div>}
        <div className="builder-actions"><button type="button" className="primary" disabled={!tested || !canPublish || busy} onClick={publish}>Publish immutable release</button>{published && <button type="button" disabled={busy} onClick={deprecate}>Deprecate release</button>}</div>
      </form>
    </div>
  </section>
}
