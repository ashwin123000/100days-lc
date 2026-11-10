# LeetCode API contract

This approved contract is implemented by the backend. All routes use the
existing Firebase bearer-token authentication. The learner UID is always
derived from the verified token, never from request data.

## Routes

The public profile and problem statistics are cached in process memory for 15
minutes; each username/year submission calendar is cached for 6 hours.
Concurrent cache misses for the same key share one upstream request. Cache
entries are bounded, are lost on process restart, and are not shared across
multiple backend instances. Authenticated learners are limited to 60 LeetCode
API requests per minute per backend instance. `refresh=true` bypasses an older
cache entry but concurrent requests for the same key share one in-flight fetch.

### `POST /api/admin/challenge/initialize`

Requires a Firebase ID token with the `admin: true` custom claim. Creates the
fixed published `challenges/leetcode-100-days` definition with a total of 100
days, without assigning or changing any questions. The operation is
transactional and idempotent: if a valid definition already exists, it is
returned unchanged with `"created": false`.

```json
{
  "challengeId": "leetcode-100-days",
  "title": "100 Days of LeetCode",
  "totalDays": 100,
  "publicationStatus": "published",
  "created": true
}
```

An administrator assigns each day separately through the existing
`PUT /api/admin/challenge/days/{day}` endpoint. No question assignments are
invented during initialization.

### `POST /api/leetcode/connect?refresh=false`

Request:

```json
{"username":"iamashwin_1"}
```

`refresh=true` bypasses the cached upstream profile/calendar-independent data
for this username and is subject to the same per-user request limit.

Validates and stores the public username, then attempts automatic challenge
verification using recent Accepted submissions. It returns the connected
profile, normalized problem statistics, assigned MLSC challenge records, and a
`challengeSync` result:

```json
{
  "profile": {
    "username": "iamashwin_1",
    "avatarUrl": null,
    "displayName": null,
    "profileUrl": "https://leetcode.com/u/iamashwin_1/",
    "ranking": null,
    "reputation": null,
    "countryName": null,
    "countryCode": null
  },
  "problemStatistics": {
    "totalSolved": null,
    "easy": {"solved": null, "total": null},
    "medium": {"solved": null, "total": null},
    "hard": {"solved": null, "total": null},
    "contestRating": null,
    "ranking": null,
    "totalSubmissions": null,
    "acceptedSubmissions": null
  },
  "contestStatistics": {
    "rating": null,
    "globalRanking": null,
    "attendedContestsCount": null,
    "topPercentage": null
  },
  "challengeRecords": [],
  "challengeSync": {
    "status": "synchronized",
    "verifiedDays": [],
    "newlyVerifiedDays": [],
    "dayStatuses": {}
  }
}
```

The actual response also contains `unavailableFields`. Each assigned challenge
record includes its `challengeDay`, `title`, `slug`, `leetcodeUrl`,
`difficulty`, `publicationStatus`, `source`, `completionStatus`,
`verificationStatus`, and `verifiedCompletion`. A connection remains valid if
challenge verification is unavailable; the sync status explains that
verification could not be completed.

Numeric values are `null` when the public upstream does not reliably supply
them; `0` means the upstream confirmed zero.

### `GET /api/leetcode/profile?refresh=false`

Returns the connected learner's profile and problem statistics using the same
`profile`, `problemStatistics`, and `contestStatistics` objects as `connect`.
`profile.ranking` is the public problem-solving rank; contest global rank is
reported separately as `contestStatistics.globalRanking`. With `refresh=true`, it
fetches fresh public data and automatically synchronizes challenge
completions. An unconnected learner receives HTTP 404 with a stable error body.

### `POST /api/challenge/sync?refresh=false`

Requires an authenticated, active learner with a linked LeetCode username.
`refresh=true` requests fresh profile and recent Accepted submission data.
Returns:

```json
{
  "status": "synchronized",
  "verifiedDays": [1],
  "newlyVerifiedDays": [1],
  "dayStatuses": {"1": "verified", "2": "unable_to_verify"}
}
```

`status` may be `synchronized`, `unable_to_verify`, or `awaiting_sync` when no
username is linked. Day statuses may be `verified`, `unable_to_verify`, or
`awaiting_sync`. Missing or out-of-window submissions do not reject a
completion.

### `GET /api/leetcode/heatmap?from=YYYY-MM-DD&to=YYYY-MM-DD&refresh=false`

Returns:

```json
{
  "username": "iamashwin_1",
  "calendar": [
    {"date": "2026-11-10", "submissions": 5, "accepted": null}
  ],
  "availableFrom": "2025-11-10",
  "availableTo": "2026-11-10",
  "availableYears": [2024, 2025, 2026]
}
```

