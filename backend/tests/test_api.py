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


def test_leetcode_upstream_errors_are_labeled_separately_from_backend_errors(monkeypatch):
    from backend.app.leetcode_service import LeetCodeUpstreamError

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
    assert response.headers["x-error-source"] == "leetcode_upstream"
    assert response.headers["x-request-id"]


def test_internal_service_errors_are_labeled_as_backend_errors(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(
        main,
        "registered_learner_count",
        lambda: (_ for _ in ()).throw(main.FirebaseServiceError("Firestore unavailable.")),
    )

    with TestClient(main.app) as client:
        response = client.get("/api/admin/learners/count", headers={"Authorization": "Bearer test"})

    assert response.status_code == 503
    assert response.headers["x-error-source"] == "backend"
    assert response.headers["x-request-id"]


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
