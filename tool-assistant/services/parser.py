from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from config import Settings
from services.ocr import BailianOCRClient, OCRServiceError
from services.schemas import PageCoverage, ParsedResume
from services.text_utils import clean_text, meaningful_char_count


class ResumeParseError(RuntimeError):
    """简历文件无法安全解析。"""


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}


def parse_resume(
    file_bytes: bytes,
    filename: str,
    settings: Settings,
    ocr_client: BailianOCRClient | None = None,
) -> ParsedResume:
    safe_name = Path(filename or "未命名").name
    if len(file_bytes) > settings.max_file_bytes:
        raise ResumeParseError(
            f"文件超过 {settings.max_file_mb} MB 限制，未解析。"
        )
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ResumeParseError("仅支持 PDF、DOCX、TXT 文件。")
    if not file_bytes:
        raise ResumeParseError("文件为空。")

    if suffix == ".pdf":
        return _parse_pdf(file_bytes, settings, ocr_client)
    if suffix == ".docx":
        return _parse_docx(file_bytes, settings)
    return _parse_txt(file_bytes, settings)


def _parse_txt(file_bytes: bytes, settings: Settings) -> ParsedResume:
    text = ""
    for encoding in ("utf-8-sig", "gbk", "gb18030"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        raise ResumeParseError("TXT 编码无法识别，请另存为 UTF-8 后重试。")
    return _finalize_text(clean_text(text), settings, [], False)


def _parse_docx(file_bytes: bytes, settings: Settings) -> ParsedResume:
    try:
        document = Document(BytesIO(file_bytes))
    except Exception as exc:
        raise ResumeParseError(f"DOCX 解析失败：{exc}") from exc

    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text = clean_text("\n".join(parts))
    if not meaningful_char_count(text):
        raise ResumeParseError("DOCX 未提取到有效文字。")
    return _finalize_text(text, settings, [], False)


def _parse_pdf(
    file_bytes: bytes,
    settings: Settings,
    ocr_client: BailianOCRClient | None,
) -> ParsedResume:
    try:
        reader = PdfReader(BytesIO(file_bytes), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ResumeParseError("PDF 已加密，无法解析。") from exc
        raw_pages = [(page.extract_text() or "") for page in reader.pages]
    except ResumeParseError:
        raise
    except Exception as exc:
        raise ResumeParseError(f"PDF 解析失败：{exc}") from exc

    page_texts = [clean_text(text) for text in raw_pages]
    page_coverages: list[PageCoverage] = []
    low_pages: list[int] = []
    for index, text in enumerate(page_texts, start=1):
        count = meaningful_char_count(text)
        if count < settings.low_text_page_chars:
            low_pages.append(index - 1)
            page_coverages.append(
                PageCoverage(
                    page=index,
                    status="待OCR",
                    text_chars=count,
                    detail=f"有效文字少于 {settings.low_text_page_chars} 个字符",
                )
            )
        else:
            page_coverages.append(
                PageCoverage(page=index, status="文字页", text_chars=count)
            )

    coverage_reasons: list[str] = []
    warnings: list[str] = []
    ocr_used = False
    if low_pages:
        page_list = _format_pages([index + 1 for index in low_pages])
        if not settings.enable_ocr:
            raise ResumeParseError(
                f"PDF 第 {page_list} 页为低文本页，请开启 OCR 后重试。"
            )
        if ocr_client is None:
            raise ResumeParseError(
                f"PDF 第 {page_list} 页需要 OCR，但未配置 DASHSCOPE_API_KEY。"
            )

        attempted: list[int] = []
        succeeded: list[int] = []
        for index in low_pages[: settings.max_ocr_pages]:
            attempted.append(index + 1)
            try:
                result = ocr_client.recognize_pdf_page(file_bytes, index)
            except OCRServiceError as exc:
                page_coverages[index] = PageCoverage(
                    page=index + 1,
                    status="OCR失败",
                    text_chars=meaningful_char_count(page_texts[index]),
                    detail=str(exc),
                )
                warnings.append(f"第 {index + 1} 页 OCR 失败：{exc}")
                continue
            page_texts[index] = result.text
            page_coverages[index] = PageCoverage(
                page=index + 1,
                status="已OCR",
                text_chars=meaningful_char_count(result.text),
            )
            ocr_used = True
            succeeded.append(index + 1)
            if result.truncated:
                warnings.append(f"第 {index + 1} 页 OCR 输出可能达到长度上限。")
                coverage_reasons.append(f"第 {index + 1} 页 OCR 输出可能被截断")

        if not succeeded:
            raise ResumeParseError(
                f"需要 OCR 的页面均识别失败：第 {_format_pages(attempted)} 页。"
            )

        for index in low_pages[settings.max_ocr_pages :]:
            page_coverages[index] = PageCoverage(
                page=index + 1,
                status="未OCR（超过页数上限）",
                text_chars=meaningful_char_count(page_texts[index]),
                detail=f"仅处理前 {settings.max_ocr_pages} 个低文本页",
            )
            coverage_reasons.append(
                f"第 {index + 1} 页超过 OCR 页数上限，未覆盖"
            )
        for index in low_pages[: settings.max_ocr_pages]:
            if page_coverages[index].status == "OCR失败":
                coverage_reasons.append(f"第 {index + 1} 页 OCR 失败，未覆盖")

        if coverage_reasons:
            warnings.append("OCR 未完整覆盖全部页面，请人工复核未覆盖页。")

    joined = "\n\n".join(
        f"[第{index}页]\n{text}" for index, text in enumerate(page_texts, start=1) if text
    )
    if not meaningful_char_count(joined):
        raise ResumeParseError("PDF 未提取到有效文字。")
    parsed = _finalize_text(joined, settings, warnings, ocr_used)
    parsed.page_coverages = page_coverages
    parsed.coverage_reasons = coverage_reasons + parsed.coverage_reasons
    parsed.coverage_complete = not parsed.coverage_reasons
    return parsed


def _finalize_text(
    text: str,
    settings: Settings,
    warnings: list[str],
    ocr_used: bool,
) -> ParsedResume:
    text = clean_text(text)
    original_count = len(text)
    truncated = original_count > settings.max_resume_chars
    coverage_reasons: list[str] = []
    if truncated:
        text = text[: settings.max_resume_chars].rstrip()
        reason = (
            f"正文超过 {settings.max_resume_chars} 字，"
            f"已保留前 {settings.max_resume_chars} 字"
        )
        coverage_reasons.append(reason)
        warnings.append(reason + "，评估范围不完整，需人工复核。")
    return ParsedResume(
        text=text,
        preview=text[:2000],
        ocr_used=ocr_used,
        coverage_complete=not coverage_reasons,
        coverage_reasons=coverage_reasons,
        warnings=warnings,
        original_char_count=original_count,
        truncated=truncated,
    )


def _format_pages(pages: list[int]) -> str:
    return "、".join(str(page) for page in pages)

