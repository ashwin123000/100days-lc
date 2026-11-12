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
    if (idToken) {
      void reportClientError(idToken, {
        operation: 'api_network_error',
        endpoint: path.split('?')[0],
        message: error instanceof Error ? error.message : 'The API request could not be reached.',
        stackTrace: error instanceof Error ? error.stack ?? '' : '',
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
  const safePayload = {
    ...payload,
    operation: String(payload.operation ?? 'client_error').slice(0, 120),
    endpoint: String(payload.endpoint ?? '/').slice(0, 300),
    message: String(payload.message ?? 'Unknown client error').slice(0, 2000),
    stackTrace: String(payload.stackTrace ?? '').slice(0, 12000),
  }
  try {
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
