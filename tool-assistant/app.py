from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from config import BASE_DIR, load_settings
from services.database import Database
from services.evaluator import ResumeEvaluator, task_resume_sort_key
from services.exporter import build_csv
from services.jd_parser import JD_PARSER_VERSION, parse_jd
from services.llm_client import DeepSeekClient, LLMServiceError
from services.parser import ResumeParseError
from services.schemas import EvaluationResult, ExperienceScope


st.set_page_config(
    page_title="简历筛查助手",
    page_icon="📄",
    layout="wide",
)

EXPERIENCE_SCOPE_LABELS = {
    ExperienceScope.PERFORMANCE_MARKETING: "效果营销投放年限",
    ExperienceScope.TOB_SALES: "ToB销售年限",
    ExperienceScope.FULL_STACK_WEB: "全栈Web开发年限",
    ExperienceScope.AI_SYSTEM_ARCHITECTURE: "AI系统架构年限",
    ExperienceScope.AI_DEVELOPMENT_TOOLS: "AI开发工具使用年限",
    ExperienceScope.TEAM_MANAGEMENT: "团队管理年限",
    ExperienceScope.BACKEND_DEVELOPMENT: "后端开发年限",
    ExperienceScope.FRONTEND_DEVELOPMENT: "前端开发年限",
    ExperienceScope.DATA_ENGINEERING: "数据工程年限",
    ExperienceScope.OTHER_RELEVANT: "其他相关工作年限",
}


def _init_state() -> None:
    if "page" not in st.session_state:
        st.session_state.page = "首页"
    if "active_task_id" not in st.session_state:
        st.session_state.active_task_id = ""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_filename(name: str) -> str:
    return Path(name or "未命名").name


def _display_header() -> None:
    st.title("简历筛查助手")
    st.warning(
        "本工具仅辅助初筛，不自动淘汰候选人，最终必须由人工复核。"
        "评估时简历文本会发送给 DeepSeek；扫描页还会发送给阿里云百炼。"
    )


