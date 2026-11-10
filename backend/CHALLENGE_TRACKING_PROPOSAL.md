# MLSC challenge tracking proposal

Status: **approved design and automatic-verification extension implemented**

This proposal reflects the decisions approved for the challenge-tracking design:
the collection paths below, consecutive verified challenge-day streaks, a
fixed denominator of 100, and the admin assignment/review APIs. The approved
extension also permits automatic verification from matching recent Accepted
LeetCode submissions.

The existing application stores published questions at `problems/{slug}` with
fields including `title`, `slug`, `leetcodeUrl`, `difficulty`, and
`isPublished`. Admins do not currently assign challenge days. Learner
`Not started` / `In progress` / `Solved` state is transient React state, not a
persisted source of verified completion. No existing source of challenge
progress or streaks was found.

Challenge reads and writes will use authenticated FastAPI routes and the
existing Firebase Admin SDK identity. No Firestore security-rule changes are
proposed or permitted by this design.

## Integrity principles

- General LeetCode activity is never a challenge completion source.
- An exact matching Accepted submission for an assigned problem, dated on or
  after `assignedAt`, may verify a completion automatically.
- Only an authorized administrator can reject a pending completion or verify
  a legacy learner report.
- Recent-submission history is limited to the public endpoint's latest 20
  entries. Missing or unavailable history never rejects or invalidates a
  completion.
- A linked public username does not prove ownership of the LeetCode account.
- A learner can submit a report, but cannot provide a learner UID, problem
  reference, reviewer, review timestamp, or verification details.
- Learners cannot write Firestore completion records directly or alter a
  verified record. All access goes through authenticated FastAPI endpoints.
- A learner has at most one current completion document for each day, enforced
  by its deterministic day-number document ID.
- Each state transition and its immutable audit event are committed in one
  Firestore transaction.
- Challenge progress uses only `verified` completion records. The denominator
  is always 100, including when some days have not yet been assigned.
- The problem record is canonical for title, difficulty, LeetCode URL and
  publication state. Challenge day documents reference it and do not mutate
  the existing admin problem records.
- Firebase token UID, admin claim and server-generated timestamps are
  authoritative.

## Firestore schema

Firestore timestamps below mean native Firestore `Timestamp` values (written
with server timestamps), not ISO strings. Document IDs and UIDs are strings.
All fields are required unless marked optional.

### Challenge definition

Path: `challenges/leetcode-100-days`

| Field | Firestore type | Rule |
|---|---|---|
| `challengeId` | string | Must equal `leetcode-100-days` and the document ID. |
| `title` | string | Non-empty display title. |
| `totalDays` | integer | Must equal 100 on every write; never configurable. |
| `publicationStatus` | string | One of `draft`, `published`, `archived`. |
| `createdAt` | timestamp | Set once by the server. |
| `updatedAt` | timestamp | Server-set on every update. |
| `updatedBy` | string | Verified administrator Firebase UID. |

Example:

```json
{
  "challengeId": "leetcode-100-days",
  "title": "100 Days of LeetCode",
  "totalDays": 100,
  "publicationStatus": "published",
  "createdAt": "Firestore Timestamp",
  "updatedAt": "Firestore Timestamp",
  "updatedBy": "firebase-admin-uid"
}
```

Only the designated challenge admin API may create or update this document.
Every write validates the fixed ID, title and `totalDays == 100`. A published
challenge cannot be silently redefined by a learner request.

### Challenge day assignment

Path: `challenges/leetcode-100-days/days/{day}`

`{day}` is the canonical base-10 integer day number from 1 through 100 (for
example, `42`).

| Field | Firestore type | Rule |
|---|---|---|
| `day` | integer | Must be in 1..100 and match the document ID. |
| `problemRef` | document reference | Must point to `problems/{problemSlug}`. |
| `problemSlug` | string | Must match the referenced problem document ID and its `slug`. |
| `leetcodeUrl` | string | Copied from the canonical problem record; must be a valid HTTPS LeetCode problem URL. |
| `assignmentStatus` | string | `assigned`; a day without a document is unassigned. |
| `assignedAt` | timestamp | Server-set when first assigned. |
| `assignedBy` | string | Verified administrator Firebase UID. |
| `updatedAt` | timestamp | Server-set on each permitted update. |
| `updatedBy` | string | Verified administrator Firebase UID. |

Example:

