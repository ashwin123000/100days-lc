import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    dataset_name: str = "kaysss/leetcode-problem-detailed"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    hf_token: str | None = None
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    semantic_min_score: float = 0.72
    semantic_min_margin: float = 0.04

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        )
        return cls(
            dataset_name=os.getenv(
                "HUGGINGFACE_DATASET",
                os.getenv(
                    "HF_DATASET_NAME",
                    "kaysss/leetcode-problem-detailed",
                ),
            ),
            embedding_model=os.getenv(
                "HF_EMBEDDING_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            hf_token=os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN"),
            cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        )
