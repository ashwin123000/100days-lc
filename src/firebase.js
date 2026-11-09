import { getApp, getApps, initializeApp } from 'firebase/app'
import { getAuth } from 'firebase/auth'
import { getFirestore } from 'firebase/firestore'
import { getStorage } from 'firebase/storage'

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

export const firebaseConfigured = Object.values(config).every(Boolean)
export const firebaseApp = firebaseConfigured
  ? getApps().length ? getApp() : initializeApp(config)
  : null
export const firebaseAuth = firebaseApp ? getAuth(firebaseApp) : null
export const firestore = firebaseApp ? getFirestore(firebaseApp) : null
export const firebaseStorage = firebaseApp ? getStorage(firebaseApp) : null

export function requireFirebase() {
  if (!firebaseApp || !firebaseAuth || !firestore || !firebaseStorage) {
    throw new Error('Firebase is not configured. Add the VITE_FIREBASE_* values from your Firebase web app to .env.local and restart Vite.')
  }
  return { auth: firebaseAuth, db: firestore, storage: firebaseStorage }
}
