from __future__ import annotations

from services.llm_client import DeepSeekClient
from services.prompts import JD_SYSTEM_PROMPT, build_jd_user_prompt
from services.schemas import StructuredJD


def parse_jd(
    llm_client: DeepSeekClient,
    jd_text: str,
    preferences: str = "",
) -> StructuredJD:
    if not jd_text.strip():
        raise ValueError("JD 不能为空。")
    return llm_client.request_json(
        system_prompt=JD_SYSTEM_PROMPT,
        user_prompt=build_jd_user_prompt(jd_text, preferences),
        response_model=StructuredJD,
    )

