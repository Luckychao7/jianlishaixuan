from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from services.rules import aggregate_hard_gate
from services.schemas import (
    CandidateFacts,
    DimensionScore,
    EvaluationResult,
    Grade,
    HardGateStatus,
    HardRequirementResult,
    MatchLevel,
    MatchResult,
    ParsedResume,
    RequirementCategory,
    StructuredJD,
)


MATCH_COEFFICIENTS = {
    MatchLevel.COMPLETE: 1.0,
    MatchLevel.PARTIAL: 0.6,
    MatchLevel.NOT_MENTIONED: 0.3,
    MatchLevel.NOT_MET: 0.0,
}

GRADE_RECOMMENDATIONS = {
    Grade.A: "强烈推荐",
    Grade.B: "推荐",
    Grade.C: "待定或人工复核",
    Grade.D: "不推荐",
}


def score_resume(
    structured_jd: StructuredJD,
    match_results: list[MatchResult],
    hard_results: list[HardRequirementResult],
    parsed: ParsedResume,
    candidate_facts: CandidateFacts,
) -> EvaluationResult:
    dimension_scores: list[DimensionScore] = []

    if structured_jd.hard_requirements:
        passed = sum(
            item.status == HardGateStatus.PASSED for item in hard_results
        )
        coefficient = passed / len(structured_jd.hard_requirements)
        dimension_scores.append(
            _dimension_score(
                "A",
                "硬性条件",
                20,
                coefficient,
                False,
                f"{passed}/{len(structured_jd.hard_requirements)} 项硬条件满足；"
                "待确认和不满足均按 0 分计。",
            )
        )
    else:
        dimension_scores.append(
            _dimension_score(
                "A", "硬性条件", 20, 0.7, True, "JD 未设置硬性条件，按中性计。"
            )
        )

    categories = [
        ("B", "核心职责与相关经验", 40, RequirementCategory.CORE),
        ("C", "专业技能与工具", 20, RequirementCategory.SKILL),
        ("D", "行业背景与项目成果", 15, RequirementCategory.DOMAIN),
        ("E", "教育、证书及加分项", 5, RequirementCategory.EDUCATION_PLUS),
    ]
    for key, name, weight, category in categories:
        items = [
            item for item in match_results if item.category == category
        ]
        if not items:
            dimension_scores.append(
                _dimension_score(
                    key, name, weight, 0.7, True, "JD 未设置该维度要求，按中性计。"
                )
            )
            continue
        coefficient = sum(
            MATCH_COEFFICIENTS[item.match_level] for item in items
        ) / len(items)
        dimension_scores.append(
            _dimension_score(
                key,
                name,
                weight,
                coefficient,
                False,
                f"{len(items)} 项要求的匹配系数平均值为 {coefficient:.2f}。",
            )
        )

    raw_score = sum(item.score for item in dimension_scores)
    hard_gate = aggregate_hard_gate(hard_results)
    cap_reasons: list[str] = []
    if hard_gate == HardGateStatus.FAILED:
        cap_reasons.append("存在明确不满足的硬性条件，分数上限 54")
    elif hard_gate == HardGateStatus.PENDING:
        cap_reasons.append("存在待确认的硬性条件，分数上限 69")
    if not parsed.coverage_complete:
        cap_reasons.append("评估范围不完整，分数上限 69")

    total_score = raw_score
    if hard_gate == HardGateStatus.FAILED:
        total_score = min(total_score, 54)
    if hard_gate == HardGateStatus.PENDING or not parsed.coverage_complete:
        total_score = min(total_score, 69)

    grade = _grade(total_score)
    recommendation = GRADE_RECOMMENDATIONS[grade]
    manual_review_required = (
        hard_gate == HardGateStatus.PENDING or not parsed.coverage_complete
    )
    risks = _build_risks(
        hard_gate,
        hard_results,
        match_results,
        parsed,
        cap_reasons,
    )
    gaps = [
        f"{item.requirement_id}：{item.desc}"
        for item in match_results
        if item.match_level in {MatchLevel.PARTIAL, MatchLevel.NOT_MET}
    ]
    pending_items = [
        f"{item.requirement_id}：{item.desc}"
        for item in hard_results
        if item.status == HardGateStatus.PENDING
    ]
    pending_items.extend(
        f"{item.requirement_id}：{item.desc}"
        for item in match_results
        if item.match_level == MatchLevel.NOT_MENTIONED
    )
    questions = _build_interview_questions(match_results)
    conclusion = _build_conclusion(
        grade,
        recommendation,
        total_score,
        raw_score,
        hard_gate,
        parsed.coverage_complete,
    )

    return EvaluationResult(
        raw_score=raw_score,
        total_score=total_score,
        grade=grade,
        recommendation=recommendation,
        hard_gate=hard_gate,
        manual_review_required=manual_review_required,
        coverage_complete=parsed.coverage_complete,
        coverage_reasons=parsed.coverage_reasons,
        cap_reasons=cap_reasons,
        conclusion=conclusion,
        hard_results=hard_results,
        match_results=match_results,
        candidate_facts=candidate_facts,
        dimension_scores=dimension_scores,
        risks=risks,
        gaps=gaps,
        pending_items=pending_items,
        interview_questions=questions,
        warnings=parsed.warnings,
        page_coverages=parsed.page_coverages,
    )


