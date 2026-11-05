from __future__ import annotations

import re
from datetime import date

from services.schemas import (
    CandidateFacts,
    EducationLevel,
    HardCheckType,
    HardGateStatus,
    HardRequirement,
    HardRequirementResult,
    MatchItem,
    MatchLevel,
)
from services.text_utils import normalize_for_evidence


DEGREE_RANK = {
    EducationLevel.HIGH_SCHOOL_OR_BELOW: 1,
    EducationLevel.ASSOCIATE: 2,
    EducationLevel.BACHELOR: 3,
    EducationLevel.MASTER: 4,
    EducationLevel.DOCTOR: 5,
}

CERTIFICATE_ALIASES = {
    "PMP": ("pmp",),
    "PMI-ACP": ("pmi-acp", "pmiacp"),
    "CPA": ("cpa", "注册会计师"),
    "CFA": ("cfa", "特许金融分析师"),
    "ACCA": ("acca",),
    "CISSP": ("cissp",),
    "CCIE": ("ccie",),
    "CCNP": ("ccnp",),
    "一级建造师": ("一级建造师",),
    "二级建造师": ("二级建造师",),
    "法律职业资格": ("法律职业资格", "法律职业资格证书"),
}


def evaluate_hard_requirements(
    requirements: list[HardRequirement],
    matches: list[MatchItem],
    facts: CandidateFacts,
    resume_text: str,
) -> list[HardRequirementResult]:
    match_map = {item.requirement_id: item for item in matches}
    results: list[HardRequirementResult] = []
    for requirement in requirements:
        if requirement.check_type == HardCheckType.EDUCATION:
            result = _education_result(requirement, facts)
        elif requirement.check_type == HardCheckType.YEARS:
            result = _years_result(requirement, facts)
        elif requirement.check_type == HardCheckType.CERTIFICATE:
            result = _certificate_result(requirement, facts, resume_text)
        else:
            result = _model_match_result(requirement, match_map.get(requirement.id))
        results.append(result)
    return results


def aggregate_hard_gate(results: list[HardRequirementResult]) -> HardGateStatus:
    if any(item.status == HardGateStatus.FAILED for item in results):
        return HardGateStatus.FAILED
    if any(item.status == HardGateStatus.PENDING for item in results):
        return HardGateStatus.PENDING
    return HardGateStatus.PASSED


def _education_result(
    requirement: HardRequirement,
    facts: CandidateFacts,
) -> HardRequirementResult:
    required = _extract_degree(requirement.desc)
    fact = facts.highest_education
    if required is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence,
            "未能从学历要求中识别明确学历等级，需人工确认。",
        )
    if not fact.reliable or fact.level == EducationLevel.UNKNOWN:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence,
            "最高学历无法从简历原文可靠确认。",
        )

    evidence_normalized = normalize_for_evidence(fact.evidence)
    in_progress = any(
        keyword in evidence_normalized
        for keyword in ("在读", "预计毕业", "应届")
    )
    if in_progress:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence,
            "学历可能尚未完成，需人工确认毕业状态。",
        )
    graduation = facts.graduation_time
    if graduation.reliable and graduation.value:
        if graduation.value > date.today().strftime("%Y-%m"):
            return _result(
                requirement,
                HardGateStatus.PENDING,
                graduation.evidence or fact.evidence,
                "毕业时间晚于当前月份，需确认学历是否已取得。",
            )

    candidate_rank = DEGREE_RANK.get(fact.level)
    required_rank = DEGREE_RANK[required]
    if candidate_rank is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence,
            "最高学历等级无法可靠转换。",
        )
    if candidate_rank >= required_rank:
        return _result(
            requirement,
            HardGateStatus.PASSED,
            fact.evidence,
            f"最高学历为{fact.level.value}，达到{required.value}要求。",
        )
    return _result(
        requirement,
        HardGateStatus.FAILED,
        fact.evidence,
        f"最高学历为{fact.level.value}，低于要求的{required.value}。",
    )


def _years_result(
    requirement: HardRequirement,
    facts: CandidateFacts,
) -> HardRequirementResult:
    required_years = _extract_years(requirement.desc)
    fact = facts.relevant_work_years
    if required_years is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence,
            "未能从年限要求中识别明确年数，需人工确认。",
        )
    if not fact.reliable or fact.value is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence,
            "岗位相关年限无法从简历原文可靠计算。",
        )
    if fact.value >= required_years:
        return _result(
            requirement,
            HardGateStatus.PASSED,
            fact.evidence,
            f"相关经历约 {fact.value:g} 年，达到 {required_years:g} 年要求；{fact.basis}",
        )
    return _result(
        requirement,
        HardGateStatus.FAILED,
        fact.evidence,
        f"相关经历约 {fact.value:g} 年，低于 {required_years:g} 年要求；{fact.basis}",
    )


