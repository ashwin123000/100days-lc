from datetime import datetime, timezone
from functools import wraps

import pytest

from backend.app import challenge_persistence as challenge


class FakeSnapshot:
    def __init__(self, path, value, database=None):
        self.path = path
        self.id = path[-1]
        self._value = value
        self.exists = value is not None
        self.reference = FakeReference(database, path) if database is not None else None

    def to_dict(self):
        return self._value.copy() if self._value is not None else None

    def get(self, key):
        return self._value.get(key) if self._value is not None else None


class FakeReference:
    def __init__(self, database, path):
        self.database = database
        self.path_parts = tuple(path)
        self.path = "/".join(path)
        self.id = path[-1]

    def __eq__(self, other):
        return isinstance(other, FakeReference) and self.path_parts == other.path_parts

    def __hash__(self):
        return hash(self.path_parts)

    def collection(self, name):
        return FakeCollection(self.database, self.path_parts + (name,))

    def get(self, transaction=None):
        if transaction is not None:
            return transaction.get(self)
        return self.database.snapshot(self.path_parts)


class FakeCollection:
    def __init__(self, database, path):
        self.database = database
        self.path = tuple(path)

    def document(self, document_id=None):
        if document_id is None:
            self.database.event_counter += 1
            document_id = f"event-{self.database.event_counter}"
        return FakeReference(self.database, self.path + (str(document_id),))

    def stream(self):
        return self.database.stream(self.path)


class FakeQuery:
    def __init__(self, database, collection_id):
        self.database = database
        self.collection_id = collection_id
        self.filters = []
        self.page_limit = None
        self.cursor_path = None

    def where(self, field, operator, value):
        self.filters.append((field, operator, value))
        return self

    def order_by(self, field):
        assert field == "__name__"
        return self

    def limit(self, value):
        self.page_limit = value
        return self

    def start_after(self, snapshot):
        self.cursor_path = snapshot.reference.path
        return self

    def stream(self):
        snapshots = [
            self.database.snapshot(path)
            for path, data in self.database.documents.items()
            if len(path) == 4
            and path[2] == self.collection_id
            and all(
                operator == "==" and data.get(field) == value
                for field, operator, value in self.filters
            )
            and (self.cursor_path is None or "/".join(path) > self.cursor_path)
        ]
        snapshots.sort(key=lambda snapshot: snapshot.reference.path)
        return snapshots[:self.page_limit]


class FakeTransaction:
    def __init__(self, database):
        self.database = database
        self.writes = []

    def get(self, reference):
        return self.database.snapshot(reference.path_parts)

    def set(self, reference, value):
        self.writes.append(("set", reference.path_parts, value.copy()))

    def update(self, reference, value):
        self.writes.append(("update", reference.path_parts, value.copy()))

    def create(self, reference, value):
        self.writes.append(("create", reference.path_parts, value.copy()))

    def commit(self):
        for operation, path, value in self.writes:
            if operation == "create" and path in self.database.documents:
                raise RuntimeError("event ID already exists")
            if operation == "update":
                self.database.documents[path].update(value)
            else:
                self.database.documents[path] = value


class FakeDatabase:
    def __init__(self):
        self.documents = {}
        self.event_counter = 0

    def collection(self, name):
        return FakeCollection(self, (name,))

    def collection_group(self, collection_id):
        return FakeQuery(self, collection_id)

    def document(self, path):
        return FakeReference(self, tuple(path.split("/")))

    def transaction(self):
        return FakeTransaction(self)

    def snapshot(self, path):
        return FakeSnapshot(tuple(path), self.documents.get(tuple(path)), self)

    def stream(self, path):
        prefix = tuple(path)
        return [
            FakeSnapshot(key, value, self)
            for key, value in sorted(self.documents.items())
            if len(key) == len(prefix) + 1 and key[:len(prefix)] == prefix
        ]


