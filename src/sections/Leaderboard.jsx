import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ExternalLink, LoaderCircle, RefreshCw, Trophy } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { fetchLeaderboard, withFirebaseToken } from '../services/api.js'
import './Leaderboard.css'

function initials(name) {
  return String(name || 'Learner')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()
}

function deduplicateLearners(result) {
  const seen = new Set()
  return (result.learners ?? []).filter((learner) => {
    if (!learner.learnerId || seen.has(learner.learnerId)) return false
    seen.add(learner.learnerId)
    return true
  })
}

function LearnerAvatar({ learner, podium = false }) {
  const [failedUrl, setFailedUrl] = useState('')
  const failed = failedUrl === learner.avatarUrl
  const className = `leaderboard-avatar${podium ? ' leaderboard-avatar-podium' : ''}`
  return (
    <span className={className} aria-hidden="true">
      {learner.avatarUrl && !failed
        ? <img src={learner.avatarUrl} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailedUrl(learner.avatarUrl)} />
        : initials(learner.displayName)}
    </span>
  )
}

function Leaderboard({ user, onBack }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const shouldReduceMotion = useReducedMotion()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await withFirebaseToken(user, fetchLeaderboard)
      setData({ ...result, learners: deduplicateLearners(result) })
    } catch (loadError) {
      setError(loadError.message || 'Could not load the leaderboard.')
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    let active = true
    withFirebaseToken(user, fetchLeaderboard)
      .then((result) => {
        if (active) setData({ ...result, learners: deduplicateLearners(result) })
      })
      .catch((loadError) => {
        if (active) setError(loadError.message || 'Could not load the leaderboard.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [user])

  const learners = data?.learners ?? []
  const podium = [learners[1], learners[0], learners[2]].filter(Boolean)

  return (
    <motion.section
      className="leaderboard-page page-shell"
      aria-labelledby="leaderboard-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <div className="leaderboard-page-top">
        <button className="back-link" type="button" onClick={onBack}><ArrowLeft size={16} /> Back to challenge</button>
        <p className="section-kicker">MLSC COMMUNITY</p>
      </div>

      <header className="leaderboard-heading">
        <p className="section-kicker">VERIFIED PROGRESS</p>
        <h1 id="leaderboard-title">Learner leaderboard</h1>
        <p>One point for each distinct challenge day verified by LeetCode or an approved review. Tied scores share rank.</p>
      </header>

      {loading ? (
        <div className="leaderboard-state" role="status"><LoaderCircle className="leaderboard-spinner" size={20} /> Loading verified learner scores…</div>
      ) : error ? (
        <div className="leaderboard-state leaderboard-error" role="alert">
          <p>{error}</p>
          <button className="leetcode-secondary-button" type="button" onClick={() => { setLoading(true); setError(''); load() }}><RefreshCw size={14} /> Retry</button>
        </div>
      ) : (
        <>
          {podium.length > 0 && (
            <section className="leaderboard-podium" aria-label="Top three learners">
              {podium.map((learner) => (
                <article className={`leaderboard-podium-card podium-rank-${learner.rank}`} key={learner.learnerId}>
                  <Trophy className="leaderboard-trophy" size={25} aria-hidden="true" />
                  <span className="leaderboard-place">{learner.rank === 1 ? '1ST PLACE' : learner.rank === 2 ? '2ND PLACE' : '3RD PLACE'}</span>
                  <LearnerAvatar learner={learner} podium />
                  <strong className="leaderboard-podium-name">{learner.displayName}</strong>
                  <span className="leaderboard-podium-score">{learner.verifiedScore} <small>verified</small></span>
                  {learner.leetcodeProfileUrl
                    ? <a className="leaderboard-profile-button" href={learner.leetcodeProfileUrl} target="_blank" rel="noreferrer">Profile <ExternalLink size={13} /></a>
                    : <span className="leaderboard-profile-unavailable">Profile unavailable</span>}
                </article>
              ))}
            </section>
          )}

          <section className="leaderboard-list-card" aria-labelledby="leaderboard-list-title">
            <div className="leaderboard-list-heading">
              <div>
                <p className="section-kicker">RANKINGS</p>
                <h2 id="leaderboard-list-title">All learners</h2>
              </div>
              <span>{data.totalLearners} learners</span>
            </div>
            {learners.length ? (
              <ol className="leaderboard-list">
                {learners.map((learner) => (
                  <li className={`leaderboard-row${learner.rank <= 3 ? ` leaderboard-row-top-${learner.rank}` : ''}`} key={learner.learnerId}>
                    <span className="leaderboard-rank">{learner.rank}</span>
                    <LearnerAvatar learner={learner} />
                    <strong className="leaderboard-learner-name">{learner.displayName}</strong>
                    <span className="leaderboard-score">{learner.verifiedScore}<small> verified</small></span>
                    {learner.leetcodeProfileUrl
                      ? <a className="leaderboard-profile-button" href={learner.leetcodeProfileUrl} target="_blank" rel="noreferrer">Profile <ExternalLink size={13} /></a>
                      : <span className="leaderboard-profile-unavailable">Profile unavailable</span>}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="leaderboard-empty">No active learner accounts are registered yet.</p>
            )}
          </section>
          <p className="leaderboard-score-note">{data.scoringRule}</p>
        </>
      )}
    </motion.section>
  )
}

export default Leaderboard
