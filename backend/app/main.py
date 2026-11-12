import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

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
    ClientErrorRequest,
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
from . import system_logs

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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID", "X-Error-Source"],
)


@app.middleware("http")
async def log_api_failures(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        logger.error(
            "api_request_exception request_id=%s method=%s route=%s error_type=%s",
            request_id,
            request.method,
            route_path,
            type(error).__name__,
        )
        if (
            request.url.path != "/api/client-errors"
            and not request.url.path.startswith("/api/admin/system-logs")
        ):
            await run_in_threadpool(
                system_logs.capture_error_from_request,
                source="BACKEND",
                endpoint=route_path,
                method=request.method,
                status=500,
                request_id=request_id,
                user_id=getattr(request.state, "user_id", None),
                duration_ms=(perf_counter() - started_at) * 1000,
                error_code=type(error).__name__,
                message=str(error),
                error=error,
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
            headers={
                "X-Request-ID": request_id,
                "X-Error-Source": "BACKEND",
            },
        )

    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    error_source = response.headers.get("X-Error-Source")
    if response.status_code >= 500 or error_source or response.status_code in {401, 403}:
        error_source = error_source or ("AUTH" if response.status_code in {401, 403} else "BACKEND")
        response.headers["X-Error-Source"] = error_source
        log_context = getattr(request.state, "log_context", {})
        should_capture = (
            request.url.path != "/api/client-errors"
            and not (
                request.url.path.startswith("/api/admin/system-logs")
                and response.status_code >= 500
            )
        )
        if should_capture:
            previous_background = response.background

            async def persist_request_error() -> None:
                try:
                    if previous_background is not None:
                        await previous_background()
                finally:
                    await run_in_threadpool(
                        system_logs.capture_error_from_request,
                        source=log_context.get("source", error_source),
                        endpoint=route_path,
                        method=request.method,
                        status=response.status_code,
                        request_id=request_id,
                        user_id=getattr(request.state, "user_id", None),
                        duration_ms=(perf_counter() - started_at) * 1000,
                        error_code=log_context.get("error_code", f"HTTP_{response.status_code}"),
                        message=log_context.get(
                            "message",
                            f"Request failed with HTTP {response.status_code}.",
                        ),
                        error=log_context.get("error"),
                        severity=log_context.get(
                            "severity",
                            "WARNING" if response.status_code in {401, 403} else "ERROR",
                        ),
                    )

            response.background = BackgroundTask(persist_request_error)
        if response.status_code >= 500:
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
frontend_error_limiter = LearnerRequestLimiter(limit=10, window_seconds=60)


def _http_error(error: ProblemLookupError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


def _catalog(request: Request) -> ProblemCatalog:
    return request.app.state.catalog


def _firebase_http_error(error: Exception, source: str | None = None) -> HTTPException:
    if source is None:
        source = "FIRESTORE" if isinstance(error, FirebaseServiceError) else "BACKEND"
    return HTTPException(
        status_code=503,
        detail=str(error),
        headers={"X-Error-Source": source},
    )


def _authenticated_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="A Firebase ID token is required.",
            headers={"X-Error-Source": "AUTH"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="A Firebase ID token is required.",
            headers={"X-Error-Source": "AUTH"},
        )
    try:
        user = verify_id_token(token)
        uid = user.get("uid")
        request.state.user_id = uid if isinstance(uid, str) else None
        return user
    except FirebaseConfigurationError as error:
        raise _firebase_http_error(error, "BACKEND") from error
    except FirebaseTokenError as error:
        raise HTTPException(
            status_code=401,
            detail="The Firebase ID token is invalid or expired.",
            headers={"X-Error-Source": "AUTH"},
        ) from error
    except FirebaseServiceError as error:
        raise _firebase_http_error(error, "AUTH") from error


def _admin_user(user: dict[str, Any] = Depends(_authenticated_user)) -> dict[str, Any]:
    if user.get("admin") is not True:
        raise HTTPException(
            status_code=403,
            detail="An authorized admin account is required.",
            headers={"X-Error-Source": "AUTH"},
        )
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
        raise _firebase_http_error(error) from error
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
        raise _firebase_http_error(error) from error
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


def _leetcode_response_error(
    error: LeetCodeServiceError,
    request: Request | None = None,
) -> HTTPException:
    if request is not None:
        request.state.log_context = {
            "source": error.source,
            "error_code": error.code,
            "message": str(error),
            "error": error,
            "severity": "WARNING" if error.status_code == 429 else "ERROR",
        }
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
        headers={
            "X-Error-Source": error.source,
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


@app.post("/api/client-errors", status_code=202)
def post_client_error(
    payload: ClientErrorRequest,
    request: Request,
    user: dict[str, Any] = Depends(_authenticated_user),
) -> dict[str, bool]:
    uid = user.get("uid")
    if not isinstance(uid, str) or not uid:
        raise HTTPException(
            status_code=401,
            detail="The Firebase ID token has no user identity.",
            headers={"X-Error-Source": "AUTH"},
        )
    if not payload.endpoint.startswith("/") or payload.endpoint.startswith("//") or "?" in payload.endpoint:
        raise HTTPException(status_code=422, detail="The error endpoint must be a relative path.")
    if not frontend_error_limiter.check(uid):
        raise HTTPException(
            status_code=429,
            detail="Too many client error reports. Try again shortly.",
            headers={"Retry-After": "60"},
        )
    system_logs.capture_error_from_request(
        source="FRONTEND",
        endpoint=payload.endpoint,
        method="CLIENT",
        status=0,
        request_id=getattr(request.state, "request_id", ""),
        user_id=uid,
        error_code=payload.operation,
        message=payload.message,
        error=None,
    )
    return {"accepted": True}


@app.get("/api/admin/system-logs")
def get_system_logs(
    page_size: int = Query(default=25, alias="pageSize", ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=512),
    source: str | None = Query(default=None, max_length=40),
    severity: str | None = Query(default=None, max_length=20),
    resolution_status: str | None = Query(default=None, alias="resolutionStatus", max_length=20),
    start_date: date | None = Query(default=None, alias="startDate"),
    end_date: date | None = Query(default=None, alias="endDate"),
    search: str | None = Query(default=None, max_length=120),
    _user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    try:
        return system_logs.list_logs(
            page_size=page_size,
            cursor=cursor,
            source=source,
            severity=severity,
            resolution_status=resolution_status,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except system_logs.SystemLogStorageError as error:
        raise _firebase_http_error(error, "FIRESTORE") from error


@app.get("/api/admin/system-logs/{log_id}")
def get_system_log(
    log_id: str,
    _user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    try:
        record = system_logs.get_log(log_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except system_logs.SystemLogStorageError as error:
        raise _firebase_http_error(error, "FIRESTORE") from error
    if record is None:
        raise HTTPException(status_code=404, detail="The requested error log was not found.")
    return record


@app.patch("/api/admin/system-logs/{log_id}/resolve")
def resolve_system_log(
    log_id: str,
    user: dict[str, Any] = Depends(_admin_user),
) -> dict[str, Any]:
    uid = user.get("uid")
    if not isinstance(uid, str) or not uid:
        raise HTTPException(
            status_code=401,
            detail="The Firebase ID token has no user identity.",
            headers={"X-Error-Source": "AUTH"},
        )
    try:
        record = system_logs.resolve_log(log_id, uid)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except system_logs.SystemLogStorageError as error:
        raise _firebase_http_error(error, "FIRESTORE") from error
    if record is None:
        raise HTTPException(status_code=404, detail="The requested error log was not found.")
    return record


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
        raise _firebase_http_error(error, "BACKEND") from error
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
        raise _firebase_http_error(error, "BACKEND") from error
    original_url = f"https://leetcode.com/problems/{problem['slug']}/"
    return ProblemRecord.model_validate({**problem, "original_url": original_url})


@app.get("/api/potd")
def get_potd() -> dict[str, Any]:
    try:
        return {"problem": get_active_potd()}
    except FirebaseConfigurationError as error:
        raise _firebase_http_error(error) from error
    except FirebaseServiceError as error:
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error, "BACKEND") from error
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
        raise _firebase_http_error(error) from error
    except FirebaseServiceError as error:
        raise _firebase_http_error(error) from error
    except RuntimeError as error:
        raise _firebase_http_error(error, "BACKEND") from error
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
        raise _firebase_http_error(error) from error
    except FirebaseServiceError as error:
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


@app.get("/api/leaderboard")
def get_learner_leaderboard(
    _learner: dict[str, str] = Depends(_challenge_learner),
) -> dict[str, Any]:
    try:
        return get_verified_challenge_leaderboard()
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


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
        raise _firebase_http_error(error) from error


@app.post("/api/leetcode/connect")
def connect_leetcode_profile(
    request: Request,
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
        raise _firebase_http_error(error) from error
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error, request) from error


@app.get("/api/leetcode/profile")
def get_leetcode_profile(
    request: Request,
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
        raise _firebase_http_error(error) from error
    except LeetCodeServiceError as error:
        raise _leetcode_response_error(error, request) from error


@app.post("/api/challenge/sync")
def sync_leetcode_challenge_completions(
    request: Request,
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
            raise _firebase_http_error(error) from error
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
        raise _leetcode_response_error(error, request) from error
    except (ChallengeConflict, ChallengeNotConfigured, ChallengeNotFound, ChallengeValidationError) as error:
        raise _challenge_http_error(error) from error
    except (FirebaseConfigurationError, FirebaseServiceError) as error:
        raise _firebase_http_error(error) from error


@app.get("/api/leetcode/heatmap")
def get_leetcode_heatmap(
    request: Request,
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
        raise _leetcode_response_error(error, request) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_date_range", "message": str(error)},
        ) from error


@app.get("/api/leetcode/stats")
def get_leetcode_stats(
    request: Request,
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
        raise _leetcode_response_error(error, request) from error


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
        raise _firebase_http_error(error) from error
