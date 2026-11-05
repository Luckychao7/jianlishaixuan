from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    dashscope_api_key: str
    dashscope_base_url: str
    dashscope_ocr_model: str
    enable_ocr: bool
    max_file_mb: int
    max_files: int
    max_ocr_pages: int
    max_resume_chars: int
    llm_timeout: int
    consistency_check: bool
    database_path: Path
    low_text_page_chars: int = 50

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def load_settings() -> Settings:
    data_dir = BASE_DIR / "data"
    return Settings(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip(),
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        dashscope_base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).strip(),
        dashscope_ocr_model=os.getenv(
            "DASHSCOPE_OCR_MODEL", "qwen3.5-ocr"
        ).strip(),
        enable_ocr=_bool_env("ENABLE_OCR", False),
        max_file_mb=_int_env("MAX_FILE_MB", 10),
        max_files=_int_env("MAX_FILES", 20),
        max_ocr_pages=_int_env("MAX_OCR_PAGES", 10),
        max_resume_chars=_int_env("MAX_RESUME_CHARS", 12000, minimum=1000),
        llm_timeout=_int_env("LLM_TIMEOUT", 120),
        consistency_check=_bool_env("CONSISTENCY_CHECK", False),
        database_path=data_dir / "app.db",
    )

