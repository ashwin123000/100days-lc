import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import {
  ArrowLeft,
  CalendarDays,
  Check,
  ExternalLink,
  Flame,
  Link2,
  LoaderCircle,
  RefreshCw,
  Trophy,
  Unlink,
} from 'lucide-react'
import {
  disconnectLeetcodeAccount,
  fetchChallengeProgress,
  fetchChallengeQuestions,
  fetchLeetcodeProfile,
  syncChallengeVerifications,
  withFirebaseToken,
} from '../services/api.js'
import { connectLeetcodeProfile, loadLeetcodeProfile } from '../services/leetcodeProfileAdapter.js'
import './LeetCodeProfile.css'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WEEKDAYS = ['Mon', '', 'Wed', '', 'Fri', '', '']
const CURRENT_YEAR = new Date().getUTCFullYear()
const TODAY_ISO = new Date().toISOString().slice(0, 10)

function formatNumber(value) {
  return Number.isFinite(value) ? new Intl.NumberFormat().format(value) : 'N/A'
}

function formatCount(value) {
  return Number.isInteger(value) && value >= 0 ? formatNumber(value) : 'N/A'
}

function displayError(error, fallback) {
  return error?.message || fallback
}

function makeInitials(username) {
  return typeof username === 'string' && username.length
    ? username.slice(0, 2).toUpperCase()
    : 'LC'
}

function getQuestionCompletionStatus(question, syncResult, syncError) {
  const syncedDayStatus = syncResult?.dayStatuses?.[String(question.day)]
  if (
    question.status === 'verified'
    || question.verifiedCompletion === true
    || question.verificationStatus === 'verified'
    || syncedDayStatus === 'verified'
  ) return 'verified'

  if (
    question.status === 'pending'
    || syncResult?.status === 'awaiting_sync'
    || syncedDayStatus === 'awaiting_sync'
  ) {
    return 'pending_sync'
  }

  if (syncError || syncResult?.status === 'unable_to_verify') {
    return 'temporarily_unavailable'
  }

  if (question.status === 'not_started' || question.status === 'rejected') {
    return 'not_solved'
  }

  return 'pending_sync'
}

function getActivityIntensity(count, maxCount) {
  if (!count) return 0
  if (maxCount <= 1) return 4
  return Math.min(4, Math.max(1, Math.ceil((count / maxCount) * 4)))
}

