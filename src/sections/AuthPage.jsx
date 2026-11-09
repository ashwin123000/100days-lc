import { useState } from 'react'
import { ArrowLeft, ArrowRight, LoaderCircle, ShieldCheck, UserRound } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useAuth } from '../hooks/useAuth.js'
import { getAuthErrorMessage } from '../utils/authErrors.js'

function AuthPage({ mode = 'learner', onBack, onAuthenticated }) {
  const { configured, profileError, retryProfileCreation, registerLearner, login, logout } = useAuth()
  const [screen, setScreen] = useState(mode === 'admin' ? 'login' : 'register')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [profileRecovery, setProfileRecovery] = useState(false)
  const shouldReduceMotion = useReducedMotion()
  const isAdminLogin = mode === 'admin'

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    const cleanEmail = email.trim()
    if (screen === 'register') {
      if (!fullName.trim()) return setError('Enter your full name.')
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) return setError('Enter a valid email address.')
      if (password.length < 6) return setError('Password must contain at least six characters.')
      if (password !== confirmPassword) return setError('The passwords do not match.')
    } else if (!cleanEmail || !password) {
      return setError('Enter your email and password.')
    }

    setBusy(true)
    try {
      if (screen === 'register') {
        await registerLearner(fullName.trim(), cleanEmail, password)
        onAuthenticated(false)
      } else {
        const result = await login(cleanEmail, password)
        if (isAdminLogin && !result.isAdmin) {
          await logout()
          throw new Error('This account is not authorized to access the admin dashboard.')
        }
        if (result.profileIncomplete) {
          setProfileRecovery(true)
          setFullName(result.user.displayName ?? '')
          return
        }
        onAuthenticated(result.isAdmin)
      }
    } catch (authError) {
      if (authError?.code === 'profile/incomplete') {
        setProfileRecovery(true)
      }
      setError(getAuthErrorMessage(authError))
    } finally {
      setBusy(false)
    }
  }

  const retryProfile = async () => {
    setBusy(true)
    setError('')
    try {
      await retryProfileCreation(fullName.trim())
      onAuthenticated(false)
    } catch (retryError) {
      setError(getAuthErrorMessage(retryError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.section
      className="login-page page-shell"
      aria-labelledby="auth-title"
      initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.3 }}
    >
      <button className="back-link" type="button" onClick={onBack}>
        <ArrowLeft size={16} /> Back to challenge
      </button>
      <div className="login-card">
        <div className="login-card-mark">{isAdminLogin ? <ShieldCheck size={23} /> : <UserRound size={23} />}</div>
        <p className="section-kicker">{isAdminLogin ? 'MLSC ADMIN' : 'MLSC CHALLENGE'}</p>
        <h1 id="auth-title">{isAdminLogin ? 'Admin sign in.' : screen === 'register' ? 'Create your account.' : 'Welcome back.'}</h1>
        <p className="login-description">
          {isAdminLogin ? 'Use an authorized organizer account to manage the challenge.' : 'Your account keeps your learning resources and progress in sync.'}
        </p>

        {screen === 'register' && !isAdminLogin && !profileRecovery && (
          <p className="auth-mode-toggle">
            Already have an account?
            <button type="button" className="text-button" onClick={() => { setError(''); setScreen('login') }}>
              Log in
            </button>
          </p>
        )}

        {!configured && (
          <p className="auth-setup-notice" role="alert">
            Firebase is not configured. Copy the project web-app settings into <code>.env.local</code>, then restart Vite.
          </p>
        )}
        {profileError && (
          <div className="auth-error" role="alert">
            <p>{profileError}</p>
          </div>
        )}

        {profileRecovery ? (
          <form className="dialog-form auth-form" onSubmit={(event) => { event.preventDefault(); retryProfile() }}>
            <label>
              Full name
              <input autoComplete="name" value={fullName} onChange={(event) => setFullName(event.target.value)} />
            </label>
            {error && <p className="dialog-error" role="alert">{error}</p>}
            <button className="primary-button dialog-submit" type="submit" disabled={!configured || busy || !fullName.trim()}>
              {busy ? 'Retrying…' : 'Retry profile setup'}
            </button>
          </form>
        ) : (
          <form className="dialog-form auth-form" onSubmit={submit}>
            {screen === 'register' && (
              <label>
                Full name
                <input autoComplete="name" value={fullName} onChange={(event) => setFullName(event.target.value)} />
              </label>
            )}
            <label>
              Email
              <input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} />
            </label>
            <label>
              Password
              <input type="password" autoComplete={screen === 'register' ? 'new-password' : 'current-password'} value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            {screen === 'register' && (
              <label>
                Confirm password
                <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
              </label>
            )}
            {error && <p className="dialog-error" role="alert">{error}</p>}
            <button className="primary-button dialog-submit" type="submit" disabled={!configured || busy}>
              {busy ? <><LoaderCircle className="spin" size={16} /> Working…</> : screen === 'register' ? 'Create learner account' : 'Log in'}
              {!busy && <ArrowRight size={17} />}
            </button>
          </form>
        )}

        {!isAdminLogin && !profileRecovery && (
          <p className="auth-mode-toggle">
            {screen === 'register' ? 'Already registered?' : 'New to the challenge?'}
            <button type="button" className="text-button" onClick={() => { setError(''); setScreen(screen === 'register' ? 'login' : 'register') }}>
              {screen === 'register' ? 'Log in' : 'Create an account'}
            </button>
          </p>
        )}
        {isAdminLogin && <p className="admin-login-note">Admin accounts are provisioned by an authorized project administrator.</p>}
      </div>
    </motion.section>
  )
}

export default AuthPage