```json
{
  "day": 42,
  "problemRef": "DocumentReference: problems/longest-consecutive-sequence",
  "problemSlug": "longest-consecutive-sequence",
  "leetcodeUrl": "https://leetcode.com/problems/longest-consecutive-sequence/",
  "assignmentStatus": "assigned",
  "assignedAt": "Firestore Timestamp",
  "assignedBy": "firebase-admin-uid",
  "updatedAt": "Firestore Timestamp",
  "updatedBy": "firebase-admin-uid"
}
```

The assignment API reads the existing problem and requires `isPublished ==
true`; it obtains the slug and URL from that document rather than trusting
client-supplied values. The effective problem `publicationStatus` is derived
from the canonical `problems/{slug}.isPublished` field at read/review time and
returned by the API. It is intentionally not duplicated in this mapping, so
unpublishing a problem cannot leave a conflicting stale status. Unpublished
questions are not returned as available challenge questions and cannot be
assigned or verified.

An unassigned day has no day document; there are no placeholder documents for
the other 99 days. Assignment does not create, rename, publish or delete a
problem. Repeating an assignment to the same problem is idempotent. Changing a
day that already has an assignment to a different problem is rejected; it
cannot rewrite learner records or audit events. Any exceptional correction
requiring historical reassignment needs a separately reviewed migration
procedure.

### Learner completion state

Path: `users/{uid}/challengeCompletions/{day}`

There is exactly one current-state document per learner/day. `{uid}` comes
only from a verified Firebase ID token; `{day}` is the canonical 1..100
decimal day number.

| Field | Firestore type | Rule |
|---|---|---|
| `day` | integer | Must match the document ID and assigned challenge day. |
| `problemRef` | document reference | Must match the day assignment and canonical problem. |
| `problemSlug` | string | Must match `problemRef` and the assignment. |
| `status` | string | One of `pending`, `verified`, `rejected`. No document means `not_started`. |
| `submittedAt` | timestamp | For a learner report, server-set report time; for automatic verification, timestamp of the matching public Accepted submission. |
| `reviewedAt` | timestamp | Server-set by an admin review; absent until reviewed. |
| `reviewerUid` | string | Verified admin UID; absent until reviewed. |
| `verifiedAt` | timestamp | Server-set automatic verification time; absent on legacy admin-reviewed records. |
| `verificationDetails` | map | Present only for verified records; admin review or automatic LeetCode evidence, schema below. |
| `createdAt` | timestamp | Server-set on the first report or automatic completion. |
| `updatedAt` | timestamp | Server-set on each state change. |

`verificationDetails` has the following exact schema when status is `verified`:

| Field | Firestore type | Rule |
|---|---|---|
| `method` | string | `admin_review` or `leetcode_recent_accepted`. |
| `note` | string | Optional administrator review note; only for `admin_review`. |
| `source` | string | Must equal `leetcode_public_graphql`; only for automatic verification. |
| `problemSlug` | string | Exact assigned LeetCode problem slug; only for automatic verification. |
| `submissionTimestamp` | timestamp | Matching Accepted submission time; only for automatic verification. |
| `submissionId` | string | Optional public submission identifier; only for automatic verification. |

Example pending record:

```json
{
  "day": 42,
  "problemRef": "DocumentReference: problems/longest-consecutive-sequence",
  "problemSlug": "longest-consecutive-sequence",
  "status": "pending",
  "submittedAt": "Firestore Timestamp",
  "createdAt": "Firestore Timestamp",
  "updatedAt": "Firestore Timestamp"
}
```

Example verified record:

```json
{
  "day": 42,
  "problemRef": "DocumentReference: problems/longest-consecutive-sequence",
  "problemSlug": "longest-consecutive-sequence",
  "status": "verified",
  "submittedAt": "Firestore Timestamp",
  "reviewedAt": "Firestore Timestamp",
  "reviewerUid": "firebase-admin-uid",
  "verificationDetails": {
    "method": "admin_review",
    "note": "Reviewed by challenge administrator"
  },
  "createdAt": "Firestore Timestamp",
  "updatedAt": "Firestore Timestamp"
}
```

Learner submission creates or changes a `rejected` record to `pending`, sets a
new server `submittedAt`, and appends an audit event. It cannot change a
`verified` record. Admin review sets `status`, `reviewedAt`, `reviewerUid`, and
`verificationDetails`; rejection sets `status`, `reviewedAt`, and
`reviewerUid`, and removes any verification details. Resubmission after
rejection does not erase the previous review history. A verified completion
cannot be downgraded or reset through the proposed endpoints. Automatic
verification uses the same deterministic completion document and appends an
event in one transaction. It records the exact assigned slug and the first
eligible submission timestamp from the recent accepted list; repeated syncs
do not create duplicate events. Unmatched, invalid, or unavailable submissions
leave completion state unchanged.

