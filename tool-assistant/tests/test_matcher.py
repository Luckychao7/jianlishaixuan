from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.matcher import sanitize_model_response
from services.schemas import (
    CandidateFacts,
    EducationFact,
    ExperienceFact,
    ExperienceScope,
    MarketingPlatform,
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


def test_wrong_scope_evidence_is_marked_unreliable() -> None:
    response = ResumeModelResponse(
        matches=[],
        candidate_facts=CandidateFacts(
            experience_facts=[
                ExperienceFact(
                    scope=ExperienceScope.AI_SYSTEM_ARCHITECTURE,
                    years=4,
                    basis="普通前端经历",
                    evidence="2020-2024 前端开发工程师",
                    reliable=True,
                )
            ]
        ),
    )
    sanitized = sanitize_model_response(
        response,
        "2020-2024 前端开发工程师，负责页面开发",
    )
    assert sanitized.candidate_facts.experience_facts[0].reliable is False


def test_frontend_only_evidence_cannot_satisfy_full_stack_scope() -> None:
    response = ResumeModelResponse(
        matches=[],
        candidate_facts=CandidateFacts(
            experience_facts=[
                ExperienceFact(
                    scope=ExperienceScope.FULL_STACK_WEB,
                    years=5,
                    basis="前端经历",
                    evidence="2020-2025 React前端开发",
                    reliable=True,
                )
            ]
        ),
    )
    sanitized = sanitize_model_response(
        response,
        "2020-2025 React前端开发",
    )
    assert sanitized.candidate_facts.experience_facts[0].reliable is False


def test_marketing_platforms_must_appear_in_scope_evidence() -> None:
    response = ResumeModelResponse(
        matches=[],
        candidate_facts=CandidateFacts(
            experience_facts=[
                ExperienceFact(
                    scope=ExperienceScope.PERFORMANCE_MARKETING,
                    years=3,
                    basis="抖音投放经历",
                    evidence="2021-2024 抖音千川投放",
                    platforms=[
                        MarketingPlatform.DOUYIN,
                        MarketingPlatform.WECHAT_CHANNELS,
                    ],
                    reliable=True,
                )
            ]
        ),
    )
    sanitized = sanitize_model_response(
        response,
        "2021-2024 抖音千川投放",
    )
    assert sanitized.candidate_facts.experience_facts[0].platforms == [
        MarketingPlatform.DOUYIN
    ]


def test_retail_sales_evidence_cannot_satisfy_tob_scope() -> None:
    response = ResumeModelResponse(
        matches=[],
        candidate_facts=CandidateFacts(
            experience_facts=[
                ExperienceFact(
                    scope=ExperienceScope.TOB_SALES,
                    years=5,
                    basis="汽车零售销售经历",
                    evidence="2020-2025 汽车零售销售顾问",
                    reliable=True,
                )
            ]
        ),
    )
    sanitized = sanitize_model_response(
        response,
        "2020-2025 汽车零售销售顾问，面向个人消费者",
    )
    assert sanitized.candidate_facts.experience_facts[0].reliable is False


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

