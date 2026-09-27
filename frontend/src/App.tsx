import { FormEvent, useEffect, useState } from 'react'

import {
  askRepository,
  buildRetrievalIndex,
  CodeSymbol,
  Dependency,
  fetchDependencies,
  fetchFile,
  fetchFiles,
  fetchGraph,
  fetchHealth,
  fetchImports,
  fetchModuleImports,
  fetchRepository,
  fetchSnapshots,
  fetchSymbols,
  fetchVulnerabilities,
  githubSourceUrl,
  GraphSummary,
  ImportRelationship,
  ingestRepository,
  Repository,
  RepositorySnapshot,
  RoutedQueryResponse,
  scanVulnerabilities,
  SourceFile,
  SourceFileDetail,
  SourceImport,
  submitRepository,
  Vulnerability,
} from './api'
import './styles.css'

type ConnectionState = 'checking' | 'online' | 'offline'
type View = 'overview' | 'ask' | 'explorer' | 'structure' | 'dependencies' | 'security'
type ProcessingStage = 'idle' | 'submitting' | 'ingesting' | 'indexing' | 'loading'

const STORAGE_KEY = 'repolens.workspace'
const navItems: Array<{ id: View; label: string; code: string }> = [
  { id: 'overview', label: 'Overview', code: 'OV' },
  { id: 'ask', label: 'Ask RepoLens', code: 'AI' },
  { id: 'explorer', label: 'Files & symbols', code: 'PY' },
  { id: 'structure', label: 'Structure', code: 'GR' },
  { id: 'dependencies', label: 'Dependencies', code: 'DP' },
  { id: 'security', label: 'Security', code: 'OS' },
]

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Request failed'
const formatBytes = (bytes: number) =>
  new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(bytes) + 'B'

