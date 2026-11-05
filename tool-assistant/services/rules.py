from __future__ import annotations

import re
from datetime import date

from services.schemas import (
    CandidateFacts,
    EducationLevel,
    ExperienceScope,
    HardCheckType,
    HardGateStatus,
    HardRequirement,
    HardRequirementResult,
    MarketingPlatform,
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
            result = _years_result(
                requirement,
                facts,
                match_map.get(requirement.id),
            )
        elif requirement.check_type == HardCheckType.CERTIFICATE:
            result = _certificate_result(requirement, facts, resume_text)
        elif requirement.check_type == HardCheckType.TEAM_SIZE:
            result = _team_size_result(
                requirement,
                facts,
                match_map.get(requirement.id),
            )
        elif (
            requirement.check_type == HardCheckType.OTHER
            and "团队" in requirement.desc
            and _extract_team_size(requirement.desc) is not None
        ):
            result = _team_size_result(requirement, facts)
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
    match: MatchItem | None,
) -> HardRequirementResult:
    required_years = _extract_years(requirement.desc)
    scope = requirement.fact_scope or _infer_experience_scope(requirement.desc)
    facts_by_scope = {item.scope: item for item in facts.experience_facts}
    fact = facts_by_scope.get(scope) if scope else None
    hard_facts = {item.requirement_id: item for item in facts.hard_facts}
    hard_fact = hard_facts.get(requirement.id)
    hard_specific_years = (
        hard_fact.numeric_value
        if (
            hard_fact is not None
            and hard_fact.reliable
            and hard_fact.numeric_value is not None
            and hard_fact.unit.casefold() in {"year", "years", "年"}
        )
        else None
    )
    scoped_years = (
        fact.years
        if fact is not None and fact.reliable and fact.years is not None
        else None
    )
    if hard_specific_years is not None:
        usable_years = hard_specific_years
        evidence = hard_fact.evidence
        basis = hard_fact.basis
        source_label = "该硬条件专项事实"
    else:
        usable_years = scoped_years
        evidence = fact.evidence if fact else ""
        basis = fact.basis if fact else ""
        source_label = _scope_label(scope) if scope else "相关经历"
    if required_years is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            fact.evidence if fact else "",
            "未能从年限要求中识别明确年数，需人工确认。",
        )
    if scope is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            "",
            "未能识别该年限要求对应的能力范围，需人工确认。",
        )
    if requirement.required_platforms:
        if fact is None or not fact.reliable:
            if match is not None and match.match_level == MatchLevel.NOT_MET:
                return _result(
                    requirement,
                    HardGateStatus.FAILED,
                    match.evidence,
                    match.reason or "简历明确显示缺少指定平台投流经验。",
                )
            return _result(
                requirement,
                HardGateStatus.PENDING,
                fact.evidence if fact else "",
                "简历未可靠提供指定平台的独立投放经验。",
            )
        missing_platforms = [
            platform
            for platform in requirement.required_platforms
            if platform not in fact.platforms
        ]
        if missing_platforms:
            missing_labels = "、".join(
                _platform_label(platform) for platform in missing_platforms
            )
            return _result(
                requirement,
                HardGateStatus.FAILED,
                fact.evidence,
                f"简历未体现以下平台的投放经验：{missing_labels}。",
            )
    if usable_years is None:
        if match is not None and match.match_level == MatchLevel.NOT_MET:
            return _result(
                requirement,
                HardGateStatus.FAILED,
                match.evidence,
                match.reason or "简历明确显示不满足该年限要求。",
            )
        return _result(
            requirement,
            HardGateStatus.PENDING,
            evidence,
            f"简历未可靠提供{source_label}达到 {required_years:g} 年的依据。",
        )
    if usable_years < required_years:
        return _result(
            requirement,
            HardGateStatus.FAILED,
            evidence,
            f"{source_label}约 {usable_years:g} 年，低于 {required_years:g} 年要求；{basis}",
        )
    if match is not None and match.match_level == MatchLevel.NOT_MET:
        return _result(
            requirement,
            HardGateStatus.FAILED,
            match.evidence,
            match.reason or "简历年限事实不能覆盖该硬条件的其他明确要求。",
        )
    if match is not None and match.match_level in {
        MatchLevel.PARTIAL,
        MatchLevel.NOT_MENTIONED,
    }:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            evidence,
            f"年限达到要求，但该硬条件仍有组成部分未确认：{match.reason}",
        )
    if usable_years >= required_years:
        return _result(
            requirement,
            HardGateStatus.PASSED,
            evidence,
            f"{source_label}约 {usable_years:g} 年，达到 {required_years:g} 年要求；{basis}",
        )
    raise AssertionError("unreachable")


