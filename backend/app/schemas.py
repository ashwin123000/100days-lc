from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProblemLookupRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    leetcode_url: str = Field(min_length=1, max_length=2048)


class LeetCodeConnectRequest(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=25,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ChallengeDayAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_slug: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        alias="problemSlug",
    )


class ChallengeCompletionReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending"]


class ChallengeCompletionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Literal["verified", "rejected"]
    review_note: str | None = Field(default=None, max_length=2000, alias="reviewNote")


class ProblemRecord(BaseModel):
    problem_id: str
    title: str
    slug: str
    description: str
    difficulty: str | None = None
    acceptance_rate: float | None = None
    total_accepted: int | str | None = None
    total_submissions: int | str | None = None
    topic_tags: list[dict[str, Any] | str] = Field(default_factory=list)
    category: str | None = None
    examples: list[dict[str, Any] | str] = Field(default_factory=list)
    constraints: Any | None = None
    input_output_information: dict[str, Any] = Field(default_factory=dict)
    starter_code: list[dict[str, str]] = Field(default_factory=list)
    code_definition: Any | None = None
    solution: Any | None = None
    similar_questions: list[dict[str, Any] | str] = Field(default_factory=list)
    sample_test_case: str | None = None
    metadata: Any | None = None
    environment_info: str | None = None
    original_url: str


class PotdPrepareRequest(ProblemLookupRequest):
    pass


class PotdPublishRequest(ProblemLookupRequest):
    solution: str = Field(default="", max_length=100_000)
    admin_notes: str = Field(default="", max_length=30_000)


class PotdResponse(BaseModel):
    problem: ProblemRecord | None


class LearnerCountResponse(BaseModel):
    count: int


class ClientErrorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=2000)
    stack_trace: str = Field(default="", strict=True, max_length=12000, alias="stackTrace")
    method: str | None = Field(default=None, strict=True, max_length=12)
    http_status: int | None = Field(default=None, strict=True, ge=100, le=599, alias="httpStatus")
    request_id: str | None = Field(default=None, strict=True, max_length=100, alias="requestId")


class ErrorResponse(BaseModel):
    detail: str
    code: str
