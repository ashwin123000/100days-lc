import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import leetcode_service, main
from backend.app.leetcode_service import (
    CALENDAR_CACHE_TTL_SECONDS,
    CALENDAR_QUERY,
    PROFILE_CACHE_TTL_SECONDS,
    PROFILE_QUERY,
    LearnerRequestLimiter,
    LeetCodeCalendarUnavailable,
    LeetCodeProfileNotFound,
    LeetCodeService,
    LeetCodeUpstreamError,
    LeetCodeUpstreamRateLimited,
    LeetCodeUpstreamTimeout,
    _normalize_submission_calendar,
    summarize_activity,
)


TOKEN_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def learner(monkeypatch):
    profile = {
        "uid": "learner-1",
        "role": "learner",
        "isActive": True,
        "leetcodeUsername": "sample_user",
    }
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-1"})
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: profile.copy())
    monkeypatch.setattr(main, "leetcode_request_limiter", LearnerRequestLimiter())
    return profile


def _profile_result(username="sample_user"):
    return {
        "profile": {
            "username": username,
            "avatarUrl": None,
            "displayName": "Sample User",
            "profileUrl": f"https://leetcode.com/u/{username}/",
        },
        "problemStatistics": {
            "totalSolved": 6,
            "easy": {"solved": 2, "total": None},
            "medium": {"solved": 3, "total": None},
            "hard": {"solved": 1, "total": None},
            "contestRating": None,
            "ranking": None,
            "totalSubmissions": 10,
            "acceptedSubmissions": None,
        },
        "recentAcceptedSlugs": ["two-sum"],
        "recentAcceptedSubmissions": [],
        "recentAcceptedAvailable": False,
    }


def _challenge_questions(*questions):
    return {
        "challengeId": "leetcode-100-days",
        "totalDays": 100,
        "questions": list(questions),
    }


def test_connect_validates_username_and_persists_authenticated_uid(monkeypatch, learner):
    captured = {}
    monkeypatch.setattr(main.leetcode_service, "get_profile", lambda username, refresh=False: _profile_result(username))
    monkeypatch.setattr(
        main,
        "connect_leetcode_username",
        lambda uid, username: captured.update(uid=uid, username=username),
    )
    monkeypatch.setattr(main, "sync_accepted_submissions", lambda *_args: {
        "status": "synchronized",
        "verifiedDays": [],
        "newlyVerifiedDays": [],
        "dayStatuses": {"1": "unable_to_verify"},
    })
    monkeypatch.setattr(main, "get_challenge_questions", lambda _uid: _challenge_questions({
        "day": 1,
        "title": "Two Sum",
        "slug": "two-sum",
        "leetcodeUrl": "https://leetcode.com/problems/two-sum/",
        "difficulty": "Easy",
        "status": "not_started",
        "verifiedCompletion": False,
        "verificationStatus": "awaiting_sync",
    }, {
        "day": 2,
        "title": "Valid Parentheses",
        "slug": "valid-parentheses",
        "leetcodeUrl": "https://leetcode.com/problems/valid-parentheses/",
        "difficulty": "Easy",
        "status": "not_started",
        "verifiedCompletion": False,
        "verificationStatus": "awaiting_sync",
    }))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/leetcode/connect",
            headers=TOKEN_HEADERS,
            json={"username": " sample_user "},
        )

    assert response.status_code == 200
    assert captured == {"uid": "learner-1", "username": "sample_user"}
    body = response.json()
    assert body["profile"]["username"] == "sample_user"
    assert body["problemStatistics"]["totalSolved"] == 6
    assert body["challengeRecords"][0]["completionStatus"] == "awaiting_sync"
    assert body["challengeRecords"][0]["verifiedCompletion"] is False
    assert body["challengeRecords"][1]["completionStatus"] == "awaiting_sync"
    assert body["challengeSync"]["status"] == "synchronized"


