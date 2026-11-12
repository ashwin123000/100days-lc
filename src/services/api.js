const CLIENT_ERROR_REPORT_LIMIT = 5
const CLIENT_ERROR_REPORT_WINDOW_MS = 60_000
const CLIENT_ERROR_DEDUPE_WINDOW_MS = 5 * 60_000
const recentClientErrorReports = new Map()
const clientErrorReportTimes = []

function sanitizeDiagnosticText(value, limit = 1200) {
  return String(value ?? '')
    .replace(
      /((?:authorization|(?:firebase[_-]?)?(?:access[_-]?token|id[_-]?token|refresh[_-]?token|token|api[_-]?key|key|password|secret|cookie|private[_-]?key|client[_-]?secret)\s*[:=]\s*)(["']))[^"']*\2/gi,
      '$1[REDACTED]$2',
    )
    .replace(
      /((?:authorization|(?:firebase[_-]?)?(?:access[_-]?token|id[_-]?token|refresh[_-]?token|token|api[_-]?key|key|password|secret|cookie|private[_-]?key|client[_-]?secret)\s*[:=]\s*))[^\s,;"']+/gi,
      '$1[REDACTED]',
    )
    .replace(
      /([?&](?:[^=&#]*(?:token|key|secret|password|cookie|auth)[^=&#]*)=)[^&#\s]*/gi,
      '$1[REDACTED]',
    )
    .replace(/\b(bearer|basic)\s+[A-Za-z0-9._~+/-]+=*/gi, '$1 [REDACTED]')
    .slice(0, limit)
}

function shouldReportClientError(payload) {
  const now = Date.now()
  while (clientErrorReportTimes.length && now - clientErrorReportTimes[0] >= CLIENT_ERROR_REPORT_WINDOW_MS) {
    clientErrorReportTimes.shift()
  }
  for (const [fingerprint, timestamp] of recentClientErrorReports) {
    if (now - timestamp >= CLIENT_ERROR_DEDUPE_WINDOW_MS) recentClientErrorReports.delete(fingerprint)
  }

  const fingerprint = [
    payload.endpoint,
    payload.method,
    payload.httpStatus,
    payload.requestId,
    payload.message,
  ].join('|')
  if (recentClientErrorReports.has(fingerprint) || clientErrorReportTimes.length >= CLIENT_ERROR_REPORT_LIMIT) {
    return false
  }

  recentClientErrorReports.set(fingerprint, now)
  clientErrorReportTimes.push(now)
  if (recentClientErrorReports.size > 256) {
    recentClientErrorReports.delete(recentClientErrorReports.keys().next().value)
  }
  return true
}

async function requestJson(path, options = {}, idToken = '') {
  let response
  const method = (options.method ?? 'GET').toUpperCase()
  const request = () => fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(idToken ? { Authorization: `Bearer ${idToken}` } : {}),
      ...options.headers,
    },
  })
  try {
    response = await request()
    if (method === 'GET' && [502, 503, 504].includes(response.status)) {
      await response.body?.cancel()
      await new Promise((resolve) => window.setTimeout(resolve, 250))
      response = await request()
    }
  } catch (error) {
    if (idToken && path.split('?')[0] !== '/api/client-errors') {
      void reportClientError(idToken, {
        operation: 'api_network_error',
        endpoint: path.split('?')[0],
        method,
        message: sanitizeDiagnosticText(
          error instanceof Error ? error.message : 'The API request could not be reached.',
        ),
        stackTrace: sanitizeDiagnosticText(error instanceof Error ? error.stack ?? '' : '', 6000),
      })
    }
    throw new Error(
      'Could not reach the API service. Check the connection and try again.',
    )
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    const requestId = response.headers.get('x-request-id')
    const errorSource = response.headers.get('x-error-source')
      ?? (response.status >= 500 ? 'gateway_or_backend' : null)
    if (response.status >= 500) {
      console.error('API request failed', {
        method,
        path,
        status: response.status,
        source: errorSource,
        requestId,
      })
      if (idToken && path.split('?')[0] !== '/api/client-errors') {
        const responseInfo = detail == null
          ? body
          : detail
        void reportClientError(idToken, {
          operation: 'api_http_5xx',
          endpoint: path.split('?')[0],
          method,
          httpStatus: response.status,
          requestId,
          message: sanitizeDiagnosticText(
            `HTTP ${response.status}: ${typeof responseInfo === 'string' ? responseInfo : JSON.stringify(responseInfo ?? 'No response details available.')}`,
          ),
        })
      }
    }
    const error = new Error(
      typeof detail === 'string'
        ? detail
        : detail?.message ??
          (response.status === 404 && !body
            ? 'The /api route was not found. Check that Vite is proxying to the MLSC FastAPI service.'
            : response.status === 502
              ? `The API gateway returned HTTP 502${method === 'GET' ? ' after a retry' : ''}. The backend may be unavailable or unable to complete this request; try again shortly.${requestId ? ` Reference: ${requestId}.` : ''}`
            : `The problem data service could not complete this request (HTTP ${response.status}).`),
    )
    error.status = response.status
    error.code = detail?.code
    error.requestId = requestId
    error.source = errorSource
    throw error
  }
  if (!body) {
    throw new Error('The problem data service returned an invalid response.')
  }
  return body
}

export async function reportClientError(idToken, payload) {
  if (!idToken) return
  try {
    const safePayload = {
      ...payload,
      operation: String(payload.operation ?? 'client_error').slice(0, 120),
      endpoint: sanitizeDiagnosticText(payload.endpoint ?? '/', 300),
      message: sanitizeDiagnosticText(payload.message ?? 'Unknown client error', 2000),
      stackTrace: sanitizeDiagnosticText(payload.stackTrace ?? '', 6000),
    }
    if (!shouldReportClientError(safePayload)) return
    const response = await fetch('/api/client-errors', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${idToken}`,
      },
      body: JSON.stringify(safePayload),
    })
    if (!response.ok) {
      console.warn('Client error report was rejected', response.status)
    }
  } catch (error) {
    console.warn('Client error report could not reach the API', error)
  }
}

export async function withFirebaseToken(user, request) {
  if (!user || typeof user.getIdToken !== 'function') {
    throw new Error('Sign in before requesting learner or administrator data.')
  }
  let token = await user.getIdToken()
  try {
    return await request(token)
  } catch (error) {
    if (error.status !== 401) throw error
    token = await user.getIdToken(true)
    return request(token)
  }
}

export function fetchProblem(problemId) {
  return requestJson(`/api/problems/${encodeURIComponent(problemId)}`)
}

export function lookupProblem(title, leetcodeUrl) {
  return requestJson('/api/problems/lookup', {
    method: 'POST',
    body: JSON.stringify({ title, leetcode_url: leetcodeUrl }),
  })
}

export function preparePotd(title, leetcodeUrl, idToken) {
  return requestJson('/api/admin/potd/prepare', {
    method: 'POST',
    body: JSON.stringify({ title, leetcode_url: leetcodeUrl }),
  }, idToken)
}

export function publishPotd(title, leetcodeUrl, solution, adminNotes, idToken) {
  return requestJson('/api/admin/potd/publish', {
    method: 'POST',
    body: JSON.stringify({
      title,
      leetcode_url: leetcodeUrl,
      solution,
      admin_notes: adminNotes,
    }),
  }, idToken).then((response) => response.problem)
}

export function assignChallengeDay(day, problemSlug, idToken) {
  return requestJson(`/api/admin/challenge/days/${encodeURIComponent(day)}`, {
    method: 'PUT',
    body: JSON.stringify({ problemSlug }),
  }, idToken)
}

export function initializeChallenge(idToken) {
  return requestJson('/api/admin/challenge/initialize', {
    method: 'POST',
  }, idToken)
}

export function fetchLearnerCount(idToken) {
  return requestJson('/api/admin/learners/count', {}, idToken)
    .then((response) => response.count)
}

export function fetchSystemLogs(idToken, params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  }
  const queryString = query.toString()
  const suffix = queryString ? `?${queryString}` : ''
  return requestJson(`/api/admin/system-logs${suffix}`, {}, idToken)
}

export function fetchSystemLog(idToken, logId) {
  return requestJson(`/api/admin/system-logs/${encodeURIComponent(logId)}`, {}, idToken)
}

export function resolveSystemLog(idToken, logId) {
  return requestJson(`/api/admin/system-logs/${encodeURIComponent(logId)}/resolve`, {
    method: 'PATCH',
  }, idToken)
}

export function fetchLeaderboard(idToken) {
  return requestJson('/api/leaderboard', {}, idToken)
}

export function connectLeetcodeAccount(username, idToken) {
  return requestJson('/api/leetcode/connect', {
    method: 'POST',
    body: JSON.stringify({ username }),
  }, idToken)
}

export function fetchLeetcodeProfile(idToken, refresh = false) {
  const params = refresh ? '?refresh=true' : ''
  return requestJson(`/api/leetcode/profile${params}`, {}, idToken)
}

export function fetchLeetcodeHeatmap(from, to, idToken, refresh = false) {
  const params = new URLSearchParams({ from, to })
  if (refresh) params.set('refresh', 'true')
  return requestJson(`/api/leetcode/heatmap?${params}`, {}, idToken)
}

export function fetchLeetcodeStats(idToken, refresh = false) {
  return requestJson(`/api/leetcode/stats${refresh ? '?refresh=true' : ''}`, {}, idToken)
}

export function disconnectLeetcodeAccount(idToken) {
  return requestJson('/api/leetcode/connect', { method: 'DELETE' }, idToken)
}

export function fetchChallengeProgress(idToken) {
  return requestJson('/api/challenge/progress', {}, idToken)
}

export function fetchChallengeQuestions(idToken) {
  return requestJson('/api/challenge/questions', {}, idToken)
}

export function syncChallengeVerifications(idToken, refresh = false) {
  const params = refresh ? '?refresh=true' : ''
  return requestJson(`/api/challenge/sync${params}`, { method: 'POST' }, idToken)
}
