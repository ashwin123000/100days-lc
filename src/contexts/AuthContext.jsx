import { useEffect, useMemo, useState } from 'react'
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
  updateProfile,
} from 'firebase/auth'
import { doc, getDoc, serverTimestamp, setDoc } from 'firebase/firestore'
import { firebaseAuth, firestore, firebaseConfigured, requireFirebase } from '../firebase.js'
import { AuthContext } from './authContext.js'

async function createLearnerProfile(user, fullName) {
  const { db } = requireFirebase()
  await updateProfile(user, { displayName: fullName })
  const reference = doc(db, 'users', user.uid)
  const existing = await getDoc(reference)
  const profile = {
    uid: user.uid,
    fullName,
    email: user.email,
    role: 'learner',
    updatedAt: serverTimestamp(),
    isActive: true,
  }
  if (!existing.exists()) profile.createdAt = serverTimestamp()
  await setDoc(reference, profile, { merge: true })
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [profile, setProfile] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(firebaseConfigured)
  const [profileError, setProfileError] = useState('')

  useEffect(() => {
    if (!firebaseConfigured || !firebaseAuth || !firestore) return undefined

    let activeChange = 0
    const unsubscribe = onAuthStateChanged(firebaseAuth, async (nextUser) => {
      const currentChange = ++activeChange
      setLoading(true)
      setUser(nextUser)
      setProfile(null)
      setIsAdmin(false)
      setProfileError('')
      if (!nextUser) {
        setLoading(false)
        return
      }

      try {
        const [profileSnapshot, tokenResult] = await Promise.all([
          getDoc(doc(firestore, 'users', nextUser.uid)),
          nextUser.getIdTokenResult(),
        ])
        if (currentChange !== activeChange) return
        setProfile(profileSnapshot.exists() ? profileSnapshot.data() : null)
        setIsAdmin(tokenResult.claims.admin === true)
      } catch (error) {
        if (currentChange === activeChange) setProfileError(error.message)
      } finally {
        if (currentChange === activeChange) setLoading(false)
      }
    })
    return () => {
      activeChange += 1
      unsubscribe()
    }
  }, [])

  const value = useMemo(() => ({
    user,
    profile,
    isAdmin,
    loading,
    profileError,
    configured: firebaseConfigured,
    async registerLearner(fullName, email, password) {
      const { auth } = requireFirebase()
      const credential = await createUserWithEmailAndPassword(auth, email, password)
      try {
        await createLearnerProfile(credential.user, fullName)
        setProfile({
          uid: credential.user.uid,
          fullName,
          email: credential.user.email,
          role: 'learner',
          isActive: true,
        })
        setProfileError('')
      } catch (error) {
        const recoveryError = new Error(
          `Your account was created, but the learner profile could not be saved: ${error.message}`,
        )
        recoveryError.code = 'profile/incomplete'
        setProfileError(recoveryError.message)
        throw recoveryError
      }
      return credential.user
    },
    async retryProfileCreation(fullName) {
      if (!user) throw new Error('Log in again before retrying profile creation.')
      await createLearnerProfile(user, fullName || user.displayName || '')
      const snapshot = await getDoc(doc(firestore, 'users', user.uid))
      setProfile(snapshot.data())
      setProfileError('')
    },
    async login(email, password) {
      const { auth } = requireFirebase()
      const credential = await signInWithEmailAndPassword(auth, email, password)
      const tokenResult = await credential.user.getIdTokenResult(true)
      const admin = tokenResult.claims.admin === true
      const profileSnapshot = await getDoc(doc(firestore, 'users', credential.user.uid))
      const currentProfile = profileSnapshot.exists() ? profileSnapshot.data() : null
      if (!admin && !currentProfile) {
        setUser(credential.user)
        setProfile(null)
        setProfileError('Your account does not have a learner profile yet. Complete the profile setup to continue.')
        return { user: credential.user, isAdmin: false, profileIncomplete: true }
      }
      if (!admin && (currentProfile.role !== 'learner' || currentProfile.isActive === false)) {
        await signOut(auth)
        throw new Error('This account does not have an active learner profile.')
      }
      setUser(credential.user)
      setProfile(currentProfile)
      setIsAdmin(admin)
      return { user: credential.user, isAdmin: admin }
    },
    async logout() {
      const { auth } = requireFirebase()
      await signOut(auth)
    },
  }), [isAdmin, loading, profile, profileError, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
