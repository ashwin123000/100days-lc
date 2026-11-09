from typing import Any

from pydantic import BaseModel, Field


class ProblemLookupRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    leetcode_url: str = Field(min_length=1, max_length=2048)


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


class ErrorResponse(BaseModel):
    detail: str
    code: str