function App() {
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [githubUrl, setGithubUrl] = useState('')
  const [repository, setRepository] = useState<Repository | null>(null)
  const [snapshot, setSnapshot] = useState<RepositorySnapshot | null>(null)
  const [view, setView] = useState<View>('overview')
  const [stage, setStage] = useState<ProcessingStage>('idle')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [files, setFiles] = useState<SourceFile[]>([])
  const [symbols, setSymbols] = useState<CodeSymbol[]>([])
  const [imports, setImports] = useState<SourceImport[]>([])
  const [graph, setGraph] = useState<GraphSummary | null>(null)
  const [dependencies, setDependencies] = useState<Dependency[]>([])
  const [vulnerabilities, setVulnerabilities] = useState<Vulnerability[]>([])

  useEffect(() => {
    let active = true
    async function boot() {
      try {
        await fetchHealth()
      } catch {
        if (active) setConnection('offline')
        return
      }
      if (!active) return
      setConnection('online')
      const saved = localStorage.getItem(STORAGE_KEY)
      if (!saved) return
      try {
        const { repositoryId, snapshotId } = JSON.parse(saved) as {
          repositoryId: string; snapshotId: string
        }
        setStage('loading')
        const [restoredRepository, snapshots] = await Promise.all([
          fetchRepository(repositoryId), fetchSnapshots(repositoryId),
        ])
        const restoredSnapshot = snapshots.find((item) => item.id === snapshotId) ?? snapshots[0]
        if (!restoredSnapshot) throw new Error('The saved repository has no indexed snapshot')
        if (!active) return
        setRepository(restoredRepository)
        setSnapshot(restoredSnapshot)
        await hydrate(restoredRepository, restoredSnapshot, active)
      } catch (restoreError) {
        if (active) {
          localStorage.removeItem(STORAGE_KEY)
          setError(`Could not restore the previous workspace: ${errorMessage(restoreError)}`)
        }
      } finally {
        if (active) setStage('idle')
      }
    }
    void boot()
    return () => { active = false }
  }, [])

  async function hydrate(repo: Repository, snap: RepositorySnapshot, active = true) {
    const results = await Promise.allSettled([
      buildRetrievalIndex(repo.id, snap.id),
      fetchFiles(repo.id, snap.id),
      fetchSymbols(repo.id, snap.id),
      fetchImports(repo.id, snap.id),
      fetchGraph(repo.id, snap.id),
      fetchDependencies(repo.id, snap.id),
      fetchVulnerabilities(repo.id, snap.id),
    ])
    if (!active) return
    const [, fileResult, symbolResult, importResult, graphResult, dependencyResult, vulnResult] = results
    if (fileResult.status === 'fulfilled') setFiles(fileResult.value)
    if (symbolResult.status === 'fulfilled') setSymbols(symbolResult.value)
    if (importResult.status === 'fulfilled') setImports(importResult.value)
    if (graphResult.status === 'fulfilled') setGraph(graphResult.value)
    if (dependencyResult.status === 'fulfilled') setDependencies(dependencyResult.value)
    if (vulnResult.status === 'fulfilled') setVulnerabilities(vulnResult.value)
    const failed = results.filter((item) => item.status === 'rejected')
    setNotice(failed.length ? `${failed.length} workspace service${failed.length > 1 ? 's are' : ' is'} unavailable. Available data is still shown.` : '')
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setNotice('')
    try {
      setStage('submitting')
      const submitted = await submitRepository(githubUrl)
      setRepository(submitted)
      setStage('ingesting')
      const ingested = await ingestRepository(submitted.id)
      setSnapshot(ingested)
      setGithubUrl('')
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        repositoryId: submitted.id, snapshotId: ingested.id,
      }))
      setStage('indexing')
      await hydrate(submitted, ingested)
      setView('overview')
    } catch (submissionError) {
      setError(errorMessage(submissionError))
    } finally {
      setStage('idle')
    }
  }

  async function retryIngestion() {
    if (!repository) return
    setError('')
    try {
      setStage('ingesting')
      const ingested = await ingestRepository(repository.id)
      setSnapshot(ingested)
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        repositoryId: repository.id, snapshotId: ingested.id,
      }))
      setStage('indexing')
      await hydrate(repository, ingested)
    } catch (ingestionError) {
      setError(errorMessage(ingestionError))
    } finally {
      setStage('idle')
    }
  }

  function resetWorkspace() {
    localStorage.removeItem(STORAGE_KEY)
    setRepository(null)
    setSnapshot(null)
    setFiles([])
    setSymbols([])
    setImports([])
    setGraph(null)
    setDependencies([])
    setVulnerabilities([])
    setError('')
    setNotice('')
  }

  if (!repository || !snapshot) {
    return <Landing
      connection={connection}
      githubUrl={githubUrl}
      setGithubUrl={setGithubUrl}
      stage={stage}
      error={error}
      repository={repository}
      onSubmit={handleSubmit}
      onRetry={retryIngestion}
    />
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <div className="repo-identity">
          <span className="repo-owner">{repository.owner}</span>
          <strong>{repository.name}</strong>
          <span className="status-pill"><i /> indexed</span>
        </div>
        <nav aria-label="Repository views">
          {navItems.map((item) => (
            <button
              className={view === item.id ? 'nav-item active' : 'nav-item'}
              key={item.id}
              onClick={() => setView(item.id)}
              type="button"
            >
              <span>{item.code}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="text-button" type="button" onClick={resetWorkspace}>＋ New repository</button>
          <Connection state={connection} />
        </div>
      </aside>

      <main className="workspace">
        <header className="context-bar">
          <div className="breadcrumb">
            <span>{repository.owner}/{repository.name}</span>
            <b>/</b>
            <strong>{navItems.find((item) => item.id === view)?.label}</strong>
          </div>
          <div className="snapshot-chip" title={snapshot.commit_sha}>
            <span>{snapshot.branch}</span>
            <code>{snapshot.commit_sha.slice(0, 12)}</code>
            <a href={`${repository.github_url}/tree/${snapshot.commit_sha}`} target="_blank" rel="noreferrer">↗</a>
          </div>
        </header>
        {notice && <div className="workspace-notice" role="status">{notice}</div>}
        <div className="view-frame">
          {view === 'overview' && <Overview repository={repository} snapshot={snapshot} graph={graph} dependencies={dependencies} vulnerabilities={vulnerabilities} />}
          {view === 'ask' && <AskView repository={repository} snapshot={snapshot} />}
          {view === 'explorer' && <Explorer repository={repository} snapshot={snapshot} files={files} symbols={symbols} />}
          {view === 'structure' && <StructureView repository={repository} snapshot={snapshot} files={files} imports={imports} graph={graph} />}
          {view === 'dependencies' && <DependenciesView repository={repository} snapshot={snapshot} dependencies={dependencies} />}
          {view === 'security' && <SecurityView repository={repository} snapshot={snapshot} dependencies={dependencies} vulnerabilities={vulnerabilities} setVulnerabilities={setVulnerabilities} />}
        </div>
      </main>
    </div>
  )
}

function Brand() {
  return <a className="brand" href="/" aria-label="RepoLens home"><span className="brand-mark">R</span><span>RepoLens<small>code intelligence</small></span></a>
}

function Connection({ state }: { state: ConnectionState }) {
  return <span className={`connection ${state}`} role="status"><i />{state === 'checking' ? 'Checking API' : state === 'online' ? 'API connected' : 'API unavailable'}</span>
}

function Landing({ connection, githubUrl, setGithubUrl, stage, error, repository, onSubmit, onRetry }: {
  connection: ConnectionState; githubUrl: string; setGithubUrl: (value: string) => void
  stage: ProcessingStage; error: string; repository: Repository | null
  onSubmit: (event: FormEvent<HTMLFormElement>) => void; onRetry: () => void
}) {
  const processing = stage !== 'idle'
  const stageLabel = stage === 'submitting' ? 'Validating repository' : stage === 'ingesting' ? 'Cloning and analysing Python' : stage === 'indexing' ? 'Building retrieval index' : stage === 'loading' ? 'Restoring workspace' : ''
  return <main className="landing">
    <header className="landing-header"><Brand /><Connection state={connection} /></header>
    <section className="hero">
      <div className="hero-copy">
        <p className="eyebrow">Repository intelligence, grounded in source</p>
        <h1>Read the system.<br /><em>Not just the files.</em></h1>
        <p className="intro">Index a public Python repository, trace its structure and dependencies, then investigate it with commit-pinned evidence.</p>
      </div>
      <div className="submit-panel">
        <div className="panel-index">01 / CONNECT</div>
        <form onSubmit={onSubmit}>
          <label htmlFor="github-url">Public GitHub repository</label>
          <input id="github-url" type="url" value={githubUrl} onChange={(event) => setGithubUrl(event.target.value)} placeholder="https://github.com/owner/repository" required disabled={processing} />
          <button className="primary-button" type="submit" disabled={processing || connection !== 'online'}>{processing ? stageLabel + '…' : 'Analyse repository'} <span>→</span></button>
        </form>
        {processing && <div className="processing" role="status"><span className="loader" /><div><strong>{stageLabel}</strong><small>This can take a minute for larger repositories.</small></div></div>}
        {error && <div className="alert error" role="alert"><strong>Analysis stopped</strong>{error}{repository && <button type="button" onClick={onRetry}>Retry ingestion</button>}</div>}
        <p className="scope-note">Public repositories only · Python source · Snapshot pinned to commit</p>
      </div>
    </section>
    <section className="capability-strip" aria-label="Capabilities">
      <span><b>AST</b> symbols & imports</span><span><b>RAG</b> hybrid retrieval</span><span><b>GRAPH</b> structure</span><span><b>OSV</b> dependency findings</span>
    </section>
  </main>
}

function ViewHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="view-heading"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{description}</p></div>{action}</div>
}

function Overview({ repository, snapshot, graph, dependencies, vulnerabilities }: {
  repository: Repository; snapshot: RepositorySnapshot; graph: GraphSummary | null
  dependencies: Dependency[]; vulnerabilities: Vulnerability[]
}) {
  const pinned = dependencies.filter((item) => item.version_resolved).length
  return <>
    <ViewHeading eyebrow="Snapshot overview" title={`${repository.owner}/${repository.name}`} description="Deterministic intelligence for one immutable repository snapshot." action={<a className="outline-button" href={`${repository.github_url}/tree/${snapshot.commit_sha}`} target="_blank" rel="noreferrer">View on GitHub ↗</a>} />
    <section className="snapshot-banner"><div><span>Analysed commit</span><code>{snapshot.commit_sha}</code></div><div><span>Default branch</span><strong>{snapshot.branch}</strong></div><div><span>Completed</span><strong>{snapshot.completed_at ? new Date(snapshot.completed_at).toLocaleString() : 'In progress'}</strong></div></section>
    <section className="metric-grid">
      <Metric value={snapshot.file_count} label="Python files" note={`${snapshot.parsed_file_count} parsed cleanly`} />
      <Metric value={snapshot.symbol_count} label="Symbols" note="Modules, classes and functions" />
      <Metric value={graph?.resolved_import_count ?? 0} label="Resolved edges" note={`${graph?.unresolved_import_count ?? 0} unresolved imports`} />
      <Metric value={dependencies.length} label="Dependencies" note={`${pinned} exact versions`} />
    </section>
    <div className="overview-grid">
      <section className="panel"><PanelTitle index="A" title="Snapshot health" /><dl className="fact-list"><Fact label="Source size" value={formatBytes(snapshot.total_bytes)} /><Fact label="Malformed files" value={snapshot.malformed_file_count.toString()} tone={snapshot.malformed_file_count ? 'warn' : 'good'} /><Fact label="Skipped files" value={snapshot.skipped_file_count.toString()} /><Fact label="Graph status" value={graph?.complete ? 'Complete' : 'Unavailable'} tone={graph?.complete ? 'good' : 'warn'} /></dl></section>
      <section className="panel"><PanelTitle index="B" title="Security posture" /><div className="security-summary"><strong>{vulnerabilities.length}</strong><span>public vulnerability finding{vulnerabilities.length === 1 ? '' : 's'}</span></div><p className="muted">Findings are package/version matches from OSV. They do not establish that this repository is exploitable.</p></section>
    </div>
  </>
}

function Metric({ value, label, note }: { value: number; label: string; note: string }) {
  return <article className="metric"><strong>{value.toLocaleString()}</strong><span>{label}</span><small>{note}</small></article>
}
function PanelTitle({ index, title }: { index: string; title: string }) { return <h3 className="panel-title"><span>{index}</span>{title}</h3> }
function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) { return <div><dt>{label}</dt><dd className={tone}>{value}</dd></div> }

