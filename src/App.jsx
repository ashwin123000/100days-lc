import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AuthProvider } from './contexts/AuthContext.jsx'
import { useAuth } from './hooks/useAuth.js'
import Navbar from './components/Navbar.jsx'
import Hero from './components/Hero.jsx'
import DsaAdventureMap from './sections/DsaAdventureMap.jsx'
import ProblemActionDialog from './components/ProblemActionDialog.jsx'
import AdminPotdDialog from './components/AdminPotdDialog.jsx'
import ChallengePlatform from './sections/ChallengePlatform.jsx'
import DailyProblem from './sections/DailyProblem.jsx'
import ProblemExplorer from './sections/ProblemExplorer.jsx'
import AdminDashboard from './sections/AdminDashboard.jsx'
import LoginPage from './sections/LoginPage.jsx'
import AuthPage from './sections/AuthPage.jsx'
import ProblemWorkspace from './sections/ProblemWorkspace.jsx'
import LeetCodeProfile from './sections/LeetCodeProfile.jsx'
import Leaderboard from './sections/Leaderboard.jsx'
import {
  saveUserNote,
  setProblemBookmarked,
  subscribeToActivePotd,
  subscribeToLearnerCounter,
  subscribeToPublishedProblems,
  subscribeToUserBookmarks,
  subscribeToUserNotes,
} from './services/firebaseData.js'
import {
  assignChallengeDay,
  fetchLearnerCount,
  initializeChallenge,
  preparePotd as preparePotdRequest,
  publishPotd as publishPotdRequest,
  withFirebaseToken,
} from './services/api.js'
import { canonicalToListProblem, canonicalToWorkspaceProblem } from './utils/problemData.js'

const routeNames = new Set(['home', 'platform', 'login', 'auth', 'admin', 'problems', 'daily', 'workspace', 'profile', 'leaderboard'])
const learnerRoutes = new Set(['platform', 'problems', 'daily', 'workspace', 'profile', 'leaderboard'])

function routeFromLocation() {
  const [name, ...parts] = window.location.hash.slice(1).split('/')
  const page = routeNames.has(name) ? name : 'home'
  return {
    page,
    problemId: page === 'workspace' ? decodeURIComponent(parts.join('/')) : null,
    topicId: page === 'problems' && parts[0] === 'topic'
      ? decodeURIComponent(parts.slice(1).join('/'))
      : null,
    authMode: page === 'auth' && parts[0] === 'admin' ? 'admin' : 'learner',
  }
}