def _certificate_result(
    requirement: HardRequirement,
    facts: CandidateFacts,
    resume_text: str,
) -> HardRequirementResult:
    required_certificates = _extract_certificates(requirement.desc)
    reliable_certificates = [
        item for item in facts.certificates if item.reliable
    ]
    if not required_certificates:
        evidence = "；".join(item.evidence for item in reliable_certificates)
        return _result(
            requirement,
            HardGateStatus.PENDING,
            evidence,
            "未能从要求中识别明确证书名称，需人工确认。",
        )

    candidate_names = " ".join(
        normalize_for_evidence(item.name) for item in reliable_certificates
    )
    missing = [
        cert
        for cert in required_certificates
        if not _certificate_found(cert, candidate_names)
    ]
    evidence = "；".join(item.evidence for item in reliable_certificates)
    if not missing:
        return _result(
            requirement,
            HardGateStatus.PASSED,
            evidence,
            f"简历已列出所需证书：{'、'.join(required_certificates)}。",
        )

    normalized_resume = normalize_for_evidence(resume_text)
    explicit_absence = any(
        f"无{normalize_for_evidence(cert)}" in normalized_resume
        or f"未取得{normalize_for_evidence(cert)}" in normalized_resume
        for cert in missing
    )
    if explicit_absence:
        return _result(
            requirement,
            HardGateStatus.FAILED,
            evidence,
            f"简历明确表示未取得：{'、'.join(missing)}。",
        )
    return _result(
        requirement,
        HardGateStatus.PENDING,
        evidence,
        f"未能可靠确认以下证书：{'、'.join(missing)}。",
    )


def _model_match_result(
    requirement: HardRequirement,
    match: MatchItem | None,
) -> HardRequirementResult:
    if match is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            "",
            "模型未返回该硬条件结果。",
        )
    if match.match_level == MatchLevel.COMPLETE:
        return _result(
            requirement,
            HardGateStatus.PASSED,
            match.evidence,
            match.reason or "简历有原文证据证明满足该硬条件。",
        )
    if match.match_level == MatchLevel.NOT_MET:
        return _result(
            requirement,
            HardGateStatus.FAILED,
            match.evidence,
            match.reason or "简历明确显示不满足该硬条件。",
        )
    return _result(
        requirement,
        HardGateStatus.PENDING,
        match.evidence,
        match.reason or "该硬条件仅部分体现或未体现，需人工确认。",
    )


def _result(
    requirement: HardRequirement,
    status: HardGateStatus,
    evidence: str,
    reason: str,
) -> HardRequirementResult:
    return HardRequirementResult(
        requirement_id=requirement.id,
        desc=requirement.desc,
        check_type=requirement.check_type,
        status=status,
        evidence=evidence,
        reason=reason,
    )


def _extract_degree(text: str) -> EducationLevel | None:
    checks = {
        EducationLevel.HIGH_SCHOOL_OR_BELOW: ("高中", "中专", "职高", "技校"),
        EducationLevel.ASSOCIATE: ("大专", "专科"),
        EducationLevel.BACHELOR: ("本科", "学士"),
        EducationLevel.MASTER: ("硕士", "研究生"),
        EducationLevel.DOCTOR: ("博士",),
    }
    found = [
        level
        for level, keywords in checks.items()
        if any(keyword in text for keyword in keywords)
    ]
    if not found:
        return None
    # 结构化要求视作“最低学历”；若描述同时提到“本科及以上、硕士优先”，
    # 不能把优先项误当强制项。
    return min(found, key=lambda level: DEGREE_RANK[level])


def _extract_years(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
    if match:
        return float(match.group(1))
    chinese_numbers = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    chinese_match = re.search(r"([一二三四五六七八九十])\s*年", text)
    if chinese_match:
        return float(chinese_numbers[chinese_match.group(1)])
    return None


def _extract_certificates(text: str) -> list[str]:
    normalized = normalize_for_evidence(text)
    found: list[str] = []
    for name, aliases in CERTIFICATE_ALIASES.items():
        if any(normalize_for_evidence(alias) in normalized for alias in aliases):
            found.append(name)
    return found


def _certificate_found(required: str, candidate_names: str) -> bool:
    aliases = CERTIFICATE_ALIASES.get(required, (required,))
    return any(normalize_for_evidence(alias) in candidate_names for alias in aliases)

