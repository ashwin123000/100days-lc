import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from .challenge_persistence import (
    ChallengeConflict,
    ChallengeNotConfigured,
    ChallengeNotFound,
    ChallengeValidationError,
    assign_challenge_day,
    get_challenge_progress,
    get_challenge_questions,
    get_pending_challenge_completions,
    get_verified_challenge_leaderboard,
    initialize_challenge,
    report_challenge_completion,
    review_challenge_completion,
    sync_accepted_submissions,
)
from .firebase_service import (
    FirebaseConfigurationError,
    FirebaseServiceError,
    FirebaseTokenError,
    verify_id_token,
)
from .leetcode_persistence import (
    LearnerProfileNotFound,
    LeetCodeUsernameAlreadyClaimed,
    connect_leetcode_username,
    disconnect_leetcode_username,
    get_learner_record,
)
from .leetcode_service import (
    LearnerRequestLimiter,
    LeetCodeServiceError,
    leetcode_service,
    summarize_activity,
)
from .problem_catalog import ProblemCatalog, ProblemLookupError
from .problem_persistence import get_active_potd, publish_potd, registered_learner_count
from .schemas import (
    ChallengeCompletionReportRequest,
    ChallengeCompletionReviewRequest,
    ChallengeDayAssignmentRequest,
    ErrorResponse,
    LeetCodeConnectRequest,
    LearnerCountResponse,
    PotdPrepareRequest,
    PotdPublishRequest,
    ProblemLookupRequest,
    ProblemRecord,
)
from .settings import Settings

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
settings = Settings.from_env()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.catalog = catalog
    yield


app = FastAPI(
    title="MLSC Problem Retrieval API",
    version="2.0.0",
    description="Verified problem retrieval, Firebase-backed publishing, and MLSC challenge progress.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def log_api_failures(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        route = request.scope.get("route")
        logger.exception(
            "api_request_exception request_id=%s method=%s route=%s",
            request_id,
            request.method,
            getattr(route, "path", "unmatched"),
        )
        raise

    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    if response.status_code >= 500:
        error_source = response.headers.get("X-Error-Source", "backend")
        response.headers.setdefault("X-Error-Source", error_source)
        logger.error(
            "api_request_failure request_id=%s method=%s route=%s status=%s source=%s duration_ms=%.1f",
            request_id,
            request.method,
            route_path,
            response.status_code,
            error_source,
            (perf_counter() - started_at) * 1000,
        )
    response.headers["X-Request-ID"] = request_id
    return response

catalog = ProblemCatalog(
    dataset_name=settings.dataset_name,
    embedding_model=settings.embedding_model,
    hf_token=settings.hf_token,
    min_score=settings.semantic_min_score,
    min_margin=settings.semantic_min_margin,
)
leetcode_request_limiter = LearnerRequestLimiter()


def _http_error(error: ProblemLookupError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


def _catalog(request: Request) -> ProblemCatalog:
    return request.app.state.catalog


def _authenticated_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A Firebase ID token is required.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="A Firebase ID token is required.")
    try:
        return verify_id_token(token)
    except FirebaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FirebaseTokenError as error:
        raise HTTPException(status_code=401, detail="The Firebase ID token is invalid or expired.") from error
    except FirebaseServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _admin_user(user: dict[str, Any] = Depends(_authenticated_user)) -> dict[str, Any]:
    if user.get("admin") is not True:
        raise HTTPException(status_code=403, detail="An authorized admin account is required.")
    return user


def _leetcode_learner(user: dict[str, Any] = Depends(_authenticated_user)) -> dict[str, Any]:
    uid = user.get("uid")
    if not isinstance(uid, str) or not uid:
        raise HTTPException(status_code=401, detail="The Firebase ID token has no user identity.")
    try:
        profile = get_learner_record(uid)
    except LearnerProfileNotFound as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if profile.get("role") != "learner" or profile.get("isActive") is False:
        raise HTTPException(status_code=403, detail="An active MLSC learner profile is required.")
    if not leetcode_request_limiter.check(uid):
        raise HTTPException(
            status_code=429,
            detail={"code": "request_rate_limited", "message": "Too many LeetCode profile requests. Try again shortly."},
            headers={"Retry-After": "60"},
        )
    return {"uid": uid, "profile": profile}


def _challenge_learner(user: dict[str, Any] = Depends(_authenticated_user)) -> dict[str, str]:
    uid = user.get("uid")
    if not isinstance(uid, str) or not uid:
        raise HTTPException(status_code=401, detail="The Firebase ID token has no user identity.")
    try:
        profile = get_learner_record(uid)
    except LearnerProfileNotFound as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if profile.get("role") != "learner" or profile.get("isActive") is False:
        raise HTTPException(status_code=403, detail="An active MLSC learner profile is required.")
    return {"uid": uid}


def _challenge_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ChallengeValidationError):
        return HTTPException(
            status_code=422,
            detail={"code": "invalid_challenge_request", "message": str(error)},
        )
    if isinstance(error, ChallengeNotConfigured):
        return HTTPException(
            status_code=404,
            detail={"code": "challenge_not_configured", "message": str(error)},
        )
    if isinstance(error, ChallengeNotFound):
        return HTTPException(
            status_code=404,
            detail={"code": "challenge_resource_not_found", "message": str(error)},
        )
    if isinstance(error, ChallengeConflict):
        return HTTPException(
            status_code=409,
            detail={"code": "challenge_conflict", "message": str(error)},
        )
    raise TypeError("Unsupported challenge error.")


