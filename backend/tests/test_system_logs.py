from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app import system_logs


class FakeCollection:
    def __init__(self):
        self.documents = []

    def add(self, data):
        self.documents.append(data)
        return "log-id"


class FakeFirestore:
    def __init__(self):
        self.logs = FakeCollection()

    def collection(self, name):
        assert name == "systemLogs"
        return self.logs


class FakeSnapshot:
    def __init__(self, document_id, data):
        self.id = document_id
        self.data = data
        self.exists = True

    def to_dict(self):
        return self.data


class FakeQuery:
    def __init__(self, collection, filters=(), cursor_id=None, page_limit=None, direction=None):
        self.collection = collection
        self.filters = list(filters)
        self.cursor_id = cursor_id
        self.page_limit = page_limit
        self.direction = direction

    def where(self, field, operator, value):
        return FakeQuery(
            self.collection,
            [*self.filters, (field, operator, value)],
            self.cursor_id,
            self.page_limit,
            self.direction,
        )

    def order_by(self, _field, direction=None):
        return FakeQuery(self.collection, self.filters, self.cursor_id, self.page_limit, direction)

    def start_after(self, snapshot):
        return FakeQuery(self.collection, self.filters, snapshot.id, self.page_limit, self.direction)

    def limit(self, value):
        return FakeQuery(self.collection, self.filters, self.cursor_id, value, self.direction)

    def stream(self):
        snapshots = [
            snapshot for snapshot in self.collection.documents
            if all(self._matches(snapshot, field, operator, value) for field, operator, value in self.filters)
        ]
        snapshots.sort(
            key=lambda snapshot: (snapshot.data["timestamp"], snapshot.id),
            reverse=self.direction == "DESCENDING",
        )
        if self.cursor_id:
            cursor_index = next(index for index, snapshot in enumerate(snapshots) if snapshot.id == self.cursor_id)
            snapshots = snapshots[cursor_index + 1:]
        return snapshots[:self.page_limit]

    def count(self):
        return FakeCount(self)

    @staticmethod
    def _matches(snapshot, field, operator, value):
        actual = snapshot.data.get(field)
        if operator == ">=":
            return actual >= value
        if operator == "<=":
            return actual <= value
        if operator == "==":
            return actual == value
        if operator == "array_contains":
            return value in actual
        raise AssertionError(f"Unexpected operator: {operator}")


class FakeCount:
    def __init__(self, query):
        self.query = query

    def get(self):
        count = len([
            snapshot for snapshot in self.query.collection.documents
            if all(self.query._matches(snapshot, field, operator, value)
                   for field, operator, value in self.query.filters)
        ])
        return [[SimpleNamespace(value=count)]]


class PaginatedFirestore(FakeFirestore):
    def __init__(self, snapshots):
        super().__init__()
        self.logs.documents = snapshots

    def collection(self, name):
        assert name == "systemLogs"
        return PaginatedCollection(self.logs.documents)


class PaginatedCollection:
    def __init__(self, snapshots):
        self.documents = snapshots

    def where(self, field, operator, value):
        return FakeQuery(self, [(field, operator, value)])

    def document(self, document_id):
        snapshot = next((item for item in self.documents if item.id == document_id), None)
        return SimpleNamespace(
            get=lambda: snapshot or SimpleNamespace(exists=False),
        )


class MutableDocument:
    def __init__(self, document_id, data):
        self.id = document_id
        self.data = data
        self.exists = True

    def get(self):
        return FakeSnapshot(self.id, self.data)

    def update(self, changes):
        self.data.update(changes)


class MutableCollection:
    def __init__(self, document):
        self.document_ref = document

    def document(self, document_id):
        assert document_id == self.document_ref.id
        return self.document_ref


class MutableFirestore:
    def __init__(self, document):
        self.collection_ref = MutableCollection(document)

    def collection(self, name):
        assert name == "systemLogs"
        return self.collection_ref


