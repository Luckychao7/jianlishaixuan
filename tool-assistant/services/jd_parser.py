from __future__ import annotations

from services.llm_client import DeepSeekClient
from services.prompts import JD_SYSTEM_PROMPT, build_jd_user_prompt
from services.schemas import (
    HardCheckType,
    JobRequirement,
    StructuredJD,
)

JD_PARSER_VERSION = "2026-11-05.2"


OBJECTIVE_HARD_TYPES = {
    HardCheckType.EDUCATION,
    HardCheckType.YEARS,
    HardCheckType.CERTIFICATE,
    HardCheckType.TEAM_SIZE,
}

SUBJECTIVE_TERMS = (
    "执念",
    "抗压",
    "目标感",
    "热情",
    "强烈兴趣",
    "学习能力",
    "学习意愿",
    "沟通能力",
    "团队协作",
    "主人翁",
    "结果导向",
    "责任心",
    "主动性",
)


def parse_jd(
    llm_client: DeepSeekClient,
    jd_text: str,
    preferences: str = "",
) -> StructuredJD:
    if not jd_text.strip():
        raise ValueError("JD 不能为空。")
    structured = llm_client.request_json(
        system_prompt=JD_SYSTEM_PROMPT,
        user_prompt=build_jd_user_prompt(jd_text, preferences),
        response_model=StructuredJD,
    )
    return normalize_hard_requirements(structured)


def normalize_hard_requirements(jd: StructuredJD) -> StructuredJD:
    retained_hard = []
    demoted = []
    for requirement in jd.hard_requirements:
        is_subjective = any(term in requirement.desc for term in SUBJECTIVE_TERMS)
        if (
            requirement.check_type not in OBJECTIVE_HARD_TYPES
            and is_subjective
        ):
            demoted.append(requirement)
        else:
            retained_hard.append(requirement)

    hard_items = [
        requirement.model_copy(update={"id": f"H{index}"})
        for index, requirement in enumerate(retained_hard, start=1)
    ]
    core_items = [
        requirement.model_copy(update={"id": f"C{index}"})
        for index, requirement in enumerate(jd.core_duties, start=1)
    ]
    skill_sources = list(jd.skills) + [
        JobRequirement(id="S1", desc=requirement.desc)
        for requirement in demoted
    ]
    skill_items = [
        requirement.model_copy(update={"id": f"S{index}"})
        for index, requirement in enumerate(skill_sources, start=1)
    ]
    domain_items = [
        requirement.model_copy(update={"id": f"D{index}"})
        for index, requirement in enumerate(jd.domain_project, start=1)
    ]
    plus_items = [
        requirement.model_copy(update={"id": f"E{index}"})
        for index, requirement in enumerate(jd.education_cert_plus, start=1)
    ]
    return StructuredJD(
        hard_requirements=hard_items,
        core_duties=core_items,
        skills=skill_items,
        domain_project=domain_items,
        education_cert_plus=plus_items,
        notes=jd.notes,
    )