def test_connect_reports_partial_success_when_challenge_storage_is_unavailable(monkeypatch, learner):
    connected = []
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda username, refresh=False: _profile_result(username),
    )
    monkeypatch.setattr(
        main,
        "connect_leetcode_username",
        lambda uid, username: connected.append((uid, username)),
    )
    monkeypatch.setattr(
        main,
        "sync_accepted_submissions",
        lambda *_args: (_ for _ in ()).throw(main.FirebaseServiceError("Firestore unavailable.")),
    )
    monkeypatch.setattr(
        main,
        "get_challenge_questions",
        lambda _uid: (_ for _ in ()).throw(main.FirebaseServiceError("Firestore unavailable.")),
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/leetcode/connect",
            headers=TOKEN_HEADERS,
            json={"username": "sample_user"},
        )

    assert response.status_code == 200
    assert connected == [("learner-1", "sample_user")]
    assert response.json()["profile"]["username"] == "sample_user"
    assert response.json()["challengeSync"]["status"] == "unable_to_verify"
    assert response.json()["challengeRecords"] == []


def test_connect_rejects_invalid_username_before_upstream_call(monkeypatch, learner):
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda *_args, **_kwargs: pytest.fail("invalid username reached the upstream service"),
    )
    with TestClient(main.app) as client:
        response = client.post(
            "/api/leetcode/connect",
            headers=TOKEN_HEADERS,
            json={"username": "bad/username"},
        )
    assert response.status_code == 422


def test_connect_requires_firebase_authentication():
    with TestClient(main.app) as client:
        response = client.post("/api/leetcode/connect", json={"username": "sample_user"})
    assert response.status_code == 401


def test_connect_returns_not_found_for_unknown_public_profile(monkeypatch, learner):
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(LeetCodeProfileNotFound("not found")),
    )
    with TestClient(main.app) as client:
        response = client.post(
            "/api/leetcode/connect",
            headers=TOKEN_HEADERS,
            json={"username": "missing_user"},
        )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "leetcode_profile_not_found"


def test_profile_reads_only_the_authenticated_learners_link(monkeypatch, learner):
    seen = []
    monkeypatch.setattr(main.leetcode_service, "get_profile", lambda username, refresh=False: seen.append(username) or _profile_result(username))
    monkeypatch.setattr(main, "get_challenge_questions", lambda _uid: _challenge_questions())
    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/profile", headers=TOKEN_HEADERS)
    assert response.status_code == 200
    assert seen == ["sample_user"]
    assert response.json()["profile"]["username"] == "sample_user"


def test_profile_refresh_runs_verification_and_returns_updated_challenge_records(monkeypatch, learner):
    profile_calls = []
    submission = {"problemSlug": "two-sum", "timestamp": 1794301200}
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda username, refresh=False: profile_calls.append((username, refresh)) or {
            **_profile_result(username),
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
    questions = [
        _challenge_questions({
            "day": 1,
            "title": "Two Sum",
            "slug": "two-sum",
            "leetcodeUrl": "https://leetcode.com/problems/two-sum/",
            "difficulty": "Easy",
            "status": "not_started",
            "verifiedCompletion": False,
            "verificationStatus": "awaiting_sync",
        }),
        _challenge_questions({
            "day": 1,
            "title": "Two Sum",
            "slug": "two-sum",
            "leetcodeUrl": "https://leetcode.com/problems/two-sum/",
            "difficulty": "Easy",
            "status": "verified",
            "verifiedCompletion": True,
            "verificationStatus": "verified",
        }),
    ]
    question_reads = []
    monkeypatch.setattr(
        main,
        "get_challenge_questions",
        lambda _uid: question_reads.append(True) or questions[len(question_reads) - 1],
    )

    with TestClient(main.app) as client:
        response = client.get(
            "/api/leetcode/profile?refresh=true",
            headers=TOKEN_HEADERS,
        )

    assert response.status_code == 200
    assert profile_calls == [("sample_user", True), ("sample_user", False)]
    assert sync_calls == [("learner-1", [submission], True)]
    assert response.json()["challengeSync"]["newlyVerifiedDays"] == [1]
    assert response.json()["challengeRecords"][0]["completionStatus"] == "verified"


def test_learner_cannot_read_another_users_connection(monkeypatch):
    monkeypatch.setattr(main, "verify_id_token", lambda _token: {"uid": "learner-2"})
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: {
        "uid": "learner-2", "role": "learner", "isActive": True, "leetcodeUsername": "other_account",
    })
    monkeypatch.setattr(main, "leetcode_request_limiter", LearnerRequestLimiter())
    seen = []
    monkeypatch.setattr(main.leetcode_service, "get_profile", lambda username, refresh=False: seen.append(username) or _profile_result(username))
    monkeypatch.setattr(main, "get_challenge_questions", lambda _uid: _challenge_questions())
    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/profile", headers=TOKEN_HEADERS)
    assert response.status_code == 200
    assert seen == ["other_account"]


