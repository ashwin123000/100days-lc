import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight,
  BrainCircuit,
  Check,
  Code2,
  Crown,
  Flame,
  GitBranch,
  Layers3,
  List,
  LockKeyhole,
  Network,
  Search,
  Trophy,
  Workflow,
} from 'lucide-react'
import { useReducedMotion } from 'motion/react'
import { ADVENTURE_TOPICS, problemMatchesAdventureTopic } from '../data/adventureTopics.js'
import {
  fetchChallengeProgress,
  fetchChallengeQuestions,
  fetchLeaderboard,
  withFirebaseToken,
} from '../services/api.js'
import { wasPublishedForCurrentSet } from '../utils/problemData.js'
import './DsaAdventureMap.css'

const topicIcons = {
  arrays: Layers3,
  strings: Code2,
  stack: List,
  lists: Search,
  trees: GitBranch,
  graphs: Network,
  dynamic: BrainCircuit,
  greedy: Workflow,
  heap: Layers3,
  boss: Crown,
}

const desktopPath = 'M 119 389 C 186 389 210 286 301 286 S 440 410 532 410 S 670 324 770 324 S 890 232 980 232 S 1164 200 1288 200 C 1240 145 1150 86 1078 86 S 925 173 826 173 S 690 92 588 92 C 500 40 400 105 280 119'
const mobilePath = 'M 100 70 C 100 140 300 140 300 210 S 100 280 100 350 S 300 420 300 490 S 100 560 100 630 S 300 700 300 770 S 100 840 100 910 S 300 980 300 1050 S 100 1120 100 1190 S 300 1260 300 1330'

function getTopicProgress(topic, problems, questions, verifiedSlugs) {
  const topicProblems = problems.filter((problem) => problemMatchesAdventureTopic(problem, topic.id))
  const topicProblemIds = new Set(topicProblems.map((problem) => problem.slug ?? problem.canonicalId))
  const retryCount = questions.filter((question) =>
    topicProblemIds.has(question.slug) && question.status === 'rejected',
  ).length

  return {
    topic,
    totalCount: topicProblems.length,
    completedCount: topicProblems.filter((problem) =>
      verifiedSlugs.has(problem.slug ?? problem.canonicalId),
    ).length,
    retryCount,
  }
}

function JourneyStat({ icon: Icon, label, value, detail, onClick, className = '' }) {
  const content = (
    <>
      <Icon className="adventure-stat-icon" size={18} aria-hidden="true" />
      <span className="adventure-stat-copy">
        <span className="adventure-stat-label">{label}</span>
        <strong className="adventure-stat-value">{value}</strong>
        <span className="adventure-stat-detail">{detail}</span>
      </span>
    </>
  )

  return onClick ? (
    <button className={`adventure-stat adventure-stat-button ${className}`} type="button" onClick={onClick} title={detail}>
      {content}
    </button>
  ) : (
    <div className={`adventure-stat ${className}`} title={detail}>
      {content}
    </div>
  )
}

function Milestone({ item, progress, onSelect, mobile = false, guest, catalogReady, activeTopicId, index }) {
  const Icon = topicIcons[item.topic.icon]
  const { topic, totalCount, completedCount, retryCount } = progress
  const locked = !guest && catalogReady && totalCount === 0
  const completed = !locked && totalCount > 0 && completedCount >= totalCount
  const state = locked
    ? 'locked'
    : completed
      ? 'completed'
      : topic.id === activeTopicId
        ? 'active'
        : 'upcoming'
  const label = locked ? `${topic.label}, locked until problems are published` : `Explore ${topic.label} problems`
  const details = guest
    ? 'Sign in to track topic progress'
    : !catalogReady
      ? 'Loading published problems…'
      : locked
        ? 'No published problems yet'
        : `${completedCount} of ${totalCount} problems completed${retryCount ? `, ${retryCount} to retry` : ''}`

  return (
    <li
      className={`adventure-milestone adventure-milestone--${state}${mobile ? ' adventure-milestone-mobile' : ''}`}
      style={mobile
        ? { '--mobile-x': index % 2 ? '75%' : '25%', '--mobile-y': `${5 + index * 10}%` }
        : { '--node-x': `${topic.x}%`, '--node-y': `${topic.y}%` }}
    >
      <button
        className="adventure-milestone-button"
        type="button"
        aria-label={label}
        aria-disabled={locked || undefined}
        disabled={locked}
        onClick={() => onSelect(topic.id)}
      >
        <span className="adventure-milestone-marker">
          {locked ? <LockKeyhole size={20} aria-hidden="true" /> : <Icon size={24} strokeWidth={1.8} aria-hidden="true" />}
          {completed && <Check className="adventure-milestone-check" size={14} aria-hidden="true" />}
        </span>
        <span className="adventure-milestone-name">{topic.label}</span>
        <span className="adventure-milestone-count">{details}</span>
      </button>
    </li>
  )
}

