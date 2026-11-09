import {
  collection,
  doc,
  getDoc,
  onSnapshot,
  query,
  runTransaction,
  serverTimestamp,
  where,
} from 'firebase/firestore'
import { requireFirebase } from '../firebase.js'

export function subscribeToActivePotd(onValue, onError) {
  const { db } = requireFirebase()
  let generation = 0
  return onSnapshot(doc(db, 'dailyPotd', 'active'), async (snapshot) => {
    const currentGeneration = ++generation
    if (!snapshot.exists() || snapshot.data().isActive !== true) {
      onValue(null)
      return
    }
    const pointer = snapshot.data()
    try {
      const problemSnapshot = await getDoc(doc(db, 'problems', pointer.problemId))
      if (currentGeneration === generation) {
        onValue(problemSnapshot.exists() ? { ...problemSnapshot.data(), potd: pointer } : null)
      }
    } catch (error) {
      if (currentGeneration === generation) onError(error)
    }
  }, onError)
}

export function subscribeToPublishedProblems(onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(
    query(collection(db, 'problems'), where('isPublished', '==', true)),
    (snapshot) => onValue(snapshot.docs.map((item) => item.data())),
    onError,
  )
}

export function subscribeToProblem(problemId, onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(doc(db, 'problems', problemId), (snapshot) => {
    onValue(snapshot.exists() ? snapshot.data() : null)
  }, onError)
}

export function subscribeToUserNote(uid, problemId, onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(doc(db, 'users', uid, 'userNotes', problemId), (snapshot) => {
    onValue(snapshot.exists() ? snapshot.data() : null)
  }, onError)
}

export async function saveUserNote(uid, problemId, content) {
  const { db } = requireFirebase()
  const reference = doc(db, 'users', uid, 'userNotes', problemId)
  await runTransaction(db, async (transaction) => {
    const existing = await transaction.get(reference)
    const note = {
      userId: uid,
      problemId,
      content,
      updatedAt: serverTimestamp(),
    }
    if (!existing.exists()) note.createdAt = serverTimestamp()
    transaction.set(reference, note, { merge: true })
  })
}

export function subscribeToBookmark(uid, problemId, onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(doc(db, 'users', uid, 'bookmarks', problemId), (snapshot) => {
    onValue(snapshot.exists())
  }, onError)
}

export function subscribeToUserBookmarks(uid, onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(
    collection(db, 'users', uid, 'bookmarks'),
    (snapshot) => onValue(new Set(snapshot.docs.map((item) => item.data().problemId))),
    onError,
  )
}

export function subscribeToUserNotes(uid, onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(
    collection(db, 'users', uid, 'userNotes'),
    (snapshot) => onValue(new Map(snapshot.docs.map((item) => [item.data().problemId, item.data()]))),
    onError,
  )
}

export async function setProblemBookmarked(uid, problemId, bookmarked) {
  const { db } = requireFirebase()
  const reference = doc(db, 'users', uid, 'bookmarks', problemId)
  await runTransaction(db, async (transaction) => {
    const current = await transaction.get(reference)
    if (bookmarked && !current.exists()) {
      transaction.set(reference, { userId: uid, problemId, createdAt: serverTimestamp() })
    } else if (!bookmarked && current.exists()) {
      transaction.delete(reference)
    }
  })
}

export function subscribeToLearnerCounter(onValue, onError) {
  const { db } = requireFirebase()
  return onSnapshot(doc(db, 'stats', 'registeredLearners'), (snapshot) => {
    onValue(snapshot.exists() ? Number(snapshot.data().count ?? 0) : null)
  }, onError)
}