def test_profile_returns_not_connected_for_learner_without_link(monkeypatch, learner):
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: {"role": "learner", "isActive": True})
    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/profile", headers=TOKEN_HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "leetcode_not_connected"


def test_non_learner_cannot_use_learner_endpoints(monkeypatch, learner):
    monkeypatch.setattr(main, "get_learner_record", lambda _uid: {
        "role": "admin", "isActive": True,
    })
    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/profile", headers=TOKEN_HEADERS)
    assert response.status_code == 403


def test_conflicting_username_claim_returns_conflict(monkeypatch, learner):
    monkeypatch.setattr(main.leetcode_service, "get_profile", lambda username, refresh=False: _profile_result(username))
    monkeypatch.setattr(
        main,
        "connect_leetcode_username",
        lambda *_args: (_ for _ in ()).throw(main.LeetCodeUsernameAlreadyClaimed("already connected")),
    )
    with TestClient(main.app) as client:
        response = client.post(
            "/api/leetcode/connect",
            headers=TOKEN_HEADERS,
            json={"username": "sample_user"},
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "leetcode_username_in_use"


def test_disconnect_only_disassociates_authenticated_learner(monkeypatch, learner):
    disconnected = []
    monkeypatch.setattr(main, "disconnect_leetcode_username", lambda uid: disconnected.append(uid) or True)
    with TestClient(main.app) as client:
        response = client.delete("/api/leetcode/connect", headers=TOKEN_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"connected": False}
    assert disconnected == ["learner-1"]


def test_heatmap_fills_confirmed_inactive_dates_and_limits_range(monkeypatch, learner):
    monkeypatch.setattr(
        main.leetcode_service,
        "get_calendar",
        lambda username, start, end, refresh=False: [
            {"date": "2026-01-01", "submissions": 2, "accepted": None},
            {"date": "2026-01-02", "submissions": 0, "accepted": None},
        ],
    )
    monkeypatch.setattr(
        main.leetcode_service,
        "get_calendar_metadata",
        lambda *_args: {"availableYears": [2025, 2026], "currentStreak": 2, "totalActiveDays": 19},
    )
    with TestClient(main.app) as client:
        response = client.get(
            "/api/leetcode/heatmap?from=2026-01-01&to=2026-01-02",
            headers=TOKEN_HEADERS,
        )
        invalid = client.get(
            "/api/leetcode/heatmap?from=2025-01-01&to=2026-01-02",
            headers=TOKEN_HEADERS,
        )
    assert response.status_code == 200
    assert response.json()["calendar"][1]["submissions"] == 0
    assert response.json()["calendar"][0]["accepted"] is None
    assert response.json()["availableYears"] == [2025, 2026]
    assert invalid.status_code == 422


def test_stats_distinguish_submissions_from_unique_solved(monkeypatch, learner):
    monkeypatch.setattr(main.leetcode_service, "get_profile", lambda _username, refresh=False: _profile_result())
    monkeypatch.setattr(
        main.leetcode_service,
        "get_calendar",
        lambda *_args, **_kwargs: [
            {"date": "2026-01-01", "submissions": 2, "accepted": None},
            {"date": "2026-01-02", "submissions": 1, "accepted": None},
            {"date": "2026-01-03", "submissions": 0, "accepted": None},
        ],
    )
    monkeypatch.setattr(
        main.leetcode_service,
        "get_calendar_metadata",
        lambda *_args: {"availableYears": [2025, 2026], "currentStreak": 3, "totalActiveDays": 22},
    )
    with TestClient(main.app) as client:
        response = client.get("/api/leetcode/stats", headers=TOKEN_HEADERS)
    assert response.status_code == 200
    assert response.json()["problemStatistics"]["totalSolved"] == 6
    assert response.json()["activity"]["totalSubmissions"] == 3
    assert response.json()["activity"]["currentStreak"] == 3
    assert response.json()["activity"]["totalActiveDays"] == 22
    assert response.json()["activity"]["longestStreak"] is None
    assert response.json()["activity"]["acceptedSubmissions"] is None


def test_normalizes_profile_statistics_without_fabricating_missing_values(monkeypatch):
    service = LeetCodeService()
    responses = iter([
        {
            "matchedUser": {
                "username": "sample_user",
                "profile": {
                    "realName": "Sample User",
                    "userAvatar": "https://evil.example/avatar.png",
                    "ranking": 42,
                    "reputation": 7,
                    "countryName": "Canada",
                    "countryCode": "CA",
                },
                "submitStats": {
                    "acSubmissionNum": [
                        {"difficulty": "All", "count": 6},
                        {"difficulty": "Easy", "count": 2},
                        {"difficulty": "Medium", "count": 3},
                        {"difficulty": "Hard", "count": 1},
                    ],
                    "totalSubmissionNum": [{"difficulty": "All", "count": 10}],
                },
            }
        },
        {"userContestRanking": {
            "rating": 1500,
            "globalRanking": 12,
            "attendedContestsCount": 22,
            "topPercentage": 1.5,
        }},
        {"recentAcSubmissionList": []},
    ])
    monkeypatch.setattr(leetcode_service, "_graphql_request", lambda *_args: next(responses))
    profile = service.get_profile("sample_user")
    assert profile["profile"]["displayName"] == "Sample User"
    assert profile["profile"]["avatarUrl"] is None
    assert profile["profile"]["ranking"] == 42
    assert profile["profile"]["reputation"] == 7
    assert profile["profile"]["countryName"] == "Canada"
    assert profile["profile"]["countryCode"] == "CA"
    assert profile["problemStatistics"]["totalSolved"] == 6
    assert profile["problemStatistics"]["totalSubmissions"] == 10
    assert profile["problemStatistics"]["acceptedSubmissions"] is None
    assert profile["problemStatistics"]["contestRating"] == 1500
    assert profile["problemStatistics"]["ranking"] == 42
    assert profile["contestStatistics"] == {
        "rating": 1500.0,
        "globalRanking": 12,
        "attendedContestsCount": 22,
        "topPercentage": 1.5,
    }
    assert profile["recentAcceptedAvailable"] is True
    assert profile["recentAcceptedSubmissions"] == []


def test_normalizes_recent_accepted_submissions_and_ignores_invalid_entries(monkeypatch):
    service = LeetCodeService()
    responses = iter([
        {
            "matchedUser": {
                "username": "sample_user",
                "profile": {},
                "submitStats": {"acSubmissionNum": [], "totalSubmissionNum": []},
            }
        },
        {"userContestRanking": None},
        {"recentAcSubmissionList": [
            {"id": 123, "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1762765200"},
            {"id": "456", "title": "Valid Parentheses", "titleSlug": "valid-parentheses", "timestamp": 1762765260},
            {"id": "bad", "titleSlug": "../two-sum", "timestamp": 1762765260},
            {"id": "bad", "titleSlug": "add-two-numbers", "timestamp": "not-a-time"},
        ]},
    ])
    monkeypatch.setattr(leetcode_service, "_graphql_request", lambda *_args: next(responses))

    profile = service.get_profile("sample_user")

    assert profile["recentAcceptedAvailable"] is True
    assert profile["recentAcceptedSubmissions"] == [
        {"problemSlug": "two-sum", "timestamp": 1762765200, "problemTitle": "Two Sum", "submissionId": "123"},
        {"problemSlug": "valid-parentheses", "timestamp": 1762765260, "problemTitle": "Valid Parentheses", "submissionId": "456"},
    ]
    assert profile["recentAcceptedSlugs"] == ["two-sum", "valid-parentheses"]


def test_graphql_nonexistent_profile_error_maps_to_profile_not_found(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"errors":[{"message":"That user does not exist."}],"data":{"matchedUser":null}}'

    monkeypatch.setattr(leetcode_service, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    with pytest.raises(LeetCodeProfileNotFound):
        leetcode_service._graphql_request(PROFILE_QUERY, {"username": "missing_user"})


def test_graphql_error_response_is_logged_without_username(monkeypatch, caplog):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"errors":[{"message":"query failed"}],"data":null}'

    monkeypatch.setattr(leetcode_service, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    with caplog.at_level(logging.WARNING, logger=leetcode_service.__name__):
        with pytest.raises(LeetCodeUpstreamError):
            leetcode_service._graphql_request(PROFILE_QUERY, {"username": "private_user"})

    assert "leetcode_graphql_response_error operation=publicProfile category=graphql_errors" in caplog.text
    assert "private_user" not in caplog.text


def test_graphql_calendar_permission_error_maps_to_specific_upstream_error(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"errors":[{"message":"no permission to check the calendar."}],"data":{"matchedUser":null}}'

    monkeypatch.setattr(leetcode_service, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    with pytest.raises(LeetCodeCalendarUnavailable) as error:
        leetcode_service._graphql_request(
            CALENDAR_QUERY,
            {"username": "sample_user", "year": 2026},
        )

    assert error.value.status_code == 503
    assert error.value.code == "leetcode_calendar_unavailable"
    assert "does not permit public access" in str(error.value)


def test_stats_preserves_profile_data_when_calendar_is_unavailable(monkeypatch, learner):
    monkeypatch.setattr(
        main.leetcode_service,
        "get_profile",
        lambda *_args, **_kwargs: _profile_result(),
    )
    monkeypatch.setattr(
        main.leetcode_service,
        "get_calendar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LeetCodeCalendarUnavailable(
                "LeetCode does not permit public access to this submission calendar."
            )
        ),
    )

    with TestClient(main.app) as client:
        stats = client.get("/api/leetcode/stats", headers=TOKEN_HEADERS)

    assert stats.status_code == 200
    assert stats.json()["problemStatistics"]["totalSolved"] == 6
    assert stats.json()["activity"] is None
    assert stats.json()["activityError"]["code"] == "leetcode_calendar_unavailable"
    assert stats.json()["unavailableFields"] == ["activity"]


def test_heatmap_surfaces_calendar_permission_failure(monkeypatch, learner):
    monkeypatch.setattr(
        main.leetcode_service,
        "get_calendar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LeetCodeCalendarUnavailable(
                "LeetCode does not permit public access to this submission calendar."
            )
        ),
    )

    with TestClient(main.app) as client:
        heatmap = client.get(
            "/api/leetcode/heatmap?from=2026-01-01&to=2026-01-02",
            headers=TOKEN_HEADERS,
        )

    assert heatmap.status_code == 503
    assert heatmap.json()["detail"]["code"] == "leetcode_calendar_unavailable"
    assert "does not permit public access" in heatmap.json()["detail"]["message"]


