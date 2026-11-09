from typing import Any

from firebase_admin import firestore
from google.api_core.exceptions import GoogleAPIError

from .firebase_service import FirebaseServiceError, firestore_client


def _problem_document(record: dict[str, Any], original_url: str, solution: str, admin_notes: str) -> dict[str, Any]:
    slug = record["slug"]
    return {
        "problemId": slug,
        "externalProblemId": record["problem_id"],
        "title": record["title"],
        "slug": slug,
        "leetcodeUrl": original_url,
        "description": record.get("description", ""),
        "difficulty": record.get("difficulty"),
        "topicTags": record.get("topic_tags", []),
        "examples": record.get("examples", []),
        "constraints": record.get("constraints"),
        "inputOutputInformation": record.get("input_output_information", {}),
        "sampleTestCase": record.get("sample_test_case"),
        "starterCode": record.get("starter_code", []),
        "datasetMetadata": record.get("metadata"),
        "codeDefinition": record.get("code_definition"),
        "environmentInfo": record.get("environment_info"),
        "similarQuestions": record.get("similar_questions", []),
        "category": record.get("category"),
        "acceptanceRate": record.get("acceptance_rate"),
        "totalAccepted": record.get("total_accepted"),
        "totalSubmissions": record.get("total_submissions"),
        "solution": solution.strip() or record.get("solution"),
        "adminNotes": admin_notes.strip(),
        "isPublished": True,
        "isActivePotd": True,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }


def publish_potd(
    record: dict[str, Any],
    original_url: str,
    solution: str,
    admin_notes: str,
    published_by: str,
) -> dict[str, Any]:
    db = firestore_client()
    problem_ref = db.collection("problems").document(record["slug"])
    potd_ref = db.collection("dailyPotd").document("active")
    problem_data = _problem_document(record, original_url, solution, admin_notes)

    @firestore.transactional
    def commit(transaction):
        current_potd = potd_ref.get(transaction=transaction)
        previous_problem_id = current_potd.get("problemId") if current_potd.exists else None
        existing_problem = problem_ref.get(transaction=transaction)
        if existing_problem.exists:
            problem_data["createdAt"] = existing_problem.get("createdAt")
        else:
            problem_data["createdAt"] = firestore.SERVER_TIMESTAMP

        if previous_problem_id and previous_problem_id != record["slug"]:
            previous_ref = db.collection("problems").document(previous_problem_id)
            previous = previous_ref.get(transaction=transaction)
            if previous.exists:
                transaction.update(previous_ref, {
                    "isActivePotd": False,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                })

        transaction.set(problem_ref, problem_data, merge=True)
        transaction.set(potd_ref, {
            "problemId": record["slug"],
            "publishedAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "isActive": True,
            "publishedBy": published_by,
        })

    try:
        commit(db.transaction())
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not save the verified POTD.") from error
    return {
        **record,
        "problem_id": record["problem_id"],
        "slug": record["slug"],
        "original_url": original_url,
        "solution": solution.strip() or record.get("solution"),
        "admin_notes": admin_notes.strip(),
        "problemId": record["slug"],
    }


def get_active_potd() -> dict[str, Any] | None:
    try:
        db = firestore_client()
        potd_snapshot = db.collection("dailyPotd").document("active").get()
        if not potd_snapshot.exists or not potd_snapshot.get("isActive"):
            return None
        problem_snapshot = db.collection("problems").document(potd_snapshot.get("problemId")).get()
        if not problem_snapshot.exists:
            return None
        return {**problem_snapshot.to_dict(), "potd": potd_snapshot.to_dict()}
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not read the active POTD.") from error


def registered_learner_count() -> int:
    try:
        db = firestore_client()
        count_snapshot = (
            db.collection("users")
            .where("role", "==", "learner")
            .count()
            .get()
        )
        return int(count_snapshot[0][0].value)
    except GoogleAPIError as error:
        raise FirebaseServiceError("Firestore could not count registered learners.") from error
