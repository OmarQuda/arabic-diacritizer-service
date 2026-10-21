import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Endpoint:
    name: str
    base_url: str
    api_key: str
    model: str
    input_rate: float = 0
    output_rate: float = 0


@dataclass(frozen=True)
class Settings:
    service_key: str
    previous_key: str
    primary: Endpoint
    fallback: Endpoint | None
    fake: bool
    timeout_s: float
    max_retries: int
    max_chars: int
    db_path: Path
    log_text: bool = False


def load_settings() -> Settings:
    # Never search parent directories or load another application's credentials.
    values = {}
    if os.getenv("DIACRITIZER_SKIP_DOTENV") != "1":
        values = dotenv_values(ROOT / ".env", interpolate=False)

    def setting(name: str, default: str = "") -> str:
        return os.getenv(name, values.get(name) or default)

    def secret(name: str) -> str:
        # Credentials must come from this repo's own file, never inherited keys.
        return values.get(name) or ""

    def endpoint(prefix: str, default_name: str) -> Endpoint:
        return Endpoint(
            setting(prefix + "PROVIDER", default_name),
            setting(prefix + "BASE_URL", "https://api.openai.com/v1" if prefix == "LLM_" else ""),
            secret(prefix + "API_KEY"),
            setting(prefix + "MODEL", "your-model" if prefix == "LLM_" else ""),
            float(setting(prefix + "INPUT_COST_PER_MILLION", "0")),
            float(setting(prefix + "OUTPUT_COST_PER_MILLION", "0")),
        )

    fallback = endpoint("FALLBACK_", "secondary")
    settings = Settings(
        secret("SERVICE_KEY"), secret("SERVICE_KEY_PREVIOUS"),
        endpoint("LLM_", "openai-compatible"), fallback if fallback.base_url else None,
        setting("FAKE_PROVIDER", "0") == "1", float(setting("TIMEOUT_S", "20")),
        int(setting("MAX_RETRIES", "1")), int(setting("MAX_CHARS", "5000")),
        ROOT / setting("DB_PATH", "data/corrections.db"), setting("LOG_TEXT", "0") == "1",
    )
    if settings.timeout_s <= 0 or not 0 <= settings.max_retries <= 5 or settings.max_chars < 1:
        raise ValueError("Invalid timeout, retry, or text limit configuration")
    if any(e.input_rate < 0 or e.output_rate < 0 for e in (settings.primary, fallback)):
        raise ValueError("Token prices must be non-negative")
    return settings
