import { ArrowLeft, ArrowRight, Clock3, Sparkles } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'

function DailyProblem({ onBack, potd, onChooseSolve }) {
  const shouldReduceMotion = useReducedMotion()

  return (
    <motion.section
      className="daily-page page-shell"
      aria-labelledby="daily-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <button className="back-link" type="button" onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" />
        All challenge paths
      </button>

      <div className="daily-problem-panel">
        <div className="daily-problem-heading">
          <div className="daily-problem-icon">
            <Sparkles size={21} aria-hidden="true" />
          </div>
          <div>
            <p className="section-kicker">TODAY&apos;S FEATURED PROBLEM</p>
            <h1 id="daily-title">{potd?.title ?? "Today's Problem of the Day"}</h1>
          </div>
        </div>

        {potd ? (
          <>
            <div className="daily-problem-meta">
              <span className="difficulty-easy"><Clock3 size={15} aria-hidden="true" /> Featured today</span>
              <span>Published by the MLSC challenge team</span>
            </div>
            <p className="daily-problem-description">
              Your community&apos;s featured problem is ready. Choose where you&apos;d like to work
              through it and keep building your daily problem-solving habit.
            </p>
            <button className="primary-button daily-external-link" type="button" onClick={onChooseSolve}>
              Choose how to solve
              <ArrowRight size={18} aria-hidden="true" />
            </button>
          </>
        ) : (
          <div className="daily-empty-state">
            <p className="daily-problem-description">
              No problem has been published for today yet. Check back after the challenge team
              shares the next POTD.
            </p>
            <button className="secondary-button" type="button" onClick={onBack}>Return to challenge paths</button>
          </div>
        )}
      </div>
    </motion.section>
  )
}

export default DailyProblem
