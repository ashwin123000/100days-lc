import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.problem_catalog import ProblemCatalog


ROWS = [
    {
        "questionFrontendId": "1",
        "questionTitle": "Two Sum",
        "TitleSlug": "two-sum",
        "content": "<p>Return the indices.</p>",
        "difficulty": "Easy",
    }
]


def fake_catalog():
    return ProblemCatalog(
        dataset_name="test/dataset",
        embedding_model="test/model",
        records_loader=lambda: ROWS,
    )


def test_potd_prepare_requires_firebase_id_token():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/potd/prepare",
            json={
                "title": "Two Sum",
                "leetcode_url": "https://leetcode.com/problems/two-sum/",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "A Firebase ID token is required."


def test_potd_prepare_rejects_non_admin_claim(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/potd/prepare",
            headers={"Authorization": "Bearer learner-token"},
            json={
                "title": "Two Sum",
                "leetcode_url": "https://leetcode.com/problems/two-sum/",
            },
        )

    assert response.status_code == 403


def test_admin_can_prepare_verified_dataset_problem(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(main, "catalog", fake_catalog())

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/potd/prepare",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "title": "Two Sum",
                "leetcode_url": "https://leetcode.com/problems/two-sum/",
            },
        )

    assert response.status_code == 200
    assert response.json()["problem_id"] == "1"
    assert response.json()["slug"] == "two-sum"
    assert response.json()["original_url"] == "https://leetcode.com/problems/two-sum/"


def test_publish_potd_requires_admin_and_persists_verified_record(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(main, "catalog", fake_catalog())

    def persist(record, url, solution, notes, published_by):
        captured.update({
            "record": record,
            "url": url,
            "solution": solution,
            "notes": notes,
            "published_by": published_by,
        })
        return {**record, "original_url": url, "solution": solution, "admin_notes": notes}

    monkeypatch.setattr(main, "publish_potd", persist)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/potd/publish",
            headers={"Authorization": "Bearer admin-token"},
            json={
                "title": "Two Sum",
                "leetcode_url": "https://leetcode.com/problems/two-sum/",
                "solution": "Use a hash map.",
                "admin_notes": "Think about complement values.",
            },
        )

    assert response.status_code == 200
    assert response.json()["problem"]["problem_id"] == "1"
    assert captured["published_by"] == "admin-1"
    assert captured["solution"] == "Use a hash map."
    assert captured["notes"] == "Think about complement values."


def test_invalid_problem_url_is_rejected_without_firebase():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/problems/lookup",
            json={"title": "Two Sum", "leetcode_url": "https://example.com/problems/two-sum/"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_leetcode_url"


def test_legacy_public_potd_write_endpoint_is_removed():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/potd",
            json={
                "title": "Two Sum",
                "leetcode_url": "https://leetcode.com/problems/two-sum/",
            },
        )

    assert response.status_code == 405


def test_api_responses_include_request_id_for_production_diagnostics():
    with TestClient(main.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_leetcode_upstream_errors_are_labeled_with_graphql_source(monkeypatch):
    from backend.app.leetcode_service import LeetCodeUpstreamError

    captured = []
    monkeypatch.setattr(main.system_logs, "capture_error_from_request", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    monkeypatch.setattr(
        main,
        "get_learner_record",
        lambda _uid: {"role": "learner", "isActive": True, "leetcodeUsername": "sample_user"},
    )
    monkeypatch.setattr(main, "leetcode_request_limiter", main.LearnerRequestLimiter())
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LeetCodeUpstreamError("LeetCode GraphQL reported an error.")
        ),
    )

    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/profile", headers={"Authorization": "Bearer test"})

    assert response.status_code == 502
    assert response.headers["x-error-source"] == "LEETCODE_GRAPHQL"
    assert response.headers["x-request-id"]
    assert captured[0]["source"] == "LEETCODE_GRAPHQL"
    assert captured[0]["request_id"] == response.headers["x-request-id"]


