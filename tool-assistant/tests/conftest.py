from __future__ import annotations

from pathlib import Path

import pytest

from config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        deepseek_api_key="test-deepseek",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-flash",
        dashscope_api_key="",
        dashscope_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_ocr_model="qwen3.5-ocr",
        enable_ocr=False,
        max_file_mb=10,
        max_files=20,
        max_ocr_pages=10,
        max_resume_chars=12000,
        llm_timeout=30,
        consistency_check=False,
        database_path=tmp_path / "app.db",
        low_text_page_chars=50,
    )

