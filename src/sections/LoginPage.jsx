import { ArrowLeft, ArrowRight, ShieldCheck, UserRound } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'

function LoginPage({ onBack, onUserContinue, onAdminLogin }) {
  const shouldReduceMotion = useReducedMotion()

  return (
    <motion.section
      className="login-page page-shell"
      aria-labelledby="login-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <button className="back-link" type="button" onClick={onBack}>
        <ArrowLeft size={16} /> Back to challenge
      </button>

      <div className="login-card">
        <div className="login-card-mark"><UserRound size={23} /></div>
        <p className="section-kicker">MLSC CHALLENGE</p>
        <h1 id="login-title">Welcome back.</h1>
        <p className="login-description">Choose how you&apos;d like to continue exploring the challenge.</p>

        <button className="primary-button user-login-button" type="button" onClick={onUserContinue}>
          Continue as a learner
          <ArrowRight size={17} />
        </button>

        <div className="admin-login-divider"><span>For challenge organizers</span></div>
        <button className="admin-login-button" type="button" onClick={onAdminLogin}>
          <ShieldCheck size={16} />
          Log in as Admin
        </button>
        <p className="admin-login-note">Authorized organizer account required.</p>
      </div>
    </motion.section>
  )
}

export default LoginPage
