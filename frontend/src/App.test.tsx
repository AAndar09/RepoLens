import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const repository = {
  id: '30c18e4e-616d-4d1d-8d01-bb706426fedd',
  github_url: 'https://github.com/openai/openai-python',
  owner: 'openai',
  name: 'openai-python',
  status: 'ready',
  ingestion_error: null,
  created_at: '2026-09-26T12:00:00Z',
  updated_at: '2026-09-26T12:00:00Z',
}

const snapshot = {
  id: '61107ab8-f9ee-456c-bf54-f53fbe15ca62',
  repository_id: repository.id,
  branch: 'main',
  commit_sha: 'a'.repeat(40),
  status: 'ready',
  error_message: null,
  file_count: 42,
  parsed_file_count: 41,
  malformed_file_count: 1,
  skipped_file_count: 2,
  reused_file_count: 0,
  processed_file_count: 42,
  removed_file_count: 0,
  symbol_count: 180,
  import_count: 75,
  total_bytes: 123456,
  created_at: '2026-09-26T12:00:01Z',
  completed_at: '2026-09-26T12:00:02Z',
}

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }))

function mockApi(evaluations: unknown[] = []) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input)
    if (url.endsWith('/health/ready')) return json({ status: 'ok', database: 'ok', vector_database: 'ok' })
    if (url.endsWith('/evaluations/results')) return json(evaluations)
    if (url.endsWith('/repositories') && init?.method === 'POST') return json(repository, 201)
    if (url.endsWith(`/repositories/${repository.id}`)) return json(repository)
    if (url.endsWith('/ingestion-jobs') || url.endsWith('/ingestion-jobs/job-id')) return json({
      id: 'job-id', repository_id: repository.id, snapshot_id: snapshot.id,
      status: 'succeeded', attempt_count: 1, error_message: null,
      created_at: snapshot.created_at, started_at: snapshot.created_at,
      completed_at: snapshot.completed_at,
    }, 202)
    if (url.endsWith(`/repositories/${repository.id}/snapshots`)) return json([snapshot])
    if (url.endsWith('/retrieval-index')) return json({
      id: 'index-id', snapshot_id: snapshot.id, status: 'ready', embedding_provider: 'hashing',
      embedding_dimensions: 384, collection_name: 'code', unit_count: 180,
      error_message: null, indexed_at: '2026-09-26T12:00:03Z',
    })
    if (url.includes('/files?')) return json([])
    if (url.includes('/symbols?')) return json([])
    if (url.includes('/imports?')) return json([])
    if (url.endsWith('/graph')) return json({
      snapshot_id: snapshot.id, module_count: 42, symbol_count: 180, import_count: 75,
      resolved_import_count: 62, unresolved_import_count: 13,
      ambiguous_import_count: 0, complete: true,
    })
    if (url.includes('/dependencies?')) return json([{
      id: 'dep-id', snapshot_id: snapshot.id, ecosystem: 'PyPI', name: 'httpx',
      normalized_name: 'httpx', specifier: '==0.28.1', resolved_version: '0.28.1',
      version_resolved: true, source_type: 'requirements', source_path: 'requirements.txt',
      source_line: 1, declaration: 'httpx==0.28.1', scope: 'runtime', marker: null,
      vulnerability_checked_at: null, vulnerability_check_error: null,
    }])
    if (url.includes('/vulnerabilities?')) return json([])
    if (url.endsWith('/queries')) return json({
      repository_id: repository.id, snapshot_id: snapshot.id, commit_sha: snapshot.commit_sha,
      question: 'Where is validation?',
      routing: { category: 'implementation', strategy: 'hybrid_retrieval', confidence: 0.91 },
      answer: 'Validation is performed at the repository submission boundary.',
      model_runs: [{
        operation: 'AnswerDraft', provider: 'gemini', model: 'gemini-3.8-flash',
        duration_ms: 410, success: true, fallback_used: false,
        input_tokens: 100, output_tokens: 20, total_tokens: 120, error_type: null,
      }],
      citations: [{
        id: 'evidence-1', snapshot_id: snapshot.id, commit_sha: snapshot.commit_sha,
        filepath: 'app/schemas/repository.py', start_line: 10, end_line: 30,
        source_url: 'https://github.com/openai/openai-python/blob/' + snapshot.commit_sha + '/app/schemas/repository.py#L10-L30',
        title: 'RepositorySubmission', excerpt: 'class RepositorySubmission: ...',
      }],
      tool_trace: [], investigation: null,
    })
    return json({ detail: `Unhandled test URL: ${url}` }, 500)
  })
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('App', () => {
  it('shows a healthy API connection', async () => {
    mockApi()
    render(<App />)
    expect(await screen.findByText('API connected')).toBeInTheDocument()
  })

  it('shows a clear unavailable state when the API cannot be reached', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('connection refused'))
    render(<App />)
    expect(await screen.findByText('API unavailable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Analyse repository/ })).toBeDisabled()
  })

  it('submits, ingests, indexes, and opens the repository workspace', async () => {
    const fetchMock = mockApi()
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('API connected')
    await user.type(screen.getByLabelText('Public GitHub repository'), repository.github_url)
    await user.click(screen.getByRole('button', { name: /Analyse repository/ }))

    expect(await screen.findByRole('heading', { name: 'openai/openai-python' })).toBeInTheDocument()
    expect(screen.getAllByText('aaaaaaaaaaaa').length).toBeGreaterThan(0)
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/repositories/${repository.id}/snapshots/${snapshot.id}/retrieval-index`),
      expect.objectContaining({ method: 'POST' }),
    )

    await user.click(screen.getByRole('button', { name: /Dependencies/ }))
    expect(await screen.findByText('httpx')).toBeInTheDocument()
    expect(screen.getByText('0.28.1')).toBeInTheDocument()
  })

  it('shows explanation and commit-pinned evidence for a repository question', async () => {
    const fetchMock = mockApi()
    const baseImplementation = fetchMock.getMockImplementation()!
    localStorage.setItem('repolens.workspace', JSON.stringify({
      repositoryId: repository.id, snapshotId: snapshot.id,
    }))
    fetchMock.mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith(`/repositories/${repository.id}`)) return json(repository)
      if (url.endsWith(`/repositories/${repository.id}/snapshots`)) return json([snapshot])
      return baseImplementation(input, init)
    })
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('heading', { name: 'openai/openai-python' })
    await user.click(screen.getByRole('button', { name: /Ask RepoLens/ }))
    await user.type(screen.getByLabelText('Question about this snapshot'), 'Where is validation?')
    await user.click(screen.getByRole('button', { name: /Run investigation/ }))

    expect(await screen.findByText(/Validation is performed/)).toBeInTheDocument()
    expect(screen.getByText('RepositorySubmission')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /RepositorySubmission/ })).toHaveAttribute(
      'href', expect.stringContaining(snapshot.commit_sha),
    )
    await user.click(screen.getByRole('button', { name: /developer trace/ }))
    expect(screen.getByText(/gemini · gemini-3.8-flash/)).toBeInTheDocument()
  })

  it('resumes a saved in-progress ingestion job', async () => {
    mockApi()
    localStorage.setItem('repolens.workspace', JSON.stringify({
      repositoryId: repository.id, jobId: 'job-id',
    }))
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'openai/openai-python' })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('repolens.workspace')!)).toEqual({
      repositoryId: repository.id, snapshotId: snapshot.id,
    })
  })

  it('shows generated evaluation metrics', async () => {
    const evaluation = {
      generated_at: '2026-09-28T00:00:00Z', dataset_id: 'sampleproject.python.v1',
      dataset_sha256: 'abc', embedding_provider: 'hashing', embedding_dimensions: 384,
      configurations: ['lexical', 'hybrid'], k_values: [5],
      retrieval_summaries: [{
        configuration: 'hybrid', case_count: 3,
        mean_recall_at_k: { '5': 1 }, mean_citation_correctness_at_k: { '5': 1 },
        latency: { sample_count: 3, mean_ms: 4.2, median_ms: 4, p95_ms: 5 },
      }],
      retrieval_comparisons: [],
      routing_category: { measured_cases: 3, accuracy: 1, latency: null },
      routing_strategy: { measured_cases: 3, accuracy: 1, latency: null },
      symbol_lookup: { measured_cases: 1, accuracy: 1, latency: null },
      tool_selection: { measured_cases: 0, accuracy: null, latency: null },
      unsupported_configurations: {},
      model_assisted_metrics: { enabled: false, metrics: {}, note: 'Not enabled.' },
    }
    mockApi([evaluation])
    localStorage.setItem('repolens.workspace', JSON.stringify({
      repositoryId: repository.id, snapshotId: snapshot.id,
    }))
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('heading', { name: 'openai/openai-python' })
    await user.click(screen.getByRole('button', { name: /Evaluations/ }))

    expect(await screen.findByRole('heading', { name: 'Model evaluations' })).toBeInTheDocument()
    expect(screen.getByText('sampleproject.python.v1')).toBeInTheDocument()
    expect(screen.getAllByText('100.0%').length).toBeGreaterThan(0)
    expect(screen.getByText('not measured')).toBeInTheDocument()
  })
})
