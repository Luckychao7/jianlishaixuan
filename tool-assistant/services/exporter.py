from __future__ import annotations

from typing import Any

import pandas as pd

from services.database import Database


EXPORT_COLUMNS = [
    "文件名",
    "总分",
    "原始分",
    "等级",
    "建议",
    "硬性门槛",
    "需人工复核",
    "一句话结论",
    "主要不匹配点",
    "风险",
    "待确认项",
    "面试问题",
    "是否OCR",
    "OCR未覆盖",
    "评估时间",
]


def build_csv(rows: list[dict[str, Any]]) -> bytes:
    output: list[dict[str, Any]] = []
    for row in rows:
        result = Database.load_result(row)
        if row.get("status") != "success" or result is None:
            output.append(
                {
                    "文件名": row.get("filename", ""),
                    "总分": "",
                    "原始分": "",
                    "等级": "",
                    "建议": "评估失败",
                    "硬性门槛": "",
                    "需人工复核": "",
                    "一句话结论": row.get("error_message", "评估失败"),
                    "主要不匹配点": "",
                    "风险": row.get("error_message", ""),
                    "待确认项": "",
                    "面试问题": "",
                    "是否OCR": "是" if row.get("ocr_used") else "否",
                    "OCR未覆盖": "",
                    "评估时间": row.get("created_at", ""),
                }
            )
            continue

        uncovered = [
            f"第{item.page}页：{item.status}"
            for item in result.page_coverages
            if item.status not in {"文字页", "已OCR"}
        ]
        output.append(
            {
                "文件名": row.get("filename", ""),
                "总分": result.total_score,
                "原始分": result.raw_score,
                "等级": result.grade.value,
                "建议": result.recommendation,
                "硬性门槛": result.hard_gate.value,
                "需人工复核": "是" if result.manual_review_required else "否",
                "一句话结论": result.conclusion,
                "主要不匹配点": "；".join(result.gaps),
                "风险": "；".join(result.risks),
                "待确认项": "；".join(result.pending_items),
                "面试问题": "；".join(result.interview_questions),
                "是否OCR": "是" if row.get("ocr_used") else "否",
                "OCR未覆盖": "；".join(uncovered),
                "评估时间": row.get("created_at", ""),
            }
        )
    frame = pd.DataFrame(output, columns=EXPORT_COLUMNS)
    return frame.to_csv(index=False).encode("utf-8-sig")