def attach_consistency_check(
    result: EvaluationResult,
    repeat_result: EvaluationResult | None,
) -> EvaluationResult:
    if repeat_result is None:
        return result
    difference = abs(result.total_score - repeat_result.total_score)
    if difference > 3:
        note = (
            f"复评分差 {difference} 分，超过 3 分，评分不稳定，建议人工复核。"
        )
        return result.model_copy(
            update={
                "consistency_note": note,
                "manual_review_required": True,
                "risks": result.risks + [note],
            }
        )
    return result.model_copy(
        update={
            "consistency_note": (
                f"复评结果稳定，两次总分相差 {difference} 分。"
            )
        }
    )


def _dimension_score(
    key: str,
    name: str,
    weight: int,
    coefficient: float,
    neutral: bool,
    reason: str,
) -> DimensionScore:
    score = int(
        (Decimal(str(weight)) * Decimal(str(coefficient))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return DimensionScore(
        key=key,
        name=name,
        weight=weight,
        score=score,
        neutral=neutral,
        reason=reason,
    )


def _grade(score: int) -> Grade:
    if score >= 85:
        return Grade.A
    if score >= 70:
        return Grade.B
    if score >= 55:
        return Grade.C
    return Grade.D


def _build_risks(
    hard_gate: HardGateStatus,
    hard_results: list[HardRequirementResult],
    match_results: list[MatchResult],
    parsed: ParsedResume,
    cap_reasons: list[str],
) -> list[str]:
    risks = list(cap_reasons)
    risks.extend(
        f"{item.requirement_id} 待确认：{item.reason}"
        for item in hard_results
        if item.status == HardGateStatus.PENDING
    )
    risks.extend(
        f"{item.requirement_id} 明确不满足：{item.reason}"
        for item in hard_results
        if item.status == HardGateStatus.FAILED
    )
    not_mentioned = [
        item for item in match_results if item.match_level == MatchLevel.NOT_MENTIONED
    ]
    if not_mentioned:
        risks.append(
            f"有 {len(not_mentioned)} 项岗位要求在简历中未体现，不代表候选人一定不具备。"
        )
    risks.extend(parsed.coverage_reasons)
    if hard_gate == HardGateStatus.FAILED:
        risks.append("硬性条件明确不通过，不进入推荐排序。")
    return _deduplicate(risks)


def _build_interview_questions(match_results: list[MatchResult]) -> list[str]:
    questions: list[str] = []
    for item in match_results:
        if item.match_level == MatchLevel.PARTIAL:
            questions.append(
                f"请结合具体项目说明您在“{item.desc}”方面的实际经验、职责和成果。"
            )
        elif item.match_level == MatchLevel.NOT_MENTIONED:
            questions.append(
                f"简历未体现“{item.desc}”，请说明相关经历或可迁移能力。"
            )
        if len(questions) >= 8:
            break
    return questions


def _build_conclusion(
    grade: Grade,
    recommendation: str,
    total_score: int,
    raw_score: int,
    hard_gate: HardGateStatus,
    coverage_complete: bool,
) -> str:
    parts = [
        f"{grade.value} 级（{total_score} 分），建议：{recommendation}",
        f"硬性条件{hard_gate.value}",
    ]
    if not coverage_complete:
        parts.append("评估范围不完整，需人工复核")
    if total_score != raw_score:
        parts.append(f"原始分 {raw_score}，因规则封顶后为 {total_score}")
    return "；".join(parts) + "。"


def _deduplicate(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result

