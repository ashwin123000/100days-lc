# Application error logs

The admin-only Error Logs page reads and updates the server-owned `systemLogs`
Firestore collection through FastAPI. The collection is not accessible to
browser clients; the existing Firestore catch-all rule continues to deny it.
All management endpoints require a Firebase ID token with the `admin: true`
custom claim.

The API provides paginated and date-bounded log listing, source/severity/status
filters, search, log detail, and resolve actions. Authenticated clients may
submit bounded frontend errors to `/api/client-errors`; the server derives the
user ID, limits reports to 10 per minute per backend process, and sanitizes
messages and stack traces before persistence. API and network errors are
captured with request IDs for correlation.

Sources are `LEETCODE_GRAPHQL`, `LEETCODE_NETWORK`, `LEETCODE_HTTP`, `BACKEND`,
`FIRESTORE`, `AUTH`, and `FRONTEND`. Identical events are deduplicated for 60
seconds by a bounded, process-local cache (up to 4,096 fingerprints). This is
best-effort deduplication, not a distributed guarantee across Render instances.
Writes that fail fall back to sanitized standard application logs and do not
fail the request that was being logged.

Expected LeetCode limitations are not application errors: an unknown or
non-public username still returns a client-facing 404 but is not added to
System Logs, and a private submission calendar returns the profile page's
partial response with a `calendarError` notice instead of a 503. Other upstream
failures continue to be recorded.

The default retention window is 30 days and can be changed with
`SYSTEM_LOG_RETENTION_DAYS` (1–365). The admin API enforces this logical window;
it does not configure Firestore TTL or delete old documents. Firestore storage
continues to accrue charges until an operator separately configures a retention
and deletion policy.

`firestore.indexes.json` contains the composite indexes used for summary
counts and token search. This feature has not been deployed; deploy Firestore
indexes before enabling it in a production backend.
