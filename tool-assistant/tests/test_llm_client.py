from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.llm_client import DeepSeekClient, LLMServiceError
from services.schemas import StructuredJD


class FakeCompletions:
    def __init__(self, contents: list[str | Exception]) -> None:
        self.contents = contents
        self.calls = 0

    def create(self, **kwargs):
        value = self.contents[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=value))
            ]
        )


def _client(contents: list[str | Exception]) -> tuple[DeepSeekClient, FakeCompletions]:
    completions = FakeCompletions(contents)
    client = DeepSeekClient.__new__(DeepSeekClient)
    client.model = "deepseek-flash"
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return client, completions


VALID_JSON = """{
  "hard_requirements": [],
  "core_duties": [{"id": "C1", "desc": "负责产品迭代"}],
  "skills": [],
  "domain_project": [],
  "education_cert_plus": [],
  "notes": ""
}"""


def test_invalid_json_is_retried_once() -> None:
    client, completions = _client(["not-json", VALID_JSON])
    result = client.request_json(
        system_prompt="json",
        user_prompt="test",
        response_model=StructuredJD,
    )
    assert result.core_duties[0].id == "C1"
    assert completions.calls == 2


def test_two_invalid_outputs_fail() -> None:
    client, completions = _client(["not-json", "{}"])
    with pytest.raises(LLMServiceError):
        client.request_json(
            system_prompt="json",
            user_prompt="test",
            response_model=StructuredJD,
        )
    assert completions.calls == 2