function AppContent() {
  const auth = useAuth()
  const [route, setRoute] = useState(routeFromLocation)
  const [rawProblems, setRawProblems] = useState([])
  const [potd, setPotd] = useState(null)
  const [dataError, setDataError] = useState('')
  const [problemsLoaded, setProblemsLoaded] = useState(false)
  const [workspaceProblem, setWorkspaceProblem] = useState(null)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [workspaceError, setWorkspaceError] = useState('')
  const [workspaceSaveError, setWorkspaceSaveError] = useState('')
  const [workspaceInitialTab, setWorkspaceInitialTab] = useState('solution')
  const [workspaceDiscussion, setWorkspaceDiscussion] = useState({})
  const [bookmarkedIds, setBookmarkedIds] = useState(new Set())
  const [userNotes, setUserNotes] = useState(new Map())
  const [statuses, setStatuses] = useState({})
  const [verifiedChallengeSlugs, setVerifiedChallengeSlugs] = useState(new Set())
  const statusOwner = useRef(auth.user?.uid ?? null)
  const [learnerCount, setLearnerCount] = useState(null)
  const [learnerCountError, setLearnerCountError] = useState('')
  const [activeAction, setActiveAction] = useState(null)
  const [potdDialogProblem, setPotdDialogProblem] = useState(null)
  const [potdDialogOpen, setPotdDialogOpen] = useState(false)
  const pendingNavTarget = useRef(null)

  useEffect(() => {
    const uid = auth.user?.uid ?? null
    if (statusOwner.current === uid) return
    statusOwner.current = uid
    setStatuses({})
    setVerifiedChallengeSlugs(new Set())
  }, [auth.user?.uid])

  const navigate = useCallback((page, problemId = null, replace = false, authMode = 'learner', topicId = null) => {
    const suffix = page === 'workspace' && problemId != null
      ? `/${encodeURIComponent(problemId)}`
      : page === 'auth' && authMode === 'admin'
        ? '/admin'
        : page === 'problems' && topicId ? `/topic/${encodeURIComponent(topicId)}` : ''
    const hash = `#${page}${suffix}`
    window.history[replace ? 'replaceState' : 'pushState'](
      { ...(window.history.state ?? {}), mlscRoute: true },
      '',
      hash,
    )
    setRoute({
      page,
      problemId: page === 'workspace' ? String(problemId ?? '') : null,
      topicId: page === 'problems' ? topicId : null,
      authMode,
    })
    setActiveAction(null)
    setPotdDialogProblem(null)
    setPotdDialogOpen(false)
  }, [])

  const navigateBack = useCallback((fallback) => {
    if (window.history.state?.mlscRoute && window.history.length > 1) {
      window.history.back()
      return
    }
    navigate(fallback)
  }, [navigate])

  useEffect(() => {
    if (!window.history.state?.mlscRoute) {
      window.history.replaceState(
        { ...(window.history.state ?? {}), mlscRoute: true },
        '',
        window.location.href,
      )
    }
    const handlePopState = () => {
      setRoute(routeFromLocation())
      setActiveAction(null)
      setPotdDialogProblem(null)
      setPotdDialogOpen(false)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (auth.loading) return
    if (route.page === 'admin') {
      if (!auth.user) navigate('auth', null, true, 'admin')
      else if (!auth.isAdmin) navigate(auth.profile ? 'platform' : 'auth', null, true, 'learner')
      return
    }
    if (learnerRoutes.has(route.page) && (!auth.user || !auth.profile || auth.profile.isActive === false)) {
      navigate('auth', null, true, 'learner')
      return
    }
    if (route.page === 'auth' && auth.user && !auth.loading) {
      if (route.authMode === 'admin') {
        if (auth.isAdmin) navigate('admin', null, true)
      } else if (auth.isAdmin) {
        navigate('admin', null, true)
      } else if (auth.profile) {
        navigate('platform', null, true)
      }
    }
  }, [auth.isAdmin, auth.loading, auth.profile, auth.user, navigate, route.authMode, route.page])

  useEffect(() => {
    if (route.page === 'home' && pendingNavTarget.current) {
      const target = pendingNavTarget.current
      pendingNavTarget.current = null
      requestAnimationFrame(() => document.querySelector(target)?.scrollIntoView({ behavior: 'smooth' }))
      return
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [route.page])

  useEffect(() => {
    const uid = auth.user?.uid
    if (!uid || (!auth.profile && !auth.isAdmin)) {
      setRawProblems([])
      setPotd(null)
      setBookmarkedIds(new Set())
      setUserNotes(new Map())
      setStatuses({})
      setVerifiedChallengeSlugs(new Set())
      setWorkspaceDiscussion({})
      setProblemsLoaded(false)
      return undefined
    }

    setDataError('')
    const unsubscribePotd = subscribeToActivePotd(
      (record) => setPotd(record),
      (error) => setDataError(error.message),
    )
    const unsubscribeProblems = subscribeToPublishedProblems(
      (records) => {
        setRawProblems(records)
        setProblemsLoaded(true)
      },
      (error) => {
        setDataError(error.message)
        setProblemsLoaded(true)
      },
    )
    const unsubscribeBookmarks = subscribeToUserBookmarks(
      uid,
      setBookmarkedIds,
      (error) => setDataError(error.message),
    )
    const unsubscribeNotes = subscribeToUserNotes(
      uid,
      setUserNotes,
      (error) => setDataError(error.message),
    )
    return () => {
      unsubscribePotd()
      unsubscribeProblems()
      unsubscribeBookmarks()
      unsubscribeNotes()
    }
  }, [auth.isAdmin, auth.profile, auth.user?.uid])

  useEffect(() => {
    if (route.page !== 'admin' || !auth.user || !auth.isAdmin) {
      setLearnerCount(null)
      return undefined
    }
    let active = true
    const loadCount = async () => {
      try {
        const token = await auth.user.getIdToken()
        const count = await fetchLearnerCount(token)
        if (active) {
          setLearnerCount(count)
          setLearnerCountError('')
        }
      } catch (error) {
        if (active) setLearnerCountError(error.message)
      }
    }
    loadCount()
    const unsubscribe = subscribeToLearnerCounter((count) => {
      if (count != null && active) {
        setLearnerCount(count)
        setLearnerCountError('')
      }
    }, (error) => {
      if (active) setLearnerCountError(error.message)
    })
    return () => {
      active = false
      unsubscribe()
    }
  }, [auth.isAdmin, auth.user, route.page])

  const navigateFromNavbar = (link) => {
    if (link.action === 'start-solving') {
      navigate(auth.user ? 'platform' : 'login')
      return
    }
    if (link.page) {
      navigate(link.page)
      return
    }
    const target = link.href === '#about' ? '#about' : null
    if (route.page === 'home') {
      document.querySelector(target || '#home')?.scrollIntoView({ behavior: 'smooth' })
      return
    }
    pendingNavTarget.current = target
    navigate('home')
  }

  const problems = useMemo(() => rawProblems.map((record) => {
    const problem = canonicalToListProblem(record)
    const canonicalId = problem.canonicalId
    const challengeVerified = verifiedChallengeSlugs.has(canonicalId)
    return {
      ...problem,
      bookmarked: bookmarkedIds.has(canonicalId),
      notes: userNotes.get(canonicalId)?.content ?? '',
      challengeVerified,
      status: challengeVerified ? 'Solved' : statuses[canonicalId] ?? 'Not started',
      discussion: workspaceDiscussion[canonicalId] ?? [],
    }
  }), [bookmarkedIds, rawProblems, statuses, userNotes, verifiedChallengeSlugs, workspaceDiscussion])

  const workspaceId = (problem) => problem?.problemId ?? problem?.canonicalId ?? problem?.slug
  const openWorkspace = useCallback((problem, tab = 'solution') => {
    const id = workspaceId(problem)
    if (!id) {
      setWorkspaceError('This problem does not have a canonical published record.')
      return
    }
    setWorkspaceInitialTab(tab)
    setWorkspaceError('')
    setWorkspaceSaveError('')
    setWorkspaceLoading(false)
    setWorkspaceProblem(canonicalToWorkspaceProblem(problem))
    navigate('workspace', id)
  }, [navigate])

  const markVerifiedChallengeProblemsSolved = useCallback((questions) => {
    const verifiedSlugs = new Set(questions.map((question) => question.slug).filter(Boolean))
    if (!verifiedSlugs.size) return
    setVerifiedChallengeSlugs((current) => new Set([...current, ...verifiedSlugs]))
    setStatuses((current) => {
      const next = { ...current }
      for (const slug of verifiedSlugs) next[slug] = 'Solved'
      return next
    })
  }, [])

  const openChallengeQuestion = useCallback((question) => {
    const problem = rawProblems.find((record) =>
      (record.slug ?? record.problemId) === question.slug
      || record.problemId === question.slug,
    )
    if (problem) {
      openWorkspace(problem)
      return
    }
    if (question.leetcodeUrl) window.open(question.leetcodeUrl, '_blank', 'noopener,noreferrer')
  }, [openWorkspace, rawProblems])

  useEffect(() => {
    if (route.page !== 'workspace' || !route.problemId || !problemsLoaded) return
    const record = [potd, ...rawProblems].find(
      (problem) => String(problem?.problemId ?? problem?.slug) === route.problemId,
    )
    if (record) {
      setWorkspaceProblem(canonicalToWorkspaceProblem(record))
      setWorkspaceLoading(false)
      setWorkspaceError('')
    } else {
      setWorkspaceProblem(null)
      setWorkspaceLoading(false)
      setWorkspaceError('This problem has not been published to the MLSC practice library.')
    }
  }, [potd, problemsLoaded, rawProblems, route.page, route.problemId])

  const retryWorkspace = () => {
    const record = [potd, ...rawProblems].find(
      (problem) => String(problem?.problemId ?? problem?.slug) === route.problemId,
    )
    if (record) {
      setWorkspaceProblem(canonicalToWorkspaceProblem(record))
      setWorkspaceError('')
      return
    }
    setWorkspaceError('This problem is not currently published in the MLSC practice library.')
  }

  const toggleBookmark = async (problem) => {
    const id = workspaceId(problem)
    if (!id || !auth.user) return
    try {
      await setProblemBookmarked(auth.user.uid, id, !bookmarkedIds.has(id))
    } catch (error) {
      setDataError(error.message)
    }
  }

  const cycleStatus = (problem) => {
    const id = workspaceId(problem)
    if (!id || verifiedChallengeSlugs.has(id)) return
    const statusesForProblem = ['Not started', 'In progress', 'Solved']
    const currentStatus = statuses[id] ?? 'Not started'
    setStatuses((current) => ({
      ...current,
      [id]: statusesForProblem[(statusesForProblem.indexOf(currentStatus) + 1) % statusesForProblem.length],
    }))
  }

  const openProblemAction = (type, problem, admin = false) => {
    if (['solution', 'notes', 'concept', 'discuss'].includes(type)) {
      openWorkspace(problem, type)
      return
    }
    setActiveAction({ type, problem, admin })
  }

  const preparePotd = async (title, url) => {
    return withFirebaseToken(auth.user, (token) => preparePotdRequest(title, url, token))
  }

  const publishPotd = async ({ title, url, solution, notes, challengeDay }) => {
    const publishedProblem = await withFirebaseToken(auth.user, async (token) => {
      await initializeChallenge(token)
      return publishPotdRequest(title, url, solution, notes, token)
    })
    const problemSlug = publishedProblem?.slug ?? publishedProblem?.problemId
    if (!problemSlug) {
      throw new Error('The problem was published, but its slug was missing, so the challenge day could not be assigned.')
    }
    try {
      await withFirebaseToken(auth.user, (token) => assignChallengeDay(challengeDay, problemSlug, token))
    } catch (error) {
      throw new Error(`The problem was published, but Day ${challengeDay} could not be assigned: ${error.message}`)
    }
    return publishedProblem
  }

  const resourceKey = workspaceProblem?.canonical_id
  const activeResource = {
    notes: userNotes.get(resourceKey)?.content ?? '',
    bookmarked: bookmarkedIds.has(resourceKey),
    discussion: workspaceDiscussion[resourceKey] ?? [],
  }

  const updateWorkspaceResource = async (updates) => {
    if (!auth.user || !resourceKey) return
    setWorkspaceSaveError('')
    try {
      if (Object.hasOwn(updates, 'notes')) {
        await saveUserNote(auth.user.uid, resourceKey, updates.notes)
      }
      if (Object.hasOwn(updates, 'bookmarked')) {
        await setProblemBookmarked(auth.user.uid, resourceKey, updates.bookmarked)
      }
      if (updates.discussion) {
        setWorkspaceDiscussion((current) => ({ ...current, [resourceKey]: updates.discussion }))
      }
    } catch (error) {
      setWorkspaceSaveError(error.message)
      throw error
    }
  }

  const startLogout = async () => {
    try {
      await auth.logout()
      navigate('login')
    } catch (error) {
      setDataError(error.message)
    }
  }

  const learnerAccess = !auth.loading && Boolean(
    auth.user && auth.profile && auth.profile.isActive !== false,
  )
  const adminAccess = !auth.loading && Boolean(auth.user && auth.isAdmin)
  const requiresLearner = learnerRoutes.has(route.page)
  const accessDenied = (requiresLearner && !learnerAccess) || (route.page === 'admin' && !adminAccess)

  return (
    <div className="min-h-screen bg-midnight text-white">
      <Navbar onNavigate={navigateFromNavbar} user={auth.user} isAdmin={auth.isAdmin} onLogout={startLogout} />
      {dataError && (learnerRoutes.has(route.page) || route.page === 'admin') && (
        <div className="api-notice" role="status">{dataError}</div>
      )}
      <main>
        {accessDenied ? (
          <div className="account-check-state" role="status">Checking your account…</div>
        ) : (
          <>
            {route.page === 'home' && (
              <>
                <Hero onStartSolving={() => navigate(auth.user ? 'platform' : 'login')} />
                <DsaAdventureMap
                  user={auth.user}
                  profile={auth.profile}
                  isAdmin={auth.isAdmin}
                  authLoading={auth.loading}
                  problems={problems}
                  problemsLoaded={problemsLoaded}
                  onContinue={() => navigate(auth.user ? 'platform' : 'login')}
                  onSelectTopic={(topicId) => {
                    if (!auth.user || !auth.profile || auth.isAdmin) {
                      navigate('login')
                      return
                    }
                    navigate('problems', null, false, 'learner', topicId)
                  }}
                  onOpenLeaderboard={() => navigate(auth.user && !auth.isAdmin ? 'leaderboard' : 'login')}
                />
              </>
            )}
            {route.page === 'login' && (
          <LoginPage
            onBack={() => navigateBack('home')}
            onUserContinue={() => navigate('auth')}
            onAdminLogin={() => navigate('auth', null, false, 'admin')}
          />
        )}
            {route.page === 'auth' && (
          <AuthPage
            mode={route.authMode}
            onBack={() => navigateBack('login')}
            onAuthenticated={(isAdmin) => navigate(isAdmin ? 'admin' : 'platform')}
          />
        )}
            {route.page === 'platform' && (
          <ChallengePlatform
            onBack={() => navigateBack('home')}
            onSelectDaily={() => potd ? openWorkspace(potd) : navigate('daily')}
            onSelectRevisit={() => navigate('problems')}
          />
        )}
            {route.page === 'daily' && (
          <DailyProblem
            onBack={() => navigateBack('platform')}
            potd={potd}
            onChooseSolve={() => potd && openWorkspace(potd)}
          />
        )}
            {route.page === 'problems' && (
          <ProblemExplorer
            problems={problems}
            potd={potd}
            topicId={route.topicId}
            loading={!problemsLoaded}
            onBack={() => navigateBack('platform')}
            onOpenPotd={() => potd && openWorkspace(potd)}
            onAction={(type, problem) => openProblemAction(type, problem)}
            onOpenProblem={openWorkspace}
            onToggleBookmark={toggleBookmark}
            onCycleStatus={cycleStatus}
          />
        )}
            {route.page === 'admin' && (
          <AdminDashboard
            problems={problems}
            potd={potd}
            learnerCount={learnerCount}
            learnerCountError={learnerCountError}
            onBack={() => navigateBack('platform')}
            onPublishPotd={() => { setPotdDialogProblem(potd); setPotdDialogOpen(true) }}
            onAction={(type, problem) => openProblemAction(type, problem, true)}
            onToggleBookmark={toggleBookmark}
            onCycleStatus={cycleStatus}
          />
        )}
            {route.page === 'workspace' && (
          <ProblemWorkspace
            key={`${resourceKey || route.problemId}-${workspaceInitialTab}`}
            problem={workspaceProblem}
            loading={workspaceLoading || (!workspaceProblem && !workspaceError)}
            error={workspaceError}
            saveError={workspaceSaveError}
            resources={activeResource}
            initialTab={workspaceInitialTab}
            onResourceChange={updateWorkspaceResource}
            onBack={() => navigateBack('problems')}
            onRetry={retryWorkspace}
          />
        )}
            {route.page === 'profile' && (
          <LeetCodeProfile
            key={auth.user?.uid}
            user={auth.user}
            linkedUsername={auth.profile?.leetcodeUsername ?? ''}
            onVerifiedProblems={markVerifiedChallengeProblemsSolved}
            onOpenQuestion={openChallengeQuestion}
            onBack={() => navigateBack('platform')}
          />
        )}
            {route.page === 'leaderboard' && (
          <Leaderboard
            user={auth.user}
            onBack={() => navigateBack('platform')}
          />
        )}
          </>
        )}
      </main>
      <ProblemActionDialog
        key={`${activeAction?.type ?? 'closed'}-${activeAction?.problem?.id ?? 'global'}`}
        action={activeAction}
        problem={activeAction?.problem}
        potd={potd}
        onClose={() => setActiveAction(null)}
      />
      {potdDialogOpen && (
        <AdminPotdDialog
          key={potdDialogProblem?.problemId ?? 'new-potd'}
          potd={potdDialogProblem}
          onPrepare={preparePotd}
          onPublish={publishPotd}
          onClose={() => {
            setPotdDialogOpen(false)
            setPotdDialogProblem(null)
          }}
        />
      )}
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}

export default App
