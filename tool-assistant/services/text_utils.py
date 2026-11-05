from __future__ import annotations

import re
import unicodedata


_NOISE_RE = re.compile(r"[\W_]+", flags=re.UNICODE)


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in text.split("\n")]
    output: list[str] = []
    blank = False
    for line in lines:
        if line:
            output.append(line)
            blank = False
        elif not blank:
            output.append("")
            blank = True
    return "\n".join(output).strip()


def meaningful_char_count(text: str) -> int:
    return len(_NOISE_RE.sub("", text))


def normalize_for_evidence(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _NOISE_RE.sub("", normalized)


def evidence_in_text(evidence: str, source_text: str) -> bool:
    normalized_evidence = normalize_for_evidence(evidence)
    if not normalized_evidence:
        return False
    return normalized_evidence in normalize_for_evidence(source_text)


def wrap_untrusted(tag: str, content: str) -> str:
    safe_content = content.replace(f"</{tag}>", f"＜/{tag}＞")
    safe_content = safe_content.replace(f"<{tag}>", f"＜{tag}＞")
    return f"<{tag}>\n{safe_content}\n</{tag}>"

