const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export type RepositoryStatus = 'submitted' | 'ingesting' | 'ready' | 'failed'
export type SnapshotStatus = 'ingesting' | 'ready' | 'failed'
export type SymbolKind = 'module' | 'class' | 'function' | 'method'

export interface HealthResponse { status: 'ok'; database: 'ok' }
export interface Repository {
  id: string; github_url: string; owner: string; name: string; status: RepositoryStatus
  ingestion_error: string | null; created_at: string; updated_at: string
}
export interface RepositorySnapshot {
  id: string; repository_id: string; branch: string; commit_sha: string; status: SnapshotStatus
  error_message: string | null; file_count: number; parsed_file_count: number
  malformed_file_count: number; skipped_file_count: number; symbol_count: number
  import_count: number; total_bytes: number; created_at: string; completed_at: string | null
}
export interface SourceFile {
  id: string; snapshot_id: string; path: string; module_name: string; sha256: string
  size_bytes: number; line_count: number; parse_status: 'parsed' | 'malformed'
  parse_error: string | null
}
export interface SourceFileDetail extends SourceFile { content: string }
export interface CodeSymbol {
  id: string; source_file_id: string; file_path: string; parent_id: string | null
  kind: SymbolKind; name: string; qualified_name: string; start_line: number
  end_line: number; is_async: boolean
}
export interface SourceImport {
  id: string; source_file_id: string; file_path: string; module: string
  imported_name: string | null; alias: string | null; level: number
  start_line: number; end_line: number
}
export interface RetrievalIndex {
  id: string; snapshot_id: string; status: 'pending' | 'indexing' | 'ready' | 'failed'
  embedding_provider: string; embedding_dimensions: number; collection_name: string
  unit_count: number; error_message: string | null; indexed_at: string | null
}
export interface GraphSummary {
  snapshot_id: string; module_count: number; symbol_count: number; import_count: number
  resolved_import_count: number; unresolved_import_count: number
  ambiguous_import_count: number; complete: boolean
}
export interface ModuleNode { id: string; path: string; module_name: string }
export interface ImportRelationship {
  import_id: string; source_module: ModuleNode; target_module: ModuleNode | null
  status: 'resolved' | 'unresolved' | 'ambiguous'; requested_module: string
  resolved_module: string | null; candidate_paths: string[]; reason: string
  start_line: number; end_line: number
}
export interface Dependency {
  id: string; snapshot_id: string; ecosystem: string; name: string; normalized_name: string
  specifier: string | null; resolved_version: string | null; version_resolved: boolean
  source_type: 'requirements' | 'pyproject'; source_path: string; source_line: number | null
  declaration: string; scope: string; marker: string | null
  vulnerability_checked_at: string | null; vulnerability_check_error: string | null
}
export interface Vulnerability {
  id: string; dependency_id: string; package_name: string; package_version: string
  osv_id: string; summary: string | null; details: string | null; aliases: string[]
  severity: Array<Record<string, unknown>>; affected: Array<Record<string, unknown>>
  references: Array<Record<string, unknown>>; published: string | null; modified: string | null
  source: string; source_url: string; queried_at: string
}
export interface VulnerabilityScan {
  snapshot_id: string; dependency_count: number; queried_count: number
  unresolved_version_count: number; failed_count: number; finding_count: number
  findings: Vulnerability[]
}
export interface Citation {
  id: string; snapshot_id: string; commit_sha: string; filepath: string
  start_line: number; end_line: number; source_url: string; title: string; excerpt: string
}
export interface ToolTrace {
  call_id: string; step: number; tool: string; arguments: Record<string, unknown>
  purpose: string; status: 'success' | 'error'; summary: string | null
  error: string | null; evidence_ids: string[]
}
export interface ModelRun {
  operation: string; provider: string; model: string; duration_ms: number
  success: boolean; fallback_used: boolean; input_tokens: number | null
  output_tokens: number | null; total_tokens: number | null; error_type: string | null
}
export interface RoutedQueryResponse {
  repository_id: string; snapshot_id: string; commit_sha: string; question: string
  routing: Record<string, unknown>; answer: string; citations: Citation[]
  tool_trace: ToolTrace[]; model_runs: ModelRun[]; investigation: unknown | null
}

