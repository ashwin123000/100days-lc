import {
  connectLeetcodeAccount,
  fetchLeetcodeHeatmap,
  fetchLeetcodeProfile,
  fetchLeetcodeStats,
} from './api.js'

function getYearRange(year) {
  const currentYear = new Date().getUTCFullYear()
  const today = new Date().toISOString().slice(0, 10)
  return {
    from: `${year}-01-01`,
    to: year === currentYear ? today : `${year}-12-31`,
  }
}

function validateProfileResponse(response) {
  if (
    !response?.profile
    || typeof response.profile.username !== 'string'
    || !response.problemStatistics
  ) {
    throw new Error('The LeetCode profile response did not match the API contract.')
  }
  return response
}

function validateCalendarResponse(response) {
  if (response?.calendarError) {
    if (
      typeof response.calendarError.code !== 'string'
      || typeof response.calendarError.message !== 'string'
    ) {
      throw new Error('The LeetCode heatmap response contained an invalid availability message.')
    }
    return {
      calendar: null,
      availableYears: null,
      error: Object.assign(new Error(response.calendarError.message), {
        code: response.calendarError.code,
      }),
    }
  }
  if (!Array.isArray(response?.calendar)) {
    throw new Error('The LeetCode heatmap response did not include a calendar.')
  }
  const calendar = response.calendar.map((day) => {
    if (
      typeof day?.date !== 'string'
      || !Number.isInteger(day.submissions)
      || day.submissions < 0
      || (day.accepted != null && (!Number.isInteger(day.accepted) || day.accepted < 0))
    ) {
      throw new Error('The LeetCode heatmap response contained invalid activity data.')
    }
    return {
      date: day.date,
      submissions: day.submissions,
      accepted: day.accepted,
    }
  })
  const availableYears = Array.isArray(response.availableYears)
    ? response.availableYears.filter((value) => Number.isInteger(value) && value >= 2000)
    : null
  return { calendar, availableYears }
}

function summarizeCalendar(calendar) {
  let totalSubmissions = 0
  let activeDays = 0

  for (const day of calendar) {
    totalSubmissions += day.submissions
    if (day.submissions > 0) activeDays += 1
  }

  return { totalSubmissions, activeDays }
}

function normalizeProblemStatistics(stats) {
  const problems = stats ?? {}
  const totalSolved = problems.totalSolved
  const difficulties = ['easy', 'medium', 'hard'].map((key) => problems[key]?.solved)
  const completeDifficultyCounts = difficulties.every(Number.isInteger)
  const consistentTotal = !completeDifficultyCounts
    || !Number.isInteger(totalSolved)
    || difficulties.reduce((sum, value) => sum + value, 0) === totalSolved

  return {
    ...problems,
    totalSolved: consistentTotal ? totalSolved : null,
    easy: problems.easy ?? { solved: null, total: null },
    medium: problems.medium ?? { solved: null, total: null },
    hard: problems.hard ?? { solved: null, total: null },
    statisticsInconsistent: !consistentTotal,
  }
}

export async function connectLeetcodeProfile(username, idToken) {
  const response = await connectLeetcodeAccount(username, idToken)
  return validateProfileResponse(response)
}

export async function loadLeetcodeProfile(year, idToken, connectedProfile = null, refresh = false) {
  const profileRequest = connectedProfile
    ? Promise.resolve(validateProfileResponse(connectedProfile))
    : fetchLeetcodeProfile(idToken).then(validateProfileResponse)
  const { from, to } = getYearRange(year)
  const [profileResult, statsResult, heatmapResult] = await Promise.allSettled([
    profileRequest,
    fetchLeetcodeStats(idToken, refresh),
    fetchLeetcodeHeatmap(from, to, idToken, refresh).then(validateCalendarResponse),
  ])

  if (profileResult.status === 'rejected') throw profileResult.reason

  const profileResponse = profileResult.value
  const statsResponse = statsResult.status === 'fulfilled' ? statsResult.value : null
  const calendarResponse = heatmapResult.status === 'fulfilled' ? heatmapResult.value : null
  const calendar = calendarResponse?.calendar ?? null
  const calendarSummary = calendar ? summarizeCalendar(calendar) : null
  const statsError = statsResult.status === 'rejected'
    ? statsResult.reason
    : statsResponse?.activityError
      ? Object.assign(new Error(statsResponse.activityError.message), {
          code: statsResponse.activityError.code,
        })
      : null
  const heatmapError = heatmapResult.status === 'rejected'
    ? heatmapResult.reason
    : heatmapResult.value.error

  return {
    profile: profileResponse.profile,
    problemStatistics: normalizeProblemStatistics(
      statsResponse?.problemStatistics ?? profileResponse.problemStatistics,
    ),
    activity: statsResponse?.activity ?? null,
    calendar,
    availableYears: calendarResponse?.availableYears ?? null,
    calendarSummary,
    unavailableFields: profileResponse.unavailableFields ?? [],
    statsError,
    heatmapError,
  }
}