def _render_home(settings, database: Database, llm_client: DeepSeekClient | None) -> None:
    st.subheader("新建评估")
    if llm_client is None:
        st.error(
            "未配置 DEEPSEEK_API_KEY，不能发起新评估。"
            "请在项目目录创建 .env 并填写密钥。"
        )
    if settings.enable_ocr and not settings.dashscope_api_key:
        st.info(
            "当前默认开启 OCR，但未配置 DASHSCOPE_API_KEY。"
            "仅含扫描页的简历会失败，普通文字简历不受影响。"
        )

    with st.form("screening_form"):
        jd_text = st.text_area(
            "岗位 JD（必填）",
            height=240,
            placeholder="粘贴完整岗位描述、任职要求等。",
        )
        preferences = st.text_area(
            "招聘补充偏好（可选）",
            height=100,
            placeholder="例如：优先考虑有SaaS行业经验的人选。请勿填写年龄、性别、婚育等无关隐私条件。",
        )
        uploaded_files = st.file_uploader(
            "批量上传简历",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
            help=(
                f"最多 {settings.max_files} 份，单文件不超过 "
                f"{settings.max_file_mb} MB。"
            ),
        )
        enable_ocr = st.checkbox(
            "为低文本 PDF 页启用阿里云百炼 OCR",
            value=settings.enable_ocr,
            help="开启后会产生云服务调用费用。只处理逐页文字少于50字的页面。",
        )
        submitted = st.form_submit_button(
            "开始评估",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return
    if not jd_text.strip():
        st.error("请先填写岗位 JD。")
        return
    if not uploaded_files:
        st.error("请至少上传一份简历。")
        return
    if len(uploaded_files) > settings.max_files:
        st.error(f"一次最多上传 {settings.max_files} 份简历。")
        return
    if llm_client is None:
        st.error("请先配置 DEEPSEEK_API_KEY。")
        return

    oversized = [
        file.name
        for file in uploaded_files
        if file.size > settings.max_file_bytes
    ]
    if oversized:
        st.error(
            f"以下文件超过 {settings.max_file_mb} MB：{'、'.join(oversized)}"
        )
        return

    run_settings = replace(settings, enable_ocr=enable_ocr)
    evaluator = ResumeEvaluator(run_settings, llm_client)
    task_id = str(uuid.uuid4())
    task_created_at = _now()
    jd_hash = hashlib.sha256(
        f"{JD_PARSER_VERSION}\n{jd_text}\n{preferences}".encode("utf-8")
    ).hexdigest()
    structured_jd = database.find_structured_jd(jd_hash)
    if structured_jd is None:
        with st.spinner("正在结构化岗位 JD，请稍候..."):
            try:
                structured_jd = parse_jd(llm_client, jd_text, preferences)
            except Exception as exc:
                st.error(f"JD 解析失败：{exc}")
                st.caption("请检查 DeepSeek 密钥、网络和 JD 内容后重试。")
                return
    else:
        st.info("已复用相同 JD 的结构化结果，保证重复评估使用同一套要求。")

    database.create_task(
        task_id=task_id,
        jd_text=jd_text,
        jd_hash=jd_hash,
        structured_jd=structured_jd,
        created_at=task_created_at,
    )
    progress = st.progress(0, text="准备评估...")
    current_label = st.empty()
    total = len(uploaded_files)
    try:
        for index, uploaded_file in enumerate(uploaded_files, start=1):
            filename = _safe_filename(uploaded_file.name)
            current_label.info(f"正在评估：{filename}（{index}/{total}）")
            started = time.perf_counter()
            preview = ""
            ocr_used = False
            result = None
            status = "failed"
            error_message = ""
            try:
                evaluated = evaluator.evaluate(
                    structured_jd,
                    uploaded_file.getvalue(),
                    filename,
                )
                preview = evaluated.parsed.preview
                ocr_used = evaluated.parsed.ocr_used
                result = evaluated.result
                status = "success"
            except (ResumeParseError, LLMServiceError) as exc:
                error_message = str(exc)
            except Exception as exc:
                error_message = f"未预期错误：{exc}"

            duration_ms = int((time.perf_counter() - started) * 1000)
            database.add_resume(
                resume_id=str(uuid.uuid4()),
                task_id=task_id,
                filename=filename,
                preview=preview,
                ocr_used=ocr_used,
                status=status,
                result=result,
                error_message=error_message,
                created_at=_now(),
                duration_ms=duration_ms,
            )
            progress.progress(
                index / total,
                text=f"已完成 {index}/{total}",
            )
    finally:
        database.complete_task(task_id)
        current_label.empty()

    st.session_state.active_task_id = task_id
    st.session_state.page = "结果"
    st.rerun()


def _render_result_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        result: EvaluationResult | None = row["_result"]
        if row["status"] != "success" or result is None:
            records.append(
                {
                    "文件名": row["filename"],
                    "总分": "",
                    "原始分": "",
                    "等级": "",
                    "建议": "评估失败",
                    "硬性门槛": "",
                    "需人工复核": "",
                    "覆盖范围": "",
                    "一句话结论": row["error_message"],
                    "状态": "失败",
                }
            )
            continue
        records.append(
            {
                "文件名": row["filename"],
                "总分": str(result.total_score),
                "原始分": str(result.raw_score),
                "等级": result.grade.value,
                "建议": result.recommendation,
                "硬性门槛": result.hard_gate.value,
                "需人工复核": "是" if result.manual_review_required else "否",
                "覆盖范围": "完整" if result.coverage_complete else "不完整",
                "一句话结论": result.conclusion,
                "状态": "成功",
            }
        )
    return pd.DataFrame(records)


def _style_result_rows(row: pd.Series) -> list[str]:
    if row.get("状态") == "失败":
        return ["background-color: #fde8e7; color: #9f1d18"] * len(row)
    if row.get("需人工复核") == "是":
        return ["background-color: #fff4d6"] * len(row)
    return [""] * len(row)


def _render_details(row: dict[str, Any]) -> None:
    filename = row["filename"]
    result: EvaluationResult | None = row["_result"]
    label = f"{filename}｜{row['status']}"
    if result is not None:
        label = (
            f"{filename}｜{result.total_score}分｜{result.grade.value}级"
            f"｜{result.recommendation}"
        )
    with st.expander(label):
        if row["status"] != "success" or result is None:
            st.error(row["error_message"] or "评估失败。")
            return

        if result.manual_review_required:
            st.warning("该结果需人工复核。")
        st.write(f"**一句话结论：** {result.conclusion}")
        if result.cap_reasons:
            st.write("**封顶原因：** " + "；".join(result.cap_reasons))
        if result.consistency_note:
            st.info(result.consistency_note)

        st.markdown("#### 硬性条件")
        if result.hard_results:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "编号": item.requirement_id,
                            "要求": item.desc,
                            "状态": item.status.value,
                            "证据": item.evidence,
                            "理由": item.reason,
                        }
                        for item in result.hard_results
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("JD 未设置硬性条件。")

        st.markdown("#### 候选人事实")
        facts = result.candidate_facts
        fact_rows = [
            {
                "事实": "最高学历",
                "提取值": facts.highest_education.level.value,
                "可靠确认": "是"
                if facts.highest_education.reliable
                else "否",
                "原文证据": facts.highest_education.evidence,
            },
            {
                "事实": "毕业时间",
                "提取值": facts.graduation_time.value or "未知",
                "可靠确认": "是"
                if facts.graduation_time.reliable
                else "否",
                "原文证据": facts.graduation_time.evidence,
            },
        ]
        for experience in facts.experience_facts:
            fact_rows.append(
                {
                    "事实": EXPERIENCE_SCOPE_LABELS[experience.scope],
                    "提取值": (
                        f"{experience.years:g} 年"
                        if experience.years is not None
                        else "无法可靠计算"
                    ),
                    "可靠确认": "是" if experience.reliable else "否",
                    "原文证据": (
                        experience.evidence
                        + "；计算依据："
                        + experience.basis
                    ).strip("；"),
                }
            )
        if not facts.experience_facts and facts.relevant_work_years.value is not None:
            fact_rows.append(
                {
                    "事实": "旧版总工作年限",
                    "提取值": f"{facts.relevant_work_years.value:g} 年",
                    "可靠确认": "是"
                    if facts.relevant_work_years.reliable
                    else "否",
                    "原文证据": (
                        facts.relevant_work_years.evidence
                        + "；计算依据："
                        + facts.relevant_work_years.basis
                    ).strip("；"),
                }
            )
        fact_rows.append(
            {
                "事实": "最大管理团队规模",
                "提取值": (
                    f"{facts.team_size.max_team_size} 人"
                    if facts.team_size.max_team_size is not None
                    else "未知"
                ),
                "可靠确认": "是" if facts.team_size.reliable else "否",
                "原文证据": facts.team_size.evidence,
            }
        )
        fact_rows.append(
            {
                "事实": "证书",
                "提取值": "、".join(
                    item.name for item in facts.certificates
                )
                or "未识别",
                "可靠确认": "；".join(
                    f"{item.name}:{'是' if item.reliable else '否'}"
                    for item in facts.certificates
                )
                or "无",
                "原文证据": "；".join(
                    item.evidence
                    for item in facts.certificates
                    if item.evidence
                ),
            }
        )
        st.dataframe(
            pd.DataFrame(fact_rows),
            hide_index=True,
            width="stretch",
        )

        st.markdown("#### 维度评分")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "维度": item.name,
                        "权重": item.weight,
                        "得分": item.score,
                        "中性计分": "是" if item.neutral else "否",
                        "说明": item.reason,
                    }
                    for item in result.dimension_scores
                ]
            ),
            hide_index=True,
            width="stretch",
        )

        st.markdown("#### 逐条匹配证据")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "编号": item.requirement_id,
                        "分类": item.category.value,
                        "要求": item.desc,
                        "匹配": item.match_level.value,
                        "证据": item.evidence,
                        "理由": item.reason,
                    }
                    for item in result.match_results
                ]
            ),
            hide_index=True,
            width="stretch",
        )

        left, right = st.columns(2)
        with left:
            st.markdown("#### 风险与待确认")
            _render_text_list(result.risks, "暂未发现额外风险。")
            _render_text_list(result.pending_items, "暂无待确认项。")
        with right:
            st.markdown("#### 主要不匹配点")
            _render_text_list(result.gaps, "暂未发现明显不匹配项。")
            st.markdown("#### 建议面试问题")
            _render_text_list(result.interview_questions, "暂无建议问题。")

        if result.page_coverages:
            st.markdown("#### PDF 页面覆盖情况")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "页码": item.page,
                            "状态": item.status,
                            "有效字符": item.text_chars,
                            "说明": item.detail,
                        }
                        for item in result.page_coverages
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        if result.warnings:
            st.markdown("#### 解析警告")
            _render_text_list(result.warnings, "")

        st.markdown("#### 解析文本预览（前2000字）")
        st.text_area(
            "解析文本",
            value=row["parsed_text_preview"] or "无预览",
            height=220,
            disabled=True,
            label_visibility="collapsed",
        )


