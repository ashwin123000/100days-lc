import { ArrowLeft, ArrowRight, BookOpenCheck, CalendarCheck2, Code2, Flame, Layers3 } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'

function ChallengePlatform({ onBack, onSelectDaily, onSelectRevisit }) {
  const shouldReduceMotion = useReducedMotion()
  const cardMotion = shouldReduceMotion
    ? {}
    : {
        initial: { opacity: 0, y: 16 },
        animate: { opacity: 1, y: 0 },
        whileHover: { y: -4 },
        transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] },
      }

  return (
    <motion.section
      className="challenge-page page-shell"
      aria-labelledby="challenge-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <button className="back-link" type="button" onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" />
        Back to home
      </button>

      <div className="page-heading">
        <p className="section-kicker">100 DAYS OF LEETCODE</p>
        <h1 id="challenge-title">Your next problem starts here.</h1>
        <p>One thoughtful solve at a time. Choose how you want to practice today.</p>
      </div>

      <div className="platform-grid">
        <motion.article
          className="platform-card platform-card-daily"
          role="link"
          tabIndex={0}
          onClick={onSelectDaily}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onSelectDaily()
            }
          }}
          {...cardMotion}
        >
          <div className="platform-art daily-art" aria-hidden="true">
            <div className="daily-art-orbit daily-art-orbit-outer" />
            <div className="daily-art-orbit daily-art-orbit-inner" />
            <div className="daily-art-icon">
              <CalendarCheck2 size={37} strokeWidth={1.5} />
            </div>
            <span className="daily-art-tile daily-art-tile-one">
              <Code2 size={16} />
            </span>
            <span className="daily-art-tile daily-art-tile-two">
              <Flame size={16} />
            </span>
            <span className="art-caption">TODAY'S CHALLENGE</span>
          </div>
          <div className="platform-card-copy">
            <div className="platform-card-label">
              <span className="status-dot" />
              DAILY PRACTICE
            </div>
            <h2>Solve Today&apos;s POTD</h2>
            <p>Take on today&apos;s featured problem and maintain your daily streak.</p>
            <span className="platform-action">
              Open today&apos;s problem
              <ArrowRight size={17} aria-hidden="true" />
            </span>
          </div>
        </motion.article>

        <motion.article
          className="platform-card platform-card-revisit"
          role="link"
          tabIndex={0}
          onClick={onSelectRevisit}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onSelectRevisit()
            }
          }}
          {...cardMotion}
        >
          <div className="platform-art revisit-art" aria-hidden="true">
            <div className="list-window">
              <div className="list-window-header">
                <span />
                <span />
                <span />
                <span className="list-window-title">PROBLEM SET</span>
              </div>
              <div className="list-window-row">
                <span className="list-number">01</span>
                <span className="list-line list-line-long" />
                <span className="list-level easy-level" />
              </div>
              <div className="list-window-row">
                <span className="list-number">02</span>
                <span className="list-line list-line-medium" />
                <span className="list-level medium-level" />
              </div>
              <div className="list-window-row">
                <span className="list-number">03</span>
                <span className="list-line list-line-short" />
                <span className="list-level hard-level" />
              </div>
            </div>
            <div className="revisit-art-badge">
              <Layers3 size={18} />
            </div>
          </div>
          <div className="platform-card-copy">
            <div className="platform-card-label">
              <span className="status-dot status-dot-muted" />
              YOUR PRACTICE LIBRARY
            </div>
            <h2>Revisit Problems</h2>
            <p>Explore previously uploaded problems, practise again and strengthen your fundamentals.</p>
            <span className="platform-action">
              Browse all problems
              <ArrowRight size={17} aria-hidden="true" />
            </span>
          </div>
        </motion.article>
      </div>
      <p className="platform-footnote">
        <BookOpenCheck size={15} aria-hidden="true" />
        Built for steady progress, shared learning, and a stronger problem-solving habit.
      </p>
    </motion.section>
  )
}

export default ChallengePlatform
