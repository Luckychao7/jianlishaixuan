from __future__ import annotations

from services.rules import evaluate_hard_requirements
from services.schemas import (
    CandidateFacts,
    CertificateFact,
    EducationFact,
    EducationLevel,
    ExperienceFact,
    ExperienceScope,
    GraduationFact,
    HardCheckType,
    HardGateStatus,
    HardRequirementFact,
    HardRequirement,
    MarketingPlatform,
    MatchItem,
    MatchLevel,
    TeamSizeFact,
)


def _education_requirement() -> HardRequirement:
    return HardRequirement(
        id="H1",
        desc="本科及以上学历",
        check_type=HardCheckType.EDUCATION,
    )


def _candidate(
    *,
    level: EducationLevel = EducationLevel.BACHELOR,
    reliable: bool = True,
    years: float | None = 5,
    years_reliable: bool = True,
    experience_years: dict[ExperienceScope, float] | None = None,
    max_team_size: int | None = 18,
    team_reliable: bool = True,
    hard_facts: list[HardRequirementFact] | None = None,
    certificates: list[CertificateFact] | None = None,
) -> CandidateFacts:
    scoped = experience_years
    if scoped is None:
        scoped = (
            {ExperienceScope.OTHER_RELEVANT: years}
            if years is not None
            else {}
        )
    return CandidateFacts(
        highest_education=EducationFact(
            level=level,
            evidence="某大学本科毕业",
            reliable=reliable,
        ),
        graduation_time=GraduationFact(
            value="2020-06",
            evidence="2020年6月毕业",
            reliable=True,
        ),
        experience_facts=[
            ExperienceFact(
                scope=scope,
                years=value,
                basis=f"{scope.value} 独立经历计算",
                evidence=f"2018-2024 {scope.value} 相关经历",
                reliable=years_reliable,
            )
            for scope, value in scoped.items()
        ],
        team_size=TeamSizeFact(
            max_team_size=max_team_size,
            evidence=f"带领{max_team_size}人团队" if max_team_size else "",
            reliable=team_reliable,
        ),
        hard_facts=hard_facts or [],
        certificates=certificates or [],
    )


def test_education_meets_requirement() -> None:
    results = evaluate_hard_requirements(
        [_education_requirement()],
        [],
        _candidate(level=EducationLevel.MASTER),
        "某大学硕士",
    )
    assert results[0].status == HardGateStatus.PASSED


def test_education_explicitly_below_requirement() -> None:
    results = evaluate_hard_requirements(
        [_education_requirement()],
        [],
        _candidate(level=EducationLevel.ASSOCIATE),
        "某学院专科",
    )
    assert results[0].status == HardGateStatus.FAILED


def test_education_requirement_uses_minimum_not_preferred_degree() -> None:
    requirement = HardRequirement(
        id="H1",
        desc="本科及以上学历，硕士优先",
        check_type=HardCheckType.EDUCATION,
    )
    results = evaluate_hard_requirements(
        [requirement],
        [],
        _candidate(level=EducationLevel.BACHELOR),
        "某大学本科",
    )
    assert results[0].status == HardGateStatus.PASSED


def test_unreliable_education_is_pending() -> None:
    results = evaluate_hard_requirements(
        [_education_requirement()],
        [],
        _candidate(level=EducationLevel.UNKNOWN, reliable=False),
        "简历没有学历信息",
    )
    assert results[0].status == HardGateStatus.PENDING


def test_years_pass_fail_and_pending() -> None:
    requirement = HardRequirement(
        id="H2",
        desc="3年以上相关经验",
        check_type=HardCheckType.YEARS,
        fact_scope=ExperienceScope.OTHER_RELEVANT,
    )
    passed = evaluate_hard_requirements(
        [requirement], [], _candidate(years=5), "2018-2024 产品经理"
    )
    failed = evaluate_hard_requirements(
        [requirement], [], _candidate(years=2), "2022-2024 产品经理"
    )
    pending = evaluate_hard_requirements(
        [requirement],
        [],
        _candidate(years=None, years_reliable=False),
        "工作经历未写日期",
    )
    assert passed[0].status == HardGateStatus.PASSED
    assert failed[0].status == HardGateStatus.FAILED
    assert pending[0].status == HardGateStatus.PENDING


