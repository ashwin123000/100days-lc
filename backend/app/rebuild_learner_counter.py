from pathlib import Path

from dotenv import load_dotenv

from .firebase_service import firestore_client


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from firebase_admin import firestore

    db = firestore_client()
    count = int(
        db.collection("users")
        .where("role", "==", "learner")
        .count()
        .get()[0][0].value
    )
    db.collection("stats").document("registeredLearners").set({
        "count": count,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    print(f"Registered learner count initialized to {count}.")


if __name__ == "__main__":
    main()