### Immutable completion events

Path: `users/{uid}/challengeCompletions/{day}/events/{eventId}`

`eventId` is generated by the server and is never reused. Events are
append-only; no endpoint updates or deletes them.

| Field | Firestore type | Rule |
|---|---|---|
| `eventType` | string | One of `reported`, `resubmitted`, `verified`, `rejected`. |
| `previousStatus` | string or null | Prior status, or null when the completion is first created. |
| `newStatus` | string | `pending`, `verified`, or `rejected`. |
| `actorUid` | string | Verified learner UID for reports, verified admin UID for reviews, or `system:leetcode` for automatic verification. |
| `timestamp` | timestamp | Server timestamp for the state transition. |
| `reviewNote` | string | Optional; allowed only on admin review events. |
| `source` | string | Optional; `leetcode_public_graphql` for automatic verification. |
| `problemSlug` | string | Optional exact assigned slug for automatic verification. |
| `submissionTimestamp` | timestamp | Optional public Accepted submission time. |
| `submissionId` | string | Optional public submission identifier. |

Example:

```json
{
  "eventType": "verified",
  "previousStatus": "pending",
  "newStatus": "verified",
  "actorUid": "firebase-admin-uid",
  "timestamp": "Firestore Timestamp",
  "reviewNote": "Reviewed by challenge administrator"
}
```

The event is stored below the completion document so the same transaction can
atomically update the current state and create its event. It records actor,
transition and time, and does not duplicate unrelated learner data.

## Data integrity and transaction boundaries

1. **Challenge initialization/update:** A transaction reads the challenge
   definition and validates `challengeId` and `totalDays == 100` before writing
   metadata. Only an authorized admin can write it. `createdAt` is immutable.
2. **Day assignment:** A transaction reads the challenge definition and
   canonical problem document, verifies the challenge is not archived and the
   problem is currently published, and reads the target mapping. It writes the
   mapping with fields copied from the canonical problem. If a mapping already
   exists for a different problem, it returns a conflict rather than changing
   the assignment; a repeated assignment to the same problem is idempotent.
   Existing problem documents are never changed.
3. **Learner report:** A transaction reads the challenge, day mapping,
   canonical problem and learner completion. It verifies authenticated UID,
   published/assigned state, and that the status is not `verified`. It writes
   the deterministic completion document and creates a fresh event document
   atomically. Client-supplied UID, problem fields, actor, status other than
   `pending`, and timestamps are rejected or ignored according to request
   validation (they are never used as authority).
4. **Admin review:** A transaction reads the challenge, mapping, canonical
   problem and completion. It checks the verified admin claim, requires a
   current `pending` status, and verifies the completion's problem reference
   still matches the assignment and is published. It atomically writes the
   `verified` or `rejected` state and an immutable event. Every accepted
   review action creates exactly one event. A repeat/stale decision returns a
   conflict instead of writing another transition.
5. **Progress calculation:** Reads only the authenticated learner's completion
   documents; counts each day at most once and counts only `verified` records
   whose day number is 1..100. The denominator remains 100. Current and longest
   streaks are runs of adjacent verified challenge day numbers, not calendar
   days or LeetCode activity. No transaction is required for this read-only
   derived summary.
6. No direct Firestore client writes or Firestore rules changes are part of
   this proposal. FastAPI verifies Firebase identity and admin authorization
   before using the Admin SDK.

## Proposed API contracts

All learner routes require a Firebase bearer ID token and derive `uid`
exclusively from its verified claims. Admin routes require the existing
`admin: true` custom claim. Errors follow the existing FastAPI `detail`
convention. These routes supplement, and do not replace, existing LeetCode
routes.

### Admin challenge setup

`POST /api/admin/challenge/initialize`

Requires a Firebase ID token with the `admin: true` custom claim. Creates the
fixed published `challenges/leetcode-100-days` definition with a total of 100
days. This operation is transactional and idempotent and does not assign
questions:

```json
{
  "challengeId": "leetcode-100-days",
  "title": "100 Days of LeetCode",
  "totalDays": 100,
  "publicationStatus": "published",
  "created": true
}
```

If a valid definition already exists, it is returned unchanged with
`"created": false`. Administrators then assign days only to published problem
records using the endpoint below.

`PUT /api/admin/challenge/days/{day}`

Request:

```json
{"problemSlug":"longest-consecutive-sequence"}
```

The service validates `day` in 1..100, reads the published problem, and
transactionally assigns it. The URL and `problemRef` are derived from the
canonical problem record. Response:

```json
{
  "day": 42,
  "assignmentStatus": "assigned",
  "publicationStatus": "published",
  "problem": {
    "slug": "longest-consecutive-sequence",
    "title": "Longest Consecutive Sequence",
    "difficulty": "Medium",
    "leetcodeUrl": "https://leetcode.com/problems/longest-consecutive-sequence/"
  }
}
```

`publicationStatus` in this response is derived from the current canonical
problem record. This adds a separate challenge-day assignment operation and
does not change the existing POTD publication workflow.

### Learner question history

`GET /api/challenge/questions`

Returns assigned, currently published days joined to canonical problem fields
and only the authenticated learner's completion. Example:

```json
{
  "challengeId": "leetcode-100-days",
  "totalDays": 100,
  "questions": [
    {
      "day": 42,
      "title": "Longest Consecutive Sequence",
      "slug": "longest-consecutive-sequence",
      "difficulty": "Medium",
      "leetcodeUrl": "https://leetcode.com/problems/longest-consecutive-sequence/",
      "assignmentStatus": "assigned",
      "publicationStatus": "published",
      "status": "verified",
      "verifiedCompletion": true,
      "submittedAt": "2026-11-10T09:00:00Z",
      "reviewedAt": "2026-11-10T10:00:00Z"
    }
  ]
}
```

For an assigned day with no completion, return `status: "not_started"` and
`verifiedCompletion: false`. Other statuses are exactly `pending`, `verified`,
and `rejected`. Unassigned or unpublished problems are not returned as
available questions. Timestamps in JSON responses are serialized as ISO 8601
UTC strings.

### Learner progress summary

`GET /api/challenge/progress`

Returns a summary derived only from verified current completion records:

```json
{
  "challengeId": "leetcode-100-days",
  "totalDays": 100,
  "completedDays": 42,
  "completionPercentage": 42,
  "remainingDays": 58,
  "currentStreak": 3,
  "longestStreak": 7,
  "recentDays": [
    {"day": 40, "status": "verified"},
    {"day": 41, "status": "verified"},
    {"day": 42, "status": "verified"}
  ]
}
```

`completionPercentage = completedDays / 100 * 100`; `remainingDays =
100 - completedDays`. Streaks are consecutive challenge day numbers with a
`verified` record, not calendar dates. If the challenge is not initialized,
the API returns `configured: false` and `null` progress values; it does not
fabricate zero progress.

### Learner completion report

`PUT /api/challenge/days/{day}/completion`

Request:

```json
{"status":"pending"}
```

The learner can submit or resubmit a report only for an assigned, published
problem. The API derives the UID, problem reference and slug, timestamp and
event actor from trusted server state. It creates a `pending` record (or
resubmits a `rejected` record). This legacy reporting endpoint remains
available, but the learner dashboard no longer relies on self-reported
completion.

### Automatic LeetCode verification

`POST /api/challenge/sync?refresh=false`

Requires an authenticated, active learner with a linked public LeetCode
username. `refresh=true` requests fresh profile and recent Accepted submission
data. Sync runs on username connection and when a learner explicitly refreshes
their profile. For every assigned day it considers only a case-insensitive
exact slug match whose submission timestamp is at or after the assignment
timestamp. The source is LeetCode's unofficial public GraphQL
`recentAcSubmissionList` query, limited to 20 entries.

The endpoint returns `status`, `verifiedDays`, `newlyVerifiedDays`, and
per-day `dayStatuses`. A missing match, an unavailable query, or a submission
outside the recent window is not evidence that the learner failed; no record
is rejected or downgraded. The public username is not proof of account
ownership, and the service does not request LeetCode credentials.

### Admin completion review

`PUT /api/admin/challenge/completions/{uid}/{day}`

Request:

```json
{"decision":"verified","reviewNote":"Reviewed by challenge administrator"}
```

or

```json
{"decision":"rejected","reviewNote":"Please resubmit after completing the assigned problem"}
```

Only an authorized admin can review a pending record. Each successful review
atomically updates the record and appends one immutable event. The API does
not accept learner-controlled verification details or timestamps. Repeated or
stale review decisions return a conflict.

### Admin pending-review queue

`GET /api/admin/challenge/completions/pending?pageSize=25&cursor={cursor}`

