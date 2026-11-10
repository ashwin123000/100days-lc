import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlsplit

from firebase_admin import firestore
from google.api_core.exceptions import GoogleAPIError

from .firebase_service import FirebaseServiceError, firestore_client

CHALLENGE_ID = "leetcode-100-days"
CHALLENGE_TITLE = "100 Days of LeetCode"
CHALLENGE_TOTAL_DAYS = 100
_PROBLEM_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ChallengeNotConfigured(RuntimeError):
    pass


class ChallengeNotFound(RuntimeError):
    pass


class ChallengeConflict(RuntimeError):
    pass


class ChallengeValidationError(ValueError):
    pass


def _validate_day(day: int) -> None:
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= CHALLENGE_TOTAL_DAYS:
        raise ChallengeValidationError("Challenge day must be an integer from 1 through 100.")


def _validate_problem_slug(slug: str) -> None:
    if not isinstance(slug, str) or not _PROBLEM_SLUG_PATTERN.fullmatch(slug):
        raise ChallengeValidationError("A valid published LeetCode problem slug is required.")


def _challenge_ref(db: Any) -> Any:
    return db.collection("challenges").document(CHALLENGE_ID)


def _day_ref(db: Any, day: int) -> Any:
    return _challenge_ref(db).collection("days").document(str(day))


def _learner_ref(db: Any, uid: str) -> Any:
    return db.collection("users").document(uid)


def _completion_ref(db: Any, uid: str, day: int) -> Any:
    return _learner_ref(db, uid).collection("challengeCompletions").document(str(day))


def _event_ref(completion_ref: Any) -> Any:
    return completion_ref.collection("events").document()


