import json
import logging
import math
import re
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GRAPHQL_URL = "https://leetcode.com/graphql"
REQUEST_TIMEOUT_SECONDS = 8
PROFILE_CACHE_TTL_SECONDS = 15 * 60
CALENDAR_CACHE_TTL_SECONDS = 6 * 60 * 60
MAX_CACHE_ENTRIES = 2048
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,25}$")
PROBLEM_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

PROFILE_QUERY = """
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
"""

CONTEST_QUERY = """
query contestRating($username: String!) {
  userContestRanking(username: $username) {
    rating
    globalRanking
    attendedContestsCount
    topPercentage
  }
}
"""

CALENDAR_QUERY = """
query submissionCalendar($username: String!, $year: Int) {
  matchedUser(username: $username) {
    userCalendar(year: $year) {
      activeYears
      streak
      totalActiveDays
      submissionCalendar
    }
  }
}
"""

RECENT_ACCEPTED_QUERY = """
query recentAccepted($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""
logger = logging.getLogger(__name__)
UPSTREAM_RETRY_DELAYS_SECONDS = (0.25,)


class LeetCodeServiceError(RuntimeError):
    status_code = 502
    code = "leetcode_upstream_error"
    source = "LEETCODE_GRAPHQL"


class LeetCodeUpstreamError(LeetCodeServiceError):
    pass


class LeetCodeProfileNotFound(LeetCodeServiceError):
    status_code = 404
    code = "leetcode_profile_not_found"


class LeetCodeUpstreamTimeout(LeetCodeServiceError):
    status_code = 504
    code = "leetcode_timeout"
    source = "LEETCODE_NETWORK"


class LeetCodeUpstreamHttpError(LeetCodeUpstreamError):
    source = "LEETCODE_HTTP"


class LeetCodeCalendarUnavailable(LeetCodeServiceError):
    status_code = 503
    code = "leetcode_calendar_unavailable"


class LeetCodeUpstreamRateLimited(LeetCodeServiceError):
    status_code = 429
    code = "leetcode_rate_limited"
    source = "LEETCODE_HTTP"


class LeetCodeUpstreamNetworkError(LeetCodeServiceError):
    source = "LEETCODE_NETWORK"


@dataclass
class CacheEntry:
    expires_at: float
    created_at: float
    value: Any


@dataclass
class CalendarYear:
    submissions: dict[str, int]
    active_years: list[int] | None
    current_streak: int | None
    total_active_days: int | None


def normalize_username(username: str) -> str:
    normalized = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("LeetCode username must be 1–25 letters, numbers, underscores, or hyphens.")
    return normalized


def _as_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        converted = int(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return converted if converted >= 0 else None


def _count_for(stats: Any, difficulty: str) -> int | None:
    if not isinstance(stats, list):
        return None
    for item in stats:
        name = item.get("difficulty") if isinstance(item, dict) else None
        if isinstance(name, str) and name.lower() == difficulty.lower():
            return _as_nonnegative_int(item.get("count"))
    return None


def _safe_avatar_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname not in {"assets.leetcode.com", "leetcode.com"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    return value


def _normalize_linked_username(username: str) -> str:
    try:
        return normalize_username(username)
    except (AttributeError, ValueError) as error:
        raise LeetCodeUpstreamError("The connected LeetCode username is invalid.") from error


def _graphql_error_category(errors: Any) -> str | None:
    if not errors:
        return None

    error_items = errors if isinstance(errors, list) else []
    messages = []
    for error in error_items:
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str):
            messages.append(message.casefold())
    if any("user does not exist" in message for message in messages):
        return "profile_not_found"
    if any("no permission to check the calendar" in message for message in messages):
        return "calendar_permission_denied"

    for error in error_items:
        if not isinstance(error, dict):
            continue
        extensions = error.get("extensions")
        code = extensions.get("code", "") if isinstance(extensions, dict) else ""
        message = error.get("message", "")
        normalized_code = code.casefold() if isinstance(code, str) else ""
        normalized_message = message.casefold() if isinstance(message, str) else ""
        if (
            "rate" in normalized_code
            or "thrott" in normalized_code
            or "rate limit" in normalized_message
            or "too many requests" in normalized_message
            or "throttl" in normalized_message
        ):
            return "rate_limited"
    return "graphql_errors"


def _graphql_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    operation_match = re.search(r"\bquery\s+([A-Za-z0-9_]+)", query)
    operation = operation_match.group(1) if operation_match else "unknown"
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://leetcode.com/",
            "User-Agent": "MLSC-100Days-Profile/1.0",
        },
        method="POST",
    )
    for attempt in range(len(UPSTREAM_RETRY_DELAYS_SECONDS) + 1):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise LeetCodeUpstreamError("LeetCode returned an unsuccessful response.")
                payload = json.loads(response.read())
            category = (
                _graphql_error_category(payload.get("errors"))
                if isinstance(payload, dict) else None
            )
            if category == "graphql_errors" and attempt < len(UPSTREAM_RETRY_DELAYS_SECONDS):
                logger.warning(
                    "leetcode_graphql_response_error operation=%s category=graphql_errors retry=1",
                    operation,
                )
                time.sleep(UPSTREAM_RETRY_DELAYS_SECONDS[attempt])
                continue
            break
        except HTTPError as error:
            if error.code == 429:
                logger.warning(
                    "leetcode_graphql_transport_error operation=%s status=429 category=rate_limited",
                    operation,
                )
                raise LeetCodeUpstreamRateLimited("LeetCode is rate limiting profile requests.") from error
            if error.code in {408, 504}:
                logger.warning(
                    "leetcode_graphql_transport_error operation=%s status=%s category=timeout",
                    operation,
                    error.code,
                )
                raise LeetCodeUpstreamTimeout("LeetCode did not respond in time.") from error
            if error.code in {502, 503} and attempt < len(UPSTREAM_RETRY_DELAYS_SECONDS):
                time.sleep(UPSTREAM_RETRY_DELAYS_SECONDS[attempt])
                continue
            logger.warning(
                "leetcode_graphql_transport_error operation=%s status=%s category=http_error",
                operation,
                error.code,
            )
            raise LeetCodeUpstreamHttpError("LeetCode returned an unsuccessful HTTP response.") from error
        except (TimeoutError, URLError) as error:
            if isinstance(error, URLError) and not isinstance(error.reason, TimeoutError):
                logger.warning(
                    "leetcode_graphql_transport_error operation=%s category=connection",
                    operation,
                )
                raise LeetCodeUpstreamNetworkError("LeetCode could not be reached.") from error
            logger.warning(
                "leetcode_graphql_transport_error operation=%s category=timeout",
                operation,
            )
            raise LeetCodeUpstreamTimeout("LeetCode did not respond in time.") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            logger.warning(
                "leetcode_graphql_response_error operation=%s category=malformed_json",
                operation,
            )
            raise LeetCodeUpstreamError("LeetCode returned malformed JSON.") from error
        except OSError as error:
            logger.warning(
                "leetcode_graphql_transport_error operation=%s category=connection",
                operation,
            )
            raise LeetCodeUpstreamNetworkError("LeetCode could not be reached.") from error

    if not isinstance(payload, dict):
        logger.warning(
            "leetcode_graphql_response_error operation=%s category=invalid_payload",
            operation,
        )
        raise LeetCodeUpstreamError("LeetCode returned an invalid response.")
    errors = payload.get("errors")
    if errors:
        category = _graphql_error_category(errors)
        if category == "profile_not_found":
            logger.warning(
                "leetcode_graphql_response_error operation=%s category=%s",
                operation,
                category,
            )
            raise LeetCodeProfileNotFound("The public LeetCode profile was not found.")
        if category == "calendar_permission_denied":
            logger.warning(
                "leetcode_graphql_response_error operation=%s category=%s",
                operation,
                category,
            )
            raise LeetCodeCalendarUnavailable(
                "LeetCode does not permit public access to this submission calendar."
            )
        if category == "rate_limited":
            logger.warning(
                "leetcode_graphql_response_error operation=%s category=rate_limited",
                operation,
            )
            raise LeetCodeUpstreamRateLimited("LeetCode is rate limiting profile requests.")
        logger.warning(
            "leetcode_graphql_response_error operation=%s category=graphql_errors count=%s",
            operation,
            len(errors) if isinstance(errors, list) else "invalid",
        )
        raise LeetCodeUpstreamError("LeetCode GraphQL reported an error.")
    data = payload.get("data")
    if not isinstance(data, dict):
        logger.warning(
            "leetcode_graphql_response_error operation=%s category=missing_data",
            operation,
        )
        raise LeetCodeUpstreamError("LeetCode returned an invalid response.")
    return data


def _normalize_submission_calendar(raw_calendar: Any) -> dict[str, int]:
    if isinstance(raw_calendar, str):
        try:
            raw_calendar = json.loads(raw_calendar)
        except json.JSONDecodeError as error:
            raise LeetCodeUpstreamError("LeetCode returned a malformed submission calendar.") from error
    if not isinstance(raw_calendar, dict):
        raise LeetCodeUpstreamError("LeetCode returned an invalid submission calendar.")

    normalized: dict[str, int] = {}
    for timestamp, raw_count in raw_calendar.items():
        try:
            timestamp_int = int(timestamp)
            count = _as_nonnegative_int(raw_count)
            if count is None:
                raise ValueError
            day = datetime.fromtimestamp(timestamp_int, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, TypeError, ValueError) as error:
            raise LeetCodeUpstreamError("LeetCode returned an invalid calendar entry.") from error
        normalized[day] = normalized.get(day, 0) + count
    return normalized


class LeetCodeService:
    def __init__(self) -> None:
        self._profile_cache: dict[str, CacheEntry] = {}
        self._calendar_cache: dict[tuple[str, int], CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._flight_lock = threading.Lock()
        self._profile_flights: dict[str, Future[Any]] = {}
        self._calendar_flights: dict[tuple[str, int], Future[Any]] = {}

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._profile_cache.clear()
            self._calendar_cache.clear()

    def _singleflight(
        self,
        key: Any,
        flights: dict[Any, Future[Any]],
        cache: dict[Any, CacheEntry],
        request_started: float | None,
        fetch: Any,
        ttl: int,
    ) -> Any:
        cached = self._cached(cache, key, request_started)
        if cached is not None:
            return cached
        with self._flight_lock:
            cached = self._cached(cache, key, request_started)
            if cached is not None:
                return cached
            future = flights.get(key)
            is_owner = future is None
            if is_owner:
                future = Future()
                flights[key] = future

        if not is_owner:
            return future.result()

        try:
            result = fetch()
            self._store(cache, key, result, ttl)
            future.set_result(result)
            return result
        except Exception as error:
            future.set_exception(error)
            raise
        finally:
            with self._flight_lock:
                if flights.get(key) is future:
                    del flights[key]

    def _cached(
        self,
        cache: dict[Any, CacheEntry],
        key: Any,
        created_after: float | None = None,
    ) -> Any | None:
        with self._cache_lock:
            entry = cache.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                del cache[key]
                return None
            if created_after is not None and entry.created_at < created_after:
                return None
            return entry.value

    def _store(self, cache: dict[Any, CacheEntry], key: Any, value: Any, ttl: int) -> None:
        with self._cache_lock:
            if key not in cache and len(cache) >= MAX_CACHE_ENTRIES:
                oldest_key = min(cache, key=lambda item: cache[item].expires_at)
                del cache[oldest_key]
            created_at = time.monotonic()
            cache[key] = CacheEntry(created_at + ttl, created_at, value)

    def get_profile(self, username: str, refresh: bool = False) -> dict[str, Any]:
        normalized = _normalize_linked_username(username)
        key = normalized.casefold()
        request_started = time.monotonic() if refresh else None
        return self._singleflight(
            key,
            self._profile_flights,
            self._profile_cache,
            request_started,
            lambda: self._fetch_profile(normalized),
            PROFILE_CACHE_TTL_SECONDS,
        )

    def _fetch_profile(self, username: str) -> dict[str, Any]:
        data = _graphql_request(PROFILE_QUERY, {"username": username})
        matched = data.get("matchedUser")
        if not isinstance(matched, dict):
            raise LeetCodeProfileNotFound("The public LeetCode profile was not found.")
        canonical_username = matched.get("username")
        if not isinstance(canonical_username, str):
            raise LeetCodeUpstreamError("LeetCode returned an invalid username.")
        canonical_username = _normalize_linked_username(canonical_username)

        profile_data = matched.get("profile")
        profile_data = profile_data if isinstance(profile_data, dict) else {}
        stats = matched.get("submitStats")
        stats = stats if isinstance(stats, dict) else {}
        accepted = stats.get("acSubmissionNum")
        submissions = stats.get("totalSubmissionNum")
        total_solved = _count_for(accepted, "All")
        if total_solved is None:
            difficulty_counts = [_count_for(accepted, name) for name in ("Easy", "Medium", "Hard")]
            if all(count is not None for count in difficulty_counts):
                total_solved = sum(difficulty_counts)

        contest_rating = None
        contest_global_ranking = None
        contests_attended = None
        contest_top_percentage = None
        problem_ranking = _as_nonnegative_int(profile_data.get("ranking"))
        reputation = _as_nonnegative_int(profile_data.get("reputation"))
        country_name = profile_data.get("countryName")
        country_code = profile_data.get("countryCode")
        if not isinstance(country_name, str) or not country_name.strip():
            country_name = None
        if not isinstance(country_code, str) or not country_code.strip():
            country_code = None
        unavailable_fields: list[str] = []
        try:
            contest_data = _graphql_request(CONTEST_QUERY, {"username": username})
            contest = contest_data.get("userContestRanking")
            if isinstance(contest, dict):
                rating = contest.get("rating")
                if (
                    isinstance(rating, (int, float))
                    and not isinstance(rating, bool)
                    and math.isfinite(rating)
                    and rating >= 0
                ):
                    contest_rating = float(rating)
                contest_global_ranking = _as_nonnegative_int(contest.get("globalRanking"))
                contests_attended = _as_nonnegative_int(contest.get("attendedContestsCount"))
                top_percentage = contest.get("topPercentage")
                if (
                    isinstance(top_percentage, (int, float))
                    and not isinstance(top_percentage, bool)
                    and math.isfinite(top_percentage)
                    and 0 <= top_percentage <= 100
                ):
                    contest_top_percentage = float(top_percentage)
                if contest_rating is None:
                    unavailable_fields.append("contestRating")
                if contest_global_ranking is None:
                    unavailable_fields.append("contestGlobalRanking")
                if contests_attended is None:
                    unavailable_fields.append("contestsAttended")
                if contest_top_percentage is None:
                    unavailable_fields.append("contestTopPercentage")
            elif contest is None:
                unavailable_fields.extend((
                    "contestRating",
                    "contestGlobalRanking",
                    "contestsAttended",
                    "contestTopPercentage",
                ))
            if contest_rating is None:
                unavailable_fields.append("contestRating")
        except LeetCodeServiceError:
            unavailable_fields.extend((
                "contestRating",
                "contestGlobalRanking",
                "contestsAttended",
                "contestTopPercentage",
            ))

        recent_submissions: list[dict[str, Any]] = []
        recent_accepted_available = False
        try:
            recent_data = _graphql_request(
                RECENT_ACCEPTED_QUERY,
                {"username": username, "limit": 20},
            )
            recent = recent_data.get("recentAcSubmissionList")
            if isinstance(recent, list):
                recent_accepted_available = True
                for item in recent:
                    if not isinstance(item, dict):
                        continue
                    slug = item.get("titleSlug")
                    timestamp = _as_nonnegative_int(item.get("timestamp"))
                    if (
                        not isinstance(slug, str)
                        or not PROBLEM_SLUG_PATTERN.fullmatch(slug)
                        or timestamp is None
                        or timestamp == 0
                    ):
                        continue
                    submission = {"problemSlug": slug, "timestamp": timestamp}
                    title = item.get("title")
                    if isinstance(title, str) and title.strip():
                        submission["problemTitle"] = title.strip()
                    submission_id = item.get("id")
                    if isinstance(submission_id, (str, int)) and not isinstance(submission_id, bool):
                        submission["submissionId"] = str(submission_id)
                    recent_submissions.append(submission)
            else:
                unavailable_fields.append("recentAcceptedSubmissions")
        except LeetCodeServiceError:
            unavailable_fields.append("recentAcceptedSubmissions")

        return {
            "profile": {
                "username": canonical_username,
                "avatarUrl": _safe_avatar_url(profile_data.get("userAvatar")),
                "displayName": (
                    profile_data.get("realName")
                    if isinstance(profile_data.get("realName"), str) and profile_data.get("realName")
                    else None
                ),
                "profileUrl": f"https://leetcode.com/u/{canonical_username}/",
                "ranking": problem_ranking,
                "reputation": reputation,
                "countryName": country_name,
                "countryCode": country_code,
            },
            "problemStatistics": {
                "totalSolved": total_solved,
                "easy": {"solved": _count_for(accepted, "Easy"), "total": None},
                "medium": {"solved": _count_for(accepted, "Medium"), "total": None},
                "hard": {"solved": _count_for(accepted, "Hard"), "total": None},
                "contestRating": contest_rating,
                "ranking": problem_ranking,
                "totalSubmissions": _count_for(submissions, "All"),
                "acceptedSubmissions": None,
            },
            "contestStatistics": {
                "rating": contest_rating,
                "globalRanking": contest_global_ranking,
                "attendedContestsCount": contests_attended,
                "topPercentage": contest_top_percentage,
            },
            "recentAcceptedSlugs": sorted({
                submission["problemSlug"].casefold()
                for submission in recent_submissions
            }),
            "recentAcceptedSubmissions": recent_submissions,
            "recentAcceptedAvailable": recent_accepted_available,
            "unavailableFields": sorted(set(unavailable_fields + [
                name
                for name, value in (
                    ("totalSolved", total_solved),
                    ("easySolved", _count_for(accepted, "Easy")),
                    ("mediumSolved", _count_for(accepted, "Medium")),
                    ("hardSolved", _count_for(accepted, "Hard")),
                    ("totalSubmissions", _count_for(submissions, "All")),
                    ("problemRanking", problem_ranking),
                    ("reputation", reputation),
                    ("countryName", country_name),
                )
                if value is None
            ] + ["acceptedSubmissions"])),
        }

    def get_calendar(
        self,
        username: str,
        start: date,
        end: date,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        normalized = _normalize_linked_username(username)
        if end < start:
            raise ValueError("The end date must be on or after the start date.")
        if (end - start).days > 365:
            raise ValueError("The requested date range cannot exceed 366 days.")

        output: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            year = cursor.year
            year_calendar = self._get_year_calendar(normalized, year, refresh)
            year_end = min(end, date(year, 12, 31))
            day = cursor
            while day <= year_end:
                output.append({
                    "date": day.isoformat(),
                    "submissions": year_calendar.submissions.get(day.isoformat(), 0),
                    "accepted": None,
                })
                day += timedelta(days=1)
            cursor = year_end + timedelta(days=1)
        return output

    def get_calendar_metadata(self, username: str, years: set[int]) -> dict[str, Any]:
        normalized = _normalize_linked_username(username)
        calendars = [
            self._get_year_calendar(normalized, year, False)
            for year in sorted(years)
        ]
        latest = calendars[-1] if calendars else None
        return {
            "availableYears": latest.active_years if latest else None,
            "currentStreak": latest.current_streak if latest else None,
            "totalActiveDays": latest.total_active_days if latest else None,
        }

    def _get_year_calendar(self, username: str, year: int, refresh: bool) -> CalendarYear:
        key = (username.casefold(), year)
        request_started = time.monotonic() if refresh else None
        def fetch() -> dict[str, int]:
            data = _graphql_request(CALENDAR_QUERY, {"username": username, "year": year})
            matched = data.get("matchedUser")
            if not isinstance(matched, dict):
                raise LeetCodeProfileNotFound("The public LeetCode profile was not found.")
            calendar = matched.get("userCalendar")
            if not isinstance(calendar, dict) or "submissionCalendar" not in calendar:
                raise LeetCodeUpstreamError("LeetCode did not provide a submission calendar.")
            active_years_value = calendar.get("activeYears")
            active_years = None
            if isinstance(active_years_value, list):
                active_years = []
                for active_year in active_years_value:
                    normalized_year = _as_nonnegative_int(active_year)
                    if normalized_year is None:
                        raise LeetCodeUpstreamError("LeetCode returned invalid calendar year metadata.")
                    active_years.append(normalized_year)
            current_streak = _as_nonnegative_int(calendar.get("streak"))
            total_active_days = _as_nonnegative_int(calendar.get("totalActiveDays"))
            return CalendarYear(
                submissions=_normalize_submission_calendar(calendar["submissionCalendar"]),
                active_years=active_years,
                current_streak=current_streak,
                total_active_days=total_active_days,
            )

        return self._singleflight(
            key,
            self._calendar_flights,
            self._calendar_cache,
            request_started,
            fetch,
            CALENDAR_CACHE_TTL_SECONDS,
        )


leetcode_service = LeetCodeService()


class LearnerRequestLimiter:
    def __init__(self, limit: int = 60, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [item for item in self._requests.get(user_id, []) if item > cutoff]
            if len(recent) >= self.limit:
                self._requests[user_id] = recent
                return False
            recent.append(now)
            self._requests[user_id] = recent
            if len(self._requests) > 4096:
                self._requests = {
                    key: requests
                    for key, requests in self._requests.items()
                    if any(item > cutoff for item in requests)
                }
            return True


def summarize_activity(calendar: list[dict[str, Any]]) -> dict[str, Any]:
    total_submissions = 0
    active_days = 0
    longest_streak = 0
    streak = 0
    for day in calendar:
        count = day["submissions"]
        total_submissions += count
        if count > 0:
            active_days += 1
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0

    current_streak = 0
    reversed_calendar = list(reversed(calendar))
    today = datetime.now(timezone.utc).date()
    if (
        reversed_calendar
        and date.fromisoformat(reversed_calendar[0]["date"]) == today
        and reversed_calendar[0]["submissions"] == 0
    ):
        reversed_calendar = reversed_calendar[1:]
    for day in reversed_calendar:
        if day["submissions"] <= 0:
            break
        current_streak += 1

    months = [{"month": month, "submissions": 0, "activeDays": 0} for month in range(12)]
    for day in calendar:
        month = date.fromisoformat(day["date"]).month - 1
        months[month]["submissions"] += day["submissions"]
        if day["submissions"] > 0:
            months[month]["activeDays"] += 1

    return {
        "totalSubmissions": total_submissions,
        "acceptedSubmissions": None,
        "activeDays": active_days,
        "currentStreak": current_streak,
        "longestStreak": longest_streak,
        "months": months,
    }
