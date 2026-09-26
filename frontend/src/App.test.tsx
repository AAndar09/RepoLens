import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('App', () => {
  it('shows a healthy API connection', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', database: 'ok' }), { status: 200 }),
    )

    render(<App />)

    expect(await screen.findByText('API connected')).toBeInTheDocument()
  })

  it('submits and ingests a public GitHub repository', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'ok', database: 'ok' }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: '30c18e4e-616d-4d1d-8d01-bb706426fedd',
            github_url: 'https://github.com/openai/openai-python',
            owner: 'openai',
            name: 'openai-python',
            status: 'submitted',
            ingestion_error: null,
            created_at: '2026-09-26T12:00:00Z',
            updated_at: '2026-09-26T12:00:00Z',
          }),
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: '61107ab8-f9ee-456c-bf54-f53fbe15ca62',
            repository_id: '30c18e4e-616d-4d1d-8d01-bb706426fedd',
            branch: 'main',
            commit_sha: 'a'.repeat(40),
            status: 'ready',
            error_message: null,
            file_count: 42,
            parsed_file_count: 41,
            malformed_file_count: 1,
            skipped_file_count: 2,
            symbol_count: 180,
            import_count: 75,
            total_bytes: 123456,
            created_at: '2026-09-26T12:00:01Z',
            completed_at: '2026-09-26T12:00:02Z',
          }),
          { status: 200 },
        ),
      )
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('API connected')
    await user.type(
      screen.getByLabelText('Public GitHub repository'),
      'https://github.com/openai/openai-python',
    )
    await user.click(screen.getByRole('button', { name: 'Ingest repository' }))

    expect(await screen.findByText(/indexed 42 Python/)).toBeInTheDocument()
    expect(screen.getByText(/1 malformed file/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/api/v1/repositories/30c18e4e-616d-4d1d-8d01-bb706426fedd/ingestions',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
