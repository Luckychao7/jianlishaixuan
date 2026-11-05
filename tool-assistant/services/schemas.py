from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


NonEmptyText = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class HardCheckType(str, Enum):
    EDUCATION = "education"
    YEARS = "years"
    CERTIFICATE = "certificate"
    SKILL = "skill"
    OTHER = "other"


class RequirementCategory(str, Enum):
    HARD = "H"
    CORE = "C"
    SKILL = "S"
    DOMAIN = "D"
    EDUCATION_PLUS = "E"


class MatchLevel(str, Enum):
    COMPLETE = "完全匹配"
    PARTIAL = "部分匹配"
    NOT_MENTIONED = "未体现"
    NOT_MET = "明确不满足"


class EducationLevel(str, Enum):
    UNKNOWN = "未知"
    HIGH_SCHOOL_OR_BELOW = "高中及以下"
    ASSOCIATE = "专科"
    BACHELOR = "本科"
    MASTER = "硕士"
    DOCTOR = "博士"


class HardGateStatus(str, Enum):
    PASSED = "通过"
    PENDING = "待确认"
    FAILED = "不通过"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class HardRequirement(StrictModel):
    id: Annotated[str, StringConstraints(pattern=r"^H[1-9]\d*$")]
    desc: NonEmptyText
    check_type: HardCheckType


class JobRequirement(StrictModel):
    id: Annotated[str, StringConstraints(pattern=r"^[CSDE][1-9]\d*$")]
    desc: NonEmptyText


class StructuredJD(StrictModel):
    hard_requirements: list[HardRequirement] = Field(default_factory=list)
    core_duties: list[JobRequirement] = Field(default_factory=list)
    skills: list[JobRequirement] = Field(default_factory=list)
    domain_project: list[JobRequirement] = Field(default_factory=list)
    education_cert_plus: list[JobRequirement] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_requirement_ids(self) -> "StructuredJD":
        groups = [
            ("H", self.hard_requirements),
            ("C", self.core_duties),
            ("S", self.skills),
            ("D", self.domain_project),
            ("E", self.education_cert_plus),
        ]
        seen: set[str] = set()
        total = 0
        for prefix, items in groups:
            local_ids: set[str] = set()
            for item in items:
                total += 1
                if not item.id.startswith(prefix):
                    raise ValueError(f"{prefix} 类要求的编号必须以 {prefix} 开头")
                if item.id in local_ids or item.id in seen:
                    raise ValueError(f"需求编号重复：{item.id}")
                local_ids.add(item.id)
                seen.add(item.id)
        if total == 0:
            raise ValueError("JD 至少需要一条可判断的要求")
        return self

    @property
    def all_requirements(self) -> list[tuple[RequirementCategory, str, str]]:
        groups: list[tuple[RequirementCategory, list[JobRequirement] | list[HardRequirement]]] = [
            (RequirementCategory.HARD, self.hard_requirements),
            (RequirementCategory.CORE, self.core_duties),
            (RequirementCategory.SKILL, self.skills),
            (RequirementCategory.DOMAIN, self.domain_project),
            (RequirementCategory.EDUCATION_PLUS, self.education_cert_plus),
        ]
        result: list[tuple[RequirementCategory, str, str]] = []
        for category, items in groups:
            for item in items:
                result.append((category, item.id, item.desc))
        return result


class EducationFact(StrictModel):
    level: EducationLevel = EducationLevel.UNKNOWN
    evidence: str = Field(default="", max_length=1000)
    reliable: bool = False


class GraduationFact(StrictModel):
    value: str | None = None
    evidence: str = Field(default="", max_length=1000)
    reliable: bool = False

    @field_validator("value")
    @classmethod
    def validate_month(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("毕业时间必须为 YYYY-MM 或空")
        return value


class WorkYearsFact(StrictModel):
    value: float | None = Field(default=None, ge=0, le=80)
    basis: str = Field(default="", max_length=1000)
    evidence: str = Field(default="", max_length=1000)
    reliable: bool = False


class CertificateFact(StrictModel):
    name: NonEmptyText
    evidence: str = Field(default="", max_length=1000)
    reliable: bool = False


class CandidateFacts(StrictModel):
    highest_education: EducationFact = Field(default_factory=EducationFact)
    graduation_time: GraduationFact = Field(default_factory=GraduationFact)
    relevant_work_years: WorkYearsFact = Field(default_factory=WorkYearsFact)
    certificates: list[CertificateFact] = Field(default_factory=list)


class MatchItem(StrictModel):
    requirement_id: Annotated[str, StringConstraints(pattern=r"^[HCSDE][1-9]\d*$")]
    match_level: MatchLevel
    evidence: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=1000)


class ResumeModelResponse(StrictModel):
    matches: list[MatchItem]
    candidate_facts: CandidateFacts

    @model_validator(mode="after")
    def unique_match_ids(self) -> "ResumeModelResponse":
        ids = [item.requirement_id for item in self.matches]
        if len(ids) != len(set(ids)):
            raise ValueError("matches 中存在重复需求编号")
        return self


class HardRequirementResult(StrictModel):
    requirement_id: str
    desc: str
    check_type: HardCheckType
    status: HardGateStatus
    evidence: str = ""
    reason: str


class MatchResult(StrictModel):
    requirement_id: str
    category: RequirementCategory
    desc: str
    match_level: MatchLevel
    evidence: str = ""
    reason: str = ""


class DimensionScore(StrictModel):
    key: str
    name: str
    weight: int
    score: int
    neutral: bool = False
    reason: str


class PageCoverage(StrictModel):
    page: int
    status: str
    text_chars: int = 0
    detail: str = ""


class EvaluationResult(StrictModel):
    raw_score: int
    total_score: int
    grade: Grade
    recommendation: str
    hard_gate: HardGateStatus
    manual_review_required: bool = False
    coverage_complete: bool = True
    coverage_reasons: list[str] = Field(default_factory=list)
    cap_reasons: list[str] = Field(default_factory=list)
    conclusion: str
    hard_results: list[HardRequirementResult] = Field(default_factory=list)
    match_results: list[MatchResult] = Field(default_factory=list)
    candidate_facts: CandidateFacts = Field(default_factory=CandidateFacts)
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    page_coverages: list[PageCoverage] = Field(default_factory=list)
    consistency_note: str = ""


class ParsedResume(StrictModel):
    text: str
    preview: str
    ocr_used: bool = False
    coverage_complete: bool = True
    coverage_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    page_coverages: list[PageCoverage] = Field(default_factory=list)
    original_char_count: int = 0
    truncated: bool = False