def test_years_are_evaluated_per_scope_not_reused() -> None:
    requirements = [
        HardRequirement(
            id="H2",
            desc="3年以上全栈Web开发经验",
            check_type=HardCheckType.YEARS,
            fact_scope=ExperienceScope.FULL_STACK_WEB,
        ),
        HardRequirement(
            id="H3",
            desc="2年以上AI系统架构经验",
            check_type=HardCheckType.YEARS,
            fact_scope=ExperienceScope.AI_SYSTEM_ARCHITECTURE,
        ),
        HardRequirement(
            id="H4",
            desc="2年以上AI开发工具使用经验",
            check_type=HardCheckType.YEARS,
            fact_scope=ExperienceScope.AI_DEVELOPMENT_TOOLS,
        ),
    ]
    results = evaluate_hard_requirements(
        requirements,
        [],
        _candidate(
            experience_years={
                ExperienceScope.FULL_STACK_WEB: 6,
                ExperienceScope.AI_SYSTEM_ARCHITECTURE: 0.5,
                ExperienceScope.AI_DEVELOPMENT_TOOLS: 1,
            }
        ),
        "六年全栈，AI架构半年，AI工具一年",
    )
    assert [item.status for item in results] == [
        HardGateStatus.PASSED,
        HardGateStatus.FAILED,
        HardGateStatus.FAILED,
    ]


def test_year_range_uses_lower_bound() -> None:
    requirement = HardRequirement(
        id="H2",
        desc="3-5年全栈Web开发经验",
        check_type=HardCheckType.YEARS,
        fact_scope=ExperienceScope.FULL_STACK_WEB,
    )
    result = evaluate_hard_requirements(
        [requirement],
        [],
        _candidate(
            experience_years={ExperienceScope.FULL_STACK_WEB: 4.5}
        ),
        "4.5年全栈开发经验",
    )
    assert result[0].status == HardGateStatus.PASSED


def test_team_size_uses_explicit_maximum() -> None:
    requirement = HardRequirement(
        id="H5",
        desc="具备10人以上研发团队管理经验",
        check_type=HardCheckType.TEAM_SIZE,
    )
    passed = evaluate_hard_requirements(
        [requirement], [], _candidate(max_team_size=18), "带领18人团队"
    )
    failed = evaluate_hard_requirements(
        [requirement], [], _candidate(max_team_size=8), "带领8人团队"
    )
    pending = evaluate_hard_requirements(
        [requirement],
        [],
        _candidate(max_team_size=None, team_reliable=False),
        "有团队协作经验",
    )
    assert passed[0].status == HardGateStatus.PASSED
    assert failed[0].status == HardGateStatus.FAILED
    assert pending[0].status == HardGateStatus.PENDING


def test_null_scoped_years_are_pending() -> None:
    requirement = HardRequirement(
        id="H4",
        desc="2年以上AI开发工具使用经验",
        check_type=HardCheckType.YEARS,
        fact_scope=ExperienceScope.AI_DEVELOPMENT_TOOLS,
    )
    candidate = _candidate(
        experience_years={ExperienceScope.AI_DEVELOPMENT_TOOLS: 0}
    )
    candidate = candidate.model_copy(
        update={
            "experience_facts": [
                candidate.experience_facts[0].model_copy(
                    update={"years": None, "reliable": False}
                )
            ]
        }
    )
    result = evaluate_hard_requirements(
        [requirement],
        [],
        candidate,
        "使用过AI工具，但无法确定年限",
    )
    assert result[0].status == HardGateStatus.PENDING


def test_performance_marketing_requires_all_requested_platforms() -> None:
    requirement = HardRequirement(
        id="H1",
        desc="1年以上抖音和视频号双平台投流经验",
        check_type=HardCheckType.YEARS,
        fact_scope=ExperienceScope.PERFORMANCE_MARKETING,
        required_platforms=[
            MarketingPlatform.DOUYIN,
            MarketingPlatform.WECHAT_CHANNELS,
        ],
    )
    base = _candidate(
        experience_years={ExperienceScope.PERFORMANCE_MARKETING: 3}
    )
    douyin_only = base.model_copy(
        update={
            "experience_facts": [
                base.experience_facts[0].model_copy(
                    update={"platforms": [MarketingPlatform.DOUYIN]}
                )
            ]
        }
    )
    dual_platform = base.model_copy(
        update={
            "experience_facts": [
                base.experience_facts[0].model_copy(
                    update={
                        "platforms": [
                            MarketingPlatform.DOUYIN,
                            MarketingPlatform.WECHAT_CHANNELS,
                        ]
                    }
                )
            ]
        }
    )
    failed = evaluate_hard_requirements(
        [requirement], [], douyin_only, "抖音投放三年，没有视频号经验"
    )
    passed = evaluate_hard_requirements(
        [requirement], [], dual_platform, "抖音和视频号投放三年"
    )
    assert failed[0].status == HardGateStatus.FAILED
    assert passed[0].status == HardGateStatus.PASSED