function DsaAdventureMap({
  user,
  profile,
  isAdmin,
  authLoading,
  problems,
  problemsLoaded,
  onContinue,
  onSelectTopic,
  onOpenLeaderboard,
}) {
  const mapRef = useRef(null)
  const [entered, setEntered] = useState(() => typeof IntersectionObserver !== 'function')
  const [journey, setJourney] = useState(null)
  const [journeyError, setJourneyError] = useState(null)
  const [reloadId, setReloadId] = useState(0)
  const reduceMotion = useReducedMotion()
  const isLearner = Boolean(
    !authLoading && user && profile?.role === 'learner' && profile.isActive !== false && !isAdmin,
  )
  const currentSetProblems = useMemo(() => problems.filter(wasPublishedForCurrentSet), [problems])

  useEffect(() => {
    if (!mapRef.current) return undefined
    if (typeof IntersectionObserver !== 'function') {
      return undefined
    }

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setEntered(true)
        observer.disconnect()
      }
    }, { threshold: 0.16 })
    observer.observe(mapRef.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!isLearner) return undefined
    let active = true
    const loadJourney = async () => {
      try {
        const [progress, leaderboard, assignments] = await withFirebaseToken(user, (token) => Promise.all([
          fetchChallengeProgress(token),
          fetchLeaderboard(token),
          fetchChallengeQuestions(token),
        ]))
        if (active) {
          setJourney({
            userId: user.uid,
            progress,
            leaderboard,
            questions: Array.isArray(assignments?.questions) ? assignments.questions : [],
          })
          setJourneyError(null)
        }
      } catch (loadError) {
        if (active) {
          setJourneyError({
            userId: user.uid,
            message: loadError.message || 'Could not load your learning journey.',
          })
        }
      }
    }
    loadJourney()
    return () => { active = false }
  }, [isLearner, user, reloadId])

  const currentJourney = journey?.userId === user?.uid ? journey : null
  const error = journeyError && journeyError.userId === user?.uid ? journeyError.message : ''
  const loading = isLearner && !currentJourney && !error

  const verifiedSlugs = useMemo(() => new Set(
    (currentJourney?.questions ?? [])
      .filter((question) => question.verifiedCompletion === true)
      .map((question) => question.slug)
      .filter(Boolean),
  ), [currentJourney?.questions])

  const progressByTopic = useMemo(() => ADVENTURE_TOPICS.map((topic) =>
    getTopicProgress(topic, currentSetProblems, currentJourney?.questions ?? [], verifiedSlugs),
  ), [currentJourney?.questions, currentSetProblems, verifiedSlugs])

  const topicsWithProblems = progressByTopic.filter((item) => item.totalCount > 0)
  const nextTopicIndex = progressByTopic.findIndex((item) =>
    item.totalCount > 0 && item.completedCount < item.totalCount,
  )
  const activeTopicIndex = nextTopicIndex >= 0
    ? nextTopicIndex
    : progressByTopic.reduce((lastIndex, item, index) => item.totalCount > 0 ? index : lastIndex, -1)
  const activeTopic = progressByTopic[activeTopicIndex]
  let completedPathUnits = 0
  for (const item of progressByTopic) {
    if (!item.totalCount) break
    completedPathUnits += item.completedCount / item.totalCount
    if (item.completedCount < item.totalCount) break
  }
  const progressPercent = isLearner
    ? Math.min(100, (completedPathUnits / ADVENTURE_TOPICS.length) * 100)
    : 0

  const learner = currentJourney?.leaderboard?.learners?.find((item) => item.learnerId === user?.uid)
  const xpValue = Number.isInteger(learner?.verifiedScore) ? `${learner.verifiedScore.toLocaleString()} XP` : '—'
  const streakValue = Number.isInteger(currentJourney?.progress?.currentStreak)
    ? `${currentJourney.progress.currentStreak} days`
    : '—'
  const rankValue = Number.isInteger(learner?.rank) ? `#${learner.rank.toLocaleString()}` : currentJourney ? 'Unranked' : '—'
  const statsNotice = authLoading
    ? 'Checking your account…'
    : isLearner
      ? currentJourney?.progress?.configured === false
        ? 'The challenge has not been configured yet.'
        : 'XP uses the verified challenge score: one point per completed day.'
      : 'Sign in with a learner account to sync your stats.'
  const activeTopicId = isLearner ? activeTopic?.topic.id : null
  const continueJourney = () => {
    if (activeTopicId) {
      onSelectTopic(activeTopicId)
      return
    }
    onContinue()
  }

  const renderPath = (path, mobile = false) => (
    <svg
      className={`adventure-roadmap-svg${mobile ? ' adventure-roadmap-svg-mobile' : ''}`}
      viewBox={mobile ? '0 0 400 1400' : '0 0 1400 540'}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path className="adventure-roadmap-future" d={path} />
      <path
        className={`adventure-roadmap-progress${entered ? ' is-visible' : ''}`}
        d={path}
        pathLength="100"
        style={{ '--roadmap-offset': String(100 - progressPercent) }}
      />
      {entered && !reduceMotion && progressPercent > 0 && (
        <circle className="adventure-roadmap-particle" r="4">
          <animateMotion dur="7s" repeatCount="indefinite" path={path} />
        </circle>
      )}
    </svg>
  )

  return (
    <section
      ref={mapRef}
      className={`adventure-map-section${entered ? ' adventure-map-entered' : ''}`}
      aria-labelledby="adventure-map-title"
    >
      <div className="adventure-map-inner">
        <header className="adventure-map-header">
          <div className="adventure-map-intro">
            <p className="adventure-map-eyebrow"><span>YOUR LEARNING JOURNEY</span></p>
            <h2 id="adventure-map-title">The <span>DSA</span> Adventure Map.</h2>
            <p className="adventure-map-subtitle">
              A structured path to master Data Structures &amp; Algorithms, one topic at a time.
            </p>
          </div>

          <div className="adventure-stats-wrap">
            <div className="adventure-stats" aria-label="Your learning statistics">
              <JourneyStat
                icon={Layers3}
                label="Total XP"
                value={loading ? '…' : error ? '—' : xpValue}
                detail="One point per verified challenge day"
              />
              <JourneyStat
                icon={Flame}
                label="Day streak"
                value={loading ? '…' : error ? '—' : streakValue}
                detail="Consecutive verified challenge days"
                className="adventure-stat-streak"
              />
              <JourneyStat
                icon={Trophy}
                label="Global rank"
                value={loading ? '…' : error ? '—' : rankValue}
                detail="Based on verified challenge completions"
                onClick={onOpenLeaderboard}
                className="adventure-stat-rank"
              />
            </div>
            <p className="adventure-stats-note" role={error ? 'alert' : undefined}>
              {error
                ? <>{error} <button type="button" onClick={() => { setJourneyError(null); setReloadId((current) => current + 1) }}>Retry</button></>
                : statsNotice}
            </p>
          </div>
        </header>

        <div className="adventure-map-visual" role="group" aria-label="Interactive DSA learning roadmap">
          <div className="adventure-map-desktop">
            {renderPath(desktopPath)}
            <ol className="adventure-milestones" aria-label="DSA topics in learning order">
              {progressByTopic.map((item, index) => (
                <Milestone
                  key={item.topic.id}
                  item={item}
                  progress={item}
                  onSelect={onSelectTopic}
                  guest={!isLearner}
                  catalogReady={problemsLoaded}
                  activeTopicId={activeTopicId}
                  index={index}
                />
              ))}
            </ol>
            <svg className="adventure-map-waves" viewBox="0 0 1440 180" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 70 C180 15 240 160 430 112 S700 15 900 95 1200 140 1440 35" />
              <path d="M0 116 C200 50 280 175 500 135 S790 40 1000 120 1280 170 1440 88" />
            </svg>
          </div>

          <div className="adventure-map-mobile">
            {renderPath(mobilePath, true)}
            <ol className="adventure-milestones-mobile" aria-label="DSA topics in learning order">
              {progressByTopic.map((item, index) => (
                <Milestone
                  key={item.topic.id}
                  item={item}
                  progress={item}
                  onSelect={onSelectTopic}
                  mobile
                  guest={!isLearner}
                  catalogReady={problemsLoaded}
                  activeTopicId={activeTopicId}
                  index={index}
                />
              ))}
            </ol>
          </div>
        </div>

        {isLearner && !loading && !error && problemsLoaded && topicsWithProblems.length === 0 && (
          <p className="adventure-map-empty" role="status">
            Topic milestones will unlock as challenge problems are published.
          </p>
        )}

        <div className="adventure-map-cta">
          <span aria-hidden="true" />
          <button type="button" className="adventure-continue-button" onClick={continueJourney}>
            Continue Your Journey
            <ArrowRight size={19} aria-hidden="true" />
          </button>
          <span aria-hidden="true" />
        </div>
      </div>
    </section>
  )
}

export default DsaAdventureMap