def test_normalizes_heatmap_counts_and_rejects_malformed_entries():
    timestamp = 1767225600
    assert _normalize_submission_calendar(json.dumps({str(timestamp): "3"})) == {
        "2026-01-01": 3,
    }
    with pytest.raises(LeetCodeUpstreamError):
        _normalize_submission_calendar('{"1767225600": "not-a-count"}')


def test_calendar_cache_avoids_duplicate_graphql_request(monkeypatch):
    service = LeetCodeService()
    calls = []
    monkeypatch.setattr(
        leetcode_service,
        "_graphql_request",
        lambda query, _variables: calls.append(query) or {
            "matchedUser": {"userCalendar": {
                "activeYears": [2025, 2026],
                "streak": 4,
                "totalActiveDays": 60,
                "submissionCalendar": "{}",
            }}
        },
    )
    first = service.get_calendar("sample_user", date(2026, 1, 1), date(2026, 1, 2))
    second = service.get_calendar("sample_user", date(2026, 1, 1), date(2026, 1, 2))
    assert first == second
    assert calls == [CALENDAR_QUERY]
    assert service.get_calendar_metadata("sample_user", {2026}) == {
        "availableYears": [2025, 2026],
        "currentStreak": 4,
        "totalActiveDays": 60,
    }


def test_profile_cache_hit_and_refresh(monkeypatch):
    service = LeetCodeService()
    calls = []
    profile_payload = {
        "matchedUser": {
            "username": "sample_user",
            "profile": {},
            "submitStats": {"acSubmissionNum": [], "totalSubmissionNum": []},
        }
    }
    responses = iter([profile_payload, {"userContestRanking": None}, {"recentAcSubmissionList": []}] * 2)
    monkeypatch.setattr(
        leetcode_service,
        "_graphql_request",
        lambda query, _variables: calls.append(query) or next(responses),
    )
    service.get_profile("sample_user")
    service.get_profile("sample_user")
    assert len(calls) == 3
    service.get_profile("sample_user", refresh=True)
    assert len(calls) == 6