def _encode_pending_cursor(document_path: str) -> str:
    return base64.urlsafe_b64encode(document_path.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_pending_cursor(cursor: str) -> str:
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        document_path = base64.b64decode(
            padded_cursor,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ChallengeValidationError("The pending review cursor is invalid.") from error
    parts = document_path.split("/")
    if (
        len(parts) != 4
        or parts[0] != "users"
        or not parts[1]
        or parts[2] != "challengeCompletions"
        or not parts[3].isdigit()
        or str(int(parts[3])) != parts[3]
        or not 1 <= int(parts[3]) <= CHALLENGE_TOTAL_DAYS
    ):
        raise ChallengeValidationError("The pending review cursor is invalid.")
    return document_path


def _timestamp_to_iso(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_timestamp(value: Any) -> bool:
    return isinstance(value, datetime)


def _validate_challenge_definition(snapshot: Any) -> dict[str, Any]:
    if not snapshot.exists:
        raise ChallengeNotConfigured("The 100-day challenge has not been configured.")
    document = snapshot.to_dict() or {}
    if (
        document.get("challengeId") != CHALLENGE_ID
        or document.get("totalDays") != CHALLENGE_TOTAL_DAYS
        or not isinstance(document.get("title"), str)
        or not document["title"].strip()
        or document.get("publicationStatus") not in {"draft", "published", "archived"}
        or not _is_timestamp(document.get("createdAt"))
        or not _is_timestamp(document.get("updatedAt"))
        or not isinstance(document.get("updatedBy"), str)
        or not document["updatedBy"]
    ):
        raise FirebaseServiceError("The stored challenge definition is invalid.")
    return document


def _challenge_document(snapshot: Any) -> dict[str, Any]:
    document = _validate_challenge_definition(snapshot)
    if document.get("publicationStatus") != "published":
        raise ChallengeNotConfigured("The 100-day challenge is not currently published.")
    return document


def _published_problem(db: Any, slug: str, transaction: Any | None = None) -> tuple[Any, dict[str, Any]]:
    _validate_problem_slug(slug)
    problem_ref = db.collection("problems").document(slug)
    snapshot = problem_ref.get(transaction=transaction) if transaction is not None else problem_ref.get()
    if not snapshot.exists:
        raise ChallengeNotFound("The referenced MLSC problem was not found.")
    problem = snapshot.to_dict() or {}
    if problem.get("isPublished") is not True:
        raise ChallengeConflict("The MLSC problem is not published.")
    if problem.get("slug") != slug:
        raise FirebaseServiceError("The stored MLSC problem slug is inconsistent.")

    url = problem.get("leetcodeUrl")
    try:
        parsed_url = urlsplit(url) if isinstance(url, str) else None
        url_port = parsed_url.port if parsed_url is not None else None
    except ValueError as error:
        raise FirebaseServiceError("The stored MLSC problem URL is invalid.") from error
    if (
        parsed_url is None
        or parsed_url.scheme != "https"
        or parsed_url.hostname != "leetcode.com"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or url_port is not None
        or parsed_url.path.rstrip("/") != f"/problems/{slug}"
        or parsed_url.fragment
    ):
        raise FirebaseServiceError("The stored MLSC problem URL is invalid.")
    if not isinstance(problem.get("title"), str) or not problem["title"].strip():
        raise FirebaseServiceError("The stored MLSC problem title is invalid.")
    return problem_ref, problem


def _validate_assignment_data(
    assignment: dict[str, Any],
    day: int,
    problem_ref: Any,
    problem: dict[str, Any],
) -> None:
    if (
        assignment.get("day") != day
        or assignment.get("assignmentStatus") != "assigned"
        or assignment.get("problemRef") != problem_ref
        or assignment.get("leetcodeUrl") != problem["leetcodeUrl"]
        or not _is_timestamp(assignment.get("assignedAt"))
        or not isinstance(assignment.get("assignedBy"), str)
        or not assignment["assignedBy"]
        or not _is_timestamp(assignment.get("updatedAt"))
        or not isinstance(assignment.get("updatedBy"), str)
        or not assignment["updatedBy"]
    ):
        raise FirebaseServiceError("The stored challenge day assignment is inconsistent.")


def _ensure_assigned_day(
    db: Any,
    day: int,
    transaction: Any,
) -> tuple[Any, dict[str, Any]]:
    challenge_ref = _challenge_ref(db)
    day_ref = _day_ref(db, day)
    challenge = challenge_ref.get(transaction=transaction)
    _challenge_document(challenge)

    assignment = day_ref.get(transaction=transaction)
    if not assignment.exists:
        raise ChallengeNotFound("No published MLSC question is assigned to this challenge day.")
    assignment_data = assignment.to_dict() or {}
    slug = assignment_data.get("problemSlug")
    problem_ref, problem = _published_problem(db, slug, transaction)
    _validate_assignment_data(assignment_data, day, problem_ref, problem)
    return problem_ref, assignment_data


def assign_challenge_day(day: int, problem_slug: str, admin_uid: str) -> dict[str, Any]:
    _validate_day(day)
    _validate_problem_slug(problem_slug)
    if not isinstance(admin_uid, str) or not admin_uid:
        raise ChallengeValidationError("An authenticated administrator UID is required.")
    db = firestore_client()
    challenge_ref = _challenge_ref(db)
    day_ref = _day_ref(db, day)
    problem_ref = db.collection("problems").document(problem_slug)

    @firestore.transactional
    def commit(transaction: Any) -> dict[str, Any]:
        challenge = challenge_ref.get(transaction=transaction)
        current_assignment = day_ref.get(transaction=transaction)
        problem_ref_checked, problem = _published_problem(db, problem_slug, transaction)
        if problem_ref_checked != problem_ref:
            raise FirebaseServiceError("The stored MLSC problem reference is inconsistent.")

        if challenge.exists:
            challenge_data = _validate_challenge_definition(challenge)
            if challenge_data.get("publicationStatus") == "archived":
                raise ChallengeConflict("An archived challenge cannot be assigned new questions.")
            if challenge_data.get("publicationStatus") != "published":
                raise ChallengeConflict("The challenge must be published before assigning questions.")
        elif current_assignment.exists:
            raise FirebaseServiceError("A challenge day exists without its challenge definition.")
        else:
            transaction.set(challenge_ref, {
                "challengeId": CHALLENGE_ID,
                "title": CHALLENGE_TITLE,
                "totalDays": CHALLENGE_TOTAL_DAYS,
                "publicationStatus": "published",
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "updatedBy": admin_uid,
            })

        if current_assignment.exists:
            current = current_assignment.to_dict() or {}
            if current.get("problemSlug") != problem_slug or current.get("problemRef") != problem_ref:
                raise ChallengeConflict("An assigned challenge day cannot be reassigned to a different problem.")
            _validate_assignment_data(current, day, problem_ref, problem)
            assigned_at = current.get("assignedAt", firestore.SERVER_TIMESTAMP)
            assigned_by = current.get("assignedBy", admin_uid)
        else:
            assigned_at = firestore.SERVER_TIMESTAMP
            assigned_by = admin_uid

        transaction.set(day_ref, {
            "day": day,
            "problemRef": problem_ref,
            "problemSlug": problem_slug,
            "leetcodeUrl": problem["leetcodeUrl"],
            "assignmentStatus": "assigned",
            "assignedAt": assigned_at,
            "assignedBy": assigned_by,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "updatedBy": admin_uid,
        })
        if challenge.exists:
            transaction.update(challenge_ref, {
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "updatedBy": admin_uid,
            })
        return {
            "day": day,
            "assignmentStatus": "assigned",
            "publicationStatus": "published",
            "problem": {
                "slug": problem_slug,
                "title": problem["title"],
                "difficulty": problem.get("difficulty"),
                "leetcodeUrl": problem["leetcodeUrl"],
            },
        }

    try:
        return commit(db.transaction())
    except (ChallengeConflict, ChallengeNotFound, ChallengeValidationError, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not assign the MLSC challenge day.") from error


def initialize_challenge(admin_uid: str) -> dict[str, Any]:
    if not isinstance(admin_uid, str) or not admin_uid:
        raise ChallengeValidationError("An authenticated administrator UID is required.")
    db = firestore_client()
    challenge_ref = _challenge_ref(db)

    @firestore.transactional
    def commit(transaction: Any) -> dict[str, Any]:
        snapshot = challenge_ref.get(transaction=transaction)
        if snapshot.exists:
            challenge = _validate_challenge_definition(snapshot)
            return {
                "challengeId": CHALLENGE_ID,
                "title": challenge["title"],
                "totalDays": CHALLENGE_TOTAL_DAYS,
                "publicationStatus": challenge["publicationStatus"],
                "created": False,
            }

        transaction.create(challenge_ref, {
            "challengeId": CHALLENGE_ID,
            "title": CHALLENGE_TITLE,
            "totalDays": CHALLENGE_TOTAL_DAYS,
            "publicationStatus": "published",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "updatedBy": admin_uid,
        })
        return {
            "challengeId": CHALLENGE_ID,
            "title": CHALLENGE_TITLE,
            "totalDays": CHALLENGE_TOTAL_DAYS,
            "publicationStatus": "published",
            "created": True,
        }

    try:
        return commit(db.transaction())
    except (ChallengeValidationError, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not initialize the MLSC challenge.") from error


def _completion_status(data: dict[str, Any] | None) -> str:
    if data is None:
        return "not_started"
    status = data.get("status")
    if status not in {"pending", "verified", "rejected"}:
        raise FirebaseServiceError("The stored challenge completion status is invalid.")
    if not all(isinstance(data.get(field), datetime) for field in ("submittedAt", "createdAt", "updatedAt")):
        raise FirebaseServiceError("The stored challenge completion timestamps are invalid.")
    if status == "pending":
        if any(field in data for field in ("reviewedAt", "reviewerUid", "verificationDetails")):
            raise FirebaseServiceError("A pending challenge completion contains review data.")
    elif status == "rejected":
        if (
            not isinstance(data.get("reviewedAt"), datetime)
            or not isinstance(data.get("reviewerUid"), str)
            or not data["reviewerUid"]
        ):
            raise FirebaseServiceError("The stored challenge rejection details are invalid.")
        if "verificationDetails" in data:
            raise FirebaseServiceError("A rejected challenge completion cannot have verification details.")
    else:
        details = data.get("verificationDetails")
        if not isinstance(details, dict):
            raise FirebaseServiceError("The stored challenge verification details are invalid.")
        method = details.get("method")
        if method == "admin_review":
            if (
                not isinstance(data.get("reviewedAt"), datetime)
                or not isinstance(data.get("reviewerUid"), str)
                or not data["reviewerUid"]
            ):
                raise FirebaseServiceError("The stored challenge review details are invalid.")
            if "note" in details and not isinstance(details["note"], str):
                raise FirebaseServiceError("The stored challenge verification note is invalid.")
        elif method == "leetcode_recent_accepted":
            if (
                not isinstance(data.get("verifiedAt"), datetime)
                or details.get("source") != "leetcode_public_graphql"
                or not isinstance(details.get("problemSlug"), str)
                or not _PROBLEM_SLUG_PATTERN.fullmatch(details["problemSlug"])
                or details["problemSlug"] != data.get("problemSlug")
                or not isinstance(details.get("submissionTimestamp"), datetime)
                or details["submissionTimestamp"] != data.get("submittedAt")
                or "reviewedAt" in data
                or "reviewerUid" in data
            ):
                raise FirebaseServiceError("The stored LeetCode verification details are invalid.")
            if "submissionId" in details and not isinstance(details["submissionId"], str):
                raise FirebaseServiceError("The stored LeetCode submission identifier is invalid.")
        else:
            raise FirebaseServiceError("The stored challenge verification method is invalid.")
    return status


def get_challenge_questions(uid: str) -> dict[str, Any]:
    try:
        db = firestore_client()
        challenge = _challenge_document(_challenge_ref(db).get())
        day_snapshots = list(_challenge_ref(db).collection("days").stream())
        questions = []
        for day_snapshot in day_snapshots:
            assignment = day_snapshot.to_dict() or {}
            day = assignment.get("day")
            if (
                isinstance(day, bool)
                or not isinstance(day, int)
                or not 1 <= day <= CHALLENGE_TOTAL_DAYS
                or day_snapshot.id != str(day)
                or assignment.get("assignmentStatus") != "assigned"
            ):
                raise FirebaseServiceError("A stored challenge day assignment is invalid.")
            try:
                problem_ref, problem = _published_problem(db, assignment.get("problemSlug"))
            except ChallengeConflict:
                continue
            _validate_assignment_data(assignment, day, problem_ref, problem)
            completion_snapshot = _completion_ref(db, uid, day).get()
            completion = completion_snapshot.to_dict() if completion_snapshot.exists else None
            status = _completion_status(completion)
            if completion is not None and (
                completion.get("day") != day
                or completion.get("problemSlug") != assignment.get("problemSlug")
                or completion.get("problemRef") != problem_ref
            ):
                raise FirebaseServiceError("The learner completion does not match its assigned problem.")
            questions.append({
                "day": day,
                "title": problem["title"],
                "slug": assignment["problemSlug"],
                "difficulty": problem.get("difficulty"),
                "leetcodeUrl": problem["leetcodeUrl"],
                "assignmentStatus": "assigned",
                "publicationStatus": "published",
                "status": status,
                "verifiedCompletion": status == "verified",
                "submittedAt": _timestamp_to_iso(completion.get("submittedAt")) if completion else None,
                "reviewedAt": _timestamp_to_iso(completion.get("reviewedAt")) if completion else None,
                "verifiedAt": (
                    _timestamp_to_iso(completion.get("verifiedAt") or completion.get("reviewedAt"))
                    if completion else None
                ),
                "verificationSource": (
                    ((completion.get("verificationDetails") or {}) if completion else {}).get("source")
                    or ("admin_review" if status == "verified" else None)
                ),
                "verificationStatus": "verified" if status == "verified" else "awaiting_sync",
            })
        return {
            "challengeId": CHALLENGE_ID,
            "totalDays": challenge["totalDays"],
            "questions": sorted(questions, key=lambda question: question["day"]),
        }
    except (ChallengeNotConfigured, ChallengeNotFound, ChallengeConflict, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not read MLSC challenge questions.") from error


def sync_accepted_submissions(
    uid: str,
    submissions: list[dict[str, Any]],
    submissions_available: bool,
) -> dict[str, Any]:
    if not isinstance(uid, str) or not uid:
        raise ChallengeValidationError("An authenticated learner UID is required.")

    questions = get_challenge_questions(uid)["questions"]
    if not submissions_available:
        return {
            "status": "unable_to_verify",
            "verifiedDays": sorted(
                question["day"]
                for question in questions
                if question["status"] == "verified"
            ),
            "dayStatuses": {
                str(question["day"]): (
                    "verified" if question["status"] == "verified" else "unable_to_verify"
                )
                for question in questions
            },
        }

    normalized_submissions: list[dict[str, Any]] = []
    for submission in submissions:
        if not isinstance(submission, dict):
            continue
        slug = submission.get("problemSlug")
        timestamp = submission.get("timestamp")
        if (
            not isinstance(slug, str)
            or not _PROBLEM_SLUG_PATTERN.fullmatch(slug)
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp <= 0
        ):
            continue
        try:
            submitted_at = datetime.fromtimestamp(timestamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        accepted = {
            "problemSlug": slug,
            "submissionTimestamp": submitted_at,
        }
        submission_id = submission.get("submissionId")
        if isinstance(submission_id, str) and submission_id:
            accepted["submissionId"] = submission_id
        normalized_submissions.append(accepted)

    if not normalized_submissions:
        return {
            "status": "synchronized",
            "verifiedDays": sorted(
                question["day"]
                for question in questions
                if question["status"] == "verified"
            ),
            "dayStatuses": {
                str(question["day"]): (
                    "verified" if question["status"] == "verified" else "unable_to_verify"
                )
                for question in questions
            },
        }
    db = firestore_client()
    db = firestore_client()
    _challenge_document(_challenge_ref(db).get())
    learner_ref = _learner_ref(db, uid)
    day_snapshots = _challenge_ref(db).collection("days").stream()
    submissions_by_slug: dict[str, list[dict[str, Any]]] = {}
    for submission in normalized_submissions:
        submissions_by_slug.setdefault(submission["problemSlug"].casefold(), []).append(submission)
    for values in submissions_by_slug.values():
        values.sort(key=lambda item: item["submissionTimestamp"])

    verified_days: set[int] = set()
    for day_snapshot in day_snapshots:
        assignment = day_snapshot.to_dict() or {}
        day = assignment.get("day")
        if (
            isinstance(day, bool)
            or not isinstance(day, int)
            or not 1 <= day <= CHALLENGE_TOTAL_DAYS
            or day_snapshot.id != str(day)
        ):
            raise FirebaseServiceError("A stored challenge day assignment is invalid.")
        slug = assignment.get("problemSlug")
        if not isinstance(slug, str) or not _PROBLEM_SLUG_PATTERN.fullmatch(slug):
            raise FirebaseServiceError("A stored challenge assignment has an invalid problem slug.")
        candidates = submissions_by_slug.get(slug.casefold(), [])
        if not candidates:
            continue
        db = firestore_client()
        challenge_ref = _challenge_ref(db)
        completion_ref = _completion_ref(db, uid, day)
        event_ref = _event_ref(completion_ref)

        @firestore.transactional
        def commit(transaction: Any) -> str | None:
            learner = learner_ref.get(transaction=transaction)
            learner_data = learner.to_dict() or {} if learner.exists else {}
            if (
                not learner.exists
                or learner_data.get("role") != "learner"
                or learner_data.get("isActive") is False
            ):
                raise ChallengeNotFound("An active MLSC learner profile is required.")
            _challenge_document(challenge_ref.get(transaction=transaction))
            problem_ref, current_assignment = _ensure_assigned_day(db, day, transaction)
            if current_assignment.get("problemSlug") != slug:
                raise ChallengeConflict("The MLSC challenge assignment changed during verification.")
            assigned_at = current_assignment["assignedAt"]
            if assigned_at.tzinfo is None:
                assigned_at = assigned_at.replace(tzinfo=timezone.utc)
            candidate = next(
                (
                    item for item in candidates
                    if item["submissionTimestamp"] >= assigned_at
                ),
                None,
            )
            if candidate is None:
                return None

            current_snapshot = completion_ref.get(transaction=transaction)
            current = current_snapshot.to_dict() if current_snapshot.exists else None
            previous_status = _completion_status(current)
            if previous_status == "verified":
                return "already_verified"
            if current is not None and (
                current.get("day") != day
                or current.get("problemRef") != problem_ref
                or current.get("problemSlug") != slug
            ):
                raise ChallengeConflict("The existing completion does not match the assigned problem.")

            verification_details: dict[str, Any] = {
                "method": "leetcode_recent_accepted",
                "source": "leetcode_public_graphql",
                "problemSlug": slug,
                "submissionTimestamp": candidate["submissionTimestamp"],
            }
            if "submissionId" in candidate:
                verification_details["submissionId"] = candidate["submissionId"]
            transaction.set(completion_ref, {
                "day": day,
                "problemRef": problem_ref,
                "problemSlug": slug,
                "status": "verified",
                "submittedAt": candidate["submissionTimestamp"],
                "verifiedAt": firestore.SERVER_TIMESTAMP,
                "verificationDetails": verification_details,
                "createdAt": current.get("createdAt", firestore.SERVER_TIMESTAMP) if current else firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })
            event_data = {
                "eventType": "verified",
                "previousStatus": previous_status if previous_status != "not_started" else None,
                "newStatus": "verified",
                "actorUid": "system:leetcode",
                "timestamp": firestore.SERVER_TIMESTAMP,
                "source": "leetcode_public_graphql",
                "problemSlug": slug,
                "submissionTimestamp": candidate["submissionTimestamp"],
            }
            if "submissionId" in candidate:
                event_data["submissionId"] = candidate["submissionId"]
            transaction.create(event_ref, event_data)
            return "newly_verified"

        try:
            if commit(db.transaction()) == "newly_verified":
                verified_days.add(day)
        except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError, FirebaseServiceError):
            raise
        except GoogleAPIError as error:
            raise FirebaseServiceError("Firestore could not synchronize LeetCode challenge completions.") from error

    updated_questions = get_challenge_questions(uid)["questions"]
    return {
        "status": "synchronized",
        "verifiedDays": sorted(
            question["day"]
            for question in updated_questions
            if question["status"] == "verified"
        ),
        "newlyVerifiedDays": sorted(verified_days),
        "dayStatuses": {
            str(question["day"]): (
                "verified" if question["status"] == "verified" else "unable_to_verify"
            )
            for question in updated_questions
        },
    }


def get_challenge_progress(uid: str) -> dict[str, Any]:
    try:
        db = firestore_client()
        challenge = _challenge_document(_challenge_ref(db).get())
        snapshots = _learner_ref(db, uid).collection("challengeCompletions").stream()
        verified_days: set[int] = set()
        for snapshot in snapshots:
            completion = snapshot.to_dict() or {}
            day = completion.get("day")
            status = _completion_status(completion)
            if (
                isinstance(day, bool)
                or not isinstance(day, int)
                or not 1 <= day <= CHALLENGE_TOTAL_DAYS
                or snapshot.id != str(day)
            ):
                raise FirebaseServiceError("A stored learner challenge completion is invalid.")
            if status == "verified":
                assignment_snapshot = _day_ref(db, day).get()
                if not assignment_snapshot.exists:
                    raise FirebaseServiceError("A verified challenge completion has no day assignment.")
                assignment = assignment_snapshot.to_dict() or {}
                problem_slug = assignment.get("problemSlug")
                if not isinstance(problem_slug, str) or not _PROBLEM_SLUG_PATTERN.fullmatch(problem_slug):
                    raise FirebaseServiceError("A verified challenge assignment has an invalid problem slug.")
                expected_problem_ref = db.collection("problems").document(problem_slug)
                problem_snapshot = expected_problem_ref.get()
                problem = problem_snapshot.to_dict() if problem_snapshot.exists else None
                if (
                    assignment.get("day") != day
                    or assignment.get("assignmentStatus") != "assigned"
                    or assignment.get("problemRef") != expected_problem_ref
                    or completion.get("problemRef") != expected_problem_ref
                    or completion.get("problemSlug") != problem_slug
                    or problem is None
                    or problem.get("slug") != problem_slug
                    or assignment.get("leetcodeUrl") != problem.get("leetcodeUrl")
                    or not _is_timestamp(assignment.get("assignedAt"))
                    or not isinstance(assignment.get("assignedBy"), str)
                    or not assignment["assignedBy"]
                    or not _is_timestamp(assignment.get("updatedAt"))
                    or not isinstance(assignment.get("updatedBy"), str)
                    or not assignment["updatedBy"]
                ):
                    raise FirebaseServiceError("A verified learner completion does not match its assignment.")
                verified_days.add(day)

        longest_streak = 0
        current_streak = 0
        previous_day = None
        run_length = 0
        for day in sorted(verified_days):
            run_length = run_length + 1 if previous_day is not None and day == previous_day + 1 else 1
            longest_streak = max(longest_streak, run_length)
            previous_day = day
        if verified_days:
            current_streak = run_length

        completed_days = len(verified_days)
        return {
            "challengeId": CHALLENGE_ID,
            "totalDays": challenge["totalDays"],
            "completedDays": completed_days,
            "completionPercentage": completed_days,
            "remainingDays": CHALLENGE_TOTAL_DAYS - completed_days,
            "currentStreak": current_streak,
            "longestStreak": longest_streak,
            "recentDays": [
                {"day": day, "status": "verified"}
                for day in sorted(verified_days)[-10:]
            ],
        }
    except (ChallengeNotConfigured, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not calculate MLSC challenge progress.") from error


def get_verified_challenge_leaderboard() -> dict[str, Any]:
    """Return public-safe scores for active learner profiles only."""
    try:
        db = firestore_client()
        learners: dict[str, dict[str, Any]] = {}
        for snapshot in db.collection("users").stream():
            profile = snapshot.to_dict() or {}
            if profile.get("role") != "learner" or profile.get("isActive") is False:
                continue
            learners[snapshot.id] = profile

        completed_days: dict[str, set[int]] = {uid: set() for uid in learners}
        assignment_cache: dict[int, tuple[Any, dict[str, Any]]] = {}
        problem_cache: dict[str, tuple[Any, dict[str, Any]]] = {}
        for learner_uid in learners:
            completions = _learner_ref(db, learner_uid).collection("challengeCompletions").stream()
            for snapshot in completions:
                day_text = snapshot.reference.path.rsplit("/", 1)[-1]
                if not day_text.isdigit():
                    raise FirebaseServiceError("A stored learner challenge completion has an invalid document path.")
                completion = snapshot.to_dict() or {}
                if _completion_status(completion) != "verified":
                    continue
                day = int(day_text)
                if (
                    not 1 <= day <= CHALLENGE_TOTAL_DAYS
                    or completion.get("day") != day
                    or snapshot.id != str(day)
                ):
                    raise FirebaseServiceError("A stored verified learner challenge completion has an invalid day.")

                if day not in assignment_cache:
                    assignment_snapshot = _day_ref(db, day).get()
                    if not assignment_snapshot.exists:
                        raise FirebaseServiceError("A verified learner completion has no challenge assignment.")
                    assignment = assignment_snapshot.to_dict() or {}
                    slug = assignment.get("problemSlug")
                    _validate_problem_slug(slug)
                    if slug not in problem_cache:
                        problem_cache[slug] = _published_problem(db, slug)
                    problem_ref, problem = problem_cache[slug]
                    _validate_assignment_data(assignment, day, problem_ref, problem)
                    assignment_cache[day] = (problem_ref, assignment)

                problem_ref, assignment = assignment_cache[day]
                if (
                    completion.get("problemSlug") != assignment.get("problemSlug")
                    or completion.get("problemRef") != problem_ref
                ):
                    raise FirebaseServiceError("A verified learner completion does not match its challenge assignment.")
                completed_days[learner_uid].add(day)

        rows = []
        for learner_uid, profile in learners.items():
            display_name = profile.get("fullName") or profile.get("displayName")
            if not isinstance(display_name, str) or not display_name.strip():
                display_name = "Learner"
            avatar_url = profile.get("avatarUrl") or profile.get("photoURL")
            if not isinstance(avatar_url, str) or not avatar_url.startswith("https://"):
                avatar_url = None
            username = profile.get("leetcodeUsername")
            leetcode_profile_url = (
                f"https://leetcode.com/u/{quote(username, safe='')}/"
                if isinstance(username, str) and username.strip()
                else None
            )
            rows.append({
                "learnerId": learner_uid,
                "displayName": display_name.strip(),
                "avatarUrl": avatar_url,
                "leetcodeProfileUrl": leetcode_profile_url,
                "verifiedScore": len(completed_days[learner_uid]),
            })

        rows.sort(key=lambda item: (-item["verifiedScore"], item["displayName"].casefold(), item["learnerId"]))
        previous_score = None
        current_rank = 0
        for index, row in enumerate(rows, start=1):
            if row["verifiedScore"] != previous_score:
                current_rank = index
                previous_score = row["verifiedScore"]
            row["rank"] = current_rank

        return {
            "scoringRule": "One point per distinct verified challenge day; tied scores share rank.",
            "totalLearners": len(rows),
            "learners": rows,
        }
    except FirebaseServiceError:
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not calculate the verified learner leaderboard.") from error


def get_pending_challenge_completions(
    page_size: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ChallengeValidationError("Page size must be an integer from 1 through 100.")
    try:
        db = firestore_client()
        query = (
            db.collection_group("challengeCompletions")
            .where("status", "==", "pending")
            .order_by("__name__")
        )
        if cursor:
            cursor_path = _decode_pending_cursor(cursor)
            cursor_snapshot = db.document(cursor_path).get()
            if not cursor_snapshot.exists:
                raise ChallengeValidationError("The pending review cursor is invalid or expired.")
            query = query.start_after(cursor_snapshot)
        snapshots = list(query.limit(page_size + 1).stream())
        has_more = len(snapshots) > page_size
        page_snapshots = snapshots[:page_size]
        items = []
        for snapshot in page_snapshots:
            path_parts = snapshot.reference.path.split("/")
            if (
                len(path_parts) != 4
                or path_parts[0] != "users"
                or not path_parts[1]
                or path_parts[2] != "challengeCompletions"
                or not path_parts[3].isdigit()
            ):
                raise FirebaseServiceError("A pending challenge completion has an invalid document path.")
            learner_uid = path_parts[1]
            day = int(path_parts[3])
            if not 1 <= day <= CHALLENGE_TOTAL_DAYS:
                raise FirebaseServiceError("A pending challenge completion has an invalid challenge day.")
            completion = snapshot.to_dict() or {}
            if completion.get("status") != "pending":
                raise FirebaseServiceError("The pending review query returned a non-pending completion.")
            if (
                completion.get("day") != day
                or not isinstance(completion.get("problemSlug"), str)
                or not _is_timestamp(completion.get("submittedAt"))
            ):
                raise FirebaseServiceError("A pending challenge completion is invalid.")
            _validate_problem_slug(completion["problemSlug"])

            learner_snapshot = _learner_ref(db, learner_uid).get()
            learner_profile = learner_snapshot.to_dict() or {} if learner_snapshot.exists else {}
            display_name = learner_profile.get("fullName") or learner_profile.get("displayName")
            if not isinstance(display_name, str):
                display_name = None

            _, problem = _problem_for_review(db, completion["problemSlug"])
            items.append({
                "learnerUid": learner_uid,
                "learnerDisplayName": display_name,
                "day": day,
                "problemTitle": problem["title"],
                "leetcodeUrl": problem["leetcodeUrl"],
                "submittedAt": _timestamp_to_iso(completion["submittedAt"]),
                "reviewStatus": "pending",
            })

        next_cursor = _encode_pending_cursor(page_snapshots[-1].reference.path) if has_more else None
        return {
            "items": items,
            "nextCursor": next_cursor,
            "pageSize": page_size,
        }
    except (ChallengeValidationError, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not read pending MLSC challenge completions.") from error


def _problem_for_review(db: Any, slug: str) -> tuple[Any, dict[str, Any]]:
    _validate_problem_slug(slug)
    problem_ref = db.collection("problems").document(slug)
    snapshot = problem_ref.get()
    if not snapshot.exists:
        raise FirebaseServiceError("A pending completion references a missing MLSC problem.")
    problem = snapshot.to_dict() or {}
    if problem.get("slug") != slug:
        raise FirebaseServiceError("A pending completion references an inconsistent MLSC problem.")
    url = problem.get("leetcodeUrl")
    try:
        parsed_url = urlsplit(url) if isinstance(url, str) else None
        url_port = parsed_url.port if parsed_url is not None else None
    except ValueError as error:
        raise FirebaseServiceError("A pending completion references an invalid MLSC problem URL.") from error
    if (
        parsed_url is None
        or parsed_url.scheme != "https"
        or parsed_url.hostname != "leetcode.com"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or url_port is not None
        or parsed_url.path.rstrip("/") != f"/problems/{slug}"
        or parsed_url.fragment
        or not isinstance(problem.get("title"), str)
        or not problem["title"].strip()
    ):
        raise FirebaseServiceError("A pending completion references an invalid MLSC problem.")
    return problem_ref, problem


def report_challenge_completion(uid: str, day: int) -> dict[str, Any]:
    _validate_day(day)
    if not isinstance(uid, str) or not uid:
        raise ChallengeValidationError("An authenticated learner UID is required.")
    db = firestore_client()
    challenge_ref = _challenge_ref(db)
    learner_ref = _learner_ref(db, uid)
    completion_ref = _completion_ref(db, uid, day)
    event_ref = _event_ref(completion_ref)

    @firestore.transactional
    def commit(transaction: Any) -> dict[str, Any]:
        learner = learner_ref.get(transaction=transaction)
        if not learner.exists or (learner.to_dict() or {}).get("role") != "learner":
            raise ChallengeNotFound("An active MLSC learner profile is required.")
        if (learner.to_dict() or {}).get("isActive") is False:
            raise ChallengeNotFound("An active MLSC learner profile is required.")
        _challenge_document(challenge_ref.get(transaction=transaction))
        problem_ref, assignment = _ensure_assigned_day(db, day, transaction)
        current_snapshot = completion_ref.get(transaction=transaction)
        current = current_snapshot.to_dict() if current_snapshot.exists else None
        previous_status = _completion_status(current)
        if previous_status == "verified":
            raise ChallengeConflict("A verified challenge completion cannot be changed.")
        if previous_status == "pending":
            raise ChallengeConflict("A challenge completion report is already pending review.")
        if current is not None and (
            current.get("day") != day
            or current.get("problemRef") != problem_ref
            or current.get("problemSlug") != assignment["problemSlug"]
        ):
            raise ChallengeConflict("The existing completion does not match the assigned problem.")

        event_type = "resubmitted" if previous_status == "rejected" else "reported"
        completion_data = {
            "day": day,
            "problemRef": problem_ref,
            "problemSlug": assignment["problemSlug"],
            "status": "pending",
            "submittedAt": firestore.SERVER_TIMESTAMP,
            "createdAt": current.get("createdAt", firestore.SERVER_TIMESTAMP) if current else firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        transaction.set(completion_ref, completion_data)
        transaction.create(event_ref, {
            "eventType": event_type,
            "previousStatus": previous_status if previous_status != "not_started" else None,
            "newStatus": "pending",
            "actorUid": uid,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        return {
            "day": day,
            "problemSlug": assignment["problemSlug"],
            "status": "pending",
            "verifiedCompletion": False,
            "submittedAt": None,
            "message": "Completion report submitted for administrator review.",
        }

    try:
        result = commit(db.transaction())
        completion = completion_ref.get().to_dict() or {}
        result["submittedAt"] = _timestamp_to_iso(completion.get("submittedAt"))
        result.pop("problemTitle", None)
        return result
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not submit the MLSC challenge completion.") from error


def review_challenge_completion(
    learner_uid: str,
    day: int,
    decision: str,
    reviewer_uid: str,
    review_note: str | None,
) -> dict[str, Any]:
    _validate_day(day)
    if not isinstance(learner_uid, str) or not learner_uid:
        raise ChallengeValidationError("A learner UID is required.")
    if not isinstance(reviewer_uid, str) or not reviewer_uid:
        raise ChallengeValidationError("An authenticated administrator UID is required.")
    if decision not in {"verified", "rejected"}:
        raise ChallengeValidationError("The review decision must be verified or rejected.")
    db = firestore_client()
    challenge_ref = _challenge_ref(db)
    learner_ref = _learner_ref(db, learner_uid)
    completion_ref = _completion_ref(db, learner_uid, day)
    event_ref = _event_ref(completion_ref)

    @firestore.transactional
    def commit(transaction: Any) -> dict[str, Any]:
        learner = learner_ref.get(transaction=transaction)
        if not learner.exists or (learner.to_dict() or {}).get("role") != "learner":
            raise ChallengeNotFound("The MLSC learner profile was not found.")
        _challenge_document(challenge_ref.get(transaction=transaction))
        problem_ref, assignment = _ensure_assigned_day(db, day, transaction)
        completion_snapshot = completion_ref.get(transaction=transaction)
        if not completion_snapshot.exists:
            raise ChallengeNotFound("No learner completion report was found for this challenge day.")
        completion = completion_snapshot.to_dict() or {}
        previous_status = _completion_status(completion)
        if previous_status != "pending":
            raise ChallengeConflict("Only pending challenge completion reports can be reviewed.")
        if (
            completion.get("day") != day
            or completion.get("problemRef") != problem_ref
            or completion.get("problemSlug") != assignment["problemSlug"]
        ):
            raise ChallengeConflict("The completion report no longer matches the assigned problem.")

        reviewed_data = {
            **completion,
            "status": decision,
            "reviewedAt": firestore.SERVER_TIMESTAMP,
            "reviewerUid": reviewer_uid,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        if decision == "verified":
            details: dict[str, Any] = {"method": "admin_review"}
            if review_note:
                details["note"] = review_note
            reviewed_data["verificationDetails"] = details
        else:
            reviewed_data.pop("verificationDetails", None)
        transaction.set(completion_ref, reviewed_data)
        event_data = {
            "eventType": decision,
            "previousStatus": "pending",
            "newStatus": decision,
            "actorUid": reviewer_uid,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }
        if review_note:
            event_data["reviewNote"] = review_note
        transaction.create(event_ref, event_data)
        return {
            "day": day,
            "problemSlug": assignment["problemSlug"],
            "status": decision,
            "verifiedCompletion": decision == "verified",
            "reviewerUid": reviewer_uid,
            "reviewedAt": None,
        }

    try:
        result = commit(db.transaction())
        completion = completion_ref.get().to_dict() or {}
        result["reviewedAt"] = _timestamp_to_iso(completion.get("reviewedAt"))
        return result
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError, FirebaseServiceError):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not review the MLSC challenge completion.") from error
