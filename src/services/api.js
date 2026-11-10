async function requestJson(path, options = {}, idToken = '') {
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(idToken ? { Authorization: `Bearer ${idToken}` } : {}),
        ...options.headers,
      },
    })
  } catch {
    throw new Error(
      'Could not reach the FastAPI service. Start it on port 8011 or set API_PROXY_TARGET to its address.',
    )
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    const error = new Error(
      typeof detail === 'string'
        ? detail
        : detail?.message ??
          (response.status === 404 && !body
            ? 'The /api route was not found. Check that Vite is proxying to the MLSC FastAPI service.'
            : `The problem data service could not complete this request (HTTP ${response.status}).`),
    )
    error.status = response.status
    error.code = detail?.code
    throw error
  }
  if (!body) {
    throw new Error('The problem data service returned an invalid response.')
  }
  return body
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
