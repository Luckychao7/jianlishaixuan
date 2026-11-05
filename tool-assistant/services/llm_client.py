from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError


class LLMServiceError(RuntimeError):
    """模型调用或结构化输出校验失败。"""


ModelT = TypeVar("ModelT", bound=BaseModel)


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int,
    ) -> None:
        if not api_key:
            raise LLMServiceError("未配置 DEEPSEEK_API_KEY")
        self.model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )

    def request_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ModelT],
        validate: Callable[[ModelT], None] | None = None,
    ) -> ModelT:
        last_error = "未知错误"
        for attempt in range(2):
            try:
                completion = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": "disabled"}},
                )
                content = completion.choices[0].message.content
                if not content:
                    raise ValueError("模型返回了空内容")
                payload = json.loads(content)
                parsed = response_model.model_validate(payload)
                if validate is not None:
                    validate(parsed)
                return parsed
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = f"模型返回结构不合法：{exc}"
            except Exception as exc:
                last_error = f"模型调用失败：{exc}"
            if attempt == 0:
                continue
        raise LLMServiceError(last_error)