@pytest.fixture
def fake_firestore(monkeypatch):
    database = FakeDatabase()
    fixed_time = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(challenge, "firestore_client", lambda: database)
    monkeypatch.setattr(challenge.firestore, "SERVER_TIMESTAMP", fixed_time)

    def transactional(function):
        @wraps(function)
        def execute(transaction):
            result = function(transaction)
            transaction.commit()
            return result

        return execute

    monkeypatch.setattr(challenge.firestore, "transactional", transactional)
    database.documents[("problems", "two-sum")] = {
        "slug": "two-sum",
        "title": "Two Sum",
        "difficulty": "Easy",
        "leetcodeUrl": "https://leetcode.com/problems/two-sum/",
        "isPublished": True,
    }
    database.documents[("users", "learner-1")] = {
        "role": "learner",
        "isActive": True,
        "bookmarks": ["preserved"],
    }
    return database


def _assign(database, day=1, slug="two-sum"):
    return challenge.assign_challenge_day(day, slug, "admin-1")


def test_initialize_challenge_creates_fixed_definition_and_is_idempotent(fake_firestore):
    first = challenge.initialize_challenge("admin-1")
    definition = fake_firestore.documents[("challenges", challenge.CHALLENGE_ID)]

    assert first == {
        "challengeId": "leetcode-100-days",
        "title": "100 Days of LeetCode",
        "totalDays": 100,
        "publicationStatus": "published",
        "created": True,
    }
    assert definition["updatedBy"] == "admin-1"
    assert definition["createdAt"] == definition["updatedAt"]
    assert challenge.initialize_challenge("admin-2") == {
        "challengeId": "leetcode-100-days",
        "title": "100 Days of LeetCode",
        "totalDays": 100,
        "publicationStatus": "published",
        "created": False,
    }
    assert definition["updatedBy"] == "admin-1"


def test_initialize_challenge_rejects_missing_admin_uid(fake_firestore):
    with pytest.raises(challenge.ChallengeValidationError):
        challenge.initialize_challenge("")


def _report_and_review(database, day=1, decision="verified", review_note=None):
    challenge.report_challenge_completion("learner-1", day)
    return challenge.review_challenge_completion(
        "learner-1", day, decision, "admin-1", review_note,
    )


def test_assignment_creates_fixed_challenge_and_rejects_reassignment(fake_firestore):
    result = _assign(fake_firestore, day=42)

    definition = fake_firestore.documents[("challenges", challenge.CHALLENGE_ID)]
    assignment = fake_firestore.documents[("challenges", challenge.CHALLENGE_ID, "days", "42")]
    assert definition["totalDays"] == 100
    assert definition["publicationStatus"] == "published"
    assert result["problem"] == {
        "slug": "two-sum",
        "title": "Two Sum",
        "difficulty": "Easy",
        "leetcodeUrl": "https://leetcode.com/problems/two-sum/",
    }
    assert assignment["problemRef"].path == "problems/two-sum"
    assert _assign(fake_firestore, day=42) == result

    fake_firestore.documents[("problems", "valid-parentheses")] = {
        **fake_firestore.documents[("problems", "two-sum")],
        "slug": "valid-parentheses",
        "leetcodeUrl": "https://leetcode.com/problems/valid-parentheses/",
    }
    with pytest.raises(challenge.ChallengeConflict):
        _assign(fake_firestore, day=42, slug="valid-parentheses")
    assert assignment["problemSlug"] == "two-sum"


@pytest.mark.parametrize("day", [0, 101, True, "1"])
def test_assignment_rejects_invalid_day(fake_firestore, day):
    with pytest.raises(challenge.ChallengeValidationError):
        challenge.assign_challenge_day(day, "two-sum", "admin-1")


def test_assignment_requires_existing_published_problem(fake_firestore):
    with pytest.raises(challenge.ChallengeNotFound):
        _assign(fake_firestore, slug="missing-problem")

    fake_firestore.documents[("problems", "unpublished")] = {
        **fake_firestore.documents[("problems", "two-sum")],
        "slug": "unpublished",
        "isPublished": False,
    }
    with pytest.raises(challenge.ChallengeConflict):
        _assign(fake_firestore, slug="unpublished")


