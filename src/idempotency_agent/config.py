"""
Configuration — load từ .env hoặc environment variables.

Tập trung toàn bộ tunable settings vào một dataclass để dễ inject trong test.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Immutable settings, đọc 1 lần lúc khởi động."""

    # AI analyzer — OpenAI-compatible (OpenRouter, MiniMax, v.v.)
    ai_api_key: str = os.getenv("AI_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "minimax/minimax-m2.5")
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
    concurrent_workers: int = int(os.getenv("CONCURRENT_WORKERS", "5"))
    n_calls: int = int(os.getenv("N_CALLS", "3"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    report_output_dir: str = os.getenv("REPORT_OUTPUT_DIR", "./reports")


settings = Settings()
