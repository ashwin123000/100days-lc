import {
  ArrowUpRight,
  Bookmark,
  BookOpenText,
  Check,
  Circle,
  FileText,
  MessageCircle,
} from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'

const columns = ['Status', 'Problem ↗', 'Solution', 'Notes', 'Bookmark', 'Concept', 'Discuss']

function ProblemTable({
  problems,
  admin = false,
  onAction,
  onOpenProblem,
  onToggleBookmark,
  onCycleStatus,
  totalCount = problems.length,
  emptyTitle,
  emptyDescription,
}) {
  const shouldReduceMotion = useReducedMotion()

  return (
    <div className={`dashboard-problem-list ${admin ? 'dashboard-problem-list-admin' : ''}`} role="table" aria-label={admin ? 'Admin problem management' : 'Challenge problems'}>
      <div className="dashboard-problem-row dashboard-problem-header" role="row">
        {columns.map((column) => (
          <span role="columnheader" key={column}>{column}</span>
        ))}
      </div>

      {problems.map((problem, index) => (
        <motion.div
          className={`dashboard-problem-row ${index % 2 ? 'dashboard-problem-row-alt' : ''}`}
          role="row"
          key={problem.id}
          initial={shouldReduceMotion ? false : { opacity: 0, y: 5 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: shouldReduceMotion ? 0 : 0.18 }}
        >
          <span className="dashboard-cell status-cell" role="cell">
            <button
              className={`problem-status-pill problem-status-${problem.status.toLowerCase().replaceAll(' ', '-')}`}
              type="button"
              disabled={problem.challengeVerified}
              onClick={() => onCycleStatus(problem)}
              aria-label={problem.challengeVerified
                ? `${problem.title} is verified complete on LeetCode`
                : `Status ${problem.status} for ${problem.title}. Change status`}
              title={problem.challengeVerified ? 'Verified from the connected LeetCode account' : 'Click to change problem status'}
            >
              {problem.status === 'Solved' ? <Check size={14} /> : <Circle size={11} />}
              <span>{problem.status}</span>
            </button>
          </span>

          <span className="dashboard-cell dashboard-problem-cell" role="cell">
            <button
              className="problem-name-button"
              type="button"
              onClick={() => (admin ? onAction('details', problem) : onOpenProblem(problem))}
            >
              <span className="problem-id">#{problem.id}</span>
              <span>{problem.title}</span>
              {problem.isActivePotd && <span className="active-potd-badge">POTD</span>}
            </button>
            <a
              className="problem-external-link"
              href={problem.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open ${problem.title} on LeetCode`}
              title="Open on LeetCode"
            >
              <ArrowUpRight size={15} />
            </a>
          </span>

          <span className="dashboard-cell table-action-cell" role="cell">
            <button className="table-action-button" type="button" onClick={() => onAction('solution', problem)} aria-label={`View solution for ${problem.title}`} title="View solution">
              <BookOpenText size={17} />
            </button>
          </span>
          <span className="dashboard-cell table-action-cell" role="cell">
            <button className={`table-action-button ${problem.notes ? 'table-action-active' : ''}`} type="button" onClick={() => onAction('notes', problem)} aria-label={`${problem.notes ? 'Edit' : 'Add'} notes for ${problem.title}`} title="Add or edit notes">
              <FileText size={17} />
            </button>
          </span>
          <span className="dashboard-cell table-action-cell" role="cell">
            <button
              className={`table-action-button ${problem.bookmarked ? 'table-action-bookmarked' : ''}`}
              type="button"
              onClick={() => onToggleBookmark(problem)}
              aria-label={`${problem.bookmarked ? 'Remove' : 'Add'} ${problem.title} ${problem.bookmarked ? 'from' : 'to'} bookmarks`}
              aria-pressed={problem.bookmarked}
              title={problem.bookmarked ? 'Remove bookmark' : 'Bookmark problem'}
            >
              <Bookmark size={17} fill={problem.bookmarked ? 'currentColor' : 'none'} />
            </button>
          </span>
          <span className="dashboard-cell table-action-cell" role="cell">
            <button className="table-action-button" type="button" onClick={() => onAction('concept', problem)} aria-label={`View concept for ${problem.title}`} title="View concept">
              <BookOpenText size={17} />
            </button>
          </span>
          <span className="dashboard-cell table-action-cell" role="cell">
            <button className={`table-action-button ${problem.discussion.length ? 'table-action-active' : ''}`} type="button" onClick={() => onAction('discuss', problem)} aria-label={`Discuss ${problem.title}`} title="Open discussion">
              <MessageCircle size={17} />
              {problem.discussion.length > 0 && <span className="discussion-count">{problem.discussion.length}</span>}
            </button>
          </span>
        </motion.div>
      ))}

      {problems.length === 0 && (
        <div className="dashboard-empty-state">
          <FileText size={22} />
          <h2>{emptyTitle ?? (totalCount ? 'No problems match these filters' : 'No published problems yet')}</h2>
          <p>{emptyDescription ?? (totalCount ? 'Try changing the search or filters.' : 'Problems appear here after an admin publishes a POTD.')}</p>
        </div>
      )}
    </div>
  )
}

export default ProblemTable
