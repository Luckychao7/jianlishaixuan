from __future__ import annotations

from services.llm_client import DeepSeekClient
from services.prompts import RESUME_SYSTEM_PROMPT, build_resume_user_prompt
from services.schemas import (
    CandidateFacts,
    CertificateFact,
    EducationFact,
    ExperienceFact,
    ExperienceScope,
    GraduationFact,
    HardRequirementFact,
    MarketingPlatform,
    MatchItem,
    MatchLevel,
    ResumeModelResponse,
    StructuredJD,
    TeamSizeFact,
    WorkYearsFact,
)
from services.text_utils import evidence_in_text, normalize_for_evidence


SCOPE_EVIDENCE_KEYWORDS = {
    ExperienceScope.PERFORMANCE_MARKETING: (
        "投流",
        "投放",
        "信息流",
        "广告",
        "千川",
        "roi",
        "获客",
        "消耗",
    ),
    ExperienceScope.TOB_SALES: (
        "tob",
        "b2b",
        "企业客户",
        "企业销售",
        "企业服务",
        "saas",
    ),
    ExperienceScope.FULL_STACK_WEB: (
        "全栈",
        "前端",
        "后端",
        "web",
        "react",
        "vue",
        "django",
        "flask",
        "fastapi",
        "spring",
    ),
    ExperienceScope.AI_SYSTEM_ARCHITECTURE: (
        "ai",
        "人工智能",
        "大模型",
        "智能体",
        "agent",
        "架构",
        "mlops",
        "模型",
    ),
    ExperienceScope.AI_DEVELOPMENT_TOOLS: (
        "codex",
        "claude",
        "gemini",
        "deepseek",
        "ai工具",
        "ai开发工具",
        "ai 工具",
    ),
    ExperienceScope.TEAM_MANAGEMENT: (
        "团队",
        "带领",
        "管理",
        "负责人",
        "leader",
        "lead",
    ),
    ExperienceScope.BACKEND_DEVELOPMENT: (
        "后端",
        "服务端",
        "java",
        "python",
        "django",
        "flask",
        "fastapi",
        "spring",
    ),
    ExperienceScope.FRONTEND_DEVELOPMENT: (
        "前端",
        "react",
        "vue",
        "html",
        "css",
    ),
    ExperienceScope.DATA_ENGINEERING: (
        "大数据",
        "数据工程",
        "流式计算",
        "kafka",
        "flink",
        "spark",
    ),
    ExperienceScope.OTHER_RELEVANT: (),
}

PLATFORM_EVIDENCE_KEYWORDS = {
    MarketingPlatform.DOUYIN: ("抖音", "巨量引擎", "千川"),
    MarketingPlatform.WECHAT_CHANNELS: ("视频号", "微信广告", "微信朋友圈"),
}


def match_resume(
    llm_client: DeepSeekClient,
    structured_jd: StructuredJD,
    resume_text: str,
) -> ResumeModelResponse:
    expected_ids = {item[1] for item in structured_jd.all_requirements}

    def validate_ids(response: ResumeModelResponse) -> None:
        actual_ids = {item.requirement_id for item in response.matches}
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        if missing or extra:
            raise ValueError(
                f"需求编号不完整；缺少={sorted(missing)}，多出={sorted(extra)}"
            )

    response = llm_client.request_json(
        system_prompt=RESUME_SYSTEM_PROMPT,
        user_prompt=build_resume_user_prompt(structured_jd, resume_text),
        response_model=ResumeModelResponse,
        validate=validate_ids,
    )
    return sanitize_model_response(response, resume_text)


