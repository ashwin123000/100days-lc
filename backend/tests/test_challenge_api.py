import pytest
from fastapi.testclient import TestClient

from backend.app import main


TOKEN_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def authenticated_learner(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    monkeypatch.setattr(main, "get_learner_record", lambda uid: {
        "uid": uid,
        "role": "learner",
        "isActive": True,
    })


def test_challenge_routes_require_firebase_authentication():
    with TestClient(main.app) as client:
        response = client.get("/api/challenge/progress")
    assert response.status_code == 401


def test_learner_routes_use_authenticated_uid(authenticated_learner, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "get_challenge_questions", lambda uid: seen.append(uid) or {
        "challengeId": "leetcode-100-days",
        "totalDays": 100,
        "questions": [],
    })
    with TestClient(main.app) as client:
        response = client.get("/api/challenge/questions", headers=TOKEN_HEADERS)

    assert response.status_code == 200
    assert seen == ["learner-1"]


def test_leaderboard_requires_learner_authentication():
    with TestClient(main.app) as client:
        response = client.get("/api/leaderboard")
    assert response.status_code == 401


def test_leaderboard_rejects_invalid_firebase_token(monkeypatch):
    monkeypatch.setattr(
        main,
        "verify_id_token",
        lambda _token: (_ for _ in ()).throw(main.FirebaseTokenError("invalid")),
    )
    with TestClient(main.app) as client:
        response = client.get("/api/leaderboard", headers=TOKEN_HEADERS)
    assert response.status_code == 401


def test_leaderboard_rejects_administrator_profiles(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1"})
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: {
        "role": "admin",
        "isActive": True,
    })
    with TestClient(main.app) as client:
        response = client.get("/api/leaderboard", headers=TOKEN_HEADERS)
    assert response.status_code == 403


def test_leaderboard_uses_the_authenticated_learner_gate(authenticated_learner, monkeypatch):
    monkeypatch.setattr(main, "get_verified_challenge_leaderboard", lambda: {
        "scoringRule": "One point per distinct verified challenge day; tied scores share rank.",
        "totalLearners": 0,
        "learners": [],
    })
    with TestClient(main.app) as client:
        response = client.get("/api/leaderboard", headers=TOKEN_HEADERS)
    assert response.status_code == 200
    assert response.json()["totalLearners"] == 0


def test_challenge_sync_uses_connected_learner_and_refresh_flag(monkeypatch, authenticated_learner):
    profile = {
        "uid": "learner-1",
        "role": "learner",
        "isActive": True,
        "leetcodeUsername": "sample_user",
    }
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: profile.copy())
    profile_calls = []
    submission = {"problemSlug": "two-sum", "timestamp": 1794301200}
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda username, refresh=False: profile_calls.append((username, refresh)) or {
            "recentAcceptedSubmissions": [submission],
            "recentAcceptedAvailable": True,
        },
    )
    sync_calls = []
    monkeypatch.setattr(
        main,
        "sync_accepted_submissions",
        lambda uid, submissions, available: sync_calls.append((uid, submissions, available)) or {
            "status": "synchronized",
            "verifiedDays": [1],
            "newlyVerifiedDays": [1],
            "dayStatuses": {"1": "verified"},
        },
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/challenge/sync?refresh=true",
            headers=TOKEN_HEADERS,
        )

    assert response.status_code == 200
    assert profile_calls == [("sample_user", True)]
    assert sync_calls == [("learner-1", [submission], True)]
    assert response.json()["newlyVerifiedDays"] == [1]


def test_challenge_sync_without_username_waits_without_fetching_leetcode(authenticated_learner, monkeypatch):
    questions = [{
        "day": 7,
        "status": "not_started",
        "verificationStatus": "awaiting_sync",
    }]
    monkeypatch.setattr(main, "get_challenge_questions", lambda _uid: {"questions": questions})
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda *_args, **_kwargs: pytest.fail("unconnected account called LeetCode"),
    )

    with TestClient(main.app) as client:
        response = client.post("/api/challenge/sync", headers=TOKEN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "status": "awaiting_sync",
        "verifiedDays": [],
        "dayStatuses": {"7": "awaiting_sync"},
    }


def test_non_learner_cannot_read_challenge_routes(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1"})
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: {
        "uid": "admin-1",
        "role": "admin",
        "isActive": True,
    })
    with TestClient(main.app) as client:
        response = client.get("/api/challenge/questions", headers=TOKEN_HEADERS)
    assert response.status_code == 403


def test_challenge_progress_returns_an_empty_state_when_unconfigured(authenticated_learner, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_challenge_progress",
        lambda _uid: (_ for _ in ()).throw(main.ChallengeNotConfigured("Challenge is missing.")),
    )
    with TestClient(main.app) as client:
        response = client.get("/api/challenge/progress", headers=TOKEN_HEADERS)

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["totalDays"] == 100


def test_pending_review_queue_requires_firebase_authentication():
    with TestClient(main.app) as client:
        response = client.get("/api/admin/challenge/completions/pending")
    assert response.status_code == 401


def test_pending_review_queue_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/challenge/completions/pending",
            headers=TOKEN_HEADERS,
        )
    assert response.status_code == 403


