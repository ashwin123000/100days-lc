import os
from functools import lru_cache
from typing import Any


class FirebaseConfigurationError(RuntimeError):
    pass


class FirebaseTokenError(RuntimeError):
    pass


class FirebaseServiceError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def firebase_app():
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as error:
        raise FirebaseConfigurationError(
            "Firebase Admin SDK is not installed. Install backend/requirements.txt."
        ) from error

    project_id = os.getenv("FIREBASE_PROJECT_ID")
    if not project_id:
        raise FirebaseConfigurationError("FIREBASE_PROJECT_ID is not configured.")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        try:
            credential = credentials.ApplicationDefault()
            app = firebase_admin.initialize_app(
                credential,
                {"projectId": project_id},
            )
        except Exception as error:
            raise FirebaseConfigurationError(
                "Firebase Admin SDK initialization failed. Configure valid Application Default Credentials for this project."
            ) from error
    return app


def firestore_client():
    try:
        from firebase_admin import firestore
    except ImportError as error:
        raise FirebaseConfigurationError(
            "Firebase Admin SDK is not installed. Install backend/requirements.txt."
        ) from error
    return firestore.client(app=firebase_app())


def verify_id_token(token: str) -> dict[str, Any]:
    try:
        from firebase_admin import auth
        from firebase_admin.exceptions import FirebaseError
    except ImportError as error:
        raise FirebaseConfigurationError(
            "Firebase Admin SDK is not installed. Install backend/requirements.txt."
        ) from error
    try:
        return auth.verify_id_token(token, app=firebase_app())
    except auth.InvalidIdTokenError as error:
        raise FirebaseTokenError("The Firebase ID token is invalid or expired.") from error
    except auth.CertificateFetchError as error:
        raise FirebaseServiceError("Firebase token verification is temporarily unavailable.") from error
    except FirebaseError as error:
        raise FirebaseServiceError("Firebase token verification failed.") from error