def sanitize_model_response(
    response: ResumeModelResponse,
    resume_text: str,
) -> ResumeModelResponse:
    matches: list[MatchItem] = []
    for item in response.matches:
        if item.match_level == MatchLevel.NOT_MENTIONED:
            matches.append(item.model_copy(update={"evidence": ""}))
            continue
        if not item.evidence or not evidence_in_text(item.evidence, resume_text):
            matches.append(
                item.model_copy(
                    update={
                        "match_level": MatchLevel.NOT_MENTIONED,
                        "evidence": "",
                        "reason": "模型证据无法在简历原文中定位，按未体现处理。",
                    }
                )
            )
            continue
        matches.append(item)

    facts = response.candidate_facts
    education_fact = facts.highest_education
    education = EducationFact(
        level=education_fact.level,
        evidence=education_fact.evidence,
        reliable=(
            education_fact.reliable
            and bool(education_fact.evidence)
            and evidence_in_text(education_fact.evidence, resume_text)
        ),
    )

    graduation_fact = facts.graduation_time
    graduation = GraduationFact(
        value=graduation_fact.value,
        evidence=graduation_fact.evidence,
        reliable=(
            graduation_fact.reliable
            and bool(graduation_fact.evidence)
            and evidence_in_text(graduation_fact.evidence, resume_text)
        ),
    )

    years_fact = facts.relevant_work_years
    years = WorkYearsFact(
        value=years_fact.value,
        basis=years_fact.basis,
        evidence=years_fact.evidence,
        reliable=(
            years_fact.reliable
            and years_fact.value is not None
            and bool(years_fact.basis)
            and bool(years_fact.evidence)
            and evidence_in_text(years_fact.evidence, resume_text)
        ),
    )

    experience_facts = []
    for fact in facts.experience_facts:
        evidence_valid = bool(fact.evidence) and evidence_in_text(
            fact.evidence, resume_text
        )
        scope_valid = _scope_evidence_matches(fact.scope, fact.evidence)
        experience_facts.append(
            ExperienceFact(
                scope=fact.scope,
                years=fact.years,
                basis=fact.basis,
                evidence=fact.evidence,
                platforms=(
                    _detect_marketing_platforms(resume_text)
                    if fact.scope == ExperienceScope.PERFORMANCE_MARKETING
                    else []
                ),
                reliable=(
                    fact.reliable
                    and fact.years is not None
                    and evidence_valid
                    and scope_valid
                    and bool(fact.basis)
                ),
            )
        )

    team_fact = facts.team_size
    team_size = TeamSizeFact(
        max_team_size=team_fact.max_team_size,
        evidence=team_fact.evidence,
        reliable=(
            team_fact.reliable
            and team_fact.max_team_size is not None
            and bool(team_fact.evidence)
            and evidence_in_text(team_fact.evidence, resume_text)
            and any(
                keyword in team_fact.evidence.casefold()
                for keyword in ("团队", "带领", "管理", "team")
            )
        ),
    )

    certificates = [
        CertificateFact(
            name=item.name,
            evidence=item.evidence,
            reliable=(
                item.reliable
                and bool(item.evidence)
                and evidence_in_text(item.evidence, resume_text)
            ),
        )
        for item in facts.certificates
    ]
    hard_facts = [
        HardRequirementFact(
            requirement_id=item.requirement_id,
            numeric_value=item.numeric_value,
            text_value=item.text_value,
            unit=item.unit,
            evidence=item.evidence,
            basis=item.basis,
            reliable=(
                item.reliable
                and bool(item.evidence)
                and evidence_in_text(item.evidence, resume_text)
            ),
        )
        for item in facts.hard_facts
    ]
    sanitized_facts = CandidateFacts(
        highest_education=education,
        graduation_time=graduation,
        experience_facts=experience_facts,
        team_size=team_size,
        hard_facts=hard_facts,
        relevant_work_years=years,
        certificates=certificates,
    )
    return ResumeModelResponse(matches=matches, candidate_facts=sanitized_facts)


def _scope_evidence_matches(scope: ExperienceScope, evidence: str) -> bool:
    normalized = normalize_for_evidence(evidence)
    if not normalized:
        return False
    if scope == ExperienceScope.FULL_STACK_WEB:
        frontend = any(
            word in normalized
            for word in ("前端", "react", "vue", "html", "css")
        )
        backend = any(
            word in normalized
            for word in (
                "后端",
                "服务端",
                "java",
                "python",
                "django",
                "flask",
                "fastapi",
                "spring",
            )
        )
        return "全栈" in normalized or (frontend and backend)
    if scope == ExperienceScope.AI_SYSTEM_ARCHITECTURE:
        ai_related = any(
            word in normalized
            for word in (
                "ai",
                "人工智能",
                "大模型",
                "智能体",
                "agent",
                "mlops",
                "机器学习",
                "深度学习",
            )
        )
        architecture_related = any(
            word in normalized for word in ("架构", "模型", "推理", "平台")
        )
        return ai_related and architecture_related
    if scope == ExperienceScope.TOB_SALES:
        return any(
            word in normalized
            for word in (
                "tob",
                "b2b",
                "企业客户",
                "企业销售",
                "企业服务",
                "saas",
                "制造业客户软件项目",
            )
        )
    if scope == ExperienceScope.AI_DEVELOPMENT_TOOLS:
        return any(
            word in normalized
            for word in ("codex", "claude", "gemini", "deepseek", "ai开发工具", "ai工具")
        )
    keywords = SCOPE_EVIDENCE_KEYWORDS[scope]
    if not keywords:
        return True
    return any(normalize_for_evidence(keyword) in normalized for keyword in keywords)


def _detect_marketing_platforms(resume_text: str) -> list[MarketingPlatform]:
    ad_keywords = (
        "投流",
        "投放",
        "信息流",
        "千川",
        "广告账户",
        "广告后台",
        "预算",
        "出价",
        "计划创建",
        "素材测试",
    )
    negative_keywords = (
        "没有",
        "未有",
        "未负责",
        "不负责",
        "不是",
        "未涉及",
        "无",
        "不具备",
        "缺乏",
    )
    detected: list[MarketingPlatform] = []
    normalized_text = normalize_for_evidence(resume_text)
    for platform, keywords in PLATFORM_EVIDENCE_KEYWORDS.items():
        for keyword in keywords:
            normalized_keyword = normalize_for_evidence(keyword)
            start = 0
            while True:
                index = normalized_text.find(normalized_keyword, start)
                if index < 0:
                    break
                window = normalized_text[max(0, index - 20) : index + 60]
                positive = any(
                    normalize_for_evidence(word) in window for word in ad_keywords
                )
                negative = any(
                    normalize_for_evidence(word) in window
                    for word in negative_keywords
                )
                if positive and not negative:
                    detected.append(platform)
                    break
                start = index + len(normalized_keyword)
            if platform in detected:
                break
    return detected

