import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
import traceback
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any
from urllib.parse import unquote_plus

from firebase_admin import firestore
from google.api_core.exceptions import GoogleAPIError

from .firebase_service import (
    FirebaseConfigurationError,
    FirebaseServiceError,
    firestore_client,
)

logger = logging.getLogger(__name__)


class SystemLogStorageError(RuntimeError):
    pass

SOURCES = {
    "LEETCODE_GRAPHQL",
    "LEETCODE_NETWORK",
    "LEETCODE_HTTP",
    "BACKEND",
    "FIRESTORE",
    "AUTH",
    "FRONTEND",
}
SEVERITIES = {"CRITICAL", "ERROR", "WARNING"}
RESOLUTION_STATUSES = {"OPEN", "RESOLVED"}
MAX_MESSAGE_LENGTH = 1000
MAX_STACK_LENGTH = 6000
MAX_SCAN_PER_PAGE = 500
MAX_DEDUPE_ENTRIES = 4096
_KEY_CHARACTER = r"(?:%[0-9a-f]{2}|[a-z0-9_.-])+"
_SENSITIVE_KEY_CHARACTER = (
    r"(?:access[_-]?token|auth(?:orization)?|api[_-]?key|client[_-]?secret|"
    r"cookie|credentials?|firebase[_-]?(?:api[_-]?key|token)|id[_-]?token|"
    r"key|password|private[_-]?key(?:[_-]?id)?|refresh[_-]?token|secret|"
    r"session|signature|token|x[_-]?api[_-]?key)"
)
_QUOTED_SECRET_ASSIGNMENT = re.compile(
    rf"""(?i)(?P<prefix>(?<![a-z0-9_.-])["']?)(?P<key>{_SENSITIVE_KEY_CHARACTER})"""
    r"""(?P<key_quote>["']?)(?P<before>\s*)(?P<separator>[:=])(?P<after>\s*)"""
    r"""(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
    re.DOTALL,
)
_UNQUOTED_SECRET_ASSIGNMENT = re.compile(
    rf"""(?i)(?P<prefix>(?<![a-z0-9_.-])["']?)(?P<key>{_SENSITIVE_KEY_CHARACTER})"""
    r"""(?P<key_quote>["']?)(?P<before>\s*)(?P<separator>[:=])(?P<after>\s*)"""
    r"""(?P<value_quote>["']?)"""
    r"""(?P<value>[^\s,;'"<>}&]*)"""
)
_AUTHORIZATION_VALUE = re.compile(
    r"""(?i)(?P<prefix>\bauthorization\s*[:=]\s*)"""
    r"""(?P<scheme>(?:bearer|basic)\s+)?(?P<value>[^\s,;"']+)"""
)
_BEARER_VALUE = re.compile(r"(?i)\b(?P<scheme>bearer|basic)\s+(?P<value>[A-Za-z0-9._~+/-]+=*)")
_ENCODED_QUERY_SECRET = re.compile(
    r"""(?i)(?P<prefix>%3f|%26)(?P<key>(?:%[0-9a-f]{2}|[a-z0-9_.-])+?)%3d"""
    r"""(?P<value>(?:(?!%26|%23).)*)"""
)
_URL_USER_PASSWORD = re.compile(
    r"(?i)(?P<prefix>https?://[^:/@\s]+:)(?P<value>[^@/\s]+)(?=@)"
)
_FIREBASE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")
_JWT_CREDENTIAL = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_GOOGLE_OAUTH_CREDENTIAL = re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b")
_SENSITIVE_NAMES = {
    "access_token",
    "auth",
    "authorization",
    "api_key",
    "apikey",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "firebase_api_key",
    "firebase_token",
    "id_token",
    "key",
    "password",
    "private_key",
    "private_key_id",
    "refresh_token",
    "secret",
    "session",
    "signature",
    "token",
    "x_api_key",
}
_SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_dedupe_lock = threading.Lock()
_recent_fingerprints: dict[str, tuple[float, int]] = {}


def sanitize_text(value: Any, limit: int = MAX_MESSAGE_LENGTH) -> str:
    if not isinstance(value, str):
        value = str(value)

    def is_sensitive_name(value: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", unquote_plus(value.strip("\"'")).casefold()).strip("_")
        return normalized in _SENSITIVE_NAMES

    def redact_quoted(match: re.Match[str]) -> str:
        if not is_sensitive_name(match.group("key")):
            return match.group(0)
        return (
            match.group("prefix")
            + match.group("key")
            + match.group("key_quote")
            + match.group("before")
            + match.group("separator")
            + match.group("after")
            + match.group("quote")
            + "[REDACTED]"
            + match.group("quote")
        )

    def redact_unquoted(match: re.Match[str]) -> str:
        if match.group("key").casefold() == "authorization":
            return match.group(0)
        if not is_sensitive_name(match.group("key")):
            return match.group(0)
        quote = match.group("value_quote")
        return (
            match.group("prefix")
            + match.group("key")
            + match.group("key_quote")
            + match.group("before")
            + match.group("separator")
            + match.group("after")
            + quote
            + "[REDACTED]"
            + (quote if quote else "")
        )

    def redact_authorization(match: re.Match[str]) -> str:
        return match.group("prefix") + (match.group("scheme") or "") + "[REDACTED]"

    def redact_bearer(match: re.Match[str]) -> str:
        return match.group("scheme") + " [REDACTED]"

    def redact_encoded_query(match: re.Match[str]) -> str:
        if not is_sensitive_name(match.group("key")):
            return match.group(0)
        return match.group("prefix") + match.group("key") + "%3D%5BREDACTED%5D"

    sanitized = _URL_USER_PASSWORD.sub(r"\g<prefix>[REDACTED]", value)
    sanitized = _ENCODED_QUERY_SECRET.sub(redact_encoded_query, sanitized)
    sanitized = _QUOTED_SECRET_ASSIGNMENT.sub(redact_quoted, sanitized)
    sanitized = _AUTHORIZATION_VALUE.sub(redact_authorization, sanitized)
    sanitized = _UNQUOTED_SECRET_ASSIGNMENT.sub(redact_unquoted, sanitized)
    sanitized = _BEARER_VALUE.sub(redact_bearer, sanitized)
    sanitized = _FIREBASE_API_KEY.sub("[REDACTED]", sanitized)
    sanitized = _JWT_CREDENTIAL.sub("[REDACTED]", sanitized)
    sanitized = _GOOGLE_OAUTH_CREDENTIAL.sub("[REDACTED]", sanitized)
    sanitized = "".join(char for char in sanitized if char in "\n\t" or ord(char) >= 32)
    return sanitized[:limit]