def _record(**overrides):
    values = {
        "source": "FRONTEND",
        "service": "frontend",
        "operation": "window_runtime_error",
        "endpoint": "/profile",
        "method": "CLIENT",
        "http_status": 0,
        "error_code": "window_runtime_error",
        "message": "A client error occurred.",
        "request_id": "request-1",
        "user_id": "learner-1",
    }
    return {**values, **overrides}


def test_record_error_sanitizes_secrets_and_deduplicates(monkeypatch):
    database = FakeFirestore()
    monkeypatch.setattr(system_logs, "firestore_client", lambda: database)
    monkeypatch.setattr(system_logs, "_recent_fingerprints", {})

    assert system_logs.record_error(**_record(message="Authorization: Bearer private-token")) is True
    assert system_logs.record_error(**_record(message="Authorization: Bearer private-token")) is False

    assert len(database.logs.documents) == 1
    assert database.logs.documents[0]["message"] == "Authorization: Bearer [REDACTED]"
    assert "private-token" not in repr(database.logs.documents[0])


@pytest.mark.parametrize(
    ("diagnostic", "visible_text"),
    [
        ("token=secret-token", "[REDACTED]"),
        ("key=secret-key", "[REDACTED]"),
        ('{"apiKey":"secret-api-key"}', "[REDACTED]"),
        ("password: super-secret", "[REDACTED]"),
        ("Authorization: Bearer auth-secret", "Bearer [REDACTED]"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "Basic [REDACTED]"),
        ("Cookie: session=private-cookie", "[REDACTED]"),
        ("https://example.test/path?access_token=secret%2Fvalue&page=2", "page=2"),
        (
            "https%3A%2F%2Fexample.test%2F%3Frefresh_token%3Dencoded%252Dsecret%26page%3D2",
            "%3Frefresh_token%3D%5BREDACTED%5D",
        ),
        ("firebase_api_key=AIzaSyDUMMYKEY012345678901234567890123456", "[REDACTED]"),
        ("private_key_id: key-id-secret", "[REDACTED]"),
        ("client_secret=oauth-client-secret", "[REDACTED]"),
        ("https://alice:url-password@example.test/path", "https://alice:[REDACTED]@"),
        (
            "id token eyJabcdefghijk.abcdefghijk.abcdefghijk",
            "id token [REDACTED]",
        ),
        ("oauth ya29.abcdefghijklmnopqrstuvwxyz012345", "oauth [REDACTED]"),
    ],
)
def test_sanitize_text_redacts_supported_credential_formats(diagnostic, visible_text):
    sanitized = system_logs.sanitize_text(diagnostic)

    assert visible_text in sanitized
    assert "secret-token" not in sanitized
    assert "secret-key" not in sanitized
    assert "secret-api-key" not in sanitized
    assert "super-secret" not in sanitized
    assert "auth-secret" not in sanitized
    assert "private-cookie" not in sanitized


def test_sanitizer_preserves_non_sensitive_debug_information():
    diagnostic = "GET /problems/two-sum?page=2&sort=recent returned 503"

    assert system_logs.sanitize_text(diagnostic) == diagnostic


def test_record_error_falls_back_to_sanitized_standard_logging(monkeypatch, caplog):
    class BrokenFirestore:
        def collection(self, _name):
            raise RuntimeError("access_token=private-token")

    monkeypatch.setattr(system_logs, "firestore_client", lambda: BrokenFirestore())
    monkeypatch.setattr(system_logs, "_recent_fingerprints", {})

    with caplog.at_level("ERROR", logger=system_logs.__name__):
        assert system_logs.record_error(**_record()) is False

    assert "system_log_persist_failed" in caplog.text
    assert "private-token" not in caplog.text


