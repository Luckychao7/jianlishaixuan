from __future__ import annotations

from services.rules import evaluate_hard_requirements
from services.schemas import (
    CandidateFacts,
    CertificateFact,
    EducationFact,
    EducationLevel,
    GraduationFact,
    HardCheckType,
    HardGateStatus,
    HardRequirement,
    WorkYearsFact,
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
    certificates: list[CertificateFact] | None = None,
) -> CandidateFacts:
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
        relevant_work_years=WorkYearsFact(
            value=years,
            basis="2018-07至2024-06相关岗位经历",
            evidence="2018.07-2024.06 产品经理",
            reliable=years_reliable,
        ),
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

