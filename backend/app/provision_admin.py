import argparse
from pathlib import Path

from dotenv import load_dotenv

from .firebase_service import firebase_app


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(
        description="Grant the Firebase admin custom claim to an existing Auth user UID."
    )
    parser.add_argument("uid", help="UID of an existing Firebase Authentication user")
    arguments = parser.parse_args()

    import firebase_admin
    from firebase_admin import auth

    app = firebase_app()
    user = auth.get_user(arguments.uid, app=app)
    existing_claims = dict(user.custom_claims or {})
    existing_claims["admin"] = True
    auth.set_custom_user_claims(user.uid, existing_claims, app=app)
    print(f"Admin claim assigned to UID {user.uid}. The user must sign in again to refresh claims.")


if __name__ == "__main__":
    main()
