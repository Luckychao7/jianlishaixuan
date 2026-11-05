from __future__ import annotations

import base64
from io import BytesIO
from dataclasses import dataclass

import pypdfium2 as pdfium
from openai import OpenAI

from services.prompts import OCR_PROMPT
from services.text_utils import clean_text


class OCRServiceError(RuntimeError):
    """百炼 OCR 调用失败。"""


@dataclass(frozen=True)
class OCRResult:
    text: str
    truncated: bool = False


def render_pdf_page_to_png(pdf_bytes: bytes, page_index: int, scale: float = 2.2) -> bytes:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        if page_index < 0 or page_index >= len(document):
            raise OCRServiceError(f"PDF 页码不存在：{page_index + 1}")
        page = document[page_index]
        try:
            bitmap = page.render(scale=scale)
            try:
                image = bitmap.to_pil().convert("RGB")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    except OCRServiceError:
        raise
    except Exception as exc:
        raise OCRServiceError(f"PDF 第 {page_index + 1} 页转图失败：{exc}") from exc
    finally:
        document.close()


class BailianOCRClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int,
    ) -> None:
        if not api_key:
            raise OCRServiceError("未配置 DASHSCOPE_API_KEY")
        self.model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )

    def recognize_image(self, png_bytes: bytes) -> OCRResult:
        encoded = base64.b64encode(png_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{encoded}"
        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {"type": "text", "text": OCR_PROMPT},
                        ],
                    }
                ],
                temperature=0,
            )
            choice = completion.choices[0]
            text = clean_text(choice.message.content or "")
            if not text:
                raise OCRServiceError("OCR 返回空文本")
            return OCRResult(
                text=text,
                truncated=choice.finish_reason == "length",
            )
        except OCRServiceError:
            raise
        except Exception as exc:
            raise OCRServiceError(f"百炼 OCR 调用失败：{exc}") from exc

    def recognize_pdf_page(self, pdf_bytes: bytes, page_index: int) -> OCRResult:
        return self.recognize_image(render_pdf_page_to_png(pdf_bytes, page_index))