def test_firestore_errors_are_labeled_with_firestore_source(monkeypatch):
    captured = []
    monkeypatch.setattr(main.system_logs, "capture_error_from_request", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(
        main,
        "registered_learner_count",
        lambda: (_ for _ in ()).throw(main.FirebaseServiceError("Firestore unavailable.")),
    )

    with TestClient(main.app) as client:
        response = client.get("/api/admin/learners/count", headers={"Authorization": "Bearer test"})

    assert response.status_code == 503
    assert response.headers["x-error-source"] == "FIRESTORE"
    assert response.headers["x-request-id"]
    assert captured[0]["source"] == "FIRESTORE"


def test_leetcode_network_errors_are_labeled_separately(monkeypatch):
    from backend.app.leetcode_service import LeetCodeUpstreamTimeout

    captured = []
    monkeypatch.setattr(main.system_logs, "capture_error_from_request", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    monkeypatch.setattr(
        main,
        "get_learner_record",
        lambda _uid: {"role": "learner", "isActive": True, "leetcodeUsername": "sample_user"},
    )
    monkeypatch.setattr(main, "leetcode_request_limiter", main.LearnerRequestLimiter())
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(LeetCodeUpstreamTimeout("LeetCode timed out.")),
    )

    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/profile", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 504
    assert response.headers["x-error-source"] == "LEETCODE_NETWORK"
    assert captured[0]["source"] == "LEETCODE_NETWORK"


def test_learner_count_is_available_only_to_admin(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(main, "registered_learner_count", lambda: 23)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/learners/count",
            headers={"Authorization": "Bearer admin-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"count": 23}


def test_system_logs_api_requires_admin_claim(monkeypatch):
    captured = []
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    monkeypatch.setattr(main.system_logs, "capture_error_from_request", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(
        main.system_logs,
        "list_logs",
        lambda **_kwargs: pytest.fail("non-admin reached the system log query"),
    )

    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/system-logs",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 403
    assert response.headers["x-error-source"] == "AUTH"
    assert captured[0]["source"] == "AUTH"
    assert captured[0]["user_id"] == "learner-1"


def test_admin_can_list_system_logs_with_filters(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})

    def list_logs(**kwargs):
        captured.update(kwargs)
        return {
            "items": [{"id": "log-1", "source": "FIRESTORE"}],
            "nextCursor": "cursor-2",
            "summary": {"total": 2, "critical": 0, "warnings": 1, "unresolved": 2},
            "retentionDays": 30,
            "scanLimitReached": False,
        }

    monkeypatch.setattr(main.system_logs, "list_logs", list_logs)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/system-logs?pageSize=10&source=FIRESTORE&search=unavailable",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "log-1"
    assert captured["page_size"] == 10
    assert captured["source"] == "FIRESTORE"
    assert captured["search"] == "unavailable"


def test_resolving_system_log_uses_verified_admin_uid(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-7", "admin": True})
    monkeypatch.setattr(
        main.system_logs,
        "resolve_log",
        lambda log_id, admin_uid: captured.update(log_id=log_id, admin_uid=admin_uid) or {
            "id": log_id,
            "resolutionStatus": "RESOLVED",
        },
    )

    with TestClient(main.app) as client:
        response = client.patch(
            "/api/admin/system-logs/log-5/resolve",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["resolutionStatus"] == "RESOLVED"
    assert captured == {"log_id": "log-5", "admin_uid": "admin-7"}


def test_authenticated_client_error_is_logged_with_server_uid(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-2"})
    monkeypatch.setattr(main.frontend_error_limiter, "check", lambda _uid: True)
    monkeypatch.setattr(
        main.system_logs,
        "capture_error_from_request",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/client-errors",
            headers={"Authorization": "Bearer test-token"},
            json={
                "operation": "unhandled_promise_rejection",
                "endpoint": "/profile",
                "message": "Client rendering failed.",
                "stackTrace": "at App (app.jsx:1)",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert captured["source"] == "FRONTEND"
    assert captured["user_id"] == "learner-2"
    assert captured["endpoint"] == "/profile"
    assert captured["error_code"] == "unhandled_promise_rejection"


def test_client_error_endpoint_rejects_external_endpoint_urls(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-2"})
    monkeypatch.setattr(main.frontend_error_limiter, "check", lambda _uid: True)
    monkeypatch.setattr(
        main.system_logs,
        "capture_error_from_request",
        lambda **_kwargs: pytest.fail("invalid endpoint was logged"),
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/client-errors",
            headers={"Authorization": "Bearer test-token"},
            json={
                "operation": "window_runtime_error",
                "endpoint": "https://example.com",
                "message": "Failure",
            },
        )

    assert response.status_code == 422


def test_unhandled_backend_errors_are_logged_and_return_request_id(monkeypatch):
    captured = []
    monkeypatch.setattr(
        main.system_logs,
        "capture_error_from_request",
        lambda **kwargs: captured.append(kwargs),
    )

    def fail_request():
        raise RuntimeError("Unexpected internal failure.")

    main.app.add_api_route("/api/test/unexpected-error", fail_request, methods=["GET"])
    route = next(
        route for route in main.app.router.routes
        if getattr(route, "path", None) == "/api/test/unexpected-error"
    )
    try:
        with TestClient(main.app) as client:
            response = client.get("/api/test/unexpected-error")
    finally:
        main.app.router.routes.remove(route)

    assert response.status_code == 500
    assert response.headers["x-error-source"] == "BACKEND"
    assert response.headers["x-request-id"]
    assert captured[0]["source"] == "BACKEND"
    assert captured[0]["error_code"] == "RuntimeError"