function AskView({ repository, snapshot }: { repository: Repository; snapshot: RepositorySnapshot }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<RoutedQueryResponse | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')
  const examples = ['How is the application structured?', 'Where is repository input validated?', 'Which dependencies have known vulnerabilities?']
  async function ask(event: FormEvent) {
    event.preventDefault(); if (!question.trim()) return
    setAsking(true); setError(''); setAnswer(null)
    try { setAnswer(await askRepository(repository.id, snapshot.id, question.trim())) }
    catch (askError) { setError(errorMessage(askError)) }
    finally { setAsking(false) }
  }
  return <>
    <ViewHeading eyebrow="Grounded investigation" title="Ask RepoLens" description="Questions are routed to deterministic lookup, retrieval, or a bounded investigation agent." />
    <section className="ask-layout">
      <div className="question-panel">
        <form onSubmit={ask}><label htmlFor="question">Question about this snapshot</label><textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="How does ingestion enforce resource limits?" rows={4} /><div className="ask-actions"><span>Scoped to <code>{snapshot.commit_sha.slice(0, 12)}</code></span><button className="primary-button" disabled={asking}>{asking ? 'Investigating…' : 'Run investigation →'}</button></div></form>
        <div className="prompt-list"><span>Try asking</span>{examples.map((example) => <button type="button" key={example} onClick={() => setQuestion(example)}>{example}</button>)}</div>
        {error && <div className="alert error" role="alert">{error}</div>}
      </div>
      <div className="answer-panel">
        {!answer && !asking && <EmptyState code="AI" title="Evidence appears here" text="Ask an architecture, implementation, dependency, documentation, or security question." />}
        {asking && <EmptyState code="···" title="Investigating the snapshot" text="RepoLens is selecting tools and gathering evidence." loading />}
        {answer && <AnswerResult answer={answer} />}
      </div>
    </section>
  </>
}

