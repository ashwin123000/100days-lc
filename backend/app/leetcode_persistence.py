import re
from typing import Any

from firebase_admin import firestore
from google.api_core.exceptions import GoogleAPIError

from .firebase_service import FirebaseServiceError, firestore_client


class LearnerProfileNotFound(RuntimeError):
    pass


class LeetCodeUsernameAlreadyClaimed(RuntimeError):
    pass


_PROBLEM_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _learner_ref(db: Any, uid: str) -> Any:
    return db.collection("users").document(uid)


def get_learner_record(uid: str) -> dict[str, Any]:
    try:
        snapshot = _learner_ref(firestore_client(), uid).get()
        if not snapshot.exists:
            raise LearnerProfileNotFound("An active MLSC learner profile is required.")
        data = snapshot.to_dict() or {}
        if data.get("role") != "learner" or data.get("isActive") is False:
            raise LearnerProfileNotFound("An active MLSC learner profile is required.")
        return data
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not read the learner profile.") from error


def connect_leetcode_username(uid: str, username: str) -> None:
    db = firestore_client()
    learner_ref = _learner_ref(db, uid)
    claim_collection = db.collection("leetcodeUsernameClaims")
    claim_ref = claim_collection.document(username.casefold())

    @firestore.transactional
    def commit(transaction: Any) -> None:
        learner = learner_ref.get(transaction=transaction)
        if not learner.exists:
            raise LearnerProfileNotFound("An active MLSC learner profile is required.")
        learner_data = learner.to_dict() or {}
        if learner_data.get("role") != "learner" or learner_data.get("isActive") is False:
            raise LearnerProfileNotFound("An active MLSC learner profile is required.")

        current_username = learner_data.get("leetcodeUsername")
        new_claim = claim_ref.get(transaction=transaction)
        if new_claim.exists and new_claim.get("uid") != uid:
            raise LeetCodeUsernameAlreadyClaimed("This LeetCode username is already connected to another learner.")

        old_claim_ref = None
        if isinstance(current_username, str) and current_username.casefold() != username.casefold():
            old_claim_ref = claim_collection.document(current_username.casefold())
            old_claim = old_claim_ref.get(transaction=transaction)
            if old_claim.exists and old_claim.get("uid") == uid:
                transaction.delete(old_claim_ref)

        transaction.set(claim_ref, {"uid": uid})
        transaction.update(learner_ref, {
            "leetcodeUsername": username,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

    try:
        commit(db.transaction())
    except (LearnerProfileNotFound, LeetCodeUsernameAlreadyClaimed):
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not save the LeetCode profile connection.") from error


def disconnect_leetcode_username(uid: str) -> bool:
    db = firestore_client()
    learner_ref = _learner_ref(db, uid)
    claim_collection = db.collection("leetcodeUsernameClaims")

    @firestore.transactional
    def commit(transaction: Any) -> bool:
        learner = learner_ref.get(transaction=transaction)
        if not learner.exists:
            raise LearnerProfileNotFound("An active MLSC learner profile is required.")
        learner_data = learner.to_dict() or {}
        if learner_data.get("role") != "learner" or learner_data.get("isActive") is False:
            raise LearnerProfileNotFound("An active MLSC learner profile is required.")

        username = learner_data.get("leetcodeUsername")
        if not isinstance(username, str) or not username:
            return False
        claim_ref = claim_collection.document(username.casefold())
        claim = claim_ref.get(transaction=transaction)
        if claim.exists and claim.get("uid") == uid:
            transaction.delete(claim_ref)
        transaction.update(learner_ref, {
            "leetcodeUsername": firestore.DELETE_FIELD,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        return True

    try:
        return commit(db.transaction())
    except LearnerProfileNotFound:
        raise
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not disconnect the LeetCode profile.") from error


def get_published_challenge_records() -> list[dict[str, Any]]:
    try:
        snapshots = (
            firestore_client()
            .collection("problems")
            .where("isPublished", "==", True)
            .stream()
        )
        records = []
        for snapshot in snapshots:
            data = snapshot.to_dict() or {}
            slug = data.get("slug") or data.get("problemId") or snapshot.id
            if not isinstance(slug, str) or not _PROBLEM_SLUG_PATTERN.fullmatch(slug):
                continue
            records.append({
                "challengeDay": data.get("challengeDay"),
                "title": data.get("title"),
                "slug": slug,
                "leetcodeUrl": f"https://leetcode.com/problems/{slug}/",
                "difficulty": data.get("difficulty"),
                "publicationStatus": "published",
            })
        return sorted(
            records,
            key=lambda record: (
                record["challengeDay"] is None,
                record["challengeDay"] if isinstance(record["challengeDay"], int) else 0,
                record["title"] or "",
            ),
        )
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not read published MLSC problems.") from error
