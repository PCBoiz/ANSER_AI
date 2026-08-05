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

# Ba ham duoi day CHUYEN sang src/core/grounding.py (05/08/2026) va import
# nguoc vao day. Ly do: phep kiem "moi con so phai co trong du lieu" truoc
# day chi chay o khau SINH DU LIEU va khau DO — khong chay luc phuc vu nguoi
# dung. Nen ta biet ro model bia so bao nhieu phan tram, va van de con so bia
# do di thang ra man hinh chu doanh nghiep.
#
# Giu MOT ban duy nhat de phep kiem luc do va phep kiem luc chay khong bao gio
# troi khoi nhau (P4) — hai ban chep tay lech nhau thi diem benchmark khong
# con noi gi ve thuc te.
from src.core.grounding import (  # noqa: E402
    customer_leak as customer_leak,
)
from src.core.grounding import (  # noqa: E402
    narration_numbers_ok as narration_numbers_ok,
)
from src.core.grounding import (  # noqa: E402
    numbers_in as numbers_in,
)

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