def test_cursor_validation_and_page_bounds():
    cursor = system_logs._encode_cursor("document-123")
    assert system_logs._decode_cursor(cursor) == "document-123"
    with pytest.raises(ValueError):
        system_logs._decode_cursor("not valid!")
    with pytest.raises(ValueError):
        system_logs.list_logs(page_size=51)
    with pytest.raises(ValueError):
        system_logs.get_log("../private")


def test_retention_window_is_logical_and_configurable(monkeypatch):
    monkeypatch.setenv("SYSTEM_LOG_RETENTION_DAYS", "14")
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)

    assert system_logs.retention_start(now) == now - timedelta(days=14)


def test_log_pagination_cursor_does_not_skip_the_extra_matching_record(monkeypatch):
    now = datetime.now(timezone.utc)
    snapshots = [
        FakeSnapshot(
            f"log-{index}",
            {
                "timestamp": now - timedelta(minutes=index),
                "source": "BACKEND",
                "severity": "ERROR",
                "resolutionStatus": "OPEN",
                "endpoint": f"/api/route-{index}",
                "message": "failure",
            },
        )
        for index in range(3)
    ]
    monkeypatch.setattr(system_logs, "firestore_client", lambda: PaginatedFirestore(snapshots))
    monkeypatch.setattr(system_logs, "_retention_days", lambda: 30)

    first_page = system_logs.list_logs(page_size=2)
    second_page = system_logs.list_logs(page_size=2, cursor=first_page["nextCursor"])

    assert [item["id"] for item in first_page["items"]] == ["log-0", "log-1"]
    assert "stackTrace" not in first_page["items"][0]
    assert first_page["nextCursor"] == system_logs._encode_cursor("log-1")
    assert [item["id"] for item in second_page["items"]] == ["log-2"]
    assert second_page["nextCursor"] is None


def test_resolve_log_records_the_authenticated_admin_and_keeps_detail(monkeypatch):
    document = MutableDocument("log-9", {
        "timestamp": datetime.now(timezone.utc),
        "source": "BACKEND",
        "message": "Failure",
        "stackTrace": "trace",
        "resolutionStatus": "OPEN",
    })
    monkeypatch.setattr(system_logs, "firestore_client", lambda: MutableFirestore(document))

    resolved = system_logs.resolve_log("log-9", "admin-3")

    assert resolved["resolutionStatus"] == "RESOLVED"
    assert resolved["resolvedBy"] == "admin-3"
    assert resolved["stackTrace"] == "trace"
    assert document.data["resolvedAt"] is not None


def test_frontend_stack_trace_is_sanitized_before_persistence(monkeypatch):
    database = FakeFirestore()
    monkeypatch.setattr(system_logs, "firestore_client", lambda: database)
    monkeypatch.setattr(system_logs, "_recent_fingerprints", {})

    system_logs.capture_error_from_request(
        source="FRONTEND",
        endpoint="/profile",
        method="GET",
        status=502,
        request_id="frontend-request-1",
        user_id="learner-1",
        message="Upstream returned token=message-secret",
        stack_trace="Error: failed?api_key=stack-secret\n at Profile (profile.js:12)",
    )

    event = database.logs.documents[0]
    assert event["message"] == "Upstream returned token=[REDACTED]"
    assert "stack-secret" not in event["stackTrace"]
    assert "api_key=[REDACTED]" in event["stackTrace"]
    assert "profile.js:12" in event["stackTrace"]


def test_frontend_request_id_is_sanitized_before_search_indexing(monkeypatch):
    database = FakeFirestore()
    monkeypatch.setattr(system_logs, "firestore_client", lambda: database)
    monkeypatch.setattr(system_logs, "_recent_fingerprints", {})

    system_logs.capture_error_from_request(
        source="FRONTEND",
        endpoint="/profile",
        method="GET",
        status=502,
        request_id="token=request-id-secret",
        user_id="learner-1",
        message="Request failed.",
    )

    event = database.logs.documents[0]
    assert event["requestId"] == "token=[REDACTED]"
    assert "request-id-secret" not in repr(event)