function AnswerResult({ answer }: { answer: RoutedQueryResponse }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const route = String(answer.routing.strategy ?? 'unknown').replaceAll('_', ' ')
  const category = String(answer.routing.category ?? 'unknown')
  return <div className="answer-result"><div className="answer-meta"><span>{category}</span><span>{route}</span><code>{answer.commit_sha.slice(0, 12)}</code></div><h3>Explanation</h3><div className="answer-copy">{answer.answer}</div><h3>Evidence <small>{answer.citations.length}</small></h3>{answer.citations.length ? <div className="evidence-list">{answer.citations.map((citation) => <a href={citation.source_url} target="_blank" rel="noreferrer" key={citation.id}><div><strong>{citation.title}</strong><span>{citation.filepath} · L{citation.start_line}–{citation.end_line}</span></div><b>↗</b><pre>{citation.excerpt}</pre></a>)}</div> : <p className="muted">No source citations were returned for this route.</p>}<button className="trace-toggle" type="button" onClick={() => setTraceOpen(!traceOpen)}>{traceOpen ? 'Hide' : 'Show'} developer trace · {answer.tool_trace.length} calls</button>{traceOpen && <div className="trace-list">{answer.model_runs.map((run, index) => <div key={`${run.operation}-${index}`}><code>{run.provider} · {run.model}</code><span className={run.success ? 'success' : 'error'}>{run.fallback_used ? 'fallback' : run.success ? 'success' : 'failed'}</span><p>{run.operation} · {run.duration_ms} ms{run.total_tokens !== null ? ` · ${run.total_tokens} tokens` : ''}</p></div>)}{answer.tool_trace.map((trace) => <div key={trace.call_id}><code>{trace.tool}</code><span className={trace.status}>{trace.status}</span><p>{trace.summary ?? trace.error ?? trace.purpose}</p></div>)}</div>}</div>
}

