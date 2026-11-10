import { useMemo, useState } from 'react'
import { ArrowDownUp, ArrowLeft, Search } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import ProblemTable from '../components/ProblemTable.jsx'
import PotdFeature from './PotdFeature.jsx'

// Learner library reset marker. Older Firestore records stay intact and become
// visible again only when republished, which updates their existing updatedAt.
const PRACTICE_LIBRARY_RESET_AT = Date.parse('2026-11-10T12:15:25Z')

function wasPublishedForCurrentSet(problem) {
  const updatedAt = problem?.updatedAt
  const timestamp = typeof updatedAt?.toMillis === 'function'
    ? updatedAt.toMillis()
    : typeof updatedAt === 'string' || updatedAt instanceof Date
      ? new Date(updatedAt).getTime()
      : 0
  return Number.isFinite(timestamp) && timestamp >= PRACTICE_LIBRARY_RESET_AT
}

function ProblemExplorer({
  problems,
  potd,
  onBack,
  onOpenPotd,
  onAction,
  onOpenProblem,
  onToggleBookmark,
  onCycleStatus,
  loading = false,
}) {
  const [search, setSearch] = useState('')
  const [difficulty, setDifficulty] = useState('All difficulties')
  const [solvedFilter, setSolvedFilter] = useState('All problems')
  const [sort, setSort] = useState('number-asc')
  const shouldReduceMotion = useReducedMotion()
  const currentSetProblems = useMemo(() => problems.filter(wasPublishedForCurrentSet), [problems])
  const currentSetPotd = wasPublishedForCurrentSet(potd) ? potd : null

  const visibleProblems = useMemo(() => {
    const query = search.trim().toLowerCase()
    return currentSetProblems
      .filter((problem) => {
        const matchesSearch =
          !query ||
          problem.title.toLowerCase().includes(query) ||
          String(problem.id).includes(query) ||
          problem.topics.some((topic) => topic.toLowerCase().includes(query))
        const matchesDifficulty =
          difficulty === 'All difficulties' || problem.difficulty === difficulty
        const isSolved = problem.status === 'Solved'
        const matchesSolved =
          solvedFilter === 'All problems' ||
          (solvedFilter === 'Solved' && isSolved) ||
          (solvedFilter === 'Unsolved' && !isSolved)
        return matchesSearch && matchesDifficulty && matchesSolved
      })
      .sort((first, second) => {
        if (sort === 'number-desc') return second.id - first.id
        if (sort === 'title-asc') return first.title.localeCompare(second.title)
        if (sort === 'acceptance-desc') return second.acceptance - first.acceptance
        return first.id - second.id
      })
  }, [currentSetProblems, difficulty, search, solvedFilter, sort])

  const solvedCount = currentSetProblems.filter((problem) => problem.status === 'Solved').length

  return (
    <motion.section
      className="problem-page page-shell"
      aria-labelledby="problem-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <div className="problem-page-top">
        <button className="back-link" type="button" onClick={onBack}>
          <ArrowLeft size={16} aria-hidden="true" />
          Challenge paths
        </button>
        <div className="problem-summary">
          <span><strong>{currentSetProblems.length}</strong> problems</span>
          <span><strong>{solvedCount}</strong> solved</span>
        </div>
      </div>

      <PotdFeature potd={currentSetPotd} onOpen={onOpenPotd} />

      <div className="problem-heading">
        <div>
          <p className="section-kicker">MLSC PRACTICE LIBRARY</p>
          <h1 id="problem-title">Revisit Problems</h1>
          <p>Pick up where you left off, revisit a concept, or save a problem for later.</p>
        </div>
      </div>

      <div className="dashboard-toolbar">
        <label className="search-field">
          <Search size={17} aria-hidden="true" />
          <span className="sr-only">Search problems</span>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search problems"
          />
        </label>
        <div className="dashboard-filters">
          <label className="select-control">
            <ArrowDownUp size={15} aria-hidden="true" />
            <span className="sr-only">Sort problems</span>
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="number-asc">Problem number</option>
              <option value="number-desc">Newest first</option>
              <option value="title-asc">Title A–Z</option>
              <option value="acceptance-desc">Acceptance rate</option>
            </select>
          </label>
          <label className="select-control">
            <span className="sr-only">Filter by difficulty</span>
            <select value={difficulty} onChange={(event) => setDifficulty(event.target.value)}>
              <option>All difficulties</option>
              <option>Easy</option>
              <option>Medium</option>
              <option>Hard</option>
            </select>
          </label>
          <label className="select-control">
            <span className="sr-only">Filter by solved status</span>
            <select value={solvedFilter} onChange={(event) => setSolvedFilter(event.target.value)}>
              <option>All problems</option>
              <option>Solved</option>
              <option>Unsolved</option>
            </select>
          </label>
        </div>
      </div>

      {loading ? (
        <div className="dashboard-empty-state" role="status"><p>Loading published problems…</p></div>
      ) : (
        <ProblemTable
          problems={visibleProblems}
          totalCount={currentSetProblems.length}
          onAction={onAction}
          onOpenProblem={onOpenProblem}
          onToggleBookmark={onToggleBookmark}
          onCycleStatus={onCycleStatus}
          emptyTitle="No new problems published yet"
          emptyDescription="New questions will appear here after an admin publishes them. Older question records and learner data remain saved."
        />
      )}
      <p className="problem-results-count">
        Showing <strong>{visibleProblems.length}</strong> of {currentSetProblems.length} problems
      </p>
    </motion.section>
  )
}

export default ProblemExplorer