def _team_size_result(
    requirement: HardRequirement,
    facts: CandidateFacts,
    match: MatchItem | None,
) -> HardRequirementResult:
    required_size = _extract_team_size(requirement.desc)
    hard_facts = {item.requirement_id: item for item in facts.hard_facts}
    hard_fact = hard_facts.get(requirement.id)
    hard_specific_size = (
        int(hard_fact.numeric_value)
        if (
            hard_fact is not None
            and hard_fact.reliable
            and hard_fact.numeric_value is not None
            and hard_fact.unit.casefold() in {"person", "people", "人"}
        )
        else None
    )
    scoped_size = (
        facts.team_size.max_team_size if facts.team_size.reliable else None
    )
    if hard_specific_size is not None:
        team_size = hard_specific_size
        evidence = hard_fact.evidence
    else:
        team_size = scoped_size
        evidence = facts.team_size.evidence
    if required_size is None:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            evidence,
            "未能从团队要求中识别明确人数，需人工确认。",
        )
    if team_size is None:
        if match is not None and match.match_level == MatchLevel.NOT_MET:
            return _result(
                requirement,
                HardGateStatus.FAILED,
                match.evidence,
                match.reason or "简历明确显示不满足团队规模要求。",
            )
        return _result(
            requirement,
            HardGateStatus.PENDING,
            evidence,
            "简历未可靠提供最大团队管理人数。",
        )
    if team_size < required_size:
        return _result(
            requirement,
            HardGateStatus.FAILED,
            evidence,
            f"最大团队规模为 {team_size} 人，低于 {required_size} 人要求。",
        )
    if match is not None and match.match_level == MatchLevel.NOT_MET:
        return _result(
            requirement,
            HardGateStatus.FAILED,
            match.evidence,
            match.reason or "团队人数达到门槛，但不满足该硬条件的其他要求。",
        )
    if match is not None and match.match_level in {
        MatchLevel.PARTIAL,
        MatchLevel.NOT_MENTIONED,
    }:
        return _result(
            requirement,
            HardGateStatus.PENDING,
            evidence,
            f"团队人数达到门槛，但该硬条件仍有组成部分未确认：{match.reason}",
        )
    if team_size >= required_size:
        return _result(
            requirement,
            HardGateStatus.PASSED,
            evidence,
            f"最大团队规模为 {team_size} 人，达到 {required_size} 人要求。",
        )
    raise AssertionError("unreachable")


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
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*[-~—至到]\s*\d+(?:\.\d+)?\s*年",
        text,
    )
    if range_match:
        # 招聘中的“3-5年”作为最低经验门槛，区间下限是 3 年。
        return float(range_match.group(1))
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


def _extract_team_size(text: str) -> int | None:
    match = re.search(r"(\d+)\s*人(?:以上|及以上|\+)", text)
    if match:
        return int(match.group(1))
    return None


def _infer_experience_scope(desc: str) -> ExperienceScope | None:
    normalized = normalize_for_evidence(desc)
    checks = [
        (
            ExperienceScope.TOB_SALES,
            ("tob销售", "企业销售", "企业客户销售", "b2b销售", "saas销售"),
        ),
        (
            ExperienceScope.PERFORMANCE_MARKETING,
            (
                "投流",
                "投放",
                "信息流广告",
                "直播投放",
                "douyin",
                "抖音",
                "视频号",
                "roi",
            ),
        ),
        (
            ExperienceScope.AI_DEVELOPMENT_TOOLS,
            ("ai开发工具", "ai工具", "codex", "claude", "gemini", "deepseek"),
        ),
        (
            ExperienceScope.AI_SYSTEM_ARCHITECTURE,
            ("ai系统架构", "ai架构", "大模型架构", "智能体架构", "mlops"),
        ),
        (
            ExperienceScope.TEAM_MANAGEMENT,
            ("团队管理", "带领团队", "研发团队负责人"),
        ),
        (ExperienceScope.FULL_STACK_WEB, ("全栈", "web开发")),
        (ExperienceScope.FRONTEND_DEVELOPMENT, ("前端", "react", "vue")),
        (
            ExperienceScope.BACKEND_DEVELOPMENT,
            ("后端", "java", "python", "django", "flask", "fastapi", "spring"),
        ),
        (
            ExperienceScope.DATA_ENGINEERING,
            ("大数据", "流式计算", "数据工程"),
        ),
        (ExperienceScope.OTHER_RELEVANT, ("相关经验", "工作年限")),
    ]
    for scope, keywords in checks:
        if any(normalize_for_evidence(keyword) in normalized for keyword in keywords):
            return scope
    return None


def _scope_label(scope: ExperienceScope) -> str:
    return {
        ExperienceScope.PERFORMANCE_MARKETING: "效果营销投放",
        ExperienceScope.TOB_SALES: "ToB销售",
        ExperienceScope.FULL_STACK_WEB: "全栈Web开发",
        ExperienceScope.AI_SYSTEM_ARCHITECTURE: "AI系统架构",
        ExperienceScope.AI_DEVELOPMENT_TOOLS: "AI开发工具",
        ExperienceScope.TEAM_MANAGEMENT: "团队管理",
        ExperienceScope.BACKEND_DEVELOPMENT: "后端开发",
        ExperienceScope.FRONTEND_DEVELOPMENT: "前端开发",
        ExperienceScope.DATA_ENGINEERING: "数据工程",
        ExperienceScope.OTHER_RELEVANT: "其他相关",
    }[scope]


def _platform_label(platform: MarketingPlatform) -> str:
    return {
        MarketingPlatform.DOUYIN: "抖音",
        MarketingPlatform.WECHAT_CHANNELS: "视频号",
    }[platform]


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