Requires a verified Firebase ID token with the `admin: true` custom claim.
`pageSize` is optional (default 25; allowed range 1–100). `cursor` is optional
and is returned by the prior page. Results contain only current `pending`
completion records. The query pages the `challengeCompletions` collection
group, ordered by document path; a cursor is a URL-safe base64 encoding of the
last returned completion document path. The endpoint projects only the
learner UID, optional profile display name, challenge day, canonical problem
title and URL, submission time, and current review status. It never returns
email, bookmarks, notes, LeetCode connection information, or other learner
fields.

Response:

```json
{
  "items": [
    {
      "learnerUid": "firebase-learner-uid",
      "learnerDisplayName": "Learner One",
      "day": 42,
      "problemTitle": "Longest Consecutive Sequence",
      "leetcodeUrl": "https://leetcode.com/problems/longest-consecutive-sequence/",
      "submittedAt": "2026-11-10T09:00:00Z",
      "reviewStatus": "pending"
    }
  ],
  "nextCursor": "dXNlcnMvZmlyZWJhc2UtbGVhcm5lci11aWQvY2hhbGxlbmdlQ29tcGxldGlvbnMvNDI",
  "pageSize": 25
}
```

`learnerDisplayName` is a string or `null` when the learner document has no
display name. `nextCursor` is a string when another page exists, otherwise
`null`. Each item has exactly the fields shown; learner email and unrelated
profile fields are not exposed. The completion and audit-event write
transactions are not changed by this read-only endpoint.

### Existing LeetCode APIs

The implementation provides the five LeetCode routes documented in
`LEETCODE_API_CONTRACT.md`:

- `POST /api/leetcode/connect`
- `GET /api/leetcode/profile`
- `GET /api/leetcode/heatmap`
- `GET /api/leetcode/stats`
- `DELETE /api/leetcode/connect`

LeetCode profile and submission data remain independent from challenge
completion. General activity is never used to verify an MLSC challenge day.

## Indexes and query plan

The proposed endpoints use document-key reads and bounded collection reads:

- Challenge definition and day assignments are read by document ID or by
  streaming the `days` subcollection (at most 100 documents).
- A learner's completion summary reads only that learner's
  `challengeCompletions` subcollection (at most 100 current-state documents).
- Review reads one completion by learner UID and day.
- The admin pending queue uses a collection-group query on
  `challengeCompletions`, filters `status == "pending"`, and orders by document
  path for cursor pagination. The query needs the Firestore collection-group
  single-field index on `status`; Firestore normally maintains single-field
  indexes automatically. No composite index is required. If the Firebase
  project has a single-field index exemption for this field, remove the
  exemption or enable the collection-group scope.
- Audit events are written under one completion; no event-list endpoint is
  proposed in this phase.

No composite Firestore indexes are required by these access patterns. Default
single-field indexes are sufficient; the implementation should avoid adding
compound filters/orderings. If a future admin review queue or event query needs
different access patterns, its index requirement must be documented and
approved separately before adding an index.

## Migration and rollout implications

1. No bulk migration is required. Existing `users` and `problems` documents
   remain unchanged; no additional collection paths are introduced.
2. Initialize the fixed challenge definition with `totalDays: 100`, then
   assign days only to already published problems. Unassigned days remain
   absent from the `days` subcollection but remain part of the denominator.
3. No completion backfill is possible: prior learner status is transient.
   Never infer completion from notes, bookmarks, LeetCode activity, or browser
   state.
4. Existing LeetCode username fields/claims and all unrelated learner data are
   untouched. Disconnecting a LeetCode username does not delete challenge
   records.
5. The canonical problem record remains the source of publication status,
   title, difficulty and LeetCode URL. Unpublishing a problem makes its day
   unavailable for new reports/reviews; it does not delete historical
   completion or audit documents.
6. No Firestore rules changes, client Firestore writes, backend schema
   migrations, or changes to existing admin/POTD records are proposed.
7. Rollback means disabling these API routes while retaining their data;
   deleting challenge records is not part of rollback.

## Approval record

- Collection paths and clarified field-level design: approved by user.
- Fixed `totalDays: 100`: approved by user.
- Administrator-only verification/rejection and immutable audit events:
  approved by user.
- Streaks based on consecutive verified challenge-day numbers: approved by
  user.
- Proposed admin day-assignment and completion-review APIs: approved by user.
- Implementation was explicitly approved after review and is included in
  `app/challenge_persistence.py`, `app/main.py`, and `app/schemas.py`, with
  focused API and persistence tests. No Firestore rules or deployment files
  were changed.