function ActivityHeatmap({ calendar, year }) {
  const { weeks, monthLabels, maxCount } = useMemo(() => {
    const dateMap = new Map(calendar.map((entry) => [entry.date, entry]))
    const start = new Date(Date.UTC(year, 0, 1))
    const end = new Date(Date.UTC(year, 11, 31))
    const firstMonday = new Date(start)
    firstMonday.setUTCDate(firstMonday.getUTCDate() - ((firstMonday.getUTCDay() + 6) % 7))
    const cells = []
    let highest = 0

    for (const date = new Date(firstMonday); date <= end; date.setUTCDate(date.getUTCDate() + 1)) {
      const iso = date.toISOString().slice(0, 10)
      const activity = dateMap.get(iso)
      const count = activity?.submissions ?? 0
      highest = Math.max(highest, count)
      cells.push({
        iso,
        month: date.getUTCMonth(),
        count,
        accepted: activity?.accepted ?? null,
        outsideYear: date.getUTCFullYear() !== year,
        future: iso > TODAY_ISO,
      })
    }

    const resultWeeks = []
    for (let index = 0; index < cells.length; index += 7) resultWeeks.push(cells.slice(index, index + 7))
    const labels = []
    for (let index = 0; index < resultWeeks.length; index += 1) {
      const firstInMonth = resultWeeks[index].find((cell) => cell.iso.endsWith('-01'))
      if (firstInMonth) labels.push({ week: index, label: MONTHS[firstInMonth.month] })
    }
    return { weeks: resultWeeks, monthLabels: labels, maxCount: highest }
  }, [calendar, year])

  return (
    <div className="leetcode-heatmap-scroll" tabIndex={0} aria-label={`${year} LeetCode submissions by day`}>
      <div className="leetcode-heatmap-content">
        <div className="leetcode-calendar-months" style={{ gridTemplateColumns: `32px repeat(${weeks.length}, 14px)` }} aria-hidden="true">
          <div />
          {weeks.map((_, index) => (
              <span className="leetcode-calendar-month" key={index}>
              {monthLabels.find((entry) => entry.week === index)?.label ?? ''}
            </span>
          ))}
        </div>
        <div className="leetcode-calendar-grid">
          <div className="leetcode-calendar-weekdays" aria-hidden="true">
            {WEEKDAYS.map((day, index) => <span key={index}>{day}</span>)}
          </div>
          {weeks.map((week, weekIndex) => (
              <div className="leetcode-calendar-week" key={weekIndex}>
              {week.map((cell) => {
                const title = cell.future
                  ? `${cell.iso}: future date; no activity data yet`
                  : `${cell.iso}: ${cell.count} submission${cell.count === 1 ? '' : 's'}; accepted: ${cell.accepted ?? 'unavailable'}`
                return (
                  <span
                    className="heatmap-cell"
                    data-intensity={getActivityIntensity(cell.count, maxCount)}
                    data-outside-year={cell.outsideYear || undefined}
                    data-future={cell.future || undefined}
                    key={cell.iso}
                    title={title}
                    aria-label={title}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, detail, icon: Icon }) {
  return (
    <article className="leetcode-stat-card">
      <p className="leetcode-stat-label"><Icon size={14} aria-hidden="true" />{label}</p>
      <strong>{value}</strong>
      <span className="leetcode-stat-detail">{detail}</span>
    </article>
  )
}

function ChallengeProgressPanel({ progress, questions, loading, error, onRetry, onOpenQuestion }) {
  const recentDays = progress?.recentDays ?? []
  const completionRate = Number.isFinite(progress?.completionPercentage)
    ? progress.completionPercentage
    : null
  return (
    <section className="leetcode-challenge-hero leetcode-dashboard-section" aria-labelledby="challenge-progress-title">
      <div className="leetcode-challenge-hero-top">
        <div>
          <p className="section-kicker">MLSC CHALLENGE TRACKING</p>
          <h2 id="challenge-progress-title">100 Days of LeetCode</h2>
          <p className="leetcode-challenge-hero-subtitle">Matching Accepted submissions verify the exact MLSC-assigned problem.</p>
        </div>
        {progress && (
          <div className="leetcode-progress-percent">
            <strong>{completionRate ?? '—'}<span>{completionRate === null ? '' : '%'}</span></strong>
            <span>challenge completion</span>
          </div>
        )}
      </div>

      {loading ? (
        <div className="leetcode-empty-state" role="status"><LoaderCircle className="leetcode-spinner" size={18} aria-hidden="true" /> Loading verified challenge progress…</div>
      ) : error && !progress ? (
        <div className="leetcode-challenge-state" role="alert">
          <p>{error}</p>
          <button className="leetcode-secondary-button" type="button" onClick={onRetry}><RefreshCw size={14} /> Retry</button>
        </div>
      ) : !progress ? (
        <div className="leetcode-empty-state" role="status">Challenge progress is not available yet.</div>
      ) : progress.configured === false ? (
        <div className="leetcode-empty-state" role="status">No challenge questions have been published yet. Check back soon.</div>
      ) : (
        <>
          {error && <div className="leetcode-challenge-state" role="alert"><p>{error}</p><button className="leetcode-secondary-button" type="button" onClick={onRetry}><RefreshCw size={14} /> Retry</button></div>}
          <div className="leetcode-challenge-progress-summary">
            <strong>{formatCount(progress.completedDays)} <span>/ {formatCount(progress.totalDays)} days</span></strong>
            <span className="leetcode-days-remaining">{formatCount(progress.remainingDays)} days remaining</span>
          </div>
          <div
            className="leetcode-challenge-progress-track"
            role="progressbar"
            aria-label="Verified challenge completion"
            aria-valuemin={0}
            aria-valuemax={progress.totalDays}
            aria-valuenow={progress.completedDays}
          >
            <span style={{ width: `${Math.min(100, Math.max(0, completionRate ?? 0))}%` }} />
          </div>
          <div className="leetcode-challenge-metrics">
            <div><span>Current challenge streak</span><strong><Flame size={16} aria-hidden="true" />{formatCount(progress.currentStreak)} <small>days</small></strong></div>
            <div><span>Longest challenge streak</span><strong><Trophy size={16} aria-hidden="true" />{formatCount(progress.longestStreak)} <small>days</small></strong></div>
            <div><span>Verified completion</span><strong>{completionRate === null ? 'N/A' : `${completionRate}%`}</strong></div>
          </div>
          <div className="leetcode-challenge-recent">
            <div className="leetcode-challenge-recent-heading"><span>RECENT VERIFIED DAYS</span><span>{recentDays.length} shown</span></div>
            {recentDays.length ? (
              <div className="leetcode-challenge-recent-days">
                {recentDays.map(({ day, status }) => {
                  const question = questions.find((record) => record.day === day)
                  return (
                    <button
                      className="leetcode-challenge-recent-day"
                      key={day}
                      type="button"
                      disabled={!question}
                      title={question ? `Open Day ${day}: ${question.title}` : `Day ${day}: ${status}`}
                      onClick={() => question && onOpenQuestion?.(question)}
                    >
                      <span className="leetcode-day-marker day-completed"><Check size={13} aria-hidden="true" /></span>
                      <small>Day {day}</small>
                    </button>
                  )
                })}
              </div>
            ) : <p className="leetcode-challenge-source-note">No challenge days have been verified yet.</p>}
          </div>
        </>
      )}
      <p className="leetcode-challenge-source-note">Only a matching Accepted submission after its challenge assignment can verify a day. LeetCode exposes only a limited recent-submission list, so an unavailable match is not treated as a failed challenge.</p>
    </section>
  )
}

function ChallengeQuestionHistory({ records, loading, error, onRetry, syncMessage, configured, onOpenQuestion }) {
  return (
    <section className="leetcode-challenge-panel leetcode-dashboard-section" aria-labelledby="challenge-history-title">
      <div className="leetcode-section-heading">
        <div>
          <p className="section-kicker">MLSC-ASSIGNED PROBLEMS</p>
          <h2 id="challenge-history-title">Challenge question history</h2>
        </div>
      </div>
      <p className="leetcode-challenge-source-note">Each day is matched by its exact LeetCode problem slug and assignment date. Public profile usernames do not prove account ownership.</p>
      {syncMessage && <p className="leetcode-inline-error" role="status">{syncMessage}</p>}
      {loading ? (
        <div className="leetcode-empty-state" role="status"><LoaderCircle className="leetcode-spinner" size={18} aria-hidden="true" /> Loading assigned challenge questions…</div>
      ) : error && !records.length ? (
        <div className="leetcode-empty-state" role="alert">
          {error}
          <button className="leetcode-secondary-button" type="button" onClick={onRetry}><RefreshCw size={14} /> Retry</button>
        </div>
      ) : !configured ? (
        <div className="leetcode-empty-state" role="status">No challenge questions have been published yet. Check back soon.</div>
      ) : !records.length ? (
        <div className="leetcode-empty-state" role="status">No challenge questions have been published yet. Check back soon.</div>
      ) : (
        <>
          {error && <div className="leetcode-challenge-state" role="alert"><p>{error}</p><button className="leetcode-secondary-button" type="button" onClick={onRetry}><RefreshCw size={14} /> Retry</button></div>}
          <div className="leetcode-question-list">
            {records.map((record) => {
              const status = record.verificationStatus
              const statusLabel = {
                verified: 'Solved',
                pending_sync: 'Sync Pending',
                not_solved: 'Not Solved',
                temporarily_unavailable: 'Temporarily Unavailable',
              }[status] ?? 'Temporarily Unavailable'
              return (
                <article className="leetcode-question-row" key={record.day}>
                  <div className="leetcode-question-day">DAY <strong>{record.day ?? '—'}</strong></div>
                  <div className="leetcode-question-detail">
                    <button className="leetcode-question-open" type="button" onClick={() => onOpenQuestion?.(record)}>
                      {record.title}
                    </button>
                    <span>{record.difficulty || 'Difficulty unavailable'} · MLSC-published</span>
                  </div>
                  <a className="leetcode-question-external" href={record.leetcodeUrl} target="_blank" rel="noreferrer">LeetCode</a>
                  <span className={`leetcode-question-status status-${status}`}>{statusLabel}</span>
                </article>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}

function LeetCodeProfile({ user, linkedUsername = '', onBack, onVerifiedProblems, onOpenQuestion }) {
  const shouldReduceMotion = useReducedMotion()
  const [year, setYear] = useState(CURRENT_YEAR)
  const [profileStatus, setProfileStatus] = useState('loading')
  const [profileResponse, setProfileResponse] = useState(null)
  const [profileData, setProfileData] = useState(null)
  const [profileDataYear, setProfileDataYear] = useState(null)
  const [profileError, setProfileError] = useState('')
  const [username, setUsername] = useState(linkedUsername)
  const [connectError, setConnectError] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const [progress, setProgress] = useState(null)
  const [challengeQuestions, setChallengeQuestions] = useState([])
  const [challengeConfigured, setChallengeConfigured] = useState(null)
  const [challengeLoading, setChallengeLoading] = useState(true)
  const [progressError, setProgressError] = useState('')
  const [questionsError, setQuestionsError] = useState('')
  const [challengeSyncMessage, setChallengeSyncMessage] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [profileRefreshRequest, setProfileRefreshRequest] = useState(0)
  const completedProfileRefresh = useRef(0)
  const previouslyVerifiedDays = useRef(new Set())

  const loadChallenges = useCallback(async ({ refresh = false, skipSync = false, syncResult = null } = {}) => {
    if (!user) return
    setChallengeLoading(true)
    setProgressError('')
    setQuestionsError('')
    let syncError = null
    let result = syncResult
    if (!skipSync) {
      try {
        result = await withFirebaseToken(
          user,
          (token) => syncChallengeVerifications(token, refresh),
        )
      } catch (error) {
        syncError = error
      }
    }
    const [progressResult, questionsResult] = await Promise.allSettled([
      withFirebaseToken(user, (token) => fetchChallengeProgress(token)),
      withFirebaseToken(user, (token) => fetchChallengeQuestions(token)),
    ])
    if (progressResult.status === 'fulfilled') setProgress(progressResult.value)
    else setProgressError(displayError(progressResult.reason, 'Could not load challenge progress.'))
    const explicitUnconfigured = (
      progressResult.status === 'fulfilled'
      && progressResult.value?.configured === false
    ) || (
      questionsResult.status === 'fulfilled'
      && questionsResult.value?.configured === false
    )
    if (explicitUnconfigured) setChallengeConfigured(false)
    else if (progressResult.status === 'fulfilled' || questionsResult.status === 'fulfilled') setChallengeConfigured(true)
    if (questionsResult.status === 'fulfilled') {
      const updatedQuestions = (questionsResult.value?.questions ?? []).map((question) => ({
        ...question,
        verificationStatus: syncError && previouslyVerifiedDays.current.has(question.day)
          ? 'verified'
          : getQuestionCompletionStatus(question, result, syncError),
      }))
      for (const question of updatedQuestions) {
        if (question.verificationStatus === 'verified') previouslyVerifiedDays.current.add(question.day)
      }
      setChallengeQuestions(updatedQuestions)
      onVerifiedProblems?.(updatedQuestions.filter((question) => question.verificationStatus === 'verified'))
    }
    else setQuestionsError(displayError(questionsResult.reason, 'Could not load assigned questions.'))
    if (syncError) {
      setChallengeSyncMessage(`${displayError(syncError, 'Automatic verification is temporarily unavailable.')} No challenge was marked incomplete; retry later.`)
    } else if (result?.status === 'unable_to_verify') {
      setChallengeSyncMessage(result.message || 'LeetCode did not provide recent accepted-submission data. No challenge was marked incomplete.')
    } else {
      setChallengeSyncMessage('')
    }
    setChallengeLoading(false)
  }, [onVerifiedProblems, user])

  useEffect(() => {
    if (!user) return undefined
    let active = true
    withFirebaseToken(user, (token) => fetchLeetcodeProfile(token))
      .then((response) => {
        if (!active) return
        setProfileResponse(response)
        setUsername(response.profile?.username ?? '')
        setProfileStatus('connected')
      })
      .catch((error) => {
        if (!active) return
        setProfileData(null)
        setProfileDataYear(null)
        setProfileResponse(null)
        if (error?.code === 'leetcode_not_connected' || error?.status === 404) {
          setProfileStatus('disconnected')
        } else {
          setProfileStatus('error')
          setProfileError(displayError(error, 'Could not load the connected LeetCode profile.'))
        }
      })
    return () => { active = false }
  }, [user])

  useEffect(() => {
    if (user) loadChallenges()
  }, [user, loadChallenges])

  useEffect(() => {
    if (!user || !profileResponse) return
    let active = true
    const refresh = profileRefreshRequest > completedProfileRefresh.current
    withFirebaseToken(user, (token) => loadLeetcodeProfile(year, token, profileResponse, refresh))
      .then((data) => {
        if (active) {
          setProfileData(data)
          setProfileDataYear(year)
          if (refresh) completedProfileRefresh.current = profileRefreshRequest
        }
      })
      .catch((error) => {
        if (active) {
          setProfileError(displayError(error, 'Could not load LeetCode statistics.'))
          if (refresh) completedProfileRefresh.current = profileRefreshRequest
        }
      })
    return () => { active = false }
  }, [user, profileResponse, year, profileRefreshRequest])

  const connectAccount = async (event) => {
    event.preventDefault()
    if (!user) {
      setConnectError('Sign in to connect a LeetCode username.')
      return
    }
    const normalizedUsername = username.trim()
    if (!normalizedUsername) {
      setConnectError('Enter your public LeetCode username.')
      return
    }
    setConnecting(true)
    setConnectError('')
    try {
      const response = await withFirebaseToken(user, (token) => connectLeetcodeProfile(normalizedUsername, token))
      setProfileData(null)
      setProfileDataYear(null)
      setUsername(response.profile.username)
      setProfileResponse(response)
      setProfileStatus('connected')
      await loadChallenges({ skipSync: true, syncResult: response.challengeSync })
    } catch (error) {
      setConnectError(displayError(error, 'Could not connect that LeetCode username.'))
    } finally {
      setConnecting(false)
    }
  }

  const disconnectAccount = async () => {
    if (!user) return
    setDisconnecting(true)
    setConnectError('')
    try {
      await withFirebaseToken(user, (token) => disconnectLeetcodeAccount(token))
      setProfileResponse(null)
      setProfileData(null)
      setProfileDataYear(null)
      setProfileStatus('disconnected')
      setUsername('')
      setConfirmDisconnect(false)
    } catch (error) {
      setConnectError(displayError(error, 'Could not disconnect the LeetCode account.'))
      setConfirmDisconnect(false)
    } finally {
      setDisconnecting(false)
    }
  }

  const retryProfileLoad = async () => {
    if (!user) return
    setProfileStatus('loading')
    setProfileError('')
    try {
      const response = await withFirebaseToken(user, (token) => fetchLeetcodeProfile(token, true))
      setProfileResponse(response)
      setUsername(response.profile?.username ?? '')
      setProfileStatus('connected')
      setProfileRefreshRequest((request) => request + 1)
      await loadChallenges({ skipSync: true, syncResult: response.challengeSync })
    } catch (error) {
      setProfileData(null)
      setProfileDataYear(null)
      setProfileStatus(error?.code === 'leetcode_not_connected' || error?.status === 404 ? 'disconnected' : 'error')
      setProfileError(displayError(error, 'Could not load the connected LeetCode profile.'))
    }
  }

  const refreshLeetcodeData = async () => {
    if (!user) return
    setRefreshing(true)
    setProfileError('')
    try {
      const response = await withFirebaseToken(user, (token) => fetchLeetcodeProfile(token, true))
      setProfileResponse(response)
      setUsername(response.profile?.username ?? '')
      setProfileStatus('connected')
      setProfileRefreshRequest((request) => request + 1)
      await loadChallenges({ skipSync: true, syncResult: response.challengeSync })
    } catch (error) {
      setProfileError(displayError(error, 'Could not refresh LeetCode data.'))
    } finally {
      setRefreshing(false)
    }
  }

  const data = profileDataYear === year ? profileData : null
  const problemStatistics = data?.problemStatistics
  const activity = data?.activity
  const calendarSummary = data?.calendarSummary
  const acceptanceRate = Number.isFinite(problemStatistics?.acceptedSubmissions)
    && Number.isFinite(problemStatistics?.totalSubmissions)
    && problemStatistics.totalSubmissions > 0
    ? `${Math.round(problemStatistics.acceptedSubmissions / problemStatistics.totalSubmissions * 100)}%`
    : 'N/A'
  const currentYear = CURRENT_YEAR
  const heatmapYears = [...new Set([
    currentYear,
    currentYear - 1,
    ...(data?.availableYears ?? []),
  ])].sort((first, second) => second - first)
  const calendarError = data?.heatmapError
  const statisticsError = data?.statsError

  return (
    <motion.section
      className="leetcode-profile-page"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.35 }}
    >
      <button className="leetcode-back-button" type="button" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" /> Back
      </button>

      <header className="leetcode-profile-heading">
        <p className="section-kicker">LEARNER DASHBOARD</p>
        <h1>Learning in motion.</h1>
        <p>Your verified 100-day challenge progress, LeetCode activity, and assigned questions.</p>
      </header>

      <section className="leetcode-profile-info leetcode-dashboard-section" aria-labelledby="leetcode-profile-info-title">
        <div className="leetcode-section-heading">
          <div>
            <p className="section-kicker">PUBLIC ACCOUNT</p>
            <h2 id="leetcode-profile-info-title">LeetCode profile information</h2>
          </div>
          {profileStatus === 'connected' && (
            <>
              <span className="leetcode-connected-status">
                <span className="leetcode-connected-dot" /> Username connected
              </span>
              <button
                className="leetcode-secondary-button"
                type="button"
                disabled={refreshing}
                onClick={refreshLeetcodeData}
              >
                {refreshing && <LoaderCircle className="leetcode-spinner" size={14} aria-hidden="true" />}
                {refreshing ? 'Refreshing…' : 'Refresh LeetCode'}
              </button>
            </>
          )}
        </div>
        {profileStatus === 'connected' && profileError && (
          <p className="leetcode-inline-error" role="alert">{profileError}</p>
        )}

        {profileStatus === 'loading' ? (
          <div className="leetcode-empty-state" role="status"><LoaderCircle className="leetcode-spinner" size={18} aria-hidden="true" /> Loading connected account…</div>
        ) : profileStatus === 'connected' && profileResponse ? (
          <div className="leetcode-profile-card" aria-label="Connected LeetCode profile">
            {profileResponse.profile.avatarUrl ? (
              <img className="leetcode-avatar" src={profileResponse.profile.avatarUrl} alt="" loading="lazy" />
            ) : (
              <div className="leetcode-avatar" aria-hidden="true">{makeInitials(profileResponse.profile.username)}</div>
            )}
            <div className="leetcode-profile-identity">
              <div className="leetcode-profile-name-row"><h3>{profileResponse.profile.username}</h3></div>
              <p>{profileResponse.profile.displayName || 'Public LeetCode profile'}</p>
              <p className="leetcode-profile-public-meta">
                Global problem rank {formatNumber(profileResponse.profile.ranking)}
                {' · '}Reputation {formatNumber(profileResponse.profile.reputation)}
                {' · '}{profileResponse.profile.countryName || 'Country unavailable'}
              </p>
              <a className="leetcode-external-link" href={profileResponse.profile.profileUrl || `https://leetcode.com/u/${encodeURIComponent(profileResponse.profile.username)}/`} target="_blank" rel="noreferrer">
                View LeetCode profile <ExternalLink size={14} aria-hidden="true" />
              </a>
            </div>
            <div className="leetcode-contest-summary">
              <span>Contest rating</span>
              <strong>{formatNumber(profileResponse.contestStatistics?.rating ?? problemStatistics?.contestRating ?? profileResponse.problemStatistics?.contestRating)}</strong>
              <small>Contest global rank {formatNumber(profileResponse.contestStatistics?.globalRanking)}</small>
              <small>{formatCount(profileResponse.contestStatistics?.attendedContestsCount)} contests · top {Number.isFinite(profileResponse.contestStatistics?.topPercentage) ? `${profileResponse.contestStatistics.topPercentage}%` : 'N/A'}</small>
            </div>
            <button className="leetcode-disconnect-button" type="button" disabled={disconnecting} onClick={() => setConfirmDisconnect(true)}>
              <Unlink size={15} aria-hidden="true" /> Disconnect
            </button>
          </div>
        ) : (
          <div className="leetcode-connect-panel">
            <div className="leetcode-connect-icon"><Link2 size={21} aria-hidden="true" /></div>
            <div className="leetcode-connect-copy">
              <h3>Connect your LeetCode profile</h3>
              <p>Only your public username is needed. This does not verify account ownership.</p>
            </div>
            <form className="leetcode-connect-form" onSubmit={connectAccount}>
              <label htmlFor="leetcode-username">Public username</label>
              <div className="leetcode-connect-controls">
                <span className="leetcode-username-prefix" aria-hidden="true">@</span>
                <input
                  id="leetcode-username"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck="false"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="your_leetcode_username"
                  aria-describedby={connectError ? 'leetcode-connect-error' : 'leetcode-connect-help'}
                  aria-invalid={Boolean(connectError)}
                  disabled={connecting}
                />
                <button className="leetcode-connect-button" type="submit" disabled={connecting || !user}>
                  {connecting ? <LoaderCircle size={16} className="leetcode-spinner" aria-hidden="true" /> : <Link2 size={16} aria-hidden="true" />}
                  {connecting ? 'Connecting…' : 'Connect'}
                </button>
              </div>
              {connectError ? (
                <p className="leetcode-inline-error" id="leetcode-connect-error" role="alert">{connectError}</p>
              ) : (
                <p className="leetcode-form-help" id="leetcode-connect-help">
                  {profileError || 'Your LeetCode password or session credentials are never requested.'}
                </p>
              )}
              {profileStatus === 'error' && <button className="leetcode-secondary-button" type="button" onClick={retryProfileLoad}>Retry profile loading</button>}
            </form>
          </div>
        )}
      </section>



      <ChallengeProgressPanel
        progress={progress}
        questions={challengeQuestions}
        loading={challengeLoading}
        error={progressError}
        onRetry={() => loadChallenges({ refresh: true })}
        onOpenQuestion={onOpenQuestion}
      />

      <section className="leetcode-activity-panel leetcode-dashboard-section" aria-labelledby="leetcode-heatmap-title">
        <div className="leetcode-section-heading">
          <div>
            <p className="section-kicker">SUBMISSION ACTIVITY</p>
            <h2 id="leetcode-heatmap-title">LeetCode contribution history</h2>
          </div>
          <label className="leetcode-year-select">
            <span className="sr-only">Heatmap year</span>
            <select value={year} onChange={(event) => setYear(Number(event.target.value))}>
              {heatmapYears.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        </div>
        {profileStatus === 'loading' ? (
          <div className="leetcode-empty-state" role="status"><LoaderCircle className="leetcode-spinner" size={18} aria-hidden="true" /> Loading LeetCode activity…</div>
        ) : !profileResponse ? (
          <div className="leetcode-empty-state" role="status">Connect a public LeetCode username below to view submission activity.</div>
        ) : calendarError ? (
          <div className="leetcode-empty-state" role={calendarError.code === 'leetcode_calendar_unavailable' ? 'status' : 'alert'}>
            {displayError(calendarError, 'Could not load the LeetCode heatmap.')}
          </div>
        ) : !data?.calendar ? (
          <div className="leetcode-empty-state" role="status"><LoaderCircle className="leetcode-spinner" size={18} aria-hidden="true" /> Loading submission calendar…</div>
        ) : (
          <>
            <div className="leetcode-heatmap-summary">
              <strong>{formatCount(calendarSummary?.totalSubmissions)}</strong> submissions in {year}
              <span>{formatCount(calendarSummary?.activeDays)} active days</span>
            </div>
            <ActivityHeatmap calendar={data.calendar} year={year} />
            <div className="leetcode-heatmap-legend" aria-label="Submission activity intensity">
              <span>Less</span>
              {[0, 1, 2, 3, 4].map((level) => <span className="heatmap-cell" data-intensity={level} key={level} aria-hidden="true" />)}
              <span>More</span>
              <span className="leetcode-accepted-legend"><Check size={13} aria-hidden="true" /> accepted counts: {data.calendar.some((entry) => entry.accepted !== null) ? 'shown in tooltips' : 'unavailable'}</span>
            </div>
          </>
        )}
      </section>

      <section className="leetcode-solved-section leetcode-dashboard-section" aria-labelledby="leetcode-solved-title">
        <div className="leetcode-section-heading">
          <div>
            <p className="section-kicker">UNIQUE PROBLEMS & ACTIVITY</p>
            <h2 id="leetcode-solved-title">Total questions solved</h2>
          </div>
          <div className="leetcode-solved-total">
            <strong>{formatCount(problemStatistics?.totalSolved)}</strong>
            <span>unique problems solved</span>
          </div>
        </div>
        <div className="leetcode-difficulty-grid">
          {['easy', 'medium', 'hard'].map((difficulty) => {
            const stats = problemStatistics?.[difficulty]
            const ratio = Number.isFinite(stats?.solved) && Number.isFinite(stats?.total) && stats.total > 0
              ? `${Math.min(100, (stats.solved / stats.total) * 100)}%`
              : '0%'
            return (
              <article className={`leetcode-difficulty-card difficulty-${difficulty}`} key={difficulty}>
                <div className="leetcode-difficulty-top">
                  <span>{difficulty}</span>
                  <strong>{formatCount(stats?.solved)}</strong>
                </div>
                <div className="leetcode-progress-track" aria-label={stats ? `${stats.solved} of ${stats.total} ${difficulty} problems` : `Unavailable ${difficulty} problem statistics`}>
                  <span style={{ width: ratio }} />
                </div>
                <p>{Number.isFinite(stats?.total) ? `of ${formatNumber(stats.total)} problems` : 'Total unavailable'}</p>
              </article>
            )
          })}
        </div>
        {statisticsError && <p className="leetcode-inline-error" role="alert">{displayError(statisticsError, 'Some LeetCode statistics are unavailable.')}</p>}
        <div className="leetcode-activity-stats leetcode-profile-stat-grid">
          <StatCard label="Total submissions" value={formatCount(problemStatistics?.totalSubmissions ?? activity?.totalSubmissions)} detail="Submission attempts · not unique problems" icon={Link2} />
          <StatCard label="Acceptance rate" value={acceptanceRate} detail="Accepted / total submissions" icon={Check} />
          <StatCard label="Active days" value={formatCount(calendarSummary?.activeDays)} detail={`in ${year}`} icon={CalendarDays} />
          <StatCard label="Current LeetCode streak" value={Number.isInteger(activity?.currentStreak) ? `${activity.currentStreak} days` : 'N/A'} detail="LeetCode activity · separate from challenge streak" icon={Flame} />
          <StatCard label="Longest LeetCode streak" value={Number.isInteger(activity?.longestStreak) ? `${activity.longestStreak} days` : 'N/A'} detail="Lifetime value unavailable publicly" icon={Trophy} />
        </div>
        <p className="leetcode-stat-connect-note">Unique solved problems and total submission attempts are separate metrics. Unavailable public values are shown as N/A, not zero.</p>
      </section>



      <ChallengeQuestionHistory
        records={challengeQuestions}
        loading={challengeLoading}
        error={questionsError}
        configured={challengeConfigured !== false}
        onRetry={() => loadChallenges({ refresh: true })}
        syncMessage={challengeSyncMessage}
        onOpenQuestion={onOpenQuestion}
      />

      {confirmDisconnect && (
        <div className="leetcode-confirm-backdrop">
          <section className="leetcode-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="leetcode-disconnect-title" aria-describedby="leetcode-disconnect-description">
            <h2 id="leetcode-disconnect-title">Disconnect this username?</h2>
            <p id="leetcode-disconnect-description">This removes only the linked public LeetCode username. It does not affect your MLSC account or challenge records.</p>
            {connectError && <p className="leetcode-inline-error" role="alert">{connectError}</p>}
            <div className="leetcode-confirm-actions">
              <button type="button" className="leetcode-secondary-button" disabled={disconnecting} autoFocus onClick={() => setConfirmDisconnect(false)}>Keep connected</button>
              <button type="button" className="leetcode-danger-button" disabled={disconnecting} onClick={disconnectAccount}>
                {disconnecting && <LoaderCircle className="leetcode-spinner" size={14} aria-hidden="true" />}
                {disconnecting ? 'Disconnecting…' : 'Disconnect'}
              </button>
            </div>
          </section>
        </div>
      )}
    </motion.section>
  )
}

export default LeetCodeProfile