def test_requirement_specific_fact_prevents_total_years_reuse() -> None:
    requirements = [
        HardRequirement(
            id="H1",
            desc="3年以上互联网品牌或电商营销经验",
            check_type=HardCheckType.YEARS,
            fact_scope=ExperienceScope.OTHER_RELEVANT,
        ),
        HardRequirement(
            id="H2",
            desc="3年以上ToB销售经验",
            check_type=HardCheckType.YEARS,
            fact_scope=ExperienceScope.TOB_SALES,
        ),
    ]
    candidate = _candidate(
        experience_years={ExperienceScope.OTHER_RELEVANT: 10},
        hard_facts=[
            HardRequirementFact(
                requirement_id="H1",
                numeric_value=4,
                unit="years",
                evidence="四年电商品牌营销",
                basis="电商品牌营销岗位",
                reliable=True,
            ),
            HardRequirementFact(
                requirement_id="H2",
                numeric_value=0.5,
                unit="years",
                evidence="ToB销售半年",
                basis="ToB销售岗位",
                reliable=True,
            ),
        ],
    )
    results = evaluate_hard_requirements(
        requirements,
        [],
        candidate,
        "四年电商品牌营销；ToB销售半年",
    )
    assert [item.status for item in results] == [
        HardGateStatus.PASSED,
        HardGateStatus.FAILED,
    ]


def test_specific_year_match_requires_semantic_condition_to_pass() -> None:
    requirement = HardRequirement(
        id="H1",
        desc="3年以上互联网品牌或电商营销经验",
        check_type=HardCheckType.YEARS,
        fact_scope=ExperienceScope.OTHER_RELEVANT,
    )
    candidate = _candidate(
        hard_facts=[
            HardRequirementFact(
                requirement_id="H1",
                numeric_value=9,
                unit="years",
                evidence="九年B2B软件市场营销",
                basis="B2B市场岗位",
                reliable=True,
            )
        ]
    )
    results = evaluate_hard_requirements(
        [requirement],
        [
            MatchItem(
                requirement_id="H1",
                match_level=MatchLevel.PARTIAL,
                evidence="九年B2B软件市场营销",
                reason="属于市场营销，但不是互联网品牌或电商营销",
            )
        ],
        candidate,
        "九年B2B软件市场营销",
    )
    assert results[0].status == HardGateStatus.PENDING


def test_unreliable_specific_fact_falls_back_to_verified_scope_fact() -> None:
    requirement = HardRequirement(
        id="H1",
        desc="3年以上互联网品牌或电商营销经验",
        check_type=HardCheckType.YEARS,
        fact_scope=ExperienceScope.OTHER_RELEVANT,
    )
    candidate = _candidate(
        experience_years={ExperienceScope.OTHER_RELEVANT: 6},
        hard_facts=[
            HardRequirementFact(
                requirement_id="H1",
                numeric_value=None,
                unit="years",
                evidence="",
                basis="",
                reliable=False,
            )
        ],
    )
    results = evaluate_hard_requirements(
        [requirement],
        [
            MatchItem(
                requirement_id="H1",
                match_level=MatchLevel.COMPLETE,
                evidence="六年电商品牌营销",
                reason="直接匹配",
            )
        ],
        candidate,
        "六年电商品牌营销",
    )
    assert results[0].status == HardGateStatus.PASSED


def test_certificate_pass_pending_and_explicit_failure() -> None:
    requirement = HardRequirement(
        id="H3",
        desc="必须持有PMP证书",
        check_type=HardCheckType.CERTIFICATE,
    )
    passed = evaluate_hard_requirements(
        [requirement],
        [],
        _candidate(
            certificates=[
                CertificateFact(
                    name="PMP",
                    evidence="PMP项目管理证书",
                    reliable=True,
                )
            ]
        ),
        "PMP项目管理证书",
    )
    pending = evaluate_hard_requirements(
        [requirement], [], _candidate(), "未提及证书"
    )
    failed = evaluate_hard_requirements(
        [requirement], [], _candidate(), "本人未取得PMP证书"
    )
    assert passed[0].status == HardGateStatus.PASSED
    assert pending[0].status == HardGateStatus.PENDING
    assert failed[0].status == HardGateStatus.FAILED

