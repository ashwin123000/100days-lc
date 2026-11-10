<<<<<<< HEAD
# MLSC — 100 Days of LeetCode

A responsive MLSC challenge app built with React, Vite, Tailwind CSS, Motion,
and Lucide React. Firebase Authentication and Cloud Firestore provide learner
identity and application data. FastAPI, LangChain, and the specified Hugging
Face dataset remain responsible for verified problem retrieval.

The app does not run or judge code. Learners solve locally or on LeetCode.

## Firebase project setup

The source is ready to connect to Firebase, but this workspace has no Firebase
project or Google Cloud credentials. Create the project in the Firebase
console, then:

1. Register a Firebase web app.
2. Enable **Authentication → Email/Password**.
3. Create a Cloud Firestore database.
4. Enable Firebase Storage (uploads are intentionally disabled for now).
5. Copy `.env.example` to `.env.local` and fill in the web-app config values
   using the `VITE_FIREBASE_*` `KEY=value` format shown there. Do not paste the
   JavaScript `const firebaseConfig = { ... }` snippet as the contents of the
   env file. These client settings are supplied by Firebase for web apps; never
   put a service-account key in this file.
6. Copy `backend/.env.example` to `backend/.env` and set `FIREBASE_PROJECT_ID`.
   Locally, authenticate the backend using Google Application Default
   Credentials or set `GOOGLE_APPLICATION_CREDENTIALS` to a private key file
   kept outside this repository. On Cloud Run, use the service identity instead
   of a downloaded key.
7. Install Firebase CLI if needed, select the project, and deploy rules/functions:

   ```sh
   npx firebase-tools login
   npx firebase-tools use --add
   npm --prefix functions install
   npx firebase-tools deploy --only firestore:rules,storage,functions
   ```

The signup form validates Firebase Auth's six-character password minimum. The
app adds no other password-complexity rules.

8. For an existing set of learner profiles, initialize the trusted signup
   counter once before normal registrations begin:

   ```sh
   python -m backend.app.rebuild_learner_counter
   ```

   The deployed Firestore functions maintain the counter for subsequent learner
   profile creations and deletions. The admin screen also reads an authoritative
   Firestore count through a protected FastAPI endpoint.
9. Create admin identities directly in Firebase Authentication. Never expose
   public admin registration. Assign the `admin: true` custom claim to the
   existing account using its UID:

   ```sh
   python -m backend.app.provision_admin FIREBASE_AUTH_UID
   ```

   This command uses Firebase Admin credentials from the backend environment.
   The admin must sign in again to refresh the claim.

The initial Firestore collections are:

- `users/{uid}` — learner profile (no passwords).
- `problems/{slug}` — one canonical, published dataset problem.
- `dailyPotd/active` — pointer to the current canonical problem.
- `users/{uid}/userNotes/{slug}` and `users/{uid}/bookmarks/{slug}` — private
  learner data with one document per problem.
- `stats/registeredLearners` — trusted aggregate counter.
- `resources` and `discussions` are reserved for later features.

`firestore.rules` restricts profiles and personal learning data to their owner,
published problems to authenticated users, and administrative reads/writes to
custom-claim admins. Storage rules deny access until the upload feature is
implemented. POTD file selection currently provides local previews only; no
file is uploaded or persisted.

## Local development

Install frontend dependencies and configure Firebase before using learner or
admin routes:

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

In another terminal, install the Python API dependencies, configure
`backend/.env`, and start FastAPI:

```powershell
python -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
# Set FIREBASE_PROJECT_ID to your Firebase project in backend/.env.
# With local Google ADC, leave GOOGLE_APPLICATION_CREDENTIALS unset.
gcloud auth application-default login
python -m uvicorn backend.app.main:app --reload --port 8011
```

Vite proxies `/api` to `http://127.0.0.1:8011` by default. Override
`API_PROXY_TARGET` before starting Vite if FastAPI uses another address.
FastAPI verifies Firebase ID tokens and custom admin claims for admin endpoints;
Firebase Admin service credentials are never sent to React.

The first problem lookup loads the Hugging Face dataset configured by
`HUGGINGFACE_DATASET`. LangChain semantic retrieval is only used when exact slug
and title matching do not find a verified match.

## Validation

```sh
npm run lint
npm run build
python -m pytest backend/tests -q
```

Firebase Auth, Firestore rules, Cloud Functions, and live project connectivity
must be verified after configuring and deploying a real Firebase project.
=======
# 100days-lc
>>>>>>> 1a8459c06b62df443272fce0c1a39c60e68d7e56
