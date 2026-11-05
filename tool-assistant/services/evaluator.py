from __future__ import annotations

from dataclasses import dataclass

from config import Settings
from services.llm_client import DeepSeekClient
from services.matcher import match_resume
from services.ocr import BailianOCRClient
from services.parser import parse_resume
from services.rules import evaluate_hard_requirements
from services.schemas import (
    EvaluationResult,
    MatchResult,
    ParsedResume,
    StructuredJD,
)
from services.scoring import attach_consistency_check, score_resume


@dataclass
class EvaluatedResume:
    parsed: ParsedResume
    result: EvaluationResult


class ResumeEvaluator:
    def __init__(self, settings: Settings, llm_client: DeepSeekClient) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.ocr_client = (
            BailianOCRClient(
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
                model=settings.dashscope_ocr_model,
                timeout=settings.llm_timeout,
            )
            if settings.enable_ocr and settings.dashscope_api_key
            else None
        )

    def evaluate(
        self,
        structured_jd: StructuredJD,
        file_bytes: bytes,
        filename: str,
    ) -> EvaluatedResume:
        parsed = parse_resume(
            file_bytes,
            filename,
            self.settings,
            self.ocr_client,
        )
        result = self._evaluate_parsed(structured_jd, parsed)

        if self.settings.consistency_check and (
            68 <= result.total_score <= 72 or 83 <= result.total_score <= 87
        ):
            try:
                repeat_result = self._evaluate_parsed(structured_jd, parsed)
                result = attach_consistency_check(result, repeat_result)
            except Exception:
                result = result.model_copy(
                    update={
                        "consistency_note": "复评调用失败，建议人工复核。",
                        "manual_review_required": True,
                    }
                )
        return EvaluatedResume(parsed=parsed, result=result)

    def _evaluate_parsed(
        self,
        structured_jd: StructuredJD,
        parsed: ParsedResume,
    ) -> EvaluationResult:
        response = match_resume(
            self.llm_client,
            structured_jd,
            parsed.text,
        )
        match_map = {item.requirement_id: item for item in response.matches}
        match_results = [
            MatchResult(
                requirement_id=requirement_id,
                category=category,
                desc=desc,
                match_level=match_map[requirement_id].match_level,
                evidence=match_map[requirement_id].evidence,
                reason=match_map[requirement_id].reason,
            )
            for category, requirement_id, desc in structured_jd.all_requirements
        ]
        hard_results = evaluate_hard_requirements(
            structured_jd.hard_requirements,
            response.matches,
            response.candidate_facts,
            parsed.text,
        )
        result = score_resume(
            structured_jd,
            match_results,
            hard_results,
            parsed,
            response.candidate_facts,
        )
        return result


def task_resume_sort_key(row: dict) -> tuple[int, int, int, str]:
    result = row.get("_result")
    if row.get("status") != "success" or result is None:
        group = 3
        score = -1
        coverage = 0
    elif result.hard_gate.value == "不通过":
        group = 2
        score = result.total_score
        coverage = int(result.coverage_complete)
    elif (
        result.hard_gate.value == "待确认"
        or not result.coverage_complete
    ):
        group = 1
        score = result.total_score
        coverage = int(result.coverage_complete)
    else:
        group = 0
        score = result.total_score
        coverage = 1
    return (group, -score, -coverage, row.get("filename", ""))