interface ApiErrorBody { detail?: string | Array<{ msg: string }> }

async function parseError(response: Response): Promise<Error> {
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  if (typeof body.detail === 'string') return new Error(body.detail)
  if (Array.isArray(body.detail)) return new Error(body.detail[0]?.msg ?? 'Request failed')
  return new Error(`Request failed (${response.status})`)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) throw await parseError(response)
  return response.json() as Promise<T>
}

const jsonPost = (body?: unknown): RequestInit => ({
  method: 'POST',
  headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})
const snapshotPath = (repositoryId: string, snapshotId: string) =>
  `/repositories/${repositoryId}/snapshots/${snapshotId}`

export const fetchHealth = () => request<HealthResponse>('/health')
export const fetchRepository = (id: string) => request<Repository>(`/repositories/${id}`)
export const fetchSnapshots = (id: string) => request<RepositorySnapshot[]>(`/repositories/${id}/snapshots`)
export const submitRepository = (githubUrl: string) =>
  request<Repository>('/repositories', jsonPost({ github_url: githubUrl }))
export const ingestRepository = (id: string) =>
  request<RepositorySnapshot>(`/repositories/${id}/ingestions`, jsonPost())
export const buildRetrievalIndex = (repositoryId: string, snapshotId: string) =>
  request<RetrievalIndex>(`${snapshotPath(repositoryId, snapshotId)}/retrieval-index`, jsonPost())
export const fetchFiles = (repositoryId: string, snapshotId: string) =>
  request<SourceFile[]>(`${snapshotPath(repositoryId, snapshotId)}/files?limit=500`)
export const fetchFile = (repositoryId: string, snapshotId: string, fileId: string) =>
  request<SourceFileDetail>(`${snapshotPath(repositoryId, snapshotId)}/files/${fileId}`)
export const fetchSymbols = (repositoryId: string, snapshotId: string) =>
  request<CodeSymbol[]>(`${snapshotPath(repositoryId, snapshotId)}/symbols?limit=500`)
export const fetchImports = (repositoryId: string, snapshotId: string) =>
  request<SourceImport[]>(`${snapshotPath(repositoryId, snapshotId)}/imports?limit=500`)
export const fetchGraph = (repositoryId: string, snapshotId: string) =>
  request<GraphSummary>(`${snapshotPath(repositoryId, snapshotId)}/graph`)
export const fetchModuleImports = (repositoryId: string, snapshotId: string, moduleId: string) =>
  request<ImportRelationship[]>(`${snapshotPath(repositoryId, snapshotId)}/graph/modules/${moduleId}/imports?limit=500`)
export const fetchDependencies = (repositoryId: string, snapshotId: string) =>
  request<Dependency[]>(`${snapshotPath(repositoryId, snapshotId)}/dependencies?limit=500`)
export const fetchVulnerabilities = (repositoryId: string, snapshotId: string) =>
  request<Vulnerability[]>(`${snapshotPath(repositoryId, snapshotId)}/vulnerabilities?limit=500`)
export const scanVulnerabilities = (repositoryId: string, snapshotId: string, refresh = false) =>
  request<VulnerabilityScan>(`${snapshotPath(repositoryId, snapshotId)}/vulnerability-scan?refresh=${refresh}&finding_limit=500`, jsonPost())
export const askRepository = (repositoryId: string, snapshotId: string, question: string) =>
  request<RoutedQueryResponse>(`${snapshotPath(repositoryId, snapshotId)}/queries`, jsonPost({ question }))

export function githubSourceUrl(
  repository: Repository, snapshot: RepositorySnapshot, path: string,
  startLine?: number, endLine?: number,
) {
  let fragment = startLine ? `#L${startLine}` : ''
  if (startLine && endLine && endLine !== startLine) fragment += `-L${endLine}`
  const encodedPath = path.split('/').map(encodeURIComponent).join('/')
  return `https://github.com/${repository.owner}/${repository.name}/blob/${snapshot.commit_sha}/${encodedPath}${fragment}`
}
