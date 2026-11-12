import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { fetchSystemLog, fetchSystemLogs, resolveSystemLog, withFirebaseToken } from '../services/api.js'

const sources = [
  'LEETCODE_GRAPHQL',
  'LEETCODE_NETWORK',
  'LEETCODE_HTTP',
  'BACKEND',
  'FIRESTORE',
  'AUTH',
  'FRONTEND',
]

function formatTimestamp(value) {
  if (!value) return '—'
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? '—' : timestamp.toLocaleString()
}

function SystemLogsDashboard({ user, onBack }) {
  const [filters, setFilters] = useState({
    search: '',
    source: '',
    severity: '',
    resolutionStatus: '',
    startDate: '',
    endDate: '',
  })
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [cursor, setCursor] = useState(null)
  const [cursorTrail, setCursorTrail] = useState([])
  const [result, setResult] = useState(null)
  const [selectedLog, setSelectedLog] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [resolving, setResolving] = useState(false)
  const [refreshCount, setRefreshCount] = useState(0)
  const shouldReduceMotion = useReducedMotion()

  useEffect(() => {
    let active = true
    withFirebaseToken(user, (token) => fetchSystemLogs(token, {
      source: filters.source,
      severity: filters.severity,
      resolutionStatus: filters.resolutionStatus,
      startDate: filters.startDate,
      endDate: filters.endDate,
      search: submittedSearch,
      pageSize: 25,
      cursor,
    }))
      .then((response) => {
        if (active) setResult(response)
      })
      .catch((loadError) => {
        if (active) setError(loadError.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [
    cursor,
    filters.endDate,
    filters.resolutionStatus,
    filters.severity,
    filters.source,
    filters.startDate,
    refreshCount,
    submittedSearch,
    user,
  ])

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }))
    setCursor(null)
    setCursorTrail([])
    setSelectedLog(null)
    setLoading(true)
    setError('')
  }

  const selectLog = async (log) => {
    setSelectedLog(log)
    try {
      const detail = await withFirebaseToken(user, (token) => fetchSystemLog(token, log.id))
      setSelectedLog(detail)
    } catch (loadError) {
      setError(loadError.message)
    }
  }

  const handleResolve = async () => {
    if (!selectedLog || selectedLog.resolutionStatus === 'RESOLVED') return
    setResolving(true)
    setError('')
    try {
      const updated = await withFirebaseToken(user, (token) => resolveSystemLog(token, selectedLog.id))
      setSelectedLog(updated)
      setResult((current) => current && ({
        ...current,
        items: filters.resolutionStatus === 'OPEN'
          ? current.items.filter((item) => item.id !== updated.id)
          : current.items.map((item) => item.id === updated.id ? updated : item),
        summary: { ...current.summary, unresolved: Math.max(0, current.summary.unresolved - 1) },
      }))
    } catch (resolveError) {
      setError(resolveError.message)
    } finally {
      setResolving(false)
    }
  }

  const goNext = () => {
    if (!result?.nextCursor) return
    setCursorTrail((current) => [...current, cursor])
    setCursor(result.nextCursor)
    setSelectedLog(null)
    setLoading(true)
    setError('')
  }

  const goPrevious = () => {
    if (!cursorTrail.length) return
    setCursor(cursorTrail[cursorTrail.length - 1])
    setCursorTrail((current) => current.slice(0, -1))
    setSelectedLog(null)
    setLoading(true)
    setError('')
  }

  return (
    <motion.section
      className="system-logs-page page-shell"
      aria-labelledby="system-logs-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <div className="admin-page-top">
        <button className="back-link" type="button" onClick={onBack}>
          <ArrowLeft size={16} /> Back to admin dashboard
        </button>
        <span className="admin-badge"><ShieldCheck size={14} /> ADMIN ONLY</span>
      </div>

      <div className="admin-heading-row">
        <div>
          <p className="section-kicker">OPERATIONS</p>
          <h1 id="system-logs-title">Error logs</h1>
          <p>Review application and upstream failures. Log history is retained for {result?.retentionDays ?? 30} days.</p>
        </div>
        <button className="logs-refresh-button" type="button" onClick={() => {
          setCursor(null)
          setCursorTrail([])
          setRefreshCount((current) => current + 1)
          setLoading(true)
          setError('')
        }} disabled={loading}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      <div className="system-log-summary" aria-label="Log summary">
        {[
          ['Total', result?.summary?.total],
          ['Critical', result?.summary?.critical],
          ['Warnings', result?.summary?.warnings],
          ['Unresolved', result?.summary?.unresolved],
        ].map(([label, count]) => (
          <article className="system-log-stat" key={label}>
            <span>{label}</span>
            <strong>{count == null ? '—' : count.toLocaleString()}</strong>
          </article>
        ))}
      </div>

      <form className="system-logs-filters" onSubmit={(event) => {
        event.preventDefault()
        setSubmittedSearch(filters.search.trim())
        setCursor(null)
        setCursorTrail([])
        setLoading(true)
        setError('')
      }}>
        <label className="search-field admin-search-field">
          <Search size={16} />
          <span className="sr-only">Search error logs</span>
          <input
            value={filters.search}
            onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
            placeholder="Search message, endpoint, request ID"
          />
        </label>
        <select aria-label="Filter by source" value={filters.source} onChange={(event) => updateFilter('source', event.target.value)}>
          <option value="">All sources</option>
          {sources.map((source) => <option key={source} value={source}>{source.replaceAll('_', ' ')}</option>)}
        </select>
        <select aria-label="Filter by severity" value={filters.severity} onChange={(event) => updateFilter('severity', event.target.value)}>
          <option value="">All severities</option>
          <option value="CRITICAL">Critical</option>
          <option value="ERROR">Error</option>
          <option value="WARNING">Warning</option>
        </select>
        <select aria-label="Filter by status" value={filters.resolutionStatus} onChange={(event) => updateFilter('resolutionStatus', event.target.value)}>
          <option value="">All statuses</option>
          <option value="OPEN">Open</option>
          <option value="RESOLVED">Resolved</option>
        </select>
        <label>
          <span>From</span>
          <input type="date" value={filters.startDate} onChange={(event) => updateFilter('startDate', event.target.value)} />
        </label>
        <label>
          <span>To</span>
          <input type="date" value={filters.endDate} onChange={(event) => updateFilter('endDate', event.target.value)} />
        </label>
        <button type="submit">Search</button>
      </form>

      {error && <div className="api-notice" role="alert">{error}</div>}
      {result?.scanLimitReached && (
        <p className="system-log-scan-note" role="status">
          <AlertTriangle size={15} /> This filtered search reached its scan limit. Narrow the date range or filters to see more matching records.
        </p>
      )}

      <div className="system-logs-content">
        <div className="system-log-table-wrap">
          {loading ? <p className="system-log-empty" role="status">Loading error logs…</p> : (
            <table className="system-log-table">
              <thead>
                <tr><th>Time</th><th>Severity</th><th>Source</th><th>Endpoint</th><th>Status</th><th>Resolution</th></tr>
              </thead>
              <tbody>
                {result?.items?.map((log) => (
                  <tr
                    key={log.id}
                    className={selectedLog?.id === log.id ? 'is-selected' : ''}
                    onClick={() => selectLog(log)}
                  >
                    <td>{formatTimestamp(log.timestamp)}</td>
                    <td><span className={`system-log-severity severity-${log.severity.toLowerCase()}`}>{log.severity}</span></td>
                    <td>{log.source.replaceAll('_', ' ')}</td>
                    <td title={log.endpoint}>{log.method} {log.endpoint}</td>
                    <td>{log.httpStatus || '—'}</td>
                    <td>{log.resolutionStatus}</td>
                  </tr>
                ))}
                {!result?.items?.length && <tr className="no-results"><td colSpan="6" className="system-log-empty">No error logs match these filters.</td></tr>}
              </tbody>
            </table>
          )}
          <div className="system-log-pagination">
            <button type="button" onClick={goPrevious} disabled={!cursorTrail.length || loading}><ChevronLeft size={16} /> Previous</button>
            <button type="button" onClick={goNext} disabled={!result?.nextCursor || loading}>Next <ChevronRight size={16} /></button>
          </div>
        </div>

        {selectedLog && (
          <aside className="system-log-detail" aria-label="Selected error log">
            <div className="system-log-detail-heading">
              <h2>Error details</h2>
              {selectedLog.resolutionStatus === 'OPEN' && (
                <button type="button" onClick={handleResolve} disabled={resolving}>
                  {resolving ? 'Resolving…' : 'Mark resolved'}
                </button>
              )}
            </div>
            <dl>
              <dt>Message</dt><dd>{selectedLog.message}</dd>
              <dt>Operation</dt><dd>{selectedLog.operation}</dd>
              <dt>Request ID</dt><dd>{selectedLog.requestId || '—'}</dd>
              <dt>User ID</dt><dd>{selectedLog.userId || '—'}</dd>
              <dt>Error code</dt><dd>{selectedLog.errorCode || '—'}</dd>
              <dt>Resolution</dt><dd>{selectedLog.resolutionStatus}{selectedLog.resolvedBy ? ` by ${selectedLog.resolvedBy}` : ''}</dd>
            </dl>
            {selectedLog.stackTrace && <pre>{selectedLog.stackTrace}</pre>}
          </aside>
        )}
      </div>
    </motion.section>
  )
}

export default SystemLogsDashboard
