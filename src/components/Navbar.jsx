import { useState } from 'react'
import { Menu, X } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import logo from '../assets/mlsc-logo-transparent.png'

const links = [
  { label: 'Home', href: '#home' },
  { label: 'PROBLEMS', action: 'start-solving' },
  { label: 'About', href: '#about' },
  { label: 'Leaderboard', comingSoon: true },
  { label: 'Profile', comingSoon: true },
  { label: 'Sign Up / Login', page: 'login' },
]

function NavigationItem({ link, onClick, mobile = false }) {
  const className = mobile ? 'mobile-nav-link' : 'nav-link'

  if (link.action === 'logout') {
    return <button className={`${className} nav-logout-button`} type="button" onClick={onClick}>{link.label}</button>
  }

  if (link.comingSoon) {
    return (
      <span
        className={`${className} nav-link-disabled`}
        role="link"
        aria-disabled="true"
        aria-label={`${link.label}, coming soon`}
        title="Available in a later challenge release"
      >
        {link.label}
      </span>
    )
  }

  return (
    <a
      className={className}
      href={link.href ?? `#${link.page}`}
      onClick={(event) => {
        event.preventDefault()
        onClick?.(link)
      }}
    >
      {link.label}
    </a>
  )
}

function Navbar({ onNavigate, user, isAdmin, onLogout }) {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const shouldReduceMotion = useReducedMotion()
  const availableLinks = user && !isAdmin
    ? links.map((link) => link.label === 'Profile'
      ? { ...link, comingSoon: false, page: 'profile' }
      : link.label === 'Leaderboard'
        ? { ...link, comingSoon: false, page: 'leaderboard' }
        : link)
    : links
  const visibleLinks = user
    ? [
      ...availableLinks.filter((link) => (
        link.page !== 'login'
        && !(isAdmin && (link.comingSoon || link.action === 'start-solving'))
      )),
      ...(isAdmin ? [
        { label: 'Admin Dashboard', page: 'admin' },
        { label: 'Error Logs', page: 'error-logs' },
      ] : []),
      { label: 'Log out', action: 'logout' },
    ]
    : availableLinks

  const handleNavigate = (link) => {
    setIsMenuOpen(false)
    onNavigate?.(link)
  }
  const handleLogout = () => {
    setIsMenuOpen(false)
    onLogout?.()
  }

  return (
    <header className="site-header">
      <nav className="nav-shell" aria-label="Main navigation">
        <a
          className="brand"
          href="#home"
          onClick={(event) => {
            event.preventDefault()
            handleNavigate({ href: '#home' })
          }}
        >
          <img className="brand-logo" src={logo} alt="Microsoft Learn Student Ambassador badge" />
          <span className="brand-name">
            <span>Microsoft Learn</span>
            <span>Students&apos; Club</span>
          </span>
        </a>

        <div className="desktop-nav">
          {visibleLinks.map((link) => (
            <NavigationItem
              link={link}
              key={link.label}
              onClick={link.action === 'logout' ? handleLogout : handleNavigate}
            />
          ))}
        </div>

        <button
          className="menu-toggle"
          type="button"
          aria-label={isMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
          aria-expanded={isMenuOpen}
          onClick={() => setIsMenuOpen((open) => !open)}
        >
          {isMenuOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
      </nav>

      <AnimatePresence>
        {isMenuOpen && (
          <motion.div
            id="mobile-navigation"
            className="mobile-nav"
            initial={shouldReduceMotion ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.2 }}
          >
            {visibleLinks.map((link) => (
              <NavigationItem
                link={link}
                key={link.label}
                mobile
                onClick={link.action === 'logout' ? handleLogout : handleNavigate}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  )
}

export default Navbar