function Explorer({ repository, snapshot, files, symbols }: { repository: Repository; snapshot: RepositorySnapshot; files: SourceFile[]; symbols: CodeSymbol[] }) {
  const [mode, setMode] = useState<'files' | 'symbols'>('files')
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<SourceFileDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const filteredFiles = files.filter((item) => item.path.toLowerCase().includes(filter.toLowerCase()))
  const filteredSymbols = symbols.filter((item) => `${item.qualified_name} ${item.kind}`.toLowerCase().includes(filter.toLowerCase()))
  async function openFile(file: SourceFile) {
    setLoading(true); setDetailError('')
    try { setSelected(await fetchFile(repository.id, snapshot.id, file.id)) }
    catch (fileError) { setSelected(null); setDetailError(errorMessage(fileError)) }
    finally { setLoading(false) }
  }
  return <>
    <ViewHeading eyebrow="Indexed source" title="Files & symbols" description="Browse deterministic AST output and open source at the indexed commit." />
    <div className="explorer-toolbar"><div className="segmented"><button className={mode === 'files' ? 'active' : ''} onClick={() => setMode('files')}>Files {files.length}</button><button className={mode === 'symbols' ? 'active' : ''} onClick={() => setMode('symbols')}>Symbols {symbols.length}</button></div><input aria-label="Filter source" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter by path or symbol…" /></div>
    <section className="explorer-grid"><div className="source-list">{mode === 'files' ? filteredFiles.map((file) => <button className={selected?.id === file.id ? 'source-row selected' : 'source-row'} type="button" key={file.id} onClick={() => void openFile(file)}><span className="file-kind">PY</span><div><strong>{file.path}</strong><small>{file.module_name} · {file.line_count} lines</small></div><i className={file.parse_status}>{file.parse_status}</i></button>) : filteredSymbols.map((symbol) => <a className="source-row" key={symbol.id} href={githubSourceUrl(repository, snapshot, symbol.file_path, symbol.start_line, symbol.end_line)} target="_blank" rel="noreferrer"><span className="file-kind">{symbol.kind.slice(0, 2).toUpperCase()}</span><div><strong>{symbol.qualified_name}</strong><small>{symbol.file_path} · L{symbol.start_line}–{symbol.end_line}</small></div><i>{symbol.kind}</i></a>)}{(mode === 'files' ? filteredFiles : filteredSymbols).length === 0 && <EmptyState code="∅" title="Nothing matched" text="Try a broader filter." />}</div><div className="code-view">{loading && <EmptyState code="···" title="Loading source" text="Reading the indexed file." loading />}{!loading && detailError && <div className="alert error" role="alert">{detailError}</div>}{!loading && !selected && !detailError && <EmptyState code="PY" title="Select a file" text="The stored snapshot source will appear here." />}{!loading && selected && <><div className="code-head"><div><strong>{selected.path}</strong><span>{selected.sha256.slice(0, 12)} · {selected.line_count} lines</span></div><a href={githubSourceUrl(repository, snapshot, selected.path)} target="_blank" rel="noreferrer">Open source ↗</a></div>{selected.parse_error && <div className="parse-error">{selected.parse_error}</div>}<pre className="source-code"><code>{selected.content}</code></pre></>}</div></section>
  </>
}

