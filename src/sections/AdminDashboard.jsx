import { useMemo, useState } from 'react'
import { ArrowLeft, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import ProblemTable from '../components/ProblemTable.jsx'
import PotdFeature from './PotdFeature.jsx'

function AdminDashboard({
  problems,
  potd,
  learnerCount,
  learnerCountError,
  onBack,
  onPublishPotd,
  onAction,
  onToggleBookmark,
  onCycleStatus,
}) {
  const [search, setSearch] = useState('')
  const shouldReduceMotion = useReducedMotion()
  const visibleProblems = useMemo(
    () => problems.filter((problem) => problem.title.toLowerCase().includes(search.trim().toLowerCase()) || String(problem.id).includes(search.trim())),
    [problems, search],
  )

  return (
    <motion.section
      className="admin-page page-shell"
      aria-labelledby="admin-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <div className="admin-page-top">
        <button className="back-link" type="button" onClick={onBack}>
          <ArrowLeft size={16} /> Back to challenge
        </button>
        <span className="admin-badge"><ShieldCheck size={14} /> ADMIN DASHBOARD</span>
      </div>

      <PotdFeature potd={potd} admin onManage={onPublishPotd} />

      <section className="learner-count-card" aria-label="Registered learners">
        <div>
          <p className="section-kicker">COMMUNITY</p>
          <h2>Total Registered Learners</h2>
        </div>
        <strong>{learnerCount == null ? '—' : learnerCount.toLocaleString()}</strong>
        {learnerCountError && <p className="dialog-error" role="status">{learnerCountError}</p>}
      </section>

      <div className="admin-heading-row">
        <div>
          <p className="section-kicker">CHALLENGE CONTENT</p>
          <h1 id="admin-title">Problem management</h1>
          <p>Manage problem resources and keep the practice library up to date.</p>
        </div>
        <span className="admin-total">{problems.length} published problems</span>
      </div>

      <div className="admin-toolbar">
        <label className="search-field admin-search-field">
          <Search size={16} />
          <span className="sr-only">Search admin problems</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search problems" />
        </label>
        <span className="admin-table-hint"><SlidersHorizontal size={15} /> Select an action in any row</span>
      </div>

      <ProblemTable
        problems={visibleProblems}
        admin
        onAction={onAction}
        onToggleBookmark={onToggleBookmark}
        onCycleStatus={onCycleStatus}
      />
      <p className="problem-results-count">
        Showing <strong>{visibleProblems.length}</strong> of {problems.length} problems
      </p>
    </motion.section>
  )
}

export default AdminDashboard
