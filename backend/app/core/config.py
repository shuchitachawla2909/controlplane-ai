"""Runtime configuration.

Every setting has a safe default. The core prototype and the full demo run
with no `.env` file and no paid API keys (`LLM_PROVIDER=mock`).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_DIR = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_DIR / ".env", _BACKEND_DIR / ".env"),
        env_prefix="",
        extra="ignore",
    )

    # --- LLM-as-judge (OPTIONAL, never required) ---------------------------
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_judge_model: str = Field(default="gpt-4o-mini", alias="OPENAI_JUDGE_MODEL")

    # --- App ------------------------------------------------------------
    demo_mode: bool = Field(default=True, alias="DEMO_MODE")
    db_url: str = Field(default=f"sqlite:///{_BACKEND_DIR / 'controlplane.db'}", alias="CONTROLPLANE_DB_URL")
    host: str = Field(default="0.0.0.0", alias="CONTROLPLANE_HOST")
    port: int = Field(default=8000, alias="CONTROLPLANE_PORT")
    seed: int = Field(default=1729, alias="CONTROLPLANE_SEED")
    seed_on_boot: bool = Field(default=False, alias="CONTROLPLANE_SEED_ON_BOOT")
    # Privacy: when False (default), persisted trace/decision records store
    # REDACTED request/response text. Detection evidence (entity types, counts,
    # offsets) is always retained. Live API responses to the immediate caller
    # are unaffected. Set True only for a deployment with its own retention
    # controls.
    store_raw: bool = Field(default=False, alias="CONTROLPLANE_STORE_RAW")
    config_dir: str = Field(default=str(_REPO_DIR / "config"), alias="CONTROLPLANE_CONFIG_DIR")

    @property
    def config_path(self) -> Path:
        p = Path(self.config_dir)
        if not p.is_absolute():
            p = (_BACKEND_DIR / p).resolve()
        return p

    @property
    def policies_dir(self) -> Path:
        return self.config_path / "policies"

    @property
    def workflows_dir(self) -> Path:
        return self.config_path / "workflows"

    @property
    def repo_dir(self) -> Path:
        return _REPO_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()