function StructureView({ repository, snapshot, files, imports, graph }: { repository: Repository; snapshot: RepositorySnapshot; files: SourceFile[]; imports: SourceImport[]; graph: GraphSummary | null }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [relationships, setRelationships] = useState<ImportRelationship[]>([])
  const [loading, setLoading] = useState(false)
  const [graphError, setGraphError] = useState('')
  async function selectModule(file: SourceFile) { setSelectedId(file.id); setLoading(true); setGraphError(''); try { setRelationships(await fetchModuleImports(repository.id, snapshot.id, file.id)) } catch (relationshipError) { setRelationships([]); setGraphError(errorMessage(relationshipError)) } finally { setLoading(false) } }
  return <>
    <ViewHeading eyebrow="Deterministic graph" title="Repository structure" description="Module containment and statically resolved imports. Dynamic calls and imports are intentionally not inferred." />
    <section className="graph-strip"><Metric value={graph?.module_count ?? files.length} label="Modules" note="Indexed Python files" /><Metric value={graph?.resolved_import_count ?? 0} label="Resolved" note="Unique internal targets" /><Metric value={graph?.unresolved_import_count ?? 0} label="Unresolved" note="Retained transparently" /><Metric value={graph?.ambiguous_import_count ?? 0} label="Ambiguous" note="No relationship invented" /></section>
    <section className="structure-grid"><div className="module-tree"><PanelTitle index="01" title="Modules" />{files.map((file) => <button type="button" className={selectedId === file.id ? 'module-row active' : 'module-row'} key={file.id} onClick={() => void selectModule(file)}><span>{file.path.split('/').map((_, index) => index === file.path.split('/').length - 1 ? '└' : '·').join(' ')}</span><div><strong>{file.module_name}</strong><small>{file.path}</small></div></button>)}</div><div className="relationship-panel"><PanelTitle index="02" title="Outgoing imports" />{!selectedId && <EmptyState code="GR" title="Select a module" text={`${imports.length} import declarations are indexed across this snapshot.`} />}{loading && <EmptyState code="···" title="Traversing graph" text="Resolving stored relationships." loading />}{graphError && <div className="alert error" role="alert">{graphError}</div>}{selectedId && !loading && !graphError && relationships.length === 0 && <EmptyState code="∅" title="No outgoing relationships" text="This module has no persisted import edges." />}{!loading && !graphError && relationships.map((edge) => <article className="edge-card" key={edge.import_id}><div><span className={`edge-status ${edge.status}`}>{edge.status}</span><strong>{edge.source_module.module_name}</strong><b>→</b><strong>{edge.target_module?.module_name ?? edge.requested_module}</strong></div><p>{edge.reason}</p><a href={githubSourceUrl(repository, snapshot, edge.source_module.path, edge.start_line, edge.end_line)} target="_blank" rel="noreferrer">{edge.source_module.path}:L{edge.start_line} ↗</a></article>)}</div></section>
  </>
}

