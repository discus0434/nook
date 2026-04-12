from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from nook.services.catalog import SERVICE_DEFINITIONS
from nook.services.runtime_secrets import (
    AWS_RUNTIME_SECRET_ID_ENV,
    DEFAULT_AWS_RUNTIME_SECRET_ID,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SOURCE_DIRECTORIES = (Path("nook"), Path("configs"))
REQUIREMENTS_DIR = Path("nook/deploy/aws/requirements")
COMMON_REQUIREMENTS = REQUIREMENTS_DIR / "common.txt"
SERVICE_REQUIREMENTS = {
    definition.name: REQUIREMENTS_DIR / f"{definition.name}.txt"
    for definition in SERVICE_DEFINITIONS
}
MEMORY_SIZES = {
    "paper_summarizer": 2048,
    "product_hunt": 512,
    "hacker_news": 512,
    "github_trending": 512,
    "reddit_explorer": 512,
    "tech_feed": 512,
    "google_alerts": 512,
    "tech_news": 512,
    "viewer": 512,
}
TIMEOUT_SECONDS = {
    "viewer": 30,
}
EXTRA_INSTALL_COMMANDS = {
    "paper_summarizer": ["python -m pip install sgmllib3k arxiv -t /asset-output"],
}


@dataclass(frozen=True, slots=True)
class AwsStackConfig:
    runtime_secret_id: str
    llm_model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str | None]) -> "AwsStackConfig":
        llm_model = env.get("LLM_MODEL")
        if not llm_model:
            raise ValueError("Missing required environment variable: LLM_MODEL")
        return cls(
            runtime_secret_id=env.get(AWS_RUNTIME_SECRET_ID_ENV)
            or DEFAULT_AWS_RUNTIME_SECRET_ID,
            llm_model=llm_model,
        )


def build_runtime_environment(
    *,
    bucket_name: str,
    runtime_secret_id: str,
    llm_model: str,
) -> dict[str, str]:
    return {
        "BUCKET_NAME": bucket_name,
        "LLM_MODEL": llm_model,
        "NOOK_RUNTIME_MODE": "aws",
        "NOOK_STORAGE_BACKEND": "s3",
        AWS_RUNTIME_SECRET_ID_ENV: runtime_secret_id,
    }


def requirements_path_for(service_name: str) -> Path:
    try:
        return SERVICE_REQUIREMENTS[service_name]
    except KeyError as error:
        raise ValueError(
            f"Unknown service requirements target: {service_name}"
        ) from error