def _leetcode_response_error(error: LeetCodeServiceError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
        headers={
            "X-Error-Source": "leetcode_upstream",
            **({"Retry-After": "60"} if error.status_code == 429 else {}),
        },
    )


def _challenge_records(uid: str) -> list[dict[str, Any]]:
    try:
        records = get_challenge_questions(uid)["questions"]
    except ChallengeNotConfigured:
        return []
    return [
        {
            **record,
            "source": "mlsc",
            "challengeDay": record["day"],
            "completionStatus": record["verificationStatus"],
        }
        for record in records
    ]


def _unconfigured_challenge_progress() -> dict[str, Any]:
    return {
        "challengeId": "leetcode-100-days",
        "configured": False,
        "totalDays": 100,
        "completedDays": None,
        "completionPercentage": None,
        "remainingDays": None,
        "currentStreak": None,
        "longestStreak": None,
        "recentDays": [],
    }


def _unconfigured_challenge_questions() -> dict[str, Any]:
    return {
        "challengeId": "leetcode-100-days",
        "configured": False,
        "totalDays": 100,
        "questions": [],
    }


def _profile_response(uid: str, username: str, refresh: bool = False) -> dict[str, Any]:
    profile = leetcode_service.get_profile(username, refresh=refresh)
    return {
        "profile": profile["profile"],
        "problemStatistics": profile["problemStatistics"],
        "contestStatistics": profile.get("contestStatistics"),
        "challengeRecords": _challenge_records(uid),
        "unavailableFields": profile.get("unavailableFields", []),
    }


