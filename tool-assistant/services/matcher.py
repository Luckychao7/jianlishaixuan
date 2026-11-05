from __future__ import annotations

from services.llm_client import DeepSeekClient
from services.prompts import RESUME_SYSTEM_PROMPT, build_resume_user_prompt
from services.schemas import (
    CandidateFacts,
    CertificateFact,
    EducationFact,
    GraduationFact,
    MatchItem,
    MatchLevel,
    ResumeModelResponse,
    StructuredJD,
    WorkYearsFact,
)
from services.text_utils import evidence_in_text


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
    sanitized_facts = CandidateFacts(
        highest_education=education,
        graduation_time=graduation,
        relevant_work_years=years,
        certificates=certificates,
    )
    return ResumeModelResponse(matches=matches, candidate_facts=sanitized_facts)