def test_failed_profile_refresh_preserves_the_previous_cache_entry(monkeypatch):
    service = LeetCodeService()
    calls = []

    def fetch_profile(_username):
        calls.append(1)
        if len(calls) == 1:
            return {"profile": {"username": "sample_user", "ranking": 42}}
        raise LeetCodeUpstreamError("upstream unavailable")

    monkeypatch.setattr(service, "_fetch_profile", fetch_profile)
    original = service.get_profile("sample_user")

    with pytest.raises(LeetCodeUpstreamError):
        service.get_profile("sample_user", refresh=True)

    assert service.get_profile("sample_user") is original
    assert len(calls) == 2


def test_concurrent_refreshes_share_one_profile_request(monkeypatch):
    service = LeetCodeService()
    started = threading.Event()
    calls = []

    def fetch(username):
        calls.append(username)
        started.set()
        time.sleep(0.05)
        return {"profile": {"username": username}}

    monkeypatch.setattr(service, "_fetch_profile", fetch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.get_profile, "sample_user", True)
        assert started.wait(timeout=1)
        second = executor.submit(service.get_profile, "sample_user", True)
        assert first.result(timeout=2) == second.result(timeout=2)
    assert calls == ["sample_user"]


def test_profile_cache_expires(monkeypatch):
    service = LeetCodeService()
    now = [10.0]
    calls = []
    monkeypatch.setattr(leetcode_service.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        service,
        "_fetch_profile",
        lambda username: calls.append(username) or {"profile": {"username": username}},
    )
    service.get_profile("sample_user")
    now[0] += PROFILE_CACHE_TTL_SECONDS + 1
    service.get_profile("sample_user")
    assert calls == ["sample_user", "sample_user"]