def _stack_trace(error: BaseException | None) -> str:
    if error is None:
        return ""
    try:
        formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__, limit=12))
    except Exception:
        formatted = f"{type(error).__name__}: {error}"
    return sanitize_text(formatted, MAX_STACK_LENGTH)


def _retention_days() -> int:
    try:
        return min(365, max(1, int(os.getenv("SYSTEM_LOG_RETENTION_DAYS", "30"))))
    except ValueError:
        return 30


def retention_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current - timedelta(days=_retention_days())


def _fingerprint(event: dict[str, Any]) -> str:
    fields = (
        "source",
        "severity",
        "userId",
        "service",
        "operation",
        "endpoint",
        "method",
        "httpStatus",
        "errorCode",
        "message",
    )
    serialized = json.dumps([event.get(field) for field in fields], separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _is_duplicate(fingerprint: str, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    try:
        window = min(3600, max(1, int(os.getenv("SYSTEM_LOG_DEDUPE_SECONDS", "60"))))
    except ValueError:
        window = 60
    with _dedupe_lock:
        expired = [
            key for key, (last_seen, _count) in _recent_fingerprints.items()
            if current - last_seen >= window
        ]
        for key in expired:
            del _recent_fingerprints[key]
        previous = _recent_fingerprints.get(fingerprint)
        if previous is not None and current - previous[0] < window:
            _recent_fingerprints[fingerprint] = (previous[0], previous[1] + 1)
            return True
        if len(_recent_fingerprints) >= MAX_DEDUPE_ENTRIES:
            oldest = min(_recent_fingerprints, key=lambda key: _recent_fingerprints[key][0])
            del _recent_fingerprints[oldest]
        _recent_fingerprints[fingerprint] = (current, 1)
        return False


def record_error(
    *,
    source: str,
    service: str,
    operation: str,
    endpoint: str,
    method: str,
    http_status: int | None,
    error_code: str,
    message: str,
    request_id: str,
    user_id: str | None = None,
    duration_ms: float | None = None,
    severity: str = "ERROR",
    error: BaseException | None = None,
    stack_trace: str | None = None,
) -> bool:
    normalized_source = source if source in SOURCES else "BACKEND"
    normalized_severity = severity if severity in SEVERITIES else "ERROR"
    safe_message = sanitize_text(message)
    safe_service = sanitize_text(service, 120)
    safe_operation = sanitize_text(operation, 120)
    safe_endpoint = sanitize_text(endpoint, 300)
    safe_error_code = sanitize_text(error_code, 120)
    safe_request_id = sanitize_text(request_id, 100)
    tokens = sorted(set(_SEARCH_TOKEN_PATTERN.findall(
        " ".join((
            normalized_source,
            safe_service,
            safe_operation,
            safe_endpoint,
            safe_error_code,
            safe_message,
            safe_request_id,
        )).casefold()
    )))
    event = {
        "source": normalized_source,
        "severity": normalized_severity,
        "service": safe_service,
        "operation": safe_operation,
        "endpoint": safe_endpoint,
        "method": sanitize_text(method.upper(), 12),
        "httpStatus": http_status,
        "durationMs": max(0, round(duration_ms)) if duration_ms is not None else None,
        "errorCode": safe_error_code,
        "message": safe_message,
        "requestId": safe_request_id,
        "userId": sanitize_text(user_id, 128) if user_id else None,
        "stackTrace": sanitize_text(
            stack_trace if stack_trace is not None else _stack_trace(error),
            MAX_STACK_LENGTH,
        ),
        "resolutionStatus": "OPEN",
        "resolvedAt": None,
        "resolvedBy": None,
        "searchTokens": tokens[:128],
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    if _is_duplicate(_fingerprint(event)):
        return False
    try:
        firestore_client().collection("systemLogs").add(event)
        return True
    except Exception as persistence_error:
        logger.error(
            "system_log_persist_failed source=%s operation=%s endpoint=%s error=%s",
            normalized_source,
            event["operation"],
            event["endpoint"],
            sanitize_text(persistence_error, 300),
        )
        return False


def _encode_cursor(document_id: str) -> str:
    return base64.urlsafe_b64encode(document_id.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("The log pagination cursor is invalid.") from error
    if not decoded or "/" in decoded or len(decoded) > 256:
        raise ValueError("The log pagination cursor is invalid.")
    return decoded


def _iso_timestamp(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize_log(snapshot: Any, include_stack_trace: bool = False) -> dict[str, Any]:
    data = snapshot.to_dict() or {}
    return {
        "id": snapshot.id,
        "timestamp": _iso_timestamp(data.get("timestamp")),
        "severity": data.get("severity", "ERROR"),
        "source": data.get("source", "BACKEND"),
        "service": data.get("service", "backend"),
        "operation": data.get("operation", "unknown"),
        "endpoint": data.get("endpoint", ""),
        "method": data.get("method", ""),
        "httpStatus": data.get("httpStatus"),
        "durationMs": data.get("durationMs"),
        "errorCode": data.get("errorCode", ""),
        "message": sanitize_text(data.get("message", "")),
        "requestId": data.get("requestId", ""),
        "userId": data.get("userId"),
        **(
            {"stackTrace": sanitize_text(data.get("stackTrace", ""), MAX_STACK_LENGTH)}
            if include_stack_trace else {}
        ),
        "resolutionStatus": data.get("resolutionStatus", "OPEN"),
        "resolvedAt": _iso_timestamp(data.get("resolvedAt")),
        "resolvedBy": data.get("resolvedBy"),
    }


def _date_range(start_date: date | None, end_date: date | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    oldest = retention_start(now)
    start = datetime.combine(start_date, datetime_time.min, timezone.utc) if start_date else oldest
    end = (
        datetime.combine(end_date + timedelta(days=1), datetime_time.min, timezone.utc)
        if end_date else now
    )
    if start_date and start_date < oldest.date():
        raise ValueError(f"Log history is limited to the last {_retention_days()} days.")
    if start >= end or end > now + timedelta(days=1):
        raise ValueError("The selected log date range is invalid.")
    return max(start, oldest), min(end, now)


def _summary(collection_ref: Any, start: datetime, end: datetime) -> dict[str, int]:
    base = collection_ref.where("timestamp", ">=", start).where("timestamp", "<=", end)

    def count(query: Any) -> int:
        result = query.count().get()
        return int(result[0][0].value)

    return {
        "total": count(base),
        "critical": count(base.where("severity", "==", "CRITICAL")),
        "warnings": count(base.where("severity", "==", "WARNING")),
        "unresolved": count(base.where("resolutionStatus", "==", "OPEN")),
    }


def _list_logs_unchecked(
    *,
    page_size: int = 25,
    cursor: str | None = None,
    source: str | None = None,
    severity: str | None = None,
    resolution_status: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    if page_size < 1 or page_size > 50:
        raise ValueError("Page size must be from 1 through 50.")
    if source and source not in SOURCES:
        raise ValueError("The selected log source is invalid.")
    if severity and severity not in SEVERITIES:
        raise ValueError("The selected severity is invalid.")
    if resolution_status and resolution_status not in RESOLUTION_STATUSES:
        raise ValueError("The selected resolution status is invalid.")
    start, end = _date_range(start_date, end_date)
    collection_ref = firestore_client().collection("systemLogs")
    query = collection_ref.where("timestamp", ">=", start).where("timestamp", "<=", end)
    search_text = sanitize_text(search or "", 120).strip().casefold()
    if search_text:
        token = next(iter(_SEARCH_TOKEN_PATTERN.findall(search_text)), "")
        if token:
            query = query.where("searchTokens", "array_contains", token)
    query = query.order_by("timestamp", direction=firestore.Query.DESCENDING)
    if cursor:
        cursor_snapshot = collection_ref.document(_decode_cursor(cursor)).get()
        if not cursor_snapshot.exists:
            raise ValueError("The log pagination cursor has expired.")
        query = query.start_after(cursor_snapshot)

    filters = (source, severity, resolution_status)
    matched = []
    matched_snapshots = []
    scanned = 0
    last_snapshot = None
    while scanned < MAX_SCAN_PER_PAGE and len(matched) <= page_size:
        batch_size = min(100, MAX_SCAN_PER_PAGE - scanned)
        snapshots = list(query.limit(batch_size).stream())
        if not snapshots:
            break
        for snapshot in snapshots:
            scanned += 1
            last_snapshot = snapshot
            record = _serialize_log(snapshot)
            if source and record["source"] != source:
                continue
            if severity and record["severity"] != severity:
                continue
            if resolution_status and record["resolutionStatus"] != resolution_status:
                continue
            if search_text and search_text not in " ".join((
                record["endpoint"],
                record["message"],
                record["requestId"],
                record["operation"],
                record["service"],
            )).casefold():
                continue
            matched.append(record)
            matched_snapshots.append(snapshot)
            if len(matched) > page_size:
                break
        if len(snapshots) < batch_size or len(matched) > page_size:
            break
        query = query.start_after(snapshots[-1])

    has_more = len(matched) > page_size or scanned == MAX_SCAN_PER_PAGE
    results = matched[:page_size]
    if len(matched) > page_size:
        cursor_snapshot = matched_snapshots[page_size - 1]
    else:
        cursor_snapshot = last_snapshot
    next_cursor = _encode_cursor(cursor_snapshot.id) if has_more and cursor_snapshot is not None else None
    return {
        "items": results,
        "nextCursor": next_cursor,
        "summary": _summary(collection_ref, start, end),
        "retentionDays": _retention_days(),
        "scanLimitReached": scanned == MAX_SCAN_PER_PAGE,
    }


def list_logs(
    *,
    page_size: int = 25,
    cursor: str | None = None,
    source: str | None = None,
    severity: str | None = None,
    resolution_status: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    try:
        return _list_logs_unchecked(
            page_size=page_size,
            cursor=cursor,
            source=source,
            severity=severity,
            resolution_status=resolution_status,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )
    except (FirebaseConfigurationError, FirebaseServiceError, GoogleAPIError) as error:
        raise SystemLogStorageError("Error logs could not be loaded from Firestore.") from error


def _get_log_unchecked(log_id: str) -> dict[str, Any] | None:
    if not log_id or "/" in log_id or len(log_id) > 256:
        raise ValueError("The log ID is invalid.")
    snapshot = firestore_client().collection("systemLogs").document(log_id).get()
    if not snapshot.exists:
        return None
    return _serialize_log(snapshot, include_stack_trace=True)


def get_log(log_id: str) -> dict[str, Any] | None:
    try:
        return _get_log_unchecked(log_id)
    except (FirebaseConfigurationError, FirebaseServiceError, GoogleAPIError) as error:
        raise SystemLogStorageError("The error log could not be loaded from Firestore.") from error


def _resolve_log_unchecked(log_id: str, admin_uid: str) -> dict[str, Any] | None:
    if not log_id or "/" in log_id or len(log_id) > 256:
        raise ValueError("The log ID is invalid.")
    reference = firestore_client().collection("systemLogs").document(log_id)
    snapshot = reference.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if data.get("resolutionStatus") != "RESOLVED":
        reference.update({
            "resolutionStatus": "RESOLVED",
            "resolvedAt": firestore.SERVER_TIMESTAMP,
            "resolvedBy": admin_uid,
        })
    return get_log(log_id)


def resolve_log(log_id: str, admin_uid: str) -> dict[str, Any] | None:
    try:
        return _resolve_log_unchecked(log_id, admin_uid)
    except (FirebaseConfigurationError, FirebaseServiceError, GoogleAPIError) as error:
        raise SystemLogStorageError("The error log could not be updated in Firestore.") from error


def capture_error_from_request(
    *,
    source: str,
    endpoint: str,
    method: str,
    status: int,
    request_id: str,
    user_id: str | None = None,
    duration_ms: float | None = None,
    error_code: str = "",
    message: str | None = None,
    error: BaseException | None = None,
    severity: str = "ERROR",
    stack_trace: str | None = None,
) -> bool:
    operation = endpoint.strip("/").replace("/", "_") or "request"
    return record_error(
        source=source,
        service={
            "LEETCODE_GRAPHQL": "leetcode_graphql",
            "LEETCODE_NETWORK": "leetcode",
            "LEETCODE_HTTP": "leetcode",
            "FIRESTORE": "firestore",
            "AUTH": "firebase_auth",
            "FRONTEND": "frontend",
        }.get(source, "backend"),
        operation=operation,
        endpoint=endpoint,
        method=method,
        http_status=status,
        error_code=error_code or f"HTTP_{status}",
        message=message or (str(error) if error else f"Request failed with HTTP {status}."),
        request_id=request_id,
        user_id=user_id,
        duration_ms=duration_ms,
        severity=severity,
        error=error,
        stack_trace=stack_trace,
    )