function DependenciesView({ repository, snapshot, dependencies }: { repository: Repository; snapshot: RepositorySnapshot; dependencies: Dependency[] }) {
  const [filter, setFilter] = useState('')
  const filtered = dependencies.filter((item) => `${item.name} ${item.scope} ${item.source_path}`.toLowerCase().includes(filter.toLowerCase()))
  return <>
    <ViewHeading eyebrow="Manifest inventory" title="Dependencies" description="Direct declarations extracted from supported Python manifests. Open ranges are not presented as installed versions." />
    <div className="table-toolbar"><span>{dependencies.length} declarations · {dependencies.filter((item) => item.version_resolved).length} exact pins</span><input aria-label="Filter dependencies" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter packages…" /></div>
    <div className="data-table"><div className="table-row table-head"><span>Package</span><span>Version / constraint</span><span>Scope</span><span>Provenance</span><span>Status</span></div>{filtered.map((item) => <div className="table-row" key={item.id}><span><strong>{item.name}</strong><small>{item.ecosystem}</small></span><code>{item.resolved_version ?? item.specifier ?? 'unpinned'}</code><span>{item.scope}</span><a href={githubSourceUrl(repository, snapshot, item.source_path, item.source_line ?? undefined)} target="_blank" rel="noreferrer">{item.source_path}{item.source_line ? `:${item.source_line}` : ''} ↗</a><span className={item.version_resolved ? 'tag good' : 'tag neutral'}>{item.version_resolved ? 'exact' : 'not resolved'}</span></div>)}{filtered.length === 0 && <EmptyState code="DP" title="No dependencies found" text="Supported manifests are requirements*.txt and PEP 621 pyproject.toml." />}</div>
  </>
}

function SecurityView({ repository, snapshot, dependencies, vulnerabilities, setVulnerabilities }: { repository: Repository; snapshot: RepositorySnapshot; dependencies: Dependency[]; vulnerabilities: Vulnerability[]; setVulnerabilities: (items: Vulnerability[]) => void }) {
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [scanNote, setScanNote] = useState('')
  async function scan() { setScanning(true); setError(''); try { const result = await scanVulnerabilities(repository.id, snapshot.id, true); setVulnerabilities(result.findings); setScanNote(`${result.queried_count} exact versions queried · ${result.unresolved_version_count} unresolved versions skipped`) } catch (scanError) { setError(errorMessage(scanError)) } finally { setScanning(false) } }
  return <>
    <ViewHeading eyebrow="Public vulnerability intelligence" title="Security findings" description="Known OSV package/version matches, kept separate from application-level interpretation." action={<button className="primary-button compact" type="button" onClick={() => void scan()} disabled={scanning || dependencies.length === 0}>{scanning ? 'Querying OSV…' : vulnerabilities.length ? 'Refresh OSV scan' : 'Run OSV scan'}</button>} />
    <div className="security-callout"><strong>Finding ≠ exploitability</strong><p>RepoLens does not currently perform reachability analysis. Verify whether the vulnerable functionality is used and whether environmental mitigations apply.</p></div>
    {scanNote && <div className="alert success" role="status">{scanNote}</div>}{error && <div className="alert error" role="alert">{error}</div>}
    <section className="finding-list">{vulnerabilities.map((finding) => <article className="finding" key={finding.id}><div className="finding-id"><span>{finding.source}</span><a href={finding.source_url} target="_blank" rel="noreferrer">{finding.osv_id} ↗</a></div><div className="finding-body"><h3>{finding.summary ?? finding.osv_id}</h3><p>{finding.details ?? 'No additional details supplied by the vulnerability source.'}</p><div className="finding-tags"><code>{finding.package_name}=={finding.package_version}</code>{finding.aliases.map((alias) => <span key={alias}>{alias}</span>)}</div></div><div className="finding-time"><span>Source checked</span><time>{new Date(finding.queried_at).toLocaleDateString()}</time></div></article>)}{vulnerabilities.length === 0 && <EmptyState code="OS" title="No cached findings" text={dependencies.some((item) => item.version_resolved) ? 'Run an OSV scan to check exact dependency versions.' : 'No exact dependency versions are available to query.'} />}</section>
  </>
}

function EmptyState({ code, title, text, loading = false }: { code: string; title: string; text: string; loading?: boolean }) {
  return <div className="empty-state"><span className={loading ? 'pulse' : ''}>{code}</span><strong>{title}</strong><p>{text}</p></div>
}

export default App