def test_calendar_cache_expires(monkeypatch):
    service = LeetCodeService()
    now = [10.0]
    calls = []
    monkeypatch.setattr(leetcode_service.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        leetcode_service,
        "_graphql_request",
        lambda *_args: calls.append(1) or {
            "matchedUser": {"userCalendar": {"submissionCalendar": "{}"}}
        },
    )
    service.get_calendar("sample_user", date(2026, 1, 1), date(2026, 1, 1))
    now[0] += CALENDAR_CACHE_TTL_SECONDS + 1
    service.get_calendar("sample_user", date(2026, 1, 1), date(2026, 1, 1))
    assert len(calls) == 2


def test_upstream_timeout_graphql_error_and_rate_limit_are_explicit(monkeypatch):
    service = LeetCodeService()

    monkeypatch.setattr(
        leetcode_service,
        "_graphql_request",
        lambda *_args: (_ for _ in ()).throw(LeetCodeUpstreamTimeout("timed out")),
    )
    with pytest.raises(LeetCodeUpstreamTimeout):
        service.get_profile("timeout_user")

    monkeypatch.setattr(
        leetcode_service,
        "_graphql_request",
        lambda *_args: (_ for _ in ()).throw(LeetCodeUpstreamError("GraphQL error")),
    )
    with pytest.raises(LeetCodeUpstreamError):
        service.get_profile("graphql_user")

    monkeypatch.setattr(
        leetcode_service,
        "_graphql_request",
        lambda *_args: (_ for _ in ()).throw(LeetCodeUpstreamRateLimited("rate limited")),
    )
    with pytest.raises(LeetCodeUpstreamRateLimited):
        service.get_profile("rate_user")


