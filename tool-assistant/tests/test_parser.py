from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document

import services.parser as parser_module
from services.ocr import OCRResult
from services.parser import ResumeParseError, parse_resume


def test_txt_utf8_and_gbk(settings) -> None:
    utf8 = parse_resume("张三 软件工程师".encode("utf-8"), "简历.txt", settings)
    gbk = parse_resume("李四 数据分析师".encode("gbk"), "简历.txt", settings)
    assert "软件工程师" in utf8.text
    assert "数据分析师" in gbk.text


def test_docx_paragraphs_and_tables(settings) -> None:
    document = Document()
    document.add_paragraph("王五 产品经理")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "技能"
    table.cell(0, 1).text = "SQL"
    output = BytesIO()
    document.save(output)
    parsed = parse_resume(output.getvalue(), "简历.docx", settings)
    assert "产品经理" in parsed.text
    assert "SQL" in parsed.text


def test_text_overflow_keeps_result_and_marks_incomplete(settings) -> None:
    text = "工作经历\n" + "产品经验" * 5000
    parsed = parse_resume(text.encode("utf-8"), "长简历.txt", settings)
    assert parsed.truncated
    assert not parsed.coverage_complete
    assert len(parsed.text) == settings.max_resume_chars


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, *args, **kwargs) -> None:
        self.is_encrypted = False
        self.pages = [
            FakePage("这是一页有足够长度的普通文字简历内容，用于测试逐页判断。" * 2),
            FakePage("封面"),
            FakePage(""),
            FakePage(""),
        ]

    def decrypt(self, password: str) -> None:
        return None


class FakeOCR:
    def __init__(self) -> None:
        self.pages: list[int] = []

    def recognize_pdf_page(self, file_bytes: bytes, page_index: int) -> OCRResult:
        self.pages.append(page_index + 1)
        return OCRResult(text=f"OCR第{page_index + 1}页 项目经历")


def test_pdf_only_ocrs_low_text_pages(monkeypatch, settings) -> None:
    monkeypatch.setattr(parser_module, "PdfReader", FakeReader)
    ocr = FakeOCR()
    run_settings = settings.__class__(
        **{**settings.__dict__, "enable_ocr": True}
    )
    parsed = parse_resume(b"%PDF", "扫描件.pdf", run_settings, ocr)
    assert ocr.pages == [2, 3, 4]
    assert parsed.ocr_used
    assert parsed.coverage_complete
    assert parsed.page_coverages[0].status == "文字页"
    assert parsed.page_coverages[1].status == "已OCR"


def test_pdf_page_limit_reports_uncovered_pages(monkeypatch, settings) -> None:
    monkeypatch.setattr(parser_module, "PdfReader", FakeReader)
    ocr = FakeOCR()
    run_settings = settings.__class__(
        **{
            **settings.__dict__,
            "enable_ocr": True,
            "max_ocr_pages": 1,
        }
    )
    parsed = parse_resume(b"%PDF", "扫描件.pdf", run_settings, ocr)
    assert ocr.pages == [2]
    assert not parsed.coverage_complete
    statuses = {item.page: item.status for item in parsed.page_coverages}
    assert statuses[3] == "未OCR（超过页数上限）"
    assert statuses[4] == "未OCR（超过页数上限）"


def test_pdf_ocr_disabled_fails_with_page_hint(monkeypatch, settings) -> None:
    monkeypatch.setattr(parser_module, "PdfReader", FakeReader)
    with pytest.raises(ResumeParseError, match="第 2、3、4 页"):
        parse_resume(b"%PDF", "扫描件.pdf", settings, None)

