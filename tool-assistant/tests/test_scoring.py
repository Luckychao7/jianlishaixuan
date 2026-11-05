from __future__ import annotations

from services.schemas import (
    CandidateFacts,
    HardCheckType,
    HardGateStatus,
    HardRequirement,
    HardRequirementResult,
    JobRequirement,
    MatchLevel,
    MatchResult,
    ParsedResume,
    RequirementCategory,
    StructuredJD,
)
from services.scoring import score_resume


def _jd() -> StructuredJD:
    return StructuredJD(
        hard_requirements=[
            HardRequirement(
                id="H1",
                desc="本科及以上",
                check_type=HardCheckType.EDUCATION,
            )
        ],
        core_duties=[JobRequirement(id="C1", desc="负责产品迭代")],
        skills=[JobRequirement(id="S1", desc="熟练使用SQL")],
        domain_project=[JobRequirement(id="D1", desc="有SaaS项目经验")],
        education_cert_plus=[JobRequirement(id="E1", desc="PMP优先")],
    )


def _matches(level: MatchLevel = MatchLevel.COMPLETE) -> list[MatchResult]:
    return [
        MatchResult(
            requirement_id=requirement_id,
            category=category,
            desc=desc,
            match_level=level,
            evidence="原文",
            reason="测试",
        )
        for category, requirement_id, desc in _jd().all_requirements
    ]


def _hard(status: HardGateStatus) -> list[HardRequirementResult]:
    return [
        HardRequirementResult(
            requirement_id="H1",
            desc="本科及以上",
            check_type=HardCheckType.EDUCATION,
            status=status,
            evidence="学历证据",
            reason="测试",
        )
    ]


def test_complete_candidate_scores_100() -> None:
    result = score_resume(
        _jd(),
        _matches(),
        _hard(HardGateStatus.PASSED),
        ParsedResume(text="原文", preview="原文"),
        CandidateFacts(),
    )
    assert result.raw_score == 100
    assert result.total_score == 100
    assert result.grade.value == "A"
    assert result.recommendation == "强烈推荐"


def test_pending_hard_condition_is_zero_and_caps_at_c() -> None:
    result = score_resume(
        _jd(),
        _matches(),
        _hard(HardGateStatus.PENDING),
        ParsedResume(text="原文", preview="原文"),
        CandidateFacts(),
    )
    assert result.raw_score == 80
    assert next(item for item in result.dimension_scores if item.key == "A").score == 0
    assert result.total_score == 69
    assert result.grade.value == "C"
    assert result.manual_review_required


def test_failed_hard_condition_forces_d() -> None:
    result = score_resume(
        _jd(),
        _matches(),
        _hard(HardGateStatus.FAILED),
        ParsedResume(text="原文", preview="原文"),
        CandidateFacts(),
    )
    assert result.total_score == 54
    assert result.grade.value == "D"
    assert result.recommendation == "不推荐"


def test_truncated_resume_caps_at_69() -> None:
    parsed = ParsedResume(
        text="原文",
        preview="原文",
        coverage_complete=False,
        coverage_reasons=["正文已截断"],
    )
    result = score_resume(
        _jd(),
        _matches(),
        _hard(HardGateStatus.PASSED),
        parsed,
        CandidateFacts(),
    )
    assert result.total_score == 69
    assert result.grade.value == "C"
    assert result.manual_review_required


def test_no_hard_requirements_use_neutral_coefficient() -> None:
    jd = _jd().model_copy(update={"hard_requirements": []})
    matches = [item for item in _matches() if item.requirement_id != "H1"]
    result = score_resume(
        jd,
        matches,
        [],
        ParsedResume(text="原文", preview="原文"),
        CandidateFacts(),
    )
    assert next(item for item in result.dimension_scores if item.key == "A").score == 14


def test_ordinary_not_mentioned_still_uses_point_three() -> None:
    result = score_resume(
        _jd(),
        _matches(MatchLevel.NOT_MENTIONED),
        _hard(HardGateStatus.PASSED),
        ParsedResume(text="原文", preview="原文"),
        CandidateFacts(),
    )
    assert result.raw_score == 45