def test_report_and_admin_verification_are_atomic_and_audited(fake_firestore):
    _assign(fake_firestore)
    report = challenge.report_challenge_completion("learner-1", 1)

    completion_path = ("users", "learner-1", "challengeCompletions", "1")
    completion = fake_firestore.documents[completion_path]
    assert completion["status"] == "pending"
    assert completion["problemSlug"] == "two-sum"
    assert report["verifiedCompletion"] is False
    assert report["submittedAt"] == "2026-11-10T09:00:00Z"

    reviewed = challenge.review_challenge_completion(
        "learner-1", 1, "verified", "admin-1", "Reviewed manually",
    )
    completion = fake_firestore.documents[completion_path]
    assert completion["status"] == "verified"
    assert completion["reviewerUid"] == "admin-1"
    assert completion["verificationDetails"] == {
        "method": "admin_review",
        "note": "Reviewed manually",
    }
    assert reviewed["reviewedAt"] == "2026-11-10T09:00:00Z"

    events = fake_firestore.stream(completion_path + ("events",))
    assert [event.to_dict()["eventType"] for event in events] == ["reported", "verified"]
    assert events[1].to_dict()["actorUid"] == "admin-1"
    assert events[1].to_dict()["reviewNote"] == "Reviewed manually"


def test_verified_completion_cannot_be_reported_or_reviewed_again(fake_firestore):
    _assign(fake_firestore)
    _report_and_review(fake_firestore)

    with pytest.raises(challenge.ChallengeConflict):
        challenge.report_challenge_completion("learner-1", 1)
    with pytest.raises(challenge.ChallengeConflict):
        challenge.review_challenge_completion("learner-1", 1, "rejected", "admin-1", None)
    assert len(fake_firestore.stream(("users", "learner-1", "challengeCompletions", "1", "events"))) == 2


def test_pending_report_cannot_be_resubmitted_as_another_report(fake_firestore):
    _assign(fake_firestore)
    challenge.report_challenge_completion("learner-1", 1)

    with pytest.raises(challenge.ChallengeConflict):
        challenge.report_challenge_completion("learner-1", 1)
    events = fake_firestore.stream(("users", "learner-1", "challengeCompletions", "1", "events"))
    assert [event.to_dict()["eventType"] for event in events] == ["reported"]


def test_rejected_report_can_be_resubmitted_without_erasing_audit(fake_firestore):
    _assign(fake_firestore)
    _report_and_review(fake_firestore, decision="rejected", review_note="Try again")

    report = challenge.report_challenge_completion("learner-1", 1)
    assert report["status"] == "pending"
    completion = fake_firestore.documents[("users", "learner-1", "challengeCompletions", "1")]
    assert completion["status"] == "pending"
    assert "reviewerUid" not in completion
    assert "verificationDetails" not in completion

    events = fake_firestore.stream(("users", "learner-1", "challengeCompletions", "1", "events"))
    assert [event.to_dict()["eventType"] for event in events] == ["reported", "rejected", "resubmitted"]


def test_progress_uses_verified_consecutive_challenge_days_only(fake_firestore):
    for day in (1, 2, 4):
        _assign(fake_firestore, day=day)
        _report_and_review(fake_firestore, day=day)

    _assign(fake_firestore, day=3)
    challenge.report_challenge_completion("learner-1", 3)
    result = challenge.get_challenge_progress("learner-1")
    assert result == {
        "challengeId": "leetcode-100-days",
        "totalDays": 100,
        "completedDays": 3,
        "completionPercentage": 3,
        "remainingDays": 97,
        "currentStreak": 1,
        "longestStreak": 2,
        "recentDays": [
            {"day": 1, "status": "verified"},
            {"day": 2, "status": "verified"},
            {"day": 4, "status": "verified"},
        ],
    }


def test_leaderboard_counts_verified_days_only_and_shares_tied_ranks(fake_firestore):
    fake_firestore.documents[("users", "learner-1")]["fullName"] = "Alex Learner"
    fake_firestore.documents[("users", "learner-2")] = {
        "role": "learner",
        "isActive": True,
        "fullName": "Blair Learner",
        "leetcodeUsername": "blair",
    }
    fake_firestore.documents[("users", "learner-3")] = {
        "role": "learner",
        "isActive": True,
        "fullName": "Casey Learner",
    }
    fake_firestore.documents[("users", "inactive-learner")] = {
        "role": "learner",
        "isActive": False,
        "fullName": "Inactive Learner",
    }
    fake_firestore.documents[("users", "admin-1")] = {
        "role": "admin",
        "isActive": True,
        "fullName": "Administrator",
    }
    _assign(fake_firestore)
    _report_and_review(fake_firestore)
    challenge.report_challenge_completion("learner-2", 1)
    challenge.review_challenge_completion("learner-2", 1, "verified", "admin-1", None)
    challenge.report_challenge_completion("learner-3", 1)

    leaderboard = challenge.get_verified_challenge_leaderboard()

    assert leaderboard["totalLearners"] == 3
    assert leaderboard["scoringRule"] == "One point per distinct verified challenge day; tied scores share rank."
    assert [
        (row["displayName"], row["verifiedScore"], row["rank"])
        for row in leaderboard["learners"]
    ] == [("Alex Learner", 1, 1), ("Blair Learner", 1, 1), ("Casey Learner", 0, 3)]
    assert leaderboard["learners"][1]["leetcodeProfileUrl"] == "https://leetcode.com/u/blair/"


