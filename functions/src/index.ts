import { initializeApp } from 'firebase-admin/app'
import { FieldValue, getFirestore } from 'firebase-admin/firestore'
import { onDocumentCreated, onDocumentDeleted } from 'firebase-functions/v2/firestore'

initializeApp()

const db = getFirestore()

async function changeLearnerCount(eventId: string, delta: number): Promise<void> {
  const eventRef = db.doc(`_functionEvents/${eventId}`)
  const counterRef = db.doc('stats/registeredLearners')
  await db.runTransaction(async (transaction) => {
    const event = await transaction.get(eventRef)
    if (event.exists) return
    transaction.create(eventRef, { processedAt: FieldValue.serverTimestamp() })
    transaction.set(counterRef, {
      count: FieldValue.increment(delta),
      updatedAt: FieldValue.serverTimestamp(),
    }, { merge: true })
  })
}

export const countNewLearner = onDocumentCreated('users/{userId}', async (event) => {
  if (event.data?.data().role !== 'learner') return
  await changeLearnerCount(event.id, 1)
})

export const countRemovedLearner = onDocumentDeleted('users/{userId}', async (event) => {
  if (event.data?.data().role !== 'learner') return
  await changeLearnerCount(event.id, -1)
})