def _sync_accepted_submissions(uid: str, profile: dict[str, Any]) -> dict[str, Any]:
    return sync_accepted_submissions(
        uid,
        profile.get("recentAcceptedSubmissions", []),
        profile.get("recentAcceptedAvailable") is True,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/problems/lookup",
    response_model=ProblemRecord,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def lookup_problem(payload: ProblemLookupRequest, request: Request) -> ProblemRecord:
    try:
        problem = _catalog(request).lookup(payload.title, payload.leetcode_url)
    except ProblemLookupError as error:
        raise _http_error(error) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ProblemRecord.model_validate({**problem, "original_url": payload.leetcode_url.strip()})


@app.get(
    "/api/problems/{problem_id}",
    response_model=ProblemRecord,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_problem(problem_id: str, request: Request) -> ProblemRecord:
    try:
        problem = _catalog(request).get_by_id(problem_id)
    except ProblemLookupError as error:
        raise _http_error(error) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    original_url = f"https://leetcode.com/problems/{problem['slug']}/"
    return ProblemRecord.model_validate({**problem, "original_url": original_url})


@app.get("/api/potd")
def get_potd() -> dict[str, Any]:
    try:
        return {"problem": get_active_potd()}
    except FirebaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FirebaseServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post(
    "/api/admin/potd/prepare",
    response_model=ProblemRecord,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def prepare_potd(
    payload: PotdPrepareRequest,
    request: Request,
    _user: dict[str, Any] = Depends(_admin_user),
) -> ProblemRecord:
    try:
        record = _catalog(request).lookup(payload.title, payload.leetcode_url)
    except ProblemLookupError as error:
        raise _http_error(error) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return ProblemRecord.model_validate({**record, "original_url": payload.leetcode_url.strip()})


@app.post(
    "/api/admin/potd/publish",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def publish_daily_potd(
    payload: PotdPublishRequest,
    request: Request,
    user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    try:
        record = _catalog(request).lookup(payload.title, payload.leetcode_url)
        published = publish_potd(
            record,
            payload.leetcode_url.strip(),
            payload.solution,
            payload.admin_notes,
            str(user["uid"]),
        )
    except ProblemLookupError as error:
        raise _http_error(error) from error
    except FirebaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FirebaseServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"problem": published}


@app.get(
    "/api/admin/learners/count",
    response_model=LearnerCountResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_learner_count(_user: dict[str, Any] = Depends(_admin_user)) -> LearnerCountResponse:
    try:
        return LearnerCountResponse(count=registered_learner_count())
    except FirebaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FirebaseServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.put("/api/admin/challenge/days/{day}")
def put_challenge_day(
    day: int,
    payload: ChallengeDayAssignmentRequest,
    user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    admin_uid = user.get("uid")
    if not isinstance(admin_uid, str) or not admin_uid:
        raise HTTPException(status_code=401, detail="The Firebase ID token has no user identity.")
    try:
        return assign_challenge_day(day, payload.problem_slug, admin_uid)
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/admin/challenge/initialize")
def post_initialize_challenge(
    user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    admin_uid = user.get("uid")
    if not isinstance(admin_uid, str) or not admin_uid:
        raise HTTPException(status_code=401, detail="The Firebase ID token has no user identity.")
    try:
        return initialize_challenge(admin_uid)
    except ChallengeValidationError as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/challenge/questions")
def get_challenge_question_history(
    learner: dict[str, str] = Depends(_challenge_learner),
) -> dict[str, Any]:
    try:
        return get_challenge_questions(learner["uid"])
    except ChallengeNotConfigured:
        return _unconfigured_challenge_questions()
    except (ChallengeConflict, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/challenge/progress")
def get_challenge_progress_summary(
    learner: dict[str, str] = Depends(_challenge_learner),
) -> dict[str, Any]:
    try:
        return get_challenge_progress(learner["uid"])
    except ChallengeNotConfigured:
        return _unconfigured_challenge_progress()
    except (ChallengeConflict, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/leaderboard")
def get_learner_leaderboard(
    _learner: dict[str, str] = Depends(_challenge_learner),
) -> dict[str, Any]:
    try:
        return get_verified_challenge_leaderboard()
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/admin/challenge/completions/pending")
def get_pending_challenge_completion_queue(
    page_size: int = Query(default=25, alias="pageSize", ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    _user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    try:
        return get_pending_challenge_completions(page_size, cursor)
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.put("/api/challenge/days/{day}/completion")
def put_challenge_completion(
    day: int,
    payload: ChallengeCompletionReportRequest,
    learner: dict[str, str] = Depends(_challenge_learner),
) -> dict[str, Any]:
    try:
        return report_challenge_completion(learner["uid"], day)
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.put("/api/admin/challenge/completions/{uid}/{day}")
def put_challenge_completion_review(
    uid: str,
    day: int,
    payload: ChallengeCompletionReviewRequest,
    user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    reviewer_uid = user.get("uid")
    if not isinstance(reviewer_uid, str) or not reviewer_uid:
        raise HTTPException(status_code=401, detail="The Firebase ID token has no user identity.")
    try:
        return review_challenge_completion(
            uid,
            day,
            payload.decision,
            reviewer_uid,
            payload.review_note,
        )
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/leetcode/connect")
def connect_leetcode_profile(
    payload: LeetCodeConnectRequest,
    refresh: bool = Query(default=False),
    learner: dict[str, Any] = Depends(_leetcode_learner),
) -> dict[str, Any]:
    try:
        profile = leetcode_service.get_profile(payload.username, refresh=refresh)
        canonical_username = profile["profile"]["username"]
        connect_leetcode_username(learner["uid"], canonical_username)
        try:
            challenge_sync = _sync_accepted_submissions(learner["uid"], profile)
        except (
            ChallengeConflict,
            ChallengeNotConfigured,
            ChallengeNotFound,
            ChallengeValidationError,
            FirebaseConfigurationError,
            FirebaseServiceError,
        ) as error:
            challenge_sync = {
                "status": "unable_to_verify",
                "message": str(error),
                "verifiedDays": [],
                "dayStatuses": {},
            }
        try:
            challenge_records = _challenge_records(learner["uid"])
        except (
            ChallengeConflict,
            ChallengeNotConfigured,
            ChallengeNotFound,
            ChallengeValidationError,
            FirebaseConfigurationError,
            FirebaseServiceError,
        ) as error:
            challenge_records = []
            challenge_sync = {
                "status": "unable_to_verify",
                "message": str(error),
                "verifiedDays": challenge_sync.get("verifiedDays", []),
                "dayStatuses": challenge_sync.get("dayStatuses", {}),
            }
        return {
            "profile": profile["profile"],
            "problemStatistics": profile["problemStatistics"],
            "contestStatistics": profile.get("contestStatistics"),
            "challengeRecords": challenge_records,
            "unavailableFields": profile.get("unavailableFields", []),
            "challengeSync": challenge_sync,
        }
    except LeetCodeUsernameAlreadyClaimed as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "leetcode_username_in_use", "message": str(error)},
        ) from error
    except LearnerProfileNotFound as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error) from error


@app.get("/api/leetcode/profile")
def get_leetcode_profile(
    refresh: bool = Query(default=False),
    learner: dict[str, Any] = Depends(_leetcode_learner),
) -> dict[str, Any]:
    username = learner["profile"].get("leetcodeUsername")
    if not username:
        raise HTTPException(
            status_code=404,
            detail={"code": "leetcode_not_connected", "message": "No LeetCode username is connected."},
        )
    try:
        response = _profile_response(learner["uid"], username, refresh=refresh)
        if refresh:
            try:
                response["challengeSync"] = _sync_accepted_submissions(
                    learner["uid"],
                    leetcode_service.get_profile(username),
                )
            except ChallengeNotConfigured as error:
                response["challengeSync"] = {
                    "status": "unable_to_verify",
                    "message": str(error),
                    "verifiedDays": [],
                    "dayStatuses": {},
                }
            response["challengeRecords"] = _challenge_records(learner["uid"])
        return response
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error) from error


@app.post("/api/challenge/sync")
def sync_leetcode_challenge_completions(
    refresh: bool = Query(default=False),
    learner: dict[str, Any] = Depends(_leetcode_learner),
) -> dict[str, Any]:
    username = learner["profile"].get("leetcodeUsername")
    if not username:
        try:
            questions = get_challenge_questions(learner["uid"])["questions"]
        except ChallengeNotConfigured:
            return {
                "status": "not_configured",
                "message": "The 100-day challenge has not been configured yet.",
                "verifiedDays": [],
                "dayStatuses": {},
            }
        except (ChallengeConflict, ChallengeNotFound, ChallengeValidationError) as error:
            raise _challenge_http_error(error) from error
        except (FirebaseConfigurationError, FirebaseServiceError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "status": "awaiting_sync",
            "verifiedDays": [],
            "dayStatuses": {
                str(question["day"]): (
                    "verified" if question["status"] == "verified" else "awaiting_sync"
                )
                for question in questions
            },
        }
    try:
        profile = leetcode_service.get_profile(username, refresh=refresh)
        return _sync_accepted_submissions(learner["uid"], profile)
    except ChallengeNotConfigured as error:
        return {
            "status": "not_configured",
            "message": str(error),
            "verifiedDays": [],
            "dayStatuses": {},
        }
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error) from error
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/leetcode/heatmap")
def get_leetcode_heatmap(
    start_date: date | None = Query(default=None, alias="from"),
    end_date: date | None = Query(default=None, alias="to"),
    refresh: bool = Query(default=False),
    learner: dict[str, Any] = Depends(_leetcode_learner),
) -> dict[str, Any]:
    username = learner["profile"].get("leetcodeUsername")
    if not username:
        raise HTTPException(
            status_code=404,
            detail={"code": "leetcode_not_connected", "message": "No LeetCode username is connected."},
        )
    today = datetime.now(timezone.utc).date()
    effective_end = end_date or today
    effective_start = start_date or effective_end - timedelta(days=364)
    if effective_end < effective_start or effective_end > today or (effective_end - effective_start).days > 365:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_date_range", "message": "The requested date range must be ordered, end no later than today, and no longer than 366 days."},
        )
    try:
        activity = leetcode_service.get_calendar(
            username,
            effective_start,
            effective_end,
            refresh=refresh,
        )
        return {
            "username": username,
            "calendar": activity,
            "availableFrom": activity[0]["date"] if activity else None,
            "availableTo": activity[-1]["date"] if activity else None,
            "availableYears": leetcode_service.get_calendar_metadata(
                username,
                set(range(effective_start.year, effective_end.year + 1)),
            )["availableYears"],
        }
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_date_range", "message": str(error)},
        ) from error


@app.get("/api/leetcode/stats")
def get_leetcode_stats(
    refresh: bool = Query(default=False),
    learner: dict[str, Any] = Depends(_leetcode_learner),
) -> dict[str, Any]:
    username = learner["profile"].get("leetcodeUsername")
    if not username:
        raise HTTPException(
            status_code=404,
            detail={"code": "leetcode_not_connected", "message": "No LeetCode username is connected."},
        )
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=364)
    try:
        profile = leetcode_service.get_profile(username, refresh=refresh)
        try:
            calendar = leetcode_service.get_calendar(username, start, end, refresh=refresh)
            calendar_metadata = leetcode_service.get_calendar_metadata(username, {end.year})
            activity = summarize_activity(calendar)
            if calendar_metadata["currentStreak"] is not None:
                activity["currentStreak"] = calendar_metadata["currentStreak"]
            activity["totalActiveDays"] = calendar_metadata["totalActiveDays"]
            activity["longestStreak"] = None
            activity_error = None
        except LeetCodeServiceError as error:
            activity = None
            activity_error = {"code": error.code, "message": str(error)}
        return {
            "username": username,
            "problemStatistics": profile["problemStatistics"],
            "contestStatistics": profile.get("contestStatistics"),
            "activity": activity,
            "activityError": activity_error,
            "unavailableFields": sorted(set(
                profile.get("unavailableFields", [])
                + (["activity"] if activity_error else [])
            )),
        }
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error) from error


@app.delete("/api/leetcode/connect")
def disconnect_leetcode_profile(
    learner: dict[str, Any] = Depends(_leetcode_learner),
) -> dict[str, bool]:
    try:
        disconnect_leetcode_username(learner["uid"])
        return {"connected": False}
    except LearnerProfileNotFound as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
