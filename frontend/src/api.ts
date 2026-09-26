const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export interface HealthResponse {
  status: 'ok'
  database: 'ok'
}

export interface Repository {
  id: string
  github_url: string
  owner: string
  name: string
  status: 'submitted' | 'ingesting' | 'ready' | 'failed'
  ingestion_error: string | null
  created_at: string
  updated_at: string
}

export interface RepositorySnapshot {
  id: string
  repository_id: string
  branch: string
  commit_sha: string
  status: 'ingesting' | 'ready' | 'failed'
  error_message: string | null
  file_count: number
  parsed_file_count: number
  malformed_file_count: number
  skipped_file_count: number
  symbol_count: number
  import_count: number
  total_bytes: number
  created_at: string
  completed_at: string | null
}

interface ApiErrorBody {
  detail?: string | Array<{ msg: string }>
}

async function parseError(response: Response): Promise<Error> {
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  if (typeof body.detail === 'string') return new Error(body.detail)
  if (Array.isArray(body.detail)) return new Error(body.detail[0]?.msg ?? 'Request failed')
  return new Error(`Request failed (${response.status})`)
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)
  if (!response.ok) throw await parseError(response)
  return response.json() as Promise<HealthResponse>
}

export async function submitRepository(githubUrl: string): Promise<Repository> {
  const response = await fetch(`${API_BASE_URL}/repositories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ github_url: githubUrl }),
  })
  if (!response.ok) throw await parseError(response)
  return response.json() as Promise<Repository>
}

export async function ingestRepository(repositoryId: string): Promise<RepositorySnapshot> {
  const response = await fetch(`${API_BASE_URL}/repositories/${repositoryId}/ingestions`, {
    method: 'POST',
  })
  if (!response.ok) throw await parseError(response)
  return response.json() as Promise<RepositorySnapshot>
}