def test_graphql_transport_handles_timeout_and_error_payload(monkeypatch):
    class FakeResponse:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    monkeypatch.setattr(
        leetcode_service,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )
    with pytest.raises(LeetCodeUpstreamTimeout):
        leetcode_service._graphql_request(PROFILE_QUERY, {"username": "sample_user"})

    monkeypatch.setattr(
        leetcode_service,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"errors":[{"message":"query failed"}],"data":null}'),
    )
    with pytest.raises(LeetCodeUpstreamError):
        leetcode_service._graphql_request(PROFILE_QUERY, {"username": "sample_user"})

    monkeypatch.setattr(
        leetcode_service,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            b'{"errors":[{"message":"Too many requests"}],"data":null}'
        ),
    )
    with pytest.raises(LeetCodeUpstreamRateLimited):
        leetcode_service._graphql_request(PROFILE_QUERY, {"username": "sample_user"})

    monkeypatch.setattr(
        leetcode_service,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"not-json"),
    )
    with pytest.raises(LeetCodeUpstreamError, match="malformed JSON"):
        leetcode_service._graphql_request(PROFILE_QUERY, {"username": "sample_user"})


def test_graphql_transport_retries_transient_gateway_failure(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"data":{"matchedUser":{"username":"sample_user"}}}'

    responses = iter([
        leetcode_service.HTTPError(
            leetcode_service.GRAPHQL_URL,
            502,
            "Bad Gateway",
            {},
            None,
        ),
        FakeResponse(),
    ])
    calls = []

    def fake_urlopen(*_args, **_kwargs):
        calls.append(True)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(leetcode_service, "urlopen", fake_urlopen)
    monkeypatch.setattr(leetcode_service.time, "sleep", lambda _delay: None)

    result = leetcode_service._graphql_request(PROFILE_QUERY, {"username": "sample_user"})

    assert result == {"matchedUser": {"username": "sample_user"}}
    assert len(calls) == 2


def test_graphql_transport_stops_after_one_gateway_retry(monkeypatch):
    calls = []

    def fail_with_gateway_error(*_args, **_kwargs):
        calls.append(True)
        raise leetcode_service.HTTPError(
            leetcode_service.GRAPHQL_URL,
            502,
            "Bad Gateway",
            {},
            None,
        )

    monkeypatch.setattr(leetcode_service, "urlopen", fail_with_gateway_error)
    monkeypatch.setattr(leetcode_service.time, "sleep", lambda _delay: None)

    with pytest.raises(LeetCodeUpstreamError):
        leetcode_service._graphql_request(PROFILE_QUERY, {"username": "sample_user"})

    assert len(calls) == 2


def test_limiter_blocks_after_configured_window_limit():
    limiter = LearnerRequestLimiter(limit=2, window_seconds=60)
    assert limiter.check("learner-1")
    assert limiter.check("learner-1")
    assert not limiter.check("learner-1")
    assert limiter.check("learner-2")


def test_activity_summary_does_not_infer_accepted_submissions():
    activity = summarize_activity([
        {"date": "2026-01-01", "submissions": 1, "accepted": None},
        {"date": "2026-01-02", "submissions": 2, "accepted": None},
        {"date": "2026-01-03", "submissions": 0, "accepted": None},
    ])
    assert activity["totalSubmissions"] == 3
    assert activity["activeDays"] == 2
    assert activity["longestStreak"] == 2
    assert activity["currentStreak"] == 0
    assert activity["acceptedSubmissions"] is None


def test_current_streak_allows_today_to_be_incomplete():
    today = datetime.now(timezone.utc).date()
    yesterday = date.fromordinal(today.toordinal() - 1)
    activity = summarize_activity([
        {"date": yesterday.isoformat(), "submissions": 2, "accepted": None},
        {"date": today.isoformat(), "submissions": 0, "accepted": None},
    ])
    assert activity["currentStreak"] == 1


def test_delete_cors_preflight_is_allowed(learner):
    with TestClient(main.app) as client:
        response = client.options(
            "/api/leetcode/connect",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_api_rate_limit_returns_retry_after(monkeypatch, learner):
    monkeypatch.setattr(main.leetcode_request_limiter, "limit", 1)
    monkeypatch.setattr(main.leetcode_service, "get_profile", lambda username, refresh=False: _profile_result(username))
    monkeypatch.setattr(main, "get_challenge_questions", lambda _uid: _challenge_questions())
    with TestClient(main.app) as client:
        first = client.get("/api/leetcode/profile", headers=TOKEN_HEADERS)
        limited = client.get("/api/leetcode/profile", headers=TOKEN_HEADERS)
    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