def test_leaderboard_returns_an_empty_result_without_registered_learners(fake_firestore):
    del fake_firestore.documents[("users", "learner-1")]

    leaderboard = challenge.get_verified_challenge_leaderboard()

    assert leaderboard["totalLearners"] == 0
    assert leaderboard["learners"] == []


def test_questions_are_scoped_to_learner_and_skip_unpublished_problem(fake_firestore):
    _assign(fake_firestore)
    first = challenge.get_challenge_questions("learner-1")
    assert first["questions"][0]["status"] == "not_started"
    assert first["questions"][0]["verifiedCompletion"] is False

    fake_firestore.documents[("problems", "two-sum")]["isPublished"] = False
    assert challenge.get_challenge_questions("learner-1")["questions"] == []


def test_accepted_submission_verifies_exact_assigned_problem_and_is_idempotent(fake_firestore):
    _assign(fake_firestore)
    timestamp = int(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc).timestamp())
    submissions = [
        {"problemSlug": "two-sums", "timestamp": timestamp + 60, "submissionId": "wrong-slug"},
        {"problemSlug": "two-sum", "timestamp": timestamp + 60, "submissionId": "accepted-1"},
    ]

    first = challenge.sync_accepted_submissions("learner-1", submissions, True)

    completion_path = ("users", "learner-1", "challengeCompletions", "1")
    completion = fake_firestore.documents[completion_path]
    assert first["verifiedDays"] == [1]
    assert first["newlyVerifiedDays"] == [1]
    assert first["dayStatuses"] == {"1": "verified"}
    assert completion["status"] == "verified"
    assert completion["problemSlug"] == "two-sum"
    assert completion["verificationDetails"] == {
        "method": "leetcode_recent_accepted",
        "source": "leetcode_public_graphql",
        "problemSlug": "two-sum",
        "submissionTimestamp": datetime.fromtimestamp(timestamp + 60, timezone.utc),
        "submissionId": "accepted-1",
    }
    assert challenge.get_challenge_progress("learner-1")["completedDays"] == 1
    events = fake_firestore.stream(completion_path + ("events",))
    assert len(events) == 1
    assert events[0].to_dict()["source"] == "leetcode_public_graphql"
    assert events[0].to_dict()["submissionId"] == "accepted-1"

    duplicate = challenge.sync_accepted_submissions("learner-1", submissions, True)
    later_window = challenge.sync_accepted_submissions("learner-1", [], True)
    assert duplicate["verifiedDays"] == [1]
    assert duplicate["newlyVerifiedDays"] == []
    assert later_window["verifiedDays"] == [1]
    assert len(fake_firestore.stream(completion_path + ("events",))) == 1


@pytest.mark.parametrize(
    "submission",
    [
        {"problemSlug": "two-sum", "timestamp": 1794301199},
        {"problemSlug": "two-sums", "timestamp": 1794301260},
        {"problemSlug": "two-sum", "timestamp": True},
        {"problemSlug": "../two-sum", "timestamp": 1794301260},
    ],
)
def test_nonmatching_or_invalid_accepted_submission_does_not_verify_day(fake_firestore, submission):
    _assign(fake_firestore)

    result = challenge.sync_accepted_submissions("learner-1", [submission], True)

    assert result["verifiedDays"] == []
    assert result["dayStatuses"] == {"1": "unable_to_verify"}
    assert ("users", "learner-1", "challengeCompletions", "1") not in fake_firestore.documents
    assert fake_firestore.stream(("users", "learner-1", "challengeCompletions", "1", "events")) == []


