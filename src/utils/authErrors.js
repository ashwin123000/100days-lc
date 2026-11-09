const authErrorMessages = {
  'auth/email-already-in-use': 'An account already exists for this email. Log in instead.',
  'auth/email-already-exists': 'An account already exists for this email. Log in instead.',
  'auth/invalid-email': 'Enter a valid email address.',
  'auth/invalid-credential': 'The email or password is incorrect.',
  'auth/wrong-password': 'The email or password is incorrect.',
  'auth/user-not-found': 'The email or password is incorrect.',
  'auth/user-disabled': 'This account has been disabled. Contact the challenge organizers.',
  'auth/too-many-requests': 'Too many attempts. Wait a little and try again.',
  'auth/network-request-failed': 'Network error. Check your connection and try again.',
  'auth/weak-password': 'Firebase email/password accounts require at least six characters.',
}

export function getAuthErrorMessage(error) {
  return authErrorMessages[error?.code] ?? error?.message ?? 'Authentication failed. Please try again.'
}
