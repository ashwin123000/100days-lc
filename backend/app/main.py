from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .firebase_service import (
    FirebaseConfigurationError,
    FirebaseServiceError,
    FirebaseTokenError,
    verify_id_token,
)
from .problem_catalog import ProblemCatalog, ProblemLookupError
from .problem_persistence import get_active_potd, publish_potd, registered_learner_count
from .schemas import (
    ErrorResponse,
    LearnerCountResponse,
    PotdPrepareRequest,
    PotdPublishRequest,
    ProblemLookupRequest,
    ProblemRecord,
)
from .settings import Settings

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
settings = Settings.from_env()


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.catalog = catalog
    yield


app = FastAPI(
    title="MLSC Problem Retrieval API",
    version="2.0.0",
    description="Verified Hugging Face problem retrieval and Firebase-backed challenge publishing.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

catalog = ProblemCatalog(
    dataset_name=settings.dataset_name,
    embedding_model=settings.embedding_model,
    hf_token=settings.hf_token,
    min_score=settings.semantic_min_score,
    min_margin=settings.semantic_min_margin,
)


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
