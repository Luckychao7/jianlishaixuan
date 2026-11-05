from __future__ import annotations

from services.jd_parser import normalize_hard_requirements
from services.schemas import (
    HardCheckType,
    HardRequirement,
    JobRequirement,
    StructuredJD,
)


def test_subjective_hard_requirement_is_retained_as_skill() -> None:
    jd = StructuredJD(
        hard_requirements=[
            HardRequirement(
                id="H1",
                desc="本科及以上学历",
                check_type=HardCheckType.EDUCATION,
            ),
            HardRequirement(
                id="H2",
                desc="对ROI和毛利有执念，抗压能力强",
                check_type=HardCheckType.OTHER,
            ),
        ],
        skills=[JobRequirement(id="S1", desc="品牌内容策划")],
    )
    normalized = normalize_hard_requirements(jd)
    assert [item.desc for item in normalized.hard_requirements] == [
        "本科及以上学历"
    ]
    assert [item.desc for item in normalized.skills] == [
        "品牌内容策划",
        "对ROI和毛利有执念，抗压能力强",
    ]
    assert [item.id for item in normalized.skills] == ["S1", "S2"]


def test_objective_hard_requirement_is_not_demoted() -> None:
    jd = StructuredJD(
        hard_requirements=[
            HardRequirement(
                id="H1",
                desc="3年以上电商营销经验",
                check_type=HardCheckType.YEARS,
                fact_scope="other_relevant",
            )
        ]
    )
    normalized = normalize_hard_requirements(jd)
    assert normalized.hard_requirements[0].desc == "3年以上电商营销经验"
    assert normalized.hard_requirements[0].id == "H1"

