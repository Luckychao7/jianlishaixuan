from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.matcher import sanitize_model_response
from services.schemas import (
    CandidateFacts,
    EducationFact,
    MatchItem,
    MatchLevel,
    ResumeModelResponse,
)


def test_fabricated_match_evidence_is_downgraded() -> None:
    response = ResumeModelResponse(
        matches=[
            MatchItem(
                requirement_id="C1",
                match_level=MatchLevel.COMPLETE,
                evidence="并不存在的项目成果",
                reason="测试",
            )
        ],
        candidate_facts=CandidateFacts(),
    )
    sanitized = sanitize_model_response(response, "负责真实项目需求分析")
    assert sanitized.matches[0].match_level == MatchLevel.NOT_MENTIONED
    assert sanitized.matches[0].evidence == ""


def test_evidence_normalization_accepts_spacing_and_punctuation_differences() -> None:
    response = ResumeModelResponse(
        matches=[
            MatchItem(
                requirement_id="C1",
                match_level=MatchLevel.COMPLETE,
                evidence="SQL 和 Axure",
                reason="测试",
            )
        ],
        candidate_facts=CandidateFacts(),
    )
    sanitized = sanitize_model_response(response, "熟练使用ＳＱＬ，和Axure。")
    assert sanitized.matches[0].match_level == MatchLevel.COMPLETE


def test_untrusted_fact_evidence_marks_fact_unreliable() -> None:
    response = ResumeModelResponse(
        matches=[],
        candidate_facts=CandidateFacts(
            highest_education=EducationFact(
                level="本科",
                evidence="北京大学本科",
                reliable=True,
            )
        ),
    )
    sanitized = sanitize_model_response(response, "某职业技术学院专科")
    assert sanitized.candidate_facts.highest_education.reliable is False


def test_invalid_enum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MatchItem(
            requirement_id="C1",
            match_level="似乎匹配",
            evidence="",
            reason="",
        )


def test_duplicate_requirement_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ResumeModelResponse(
            matches=[
                MatchItem(
                    requirement_id="C1",
                    match_level=MatchLevel.COMPLETE,
                    evidence="a",
                    reason="a",
                ),
                MatchItem(
                    requirement_id="C1",
                    match_level=MatchLevel.PARTIAL,
                    evidence="b",
                    reason="b",
                ),
            ],
            candidate_facts=CandidateFacts(),
        )

