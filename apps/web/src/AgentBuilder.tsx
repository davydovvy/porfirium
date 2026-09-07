import { FormEvent, useState } from 'react'
import { apiFetch } from './auth'

type Release = { release_id: string; agent_id: string; version: string; status: string }

const exampleManifest = {
  apiVersion: 'porfirium.ai/v1',
  kind: 'Agent',
  metadata: {
    name: 'my-agent',
    version: '1.0.0',
    displayName: 'My Agent',
    description: 'An independently built Porfirium agent.',
  },
  spec: {
    image: 'registry:5000/porfirium/my-agent@sha256:' + '0'.repeat(64),
    entrypoint: 'my_agent.main:graph',
    sdk: '>=1.0,<2.0',
    models: ['default'],
    tools: [],
    configSchema: {},
    resources: { cpu: '500m', memory: '256Mi', timeoutSeconds: 300 },
  },
}

async function json<T>(path: string, init: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.title ?? body.detail ?? `Request failed (${response.status})`)
  return body as T
}

function command(body?: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export function AgentBuilder({ canPublish, canAdmin, onCatalogChanged }: {
  canPublish: boolean
  canAdmin: boolean
  onCatalogChanged: () => void
}) {
  const [manifest, setManifest] = useState(JSON.stringify(exampleManifest, null, 2))
  const [image, setImage] = useState(exampleManifest.spec.image)
  const [provenance, setProvenance] = useState(JSON.stringify({
    subjectDigest: 'sha256:' + '0'.repeat(64),
    keyId: 'ci-key',
    signature: '',
  }, null, 2))
  const [release, setRelease] = useState<Release | null>(null)
  const [status, setStatus] = useState('Supply output from the trusted image build and signing pipeline.')
  const [busy, setBusy] = useState(false)

  async function publish(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const parsedManifest = JSON.parse(manifest)
      const parsedProvenance = JSON.parse(provenance)
      const published = await json<Release>('/api/v1/releases', command({
        manifest: parsedManifest, image, provenance: parsedProvenance,
      }))
      setRelease(published)
      setStatus(`Published immutable release ${published.agent_id}:${published.version}.`)
      onCatalogChanged()
    } catch (reason) {
      setStatus((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function selectDefault() {
    if (!release) return
    setBusy(true)
    try {
      await json(`/api/v1/agents/${release.agent_id}/default-release`, command({
        release_id: release.release_id,
      }))
      setStatus(`${release.agent_id}:${release.version} is now the default for new conversations.`)
      onCatalogChanged()
    } catch (reason) {
      setStatus((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function deprecate() {
    if (!release) return
    setBusy(true)
    try {
      await json(`/api/v1/releases/${release.release_id}:deprecate`, command())
      setStatus(`Deprecated ${release.agent_id}:${release.version}; existing conversations stay pinned.`)
      setRelease(null)
      onCatalogChanged()
    } catch (reason) {
      setStatus((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <section className="builder">
    <header><div><small>SIGNED OCI RELEASES</small><h1>Agent publication</h1></div>
      <p role="status">{status}</p></header>
    <form onSubmit={publish}>
      <fieldset disabled={busy || !canPublish}><legend>Verified build output</legend>
        <label>Digest-pinned image<input value={image} onChange={(event) => setImage(event.target.value)} /></label>
        <label>Agent manifest<textarea rows={18} value={manifest} onChange={(event) => setManifest(event.target.value)} /></label>
        <label>Signed provenance<textarea rows={8} value={provenance} onChange={(event) => setProvenance(event.target.value)} /></label>
      </fieldset>
      <div className="builder-actions">
        <button className="primary" type="submit" disabled={busy || !canPublish}>Publish immutable release</button>
        <button type="button" disabled={busy || !canAdmin || !release} onClick={selectDefault}>Use for new conversations</button>
        <button type="button" disabled={busy || !canAdmin || !release} onClick={deprecate}>Deprecate release</button>
      </div>
      {!canPublish && <p>Publication requires the agent publisher role.</p>}
    </form>
  </section>
}