def test_pending_review_queue_forwards_page_size_and_cursor_only_to_admin_service(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(
        main,
        "get_pending_challenge_completions",
        lambda page_size, cursor: captured.update(page_size=page_size, cursor=cursor) or {
            "items": [{
                "learnerUid": "learner-1",
                "learnerDisplayName": "Learner One",
                "day": 7,
                "problemTitle": "Two Sum",
                "leetcodeUrl": "https://leetcode.com/problems/two-sum/",
                "submittedAt": "2026-11-10T09:00:00Z",
                "reviewStatus": "pending",
            }],
            "nextCursor": "cursor-value",
            "pageSize": page_size,
        },
    )
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/challenge/completions/pending?pageSize=1&cursor=cursor-value",
            headers=TOKEN_HEADERS,
        )

    assert response.status_code == 200
    assert captured == {"page_size": 1, "cursor": "cursor-value"}
    assert response.json()["items"][0]["reviewStatus"] == "pending"
    assert response.json()["nextCursor"] == "cursor-value"


def test_pending_review_queue_validates_pagination_parameters(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/challenge/completions/pending?pageSize=101",
            headers=TOKEN_HEADERS,
        )
    assert response.status_code == 422


def test_admin_assignment_requires_admin_claim(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/challenge/days/1",
            headers=TOKEN_HEADERS,
            json={"problemSlug": "two-sum"},
        )
    assert response.status_code == 403


def test_challenge_initialization_requires_admin_claim(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    monkeypatch.setattr(
        main,
        "initialize_challenge",
        lambda *_args: pytest.fail("non-admin reached challenge initialization"),
    )
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/challenge/initialize",
            headers=TOKEN_HEADERS,
        )
    assert response.status_code == 403


def test_challenge_initialization_uses_verified_admin_uid(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    seen = []
    monkeypatch.setattr(
        main,
        "initialize_challenge",
        lambda admin_uid: seen.append(admin_uid) or {
            "challengeId": "leetcode-100-days",
            "title": "100 Days of LeetCode",
            "totalDays": 100,
            "publicationStatus": "published",
            "created": True,
        },
    )
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/challenge/initialize",
            headers=TOKEN_HEADERS,
        )
    assert response.status_code == 200
    assert seen == ["admin-1"]
    assert response.json()["created"] is True


def test_admin_assignment_uses_admin_uid_and_validated_problem_slug(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(
        main,
        "assign_challenge_day",
        lambda day, slug, admin_uid: captured.update(day=day, slug=slug, admin_uid=admin_uid) or {
            "day": day,
            "assignmentStatus": "assigned",
            "publicationStatus": "published",
        },
    )
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/challenge/days/42",
            headers=TOKEN_HEADERS,
            json={"problemSlug": "two-sum"},
        )
    assert response.status_code == 200
    assert captured == {"day": 42, "slug": "two-sum", "admin_uid": "admin-1"}


def test_assignment_rejects_invalid_problem_slug(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/challenge/days/1",
            headers=TOKEN_HEADERS,
            json={"problemSlug": "https://example.com"},
        )
    assert response.status_code == 422


def test_learner_report_cannot_request_verified_status(authenticated_learner):
    with TestClient(main.app) as client:
        response = client.put(
            "/api/challenge/days/1/completion",
            headers=TOKEN_HEADERS,
            json={"status": "verified"},
        )
    assert response.status_code == 422


def test_learner_report_rejects_client_supplied_identity(authenticated_learner):
    with TestClient(main.app) as client:
        response = client.put(
            "/api/challenge/days/1/completion",
            headers=TOKEN_HEADERS,
            json={"status": "pending", "uid": "victim"},
        )
    assert response.status_code == 422


def test_learner_report_passes_only_authenticated_uid(authenticated_learner, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "report_challenge_completion", lambda uid, day: seen.append((uid, day)) or {
        "day": day,
        "status": "pending",
        "verifiedCompletion": False,
    })
    with TestClient(main.app) as client:
        response = client.put(
            "/api/challenge/days/3/completion",
            headers=TOKEN_HEADERS,
            json={"status": "pending"},
        )
    assert response.status_code == 200
    assert seen == [("learner-1", 3)]


def test_review_requires_admin_and_uses_verified_reviewer_uid(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    monkeypatch.setattr(
        main,
        "review_challenge_completion",
        lambda uid, day, decision, reviewer_uid, note: captured.update(
            uid=uid, day=day, decision=decision, reviewer_uid=reviewer_uid, note=note,
        ) or {"status": decision},
    )
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/challenge/completions/learner-2/42",
            headers=TOKEN_HEADERS,
            json={"decision": "verified", "reviewNote": "Checked"},
        )
    assert response.status_code == 200
    assert captured == {
        "uid": "learner-2",
        "day": 42,
        "decision": "verified",
        "reviewer_uid": "admin-1",
        "note": "Checked",
    }


def test_review_rejects_extra_client_identity_field(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "admin-1", "admin": True})
    with TestClient(main.app) as client:
        response = client.put(
            "/api/admin/challenge/completions/learner-2/42",
            headers=TOKEN_HEADERS,
            json={"decision": "verified", "reviewerUid": "forged-admin"},
        )
    assert response.status_code == 422
