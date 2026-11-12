import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import {
  connectLeetcodeAccount,
  fetchSystemLogs,
  reportClientError,
} from './api.js'
import { loadLeetcodeProfile } from './leetcodeProfileAdapter.js'

const originalFetch = globalThis.fetch
const originalWindow = globalThis.window
const originalWarn = console.warn
const originalNow = Date.now

afterEach(() => {
  globalThis.fetch = originalFetch
  Date.now = originalNow
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
  console.warn = originalWarn
})

function jsonResponse(status, body, requestId) {
  const headers = { 'Content-Type': 'application/json' }
  if (requestId) headers['X-Request-ID'] = requestId
  return new Response(JSON.stringify(body), { status, headers })
}

test('reports HTTP 500 details and still rejects the original API request', async () => {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    if (url === '/api/client-errors') return jsonResponse(202, { accepted: true })
    return jsonResponse(500, { detail: 'Firestore failed token=diagnostic-secret' }, 'request-500')
  }

  await assert.rejects(
    connectLeetcodeAccount('sample_user', 'firebase-id-token'),
    (error) => error.status === 500,
  )
  await new Promise(setImmediate)

  const report = calls.find((call) => call.url === '/api/client-errors')
  assert.ok(report)
  const payload = JSON.parse(report.options.body)
  assert.equal(payload.endpoint, '/api/leetcode/connect')
  assert.equal(payload.method, 'POST')
  assert.equal(payload.httpStatus, 500)
  assert.equal(payload.requestId, 'request-500')
  assert.match(payload.message, /token=\[REDACTED\]/)
  assert.doesNotMatch(payload.message, /diagnostic-secret/)
})

test('loads profile data when LeetCode does not allow public calendar access', async () => {
  globalThis.fetch = async (url) => {
    if (url === '/api/leetcode/profile') {
      return jsonResponse(200, {
        profile: { username: 'sample_user' },
        problemStatistics: { totalSolved: 10 },
      })
    }
    if (url === '/api/leetcode/stats') {
      return jsonResponse(200, {
        problemStatistics: { totalSolved: 10 },
        activity: null,
        activityError: null,
      })
    }
    if (url.startsWith('/api/leetcode/heatmap')) {
      return jsonResponse(200, {
        calendar: null,
        calendarError: {
          code: 'leetcode_calendar_unavailable',
          message: 'LeetCode does not permit public access to this submission calendar.',
        },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  const result = await loadLeetcodeProfile(2026, 'firebase-id-token')

  assert.equal(result.profile.username, 'sample_user')
  assert.equal(result.calendar, null)
  assert.equal(result.heatmapError.code, 'leetcode_calendar_unavailable')
})

test('reports a final gateway 502 once after the bounded GET retry', async () => {
  const calls = []
  globalThis.window = { setTimeout: (callback) => callback() }
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    if (url === '/api/client-errors') return jsonResponse(202, { accepted: true })
    return jsonResponse(502, { detail: 'Gateway could not reach backend.' }, 'gateway-request')
  }

  await assert.rejects(
    fetchSystemLogs('firebase-id-token'),
    (error) => error.status === 502,
  )
  await new Promise(setImmediate)

  assert.equal(calls.filter((call) => call.url.startsWith('/api/admin/system-logs')).length, 2)
  const reports = calls.filter((call) => call.url === '/api/client-errors')
  assert.equal(reports.length, 1)
  const payload = JSON.parse(reports[0].options.body)
  assert.equal(payload.endpoint, '/api/admin/system-logs')
  assert.equal(payload.method, 'GET')
  assert.equal(payload.httpStatus, 502)
  assert.equal(payload.requestId, 'gateway-request')
})

test('does not report expected authorization, not-found, or validation errors', async () => {
  let calls = 0
  globalThis.fetch = async () => {
    calls += 1
    return jsonResponse(403, { detail: 'Forbidden.' })
  }

  await assert.rejects(connectLeetcodeAccount('sample_user', 'firebase-id-token'))
  await new Promise(setImmediate)
  assert.equal(calls, 1)
})

test('reporting endpoint failures are caught and never recurse', async () => {
  const urls = []
  console.warn = () => {}
  globalThis.fetch = async (url) => {
    urls.push(url)
    throw new Error('network unavailable')
  }

  await assert.rejects(fetchSystemLogs('firebase-id-token'))
  await new Promise(setImmediate)

  assert.deepEqual(urls, ['/api/admin/system-logs', '/api/client-errors'])
})

test('client reporting deduplicates identical events', async () => {
  let calls = 0
  globalThis.fetch = async () => {
    calls += 1
    return jsonResponse(202, { accepted: true })
  }
  const event = {
    operation: 'client_dedupe_test',
    endpoint: '/profile',
    message: 'A repeatable client failure.',
  }

  await reportClientError('firebase-id-token', event)
  await reportClientError('firebase-id-token', event)

  assert.equal(calls, 1)
})

test('client reporting is limited to five events per minute', async () => {
  const now = originalNow()
  Date.now = () => now + 10 * 60_000
  let calls = 0
  globalThis.fetch = async () => {
    calls += 1
    return jsonResponse(202, { accepted: true })
  }

  for (let index = 0; index < 6; index += 1) {
    await reportClientError('firebase-id-token', {
      operation: `client_throttle_test_${index}`,
      endpoint: `/profile/${index}`,
      message: `Distinct failure ${index}.`,
    })
  }

  assert.equal(calls, 5)
})
