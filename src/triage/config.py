"""Environment-driven settings. No credentials or endpoints are hard-coded (D4)."""
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    db_path: str = "./data/triage.sqlite3"
    chroma_host: str = ""
    chroma_port: int = 8000
    chroma_collection: str = "regulations"
    corpus_dir: str = "./corpus"
    verified_passages_file: str = "./corpus/verified_passages.json"
    placeholder_delay_seconds: float = 2.0
    embed_model: str = ""
    hf_home: str = ""
    queue_name: str = "petitions"

    # --- Phase 3: agents (all injected at runtime; nothing here is a credential) ---
    agent_mode: str = "agents"            # "agents" | "placeholder" (explicit opt-in, used by Phase 1 tests)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
    prompts_dir: str = "./prompts"
    triage_prompt_version: str = "v1"
    research_prompt_version: str = "v1"
    verifier_prompt_version: str = "v1"
    max_research_steps: int = 8
    max_tool_calls: int = 10
    max_run_seconds: float = 120.0
    tool_timeout_seconds: float = 15.0
    max_verify_retries: int = 2
    search_top_k: int = 5
    triage_min_confidence: float = 0.5   # below this the petition is treated as ambiguous and escalated for clarification

    # --- Phase 4: reliability (no credentials; the fallback provider is optional) ---
    llm_name: str = "primary"
    fallback_llm_base_url: str = ""
    fallback_llm_api_key: str = ""
    fallback_llm_model: str = ""
    llm_max_attempts: int = 3             # total tries per provider for retryable errors
    llm_rate_limit_max_attempts: int = 8  # 429s are usually transient (e.g. tokens-per-minute); wait more, within the run budget
    llm_backoff_base_seconds: float = 0.5
    llm_backoff_cap_seconds: float = 8.0
    breaker_failure_threshold: int = 5
    breaker_cooldown_seconds: float = 30.0
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 30         # per client per window, POST /v1/petitions
    rate_limit_window_seconds: int = 60
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600

    # --- Auth & Security ---
    auth_token_expire_seconds: int = 7200
    auth_rate_limit_requests: int = 15
    auth_rate_limit_window_seconds: int = 60
    demo_accounts_enabled: bool = True
    auth_enforce_strict: bool = False

    # --- Phase 5 ---
    guardrails_enabled: bool = True
    price_prompt_per_1k: Optional[float] = None       # USD per 1000 prompt tokens; None = pricing unknown
    price_completion_per_1k: Optional[float] = None
    eval_results_dir: str = "./eval/results"
    auto_eval_sample_rate: float = 0.0                # fraction of finished runs scored by the LLM judge (0 = off)

    @field_validator("price_prompt_per_1k", "price_completion_per_1k", mode="before")
    @classmethod
    def _blank_price_is_unknown(cls, v):
        """docker compose passes unset optional variables as ''. Blank = pricing unknown, not a parse error."""
        return None if isinstance(v, str) and not v.strip() else v


def get_settings() -> Settings:
    """Read the environment on every call so tests can override it."""
    return Settings()