def _render_text_list(items: list[str], empty_message: str) -> None:
    if not items:
        if empty_message:
            st.caption(empty_message)
        return
    for item in items:
        st.markdown(f"- {item}")


def _render_results(settings, database: Database) -> None:
    task_id = st.session_state.active_task_id
    task = database.get_task(task_id) if task_id else None
    if not task:
        st.info("尚无评估结果，请先在首页发起评估。")
        if st.button("返回首页"):
            st.session_state.page = "首页"
            st.rerun()
        return
    st.subheader("评估结果")
    st.caption(
        f"任务时间：{task['created_at']}　JD摘要："
        f"{task['jd_text'][:100].replace(chr(10), ' ')}"
    )

    rows = database.list_resumes(task_id)
    for row in rows:
        row["_result"] = database.load_result(row)
    rows.sort(key=task_resume_sort_key)

    grades = ["全部", "A", "B", "C", "D", "失败"]
    selected_grade = st.selectbox("按等级筛选", grades)
    if selected_grade == "失败":
        visible_rows = [row for row in rows if row["status"] != "success"]
    elif selected_grade != "全部":
        visible_rows = [
            row
            for row in rows
            if row["_result"] is not None
            and row["_result"].grade.value == selected_grade
        ]
    else:
        visible_rows = rows

    frame = _render_result_table(visible_rows)
    if frame.empty:
        st.info("当前筛选条件下没有结果。")
    else:
        styled = frame.style.apply(_style_result_rows, axis=1)
        st.dataframe(styled, hide_index=True, width="stretch")

    st.download_button(
        "导出当前任务 CSV",
        data=build_csv(rows),
        file_name=f"简历筛查结果_{task_id[:8]}.csv",
        mime="text/csv",
        type="primary",
    )

    st.subheader("简历详情")
    for row in visible_rows:
        _render_details(row)


