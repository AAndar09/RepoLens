import { FormEvent, useEffect, useState } from 'react'

import {
  fetchHealth,
  ingestRepository,
  Repository,
  RepositorySnapshot,
  submitRepository,
} from './api'
import './styles.css'

type ConnectionState = 'checking' | 'online' | 'offline'

function App() {
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [githubUrl, setGithubUrl] = useState('')
  const [repository, setRepository] = useState<Repository | null>(null)
  const [snapshot, setSnapshot] = useState<RepositorySnapshot | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let active = true
    fetchHealth()
      .then(() => active && setConnection('online'))
      .catch(() => active && setConnection('offline'))
    return () => {
      active = false
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    setRepository(null)
    setSnapshot(null)
    try {
      const submittedRepository = await submitRepository(githubUrl)
      setRepository(submittedRepository)
      setGithubUrl('')
      setSnapshot(await ingestRepository(submittedRepository.id))
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : 'Ingestion failed')
    } finally {
      setSubmitting(false)
    }
  }

  async function retryIngestion() {
    if (!repository) return
    setSubmitting(true)
    setError('')
    try {
      setSnapshot(await ingestRepository(repository.id))
    } catch (ingestionError) {
      setError(ingestionError instanceof Error ? ingestionError.message : 'Ingestion failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main>
      <header>
        <a className="brand" href="/" aria-label="RepoLens home">
          <span className="brand-mark">R</span>
          RepoLens
        </a>
        <span className={`connection ${connection}`} role="status">
          <span aria-hidden="true" />
          {connection === 'checking'
            ? 'Checking API'
            : connection === 'online'
              ? 'API connected'
              : 'API unavailable'}
        </span>
      </header>

      <section className="hero">
        <p className="eyebrow">Understand the code in front of you</p>
        <h1>See a repository<br />with sharper focus.</h1>
        <p className="intro">
          Submit a public Python repository to capture its current commit and map its source code.
        </p>

        <form onSubmit={handleSubmit}>
          <label htmlFor="github-url">Public GitHub repository</label>
          <div className="input-row">
            <input
              id="github-url"
              name="github-url"
              type="url"
              value={githubUrl}
              onChange={(event) => setGithubUrl(event.target.value)}
              placeholder="https://github.com/owner/repository"
              required
              disabled={submitting}
            />
            <button type="submit" disabled={submitting || connection !== 'online'}>
              {submitting ? 'Ingesting…' : 'Ingest repository'}
            </button>
          </div>
        </form>

        {error && <p className="message error" role="alert">{error}</p>}
        {error && repository && !snapshot && (
          <button className="retry" type="button" onClick={retryIngestion} disabled={submitting}>
            Retry ingestion
          </button>
        )}
        {repository && snapshot && (
          <p className="message success" role="status">
            <strong>{repository.owner}/{repository.name}</strong> indexed {snapshot.file_count} Python
            {' '}files and {snapshot.symbol_count} symbols at {snapshot.branch}@
            {snapshot.commit_sha.slice(0, 12)}.
            {snapshot.malformed_file_count > 0 && (
              <> {snapshot.malformed_file_count} malformed file(s) were retained with errors.</>
            )}
          </p>
        )}
      </section>

      <footer>Phase 2 · Python code intelligence</footer>
    </main>
  )
}

export default App