def test_unavailable_recent_submissions_never_reject_or_erase_existing_verification(fake_firestore):
    _assign(fake_firestore)
    timestamp = int(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc).timestamp())
    challenge.sync_accepted_submissions(
        "learner-1",
        [{"problemSlug": "two-sum", "timestamp": timestamp}],
        True,
    )

    result = challenge.sync_accepted_submissions("learner-1", [], False)

    assert result["status"] == "unable_to_verify"
    assert result["verifiedDays"] == [1]
    assert result["dayStatuses"] == {"1": "verified"}
    assert fake_firestore.documents[("users", "learner-1", "challengeCompletions", "1")]["status"] == "verified"
    assert len(fake_firestore.stream(("users", "learner-1", "challengeCompletions", "1", "events"))) == 1


def test_accepted_submission_can_resolve_legacy_pending_report(fake_firestore):
    _assign(fake_firestore)
    challenge.report_challenge_completion("learner-1", 1)
    timestamp = int(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc).timestamp())

    challenge.sync_accepted_submissions(
        "learner-1",
        [{"problemSlug": "two-sum", "timestamp": timestamp}],
        True,
    )

    completion = fake_firestore.documents[("users", "learner-1", "challengeCompletions", "1")]
    events = fake_firestore.stream(("users", "learner-1", "challengeCompletions", "1", "events"))
    assert completion["status"] == "verified"
    assert completion["verificationDetails"]["method"] == "leetcode_recent_accepted"
    assert len(events) == 2
    assert events[-1].to_dict()["previousStatus"] == "pending"


def test_missing_challenge_does_not_fabricate_progress(fake_firestore):
    with pytest.raises(challenge.ChallengeNotConfigured):
        challenge.get_challenge_progress("learner-1")


def test_pending_review_queue_paginates_and_exposes_only_review_fields(fake_firestore):
    _assign(fake_firestore)
    for learner_uid, display_name in (
        ("learner-1", "Learner One"),
        ("learner-2", "Learner Two"),
        ("learner-3", "Learner Three"),
    ):
        fake_firestore.documents[("users", learner_uid)] = {
            "role": "learner",
            "isActive": True,
            "fullName": display_name,
            "email": f"{learner_uid}@example.com",
            "bookmarks": ["private-bookmark"],
        }
        challenge.report_challenge_completion(learner_uid, 1)

    fake_firestore.documents[("users", "learner-4")] = {
        "role": "learner",
        "isActive": True,
        "fullName": "Already Reviewed",
    }
    challenge.report_challenge_completion("learner-4", 1)
    challenge.review_challenge_completion("learner-4", 1, "verified", "admin-1", None)

    first_page = challenge.get_pending_challenge_completions(page_size=2)
    second_page = challenge.get_pending_challenge_completions(
        page_size=2,
        cursor=first_page["nextCursor"],
    )

    all_items = first_page["items"] + second_page["items"]
    assert len(first_page["items"]) == 2
    assert first_page["nextCursor"]
    assert second_page["nextCursor"] is None
    assert {item["learnerUid"] for item in all_items} == {"learner-1", "learner-2", "learner-3"}
    assert all(item["reviewStatus"] == "pending" for item in all_items)
    assert all(item["problemTitle"] == "Two Sum" for item in all_items)
    assert all(item["leetcodeUrl"] == "https://leetcode.com/problems/two-sum/" for item in all_items)
    assert all(item["learnerDisplayName"] for item in all_items)
    assert all(set(item) == {
        "learnerUid",
        "learnerDisplayName",
        "day",
        "problemTitle",
        "leetcodeUrl",
        "submittedAt",
        "reviewStatus",
    } for item in all_items)
    assert all("email" not in item and "bookmarks" not in item for item in all_items)


def test_pending_review_queue_rejects_invalid_page_size_and_cursor(fake_firestore):
    with pytest.raises(challenge.ChallengeValidationError):
        challenge.get_pending_challenge_completions(page_size=0)
    with pytest.raises(challenge.ChallengeValidationError):
        challenge.get_pending_challenge_completions(cursor="not-a-valid-cursor")