The calendar is complete for the requested inclusive interval. LeetCode's
valid sparse `submissionCalendar` map is treated as a complete activity map;
dates absent from that map are zero-submission days. A missing or malformed
calendar is an upstream error, not a zero-filled result. `availableFrom` and
`availableTo` describe the returned date coverage, not the age of the account.
The frontend adapter currently consumes `calendar` entries with `date`,
`submissions`, and `accepted`. `availableYears` comes from LeetCode's public
`userCalendar.activeYears`; a missing value is `null`, not an inferred account
history.

### `GET /api/leetcode/stats?refresh=false`

Returns the normalized `problemStatistics` and an `activity` object containing
`totalSubmissions`, `acceptedSubmissions`, `activeDays`, `totalActiveDays`,
`currentStreak`, `longestStreak`, and monthly submission/active-day totals.
`currentStreak` and `totalActiveDays` use public `userCalendar` values when
available. A lifetime `longestStreak` is `null` because the public query does
not reliably expose it; the frontend displays N/A rather than presenting a
partial-year maximum as an all-time value. Each value may be `null` when it
cannot be derived reliably. `refresh=true` bypasses cached
profile and calendar data for that request.

If LeetCode denies public calendar access, the stats route still returns the
problem and contest statistics from the successful profile query, with
`activity: null`, `activityError.code: "leetcode_calendar_unavailable"`, an
explanatory `activityError.message`, and `"activity"` in `unavailableFields`.
It does not fabricate zero-valued activity. The heatmap route returns HTTP 503
with `detail.code` set to `leetcode_calendar_unavailable` and an explanatory
`detail.message`.

The profile response includes `unavailableFields` when optional upstream
queries (such as contest rating or recent accepted submissions) fail. These
fields remain `null`; their failures are not interpreted as zero.

### `DELETE /api/leetcode/connect`

Removes only the authenticated learner's LeetCode username association and its
uniqueness claim. It does not delete the Firebase account or learner document.

## Automatic challenge verification

The backend uses these public GraphQL selections:

```graphql
query publicProfile($username: String!) {
  matchedUser(username: $username) {
    username
    profile { realName userAvatar ranking reputation countryName countryCode }
    submitStats {
      acSubmissionNum { difficulty count }
      totalSubmissionNum { difficulty count }
    }
  }
}

query contestRating($username: String!) {
  userContestRanking(username: $username) {
    rating globalRanking attendedContestsCount topPercentage
  }
}

query submissionCalendar($username: String!, $year: Int) {
  matchedUser(username: $username) {
    userCalendar(year: $year) {
      activeYears streak totalActiveDays submissionCalendar
    }
  }
}

query recentAccepted($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id title titleSlug timestamp
  }
}
```

The backend requests the latest 20 entries from LeetCode's unofficial public
GraphQL `recentAcSubmissionList` query, including title, exact problem slug,
Unix timestamp, and optional submission ID. This LeetCode field returns
Accepted submissions only. LeetCode may change or disable this
query; unavailable data is reported as unable to verify. The endpoint supplies
Accepted submissions only, but the API is unofficial and has not been
independently verified as a permanent contract.

For each MLSC-assigned day, the backend requires a case-insensitive exact match
to the assigned problem slug and a submission timestamp at or after the
assignment's `assignedAt`. It records the public evidence in the existing
`users/{uid}/challengeCompletions/{day}` document and appends an immutable
event transactionally. A repeated sync does not create another event.

The most recent 20 entries do not prove that no older submission exists.
Unmatched or unavailable history therefore cannot reject a completion or
downgrade a verified record. The linked public username is not proof of
LeetCode account ownership; the integration never requests LeetCode
credentials. The contribution calendar and general profile statistics are not
used to verify challenge days.

## Approved Firestore additions

- Add only `leetcodeUsername` to the authenticated learner's existing
  `users/{uid}` document.
- Add `leetcodeUsernameClaims/{normalized_username}` documents containing the
  owning Firebase UID, used transactionally to prevent two learners from
  claiming the same public username.
- Do not store LeetCode credentials, upstream response payloads, or private
  submission data in Firestore.
- Keep upstream response caching in process memory with bounded TTLs; no new
  cache collection or infrastructure.

## Frontend behavior

The learner dashboard uses the profile and heatmap routes, triggers challenge
synchronization on load and refresh, and reloads progress and assigned
questions after sync. It displays verified, awaiting-sync, or unable-to-verify
states; it does not offer a self-reported completion action. Legacy report and
admin-review routes remain available for existing records and workflows.
