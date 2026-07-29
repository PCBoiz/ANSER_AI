"""
dgen_common.py — helper dùng chung cho pipeline sinh dữ liệu v3.

Ba script sinh dữ liệu (extraction / narration / n8n) đều cần:
  - so khớp chuỗi tiếng Việt bỏ dấu (verify tin nhắn teacher viết ra)
  - kiểm tra "mọi con số trong câu trả lời phải có trong context" (P1:
    LLM chỉ diễn giải số do engine tính, không được bịa số)
  - đọc/ghi JSONL incremental + resume theo id (API có thể đứt giữa chừng)
  - client DeepSeek (R2b: key CHỈ từ env, đặt trong Colab Secrets)
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

# Mọi file sinh ra đều nằm đây — tách khỏi src/data (dữ liệu runtime).
#
# Đổi được bằng env (P5: đường dẫn không đóng cứng trong code). Trên Colab nên
# trỏ thẳng vào Google Drive: dữ liệu sinh ra TỐN TIỀN API và ~20 phút, để ở
# /content là mất sạch khi hết phiên.
#   export ANSER_GENERATED_DIR=/content/drive/MyDrive/ANSER_AI_Logistics/generated
GENERATED_DIR = Path(
    os.getenv("ANSER_GENERATED_DIR", "").strip() or (Path(__file__).parent / "generated")
)


# ---------------------------------------------------------------------------
# So khớp tiếng Việt
# ---------------------------------------------------------------------------

def strip_diacritics(text: str) -> str:
    """'Hải Phòng' -> 'Hai Phong'. Dùng để so khớp khi teacher viết không dấu."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D")


def fuzzy_contains(haystack: str, needle: str) -> bool:
    """Chứa chuỗi con, bỏ dấu + không phân biệt hoa thường."""
    return strip_diacritics(needle).lower() in strip_diacritics(haystack).lower()


# ---------------------------------------------------------------------------
# Kiểm tra số liệu trong lời diễn giải (P1)
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")


def numbers_in(text: str) -> set[str]:
    """Tập các con số đã bỏ dấu phân tách nghìn: '3.450.000đ' -> '3450000'."""
    return {
        m.group(0).replace(".", "").replace(",", "")
        for m in _NUM_RE.finditer(text)
    }


def narration_numbers_ok(answer: str, context: str, min_digits: int = 4):
    """
    Mọi con số >= `min_digits` chữ số trong answer PHẢI xuất hiện trong context.

    Đây là chốt chặn P1 cho dữ liệu diễn giải: teacher chỉ được diễn đạt lại
    số do engine tính, số "sáng tác" là loại. Số ngắn (<4 chữ số: %, số câu,
    ngày trong tháng) được bỏ qua để tránh loại oan.

    Trả (ok, con_số_vi_phạm | None).
    """
    ctx_numbers = numbers_in(context)
    for token in numbers_in(answer):
        if len(token) >= min_digits and token not in ctx_numbers:
            return False, token
    return True, None


# Từ CẤM trong nội dung soạn cho KHÁCH CUỐI (P2: biên là bí mật kinh doanh).
# So word-boundary CÓ DẤU — bỏ dấu sẽ khiến "lãi" khớp nhầm "lại".
_CUSTOMER_FORBIDDEN_RE = re.compile(
    r"\b(biên|margin|lãi|giá gốc|giá nhà xe|carrier_cost|internal)\b",
    re.IGNORECASE,
)


def customer_leak(answer: str) -> list[str]:
    """Các từ lộ thông tin nội bộ tìm thấy trong nội dung gửi khách cuối."""
    return _CUSTOMER_FORBIDDEN_RE.findall(answer)


# ---------------------------------------------------------------------------
# JSONL incremental + resume
# ---------------------------------------------------------------------------

def load_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: str | Path, obj: dict) -> None:
    """Ghi + flush NGAY — đứt API giữa chừng không mất entry đã xong."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()


def done_ids(path: str | Path, key: str = "_id") -> set[str]:
    """Id đã xử lý trong file output — chạy lại script tự bỏ qua (resume)."""
    return {obj[key] for obj in load_jsonl(path) if key in obj}


# ---------------------------------------------------------------------------
# DeepSeek client (chỉ dùng trong script *_generate — import lười để
# test CPU/CI không cần cài openai)
# ---------------------------------------------------------------------------

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def get_async_client():
    from openai import AsyncOpenAI  # import lười: CI không cài openai

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "DEEPSEEK_API_KEY chưa set. Trên Colab: Secrets (biểu tượng chìa "
            "khoá) -> thêm DEEPSEEK_API_KEY rồi bật notebook access. "
            "KHÔNG hardcode key vào file (AGENTS.md R2b)."
        )
    return AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