def _render_history(database: Database) -> None:
    st.subheader("历史任务")
    tasks = database.list_tasks()
    if not tasks:
        st.info("暂无历史任务。")
        return

    frame = pd.DataFrame(
        [
            {
                "任务ID": task["id"][:8],
                "JD摘要": task["jd_text"][:100].replace("\n", " "),
                "简历数": task["resume_count"],
                "成功数": task["success_count"] or 0,
                "状态": task["status"],
                "创建时间": task["created_at"],
            }
            for task in tasks
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")

    task_labels = {
        f"{task['created_at']}｜{task['jd_text'][:45].replace(chr(10), ' ')}": task[
            "id"
        ]
        for task in tasks
    }
    selected_label = st.selectbox("选择历史任务", list(task_labels))
    selected_id = task_labels[selected_label]

    left, right = st.columns(2)
    with left:
        if st.button("查看该任务结果", width="stretch"):
            st.session_state.active_task_id = selected_id
            st.session_state.page = "结果"
            st.rerun()
    with right:
        confirm_delete = st.checkbox("确认删除所选任务及其评估结果")
        if st.button(
            "删除所选任务",
            disabled=not confirm_delete,
            width="stretch",
        ):
            database.delete_task(selected_id)
            if st.session_state.active_task_id == selected_id:
                st.session_state.active_task_id = ""
            st.rerun()

    st.divider()
    st.markdown("#### 清空全部历史")
    confirm_clear = st.checkbox("我确认清空全部任务和评估结果")
    if st.button(
        "清空全部",
        disabled=not confirm_clear,
        type="secondary",
    ):
        database.clear_all()
        st.session_state.active_task_id = ""
        st.rerun()


def main() -> None:
    _init_state()
    settings = load_settings()
    database = Database(settings.database_path)
    llm_client: DeepSeekClient | None
    try:
        llm_client = DeepSeekClient(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout=settings.llm_timeout,
        )
    except LLMServiceError:
        llm_client = None

    _display_header()
    if llm_client is None:
        st.sidebar.error("未配置 DeepSeek 密钥")
    else:
        st.sidebar.caption(f"模型：{settings.deepseek_model}")
    st.sidebar.caption(f"项目目录：{BASE_DIR}")

    options = ["首页", "历史"]
    if st.session_state.active_task_id:
        options.insert(1, "结果")
    current = st.session_state.page
    if current not in options:
        current = "首页"
    page = st.sidebar.radio("页面导航", options, index=options.index(current))
    st.session_state.page = page

    if page == "首页":
        _render_home(settings, database, llm_client)
    elif page == "结果":
        _render_results(settings, database)
    else:
        _render_history(database)


if __name__ == "__main__":
    main()

