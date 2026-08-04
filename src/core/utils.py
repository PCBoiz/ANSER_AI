import json
from typing import Any, Optional

import httpx


class HttpClientPool:
    # Optional: `None` là trạng thái hợp lệ (chưa mở, hoặc đã đóng) — khai
    # `httpx.AsyncClient = None` là nói dối kiểu, mypy bắt đúng.
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client and not cls._client.is_closed:
            await cls._client.aclose()
            cls._client = None


def extract_json_block(text: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Tách object JSON đầu tiên trong text bằng cách đếm ngoặc.

    Trả `(dict, None)` nếu hợp lệ, hoặc `(None, lý_do_lỗi)`. Đếm ngoặc chứ không
    dùng regex vì workflow JSON lồng nhiều tầng, và regex không đếm được độ sâu.

    CHUYỂN TỪ `src/api/routes/chat.py` SANG ĐÂY (03/08/2026)
    -------------------------------------------------------
    Hàm này là hàm THUẦN — đếm ngoặc trên một chuỗi, không biết gì về HTTP. Nhưng
    nó nằm trong module route, nên `agents/agentic.py` phải import ngược lên
    `src.api.routes.chat` — và phải đặt import đó trong thân hàm.

    Một module tầng điều phối kéo ngược tầng HTTP vào, chỉ để dùng một hàm cắt
    chuỗi. Import đặt trong thân hàm nên né được vòng lặp import lúc nạp module
    và KHÔNG AI THẤY GÌ — phát hiện khi đối chiếu sơ đồ vẽ tay với bản đồ Grapuco
    sinh tự động.

    `chat.py` giữ một alias để 5 chỗ gọi cũ trong đó không phải sửa.
    """
    if not text:
        return None, "empty output"

    start = text.find("{")
    if start == -1:
        return None, "no JSON object found"

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate), None
                except json.JSONDecodeError as exc:
                    # Thử json_repair cho lỗi nhẹ (dấu phẩy thừa...)
                    try:
                        from json_repair import repair_json
                        repaired: Any = repair_json(candidate, return_objects=True)
                        if isinstance(repaired, dict) and repaired:
                            return repaired, None
                    except Exception:
                        pass
                    return None, f"JSONDecodeError: {exc.msg} tại vị trí {exc.pos}"

    return None, "unbalanced braces (thiếu dấu })"
