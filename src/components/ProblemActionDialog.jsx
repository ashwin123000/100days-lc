import { useEffect } from 'react'
import { ArrowUpRight, X } from 'lucide-react'

function ProblemActionDialog({ action, problem, onClose }) {
  useEffect(() => {
    if (!action) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [action, onClose])

  if (!action || !problem) return null

  const topicNames = (problem.topics ?? [])
    .map((topic) => typeof topic === 'string' ? topic : topic?.name)
    .filter(Boolean)

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section className="action-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <div className="dialog-top">
          <div className="dialog-title-wrap">
            <p className="section-kicker">PUBLISHED PROBLEM</p>
            <h2 id="dialog-title">{problem.title}</h2>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Close dialog"><X size={19} /></button>
        </div>
        <p className="dialog-body">
          {problem.difficulty}
          {topicNames.length > 0 ? ` · ${topicNames.join(', ')}` : ''}
          {problem.acceptance != null ? ` · ${problem.acceptance}% acceptance` : ''}
        </p>
        {problem.url && (
          <a className="primary-button dialog-action-button" href={problem.url} target="_blank" rel="noopener noreferrer">
            Open on LeetCode <ArrowUpRight size={17} />
          </a>
        )}
      </section>
    </div>
  )
}

export default ProblemActionDialog
