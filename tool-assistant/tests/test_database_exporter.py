from __future__ import annotations

from services.database import Database
from services.schemas import (
    EvaluationResult,
    Grade,
    HardGateStatus,
    JobRequirement,
    StructuredJD,
)
from services.exporter import build_csv


def _structured_jd() -> StructuredJD:
    return StructuredJD(
        core_duties=[JobRequirement(id="C1", desc="产品分析")],
    )


def test_database_cascades_and_exports_bom(settings) -> None:
    database = Database(settings.database_path)
    database.create_task(
        task_id="task-1",
        jd_text="测试JD",
        jd_hash="hash",
        structured_jd=_structured_jd(),
        created_at="2026-01-01T10:00:00+08:00",
    )
    database.add_resume(
        resume_id="resume-1",
        task_id="task-1",
        filename="张三.pdf",
        preview="预览",
        ocr_used=False,
        status="failed",
        result=None,
        error_message="疑似扫描件",
        created_at="2026-01-01T10:00:01+08:00",
        duration_ms=10,
    )
    assert len(database.list_resumes("task-1")) == 1
    csv_bytes = build_csv(database.list_resumes("task-1"))
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert "疑似扫描件" in csv_bytes.decode("utf-8-sig")
    database.delete_task("task-1")
    assert database.list_resumes("task-1") == []


def test_database_round_trips_successful_result(settings) -> None:
    database = Database(settings.database_path)
    database.create_task(
        task_id="task-2",
        jd_text="测试JD",
        jd_hash="hash",
        structured_jd=_structured_jd(),
        created_at="2026-01-01T10:00:00+08:00",
    )
    result = EvaluationResult(
        raw_score=90,
        total_score=90,
        grade=Grade.A,
        recommendation="强烈推荐",
        hard_gate=HardGateStatus.PASSED,
        conclusion="A 级（90 分）",
    )
    database.add_resume(
        resume_id="resume-2",
        task_id="task-2",
        filename="李四.docx",
        preview="预览",
        ocr_used=False,
        status="success",
        result=result,
        error_message="",
        created_at="2026-01-01T10:00:01+08:00",
        duration_ms=10,
    )
    loaded = database.load_result(database.list_resumes("task-2")[0])
    assert loaded is not None
    assert loaded.total_score == 90
    assert loaded.recommendation == "强烈推荐"

