"""Settings, read from the environment (prefix `COUNTERSIGN_`) or a `.env` file."""

import math
from datetime import date
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from countersign.llm.client import DEFAULT_RETRIES, worst_case_seconds

ROLES = ("operator", "reviewer")

# Parsing, rendering and writing the result, on top of the model calls of one document.
_LEASE_MARGIN_S = 60


class ApiKey(BaseModel):
    name: str
    role: str
    key: str


def parse_api_keys(value: str) -> list[ApiKey]:
    """Read "name:role:key,..."; any entry that is not exactly that is an error.

    An entry that was silently dropped would leave fewer keys than intended, and with
    none left the API is open. The messages never repeat a key.
    """
    if not value.strip():
        return []
    keys = []
    for position, item in enumerate(value.split(","), start=1):
        parts = [part.strip() for part in item.split(":", 2)]
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"entry {position} is not of the form name:role:key")
        name, role, key = parts
        if role not in ROLES:
            raise ValueError(f"entry {position} ({name}): the role must be one of {ROLES}")
        keys.append(ApiKey(name=name, role=role, key=key))
    return keys


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COUNTERSIGN_",
        env_file=".env",
        extra="ignore",
        # A value that fails validation may be a secret (the API keys).
        hide_input_in_errors=True,
    )

    # Storage
    database_url: str = "sqlite:///var/countersign.db"
    storage_dir: Path = Path("var/documents")
    export_dir: Path = Path("var/export")
    reference_dir: Path = Path("data/reference")

    # Models
    ollama_url: str = "http://127.0.0.1:11434"
    small_model: str = "qwen3.5:4b"
    large_model: str = "qwen3.5:9b"
    model_timeout_s: float = Field(default=240.0, gt=0)
    # Tries after the first one, when the model server answers an error.
    model_retries: int = Field(default=DEFAULT_RETRIES, ge=0)
    # Answer from recorded cassettes instead of a model server. Lets the application run
    # on the sample documents without a GPU; any other document fails as "model
    # unavailable".
    replay_dir: Path | None = None
    # The date the checks take for today. Unset, it is the real date. The recorded
    # samples are dated: replayed a year later they would all be "too old".
    today: date | None = None

    # Queue and workers
    workers: int = Field(default=1, ge=0)
    poll_interval_s: float = Field(default=1.0, gt=0)
    # The least time a claimed job is protected. The lease actually used is never
    # shorter than what one document can take: see `lease_seconds`.
    job_lease_s: int = Field(default=300, ge=1)
    job_max_attempts: int = Field(default=3, ge=1)
    job_backoff_s: float = Field(default=5.0, ge=0)

    # API. Keys are "name:role:key" separated by commas; roles are "operator" and
    # "reviewer". Without any key the API is open, which is only acceptable on localhost:
    # serving on another address then needs `allow_open`.
    api_keys: str = ""
    allow_open: bool = False
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=1)

    # Telemetry. Spans are exported over OTLP/HTTP when an endpoint is set.
    otlp_endpoint: str | None = None
    log_level: str = "INFO"

    @field_validator("api_keys")
    @classmethod
    def _keys_parse_entirely(cls, value: str) -> str:
        parse_api_keys(value)
        return value

    def parsed_api_keys(self) -> list[ApiKey]:
        return parse_api_keys(self.api_keys)

    def lease_seconds(self, tiers: int) -> int:
        """How long a claimed job is protected from other workers.

        Nothing renews a lease, so it must outlast the slowest document: every tier
        called, every try of every call running into the timeout. A shorter lease would
        hand a job that is still being read to a second worker.
        """
        slowest = tiers * worst_case_seconds(self.model_timeout_s, self.model_retries)
        return max(self.job_lease_s, math.ceil(slowest) + _LEASE_MARGIN_S)

    def refusal_to_serve(self, host: str) -> str | None:
        """Why the API must not listen on `host` with these settings, if it must not."""
        if self.parsed_api_keys() or self.allow_open or is_loopback(host):
            return None
        return (
            f"refusing to serve on {host} without API keys: set COUNTERSIGN_API_KEYS, or "
            "COUNTERSIGN_ALLOW_OPEN=true if something else decides who can reach the port"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
