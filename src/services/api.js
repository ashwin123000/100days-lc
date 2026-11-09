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
    throw new Error(
      typeof detail === 'string'
        ? detail
        : detail?.message ??
          (response.status === 404 && !body
            ? 'The /api route was not found. Check that Vite is proxying to the MLSC FastAPI service.'
            : `The problem data service could not complete this request (HTTP ${response.status}).`),
    )
  }
  if (!body) {
    throw new Error('The problem data service returned an invalid response.')
  }
  return body
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

export function fetchLearnerCount(idToken) {
  return requestJson('/api/admin/learners/count', {}, idToken)
    .then((response) => response.count)
}
