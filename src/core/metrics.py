"""
src/core/metrics.py — nhật ký ai_metrics_log: đo chất lượng từng lượt Brain.

VÌ SAO CẦN (bug #6 ARCHITECTURE §11.5: "không đo được cải tiến nào có tác dụng")
--------------------------------------------------------------------------------
Mọi thay đổi cho tới nay — đổi router, bật guided decoding, fine-tune v3 — đều
được đánh giá bằng cảm nhận. Không có số thì không biết bản mới tốt hơn hay chỉ
khác đi. File này ghi lại mỗi lượt: nhánh nào, mất bao lâu, có phải hỏi lại
không, có sinh được workflow hợp lệ không.

NGUỒN DATA FINE-TUNE VÒNG SAU
-----------------------------
Log này còn là nguồn dữ liệu thật quý nhất: câu hỏi CỦA KHÁCH THẬT kèm kết quả.
Vòng fine-tune sau lấy từ đây thay vì tiếp tục sinh giả lập.

BẢO MẬT (P2 + R2b)
------------------
- Nội dung tin nhắn chỉ ghi khi bật `AI_METRICS_LOG_CONTENT=1` (mặc định TẮT).
  Mặc định chỉ ghi metadata: độ dài, nhánh, thời gian, cờ thành công.
- Không bao giờ ghi khối `internal` của báo giá (biên lợi nhuận).
- Ghi lỗi KHÔNG BAO GIỜ làm hỏng request — mọi ngoại lệ bị nuốt có log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("projecta.metrics")

# Bật ghi nội dung tin nhắn (mặc định TẮT — nội dung là dữ liệu khách, P2).
LOG_CONTENT = os.getenv("AI_METRICS_LOG_CONTENT", "0") == "1"
# Đường ghi mặc định: file JSONL cạnh dữ liệu. Đặt rỗng để tắt hẳn.
METRICS_PATH = os.getenv(
    "AI_METRICS_PATH",
    str(Path(__file__).resolve().parents[2] / "src" / "data" / "ai_metrics_log.jsonl"),
)

_write_lock = threading.Lock()

# Trường KHÔNG BAO GIỜ được ghi, kể cả khi LOG_CONTENT=1 (P2: bí mật kinh doanh)
_FORBIDDEN_KEYS = {"internal", "margin", "base_margin_pct", "carrier_cost",
                   "min_margin_amount", "pricing_rule"}

_SECRET_RE = re.compile(
    r"(postgres(?:ql)?://\S+|npg_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})"
)


def _redact(value: Any) -> Any:
    """Bỏ trường cấm và che secret trước khi ghi."""
    if isinstance(value, dict):
        return {
            k: ("[ĐÃ ẨN]" if k in _FORBIDDEN_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_RE.sub("[SECRET]", value)
    return value


@dataclass
class TurnMetric:
    """Một lượt Brain xử lý. Đặt tên trường khớp cột bảng `ai_metrics_log`."""
    request_id: str
    route: str
    ok: bool
    latency_ms: int
    user_id: Optional[int] = None
    store_id: Optional[int] = None
    router_score: Optional[float] = None
    router_margin: Optional[float] = None
    router_method: Optional[str] = None
    message_chars: int = 0
    answer_chars: int = 0
    history_turns: int = 0
    # Cờ theo nhánh — cái nào không áp dụng thì để None
    asked_back: Optional[bool] = None        # có phải hỏi lại người dùng không
    workflow_valid: Optional[bool] = None    # TECHNICAL: sinh được JSON hợp lệ
    workflow_retried: Optional[bool] = None  # TECHNICAL: có phải retry không
    tool_calls: Optional[int] = None         # vòng agentic: số tool đã gọi
    # Chốt chặn neo số liệu đã chặn câu trả lời vì lý do gì ("bịa số" /
    # "lộ nội bộ"). Đếm được cái này mới biết model bịa bao nhiêu LÚC CHẠY THẬT
    # — trước đây chỉ biết con số lúc benchmark, trên tập eval 27 câu.
    blocked_reason: Optional[str] = None
    error: Optional[str] = None
    extra: dict = field(default_factory=dict)
    ts: str = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(metric: TurnMetric) -> None:
    """
    Ghi một lượt. KHÔNG BAO GIỜ raise — đo đạc hỏng không được làm hỏng
    nghiệp vụ.
    """
    if not METRICS_PATH:
        return
    try:
        row = asdict(metric)
        row["extra"] = _redact(row.get("extra") or {})
        if not LOG_CONTENT:
            row.pop("message", None)
        path = Path(METRICS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _write_lock:            # nhiều worker cùng ghi một file
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as exc:
        logger.warning("Không ghi được ai_metrics_log: %s", exc)


class Timer:
    """
    Đo độ trễ một lượt:

        with Timer() as t:
            ...
        record(TurnMetric(..., latency_ms=t.ms))
    """

    def __enter__(self):
        self._t0 = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc_info):
        self.ms = int((time.perf_counter() - self._t0) * 1000)
        return False


def summarize(path: str | None = None, limit: int = 5000) -> dict[str, Any]:
    """
    Thống kê nhanh để so sánh trước/sau một thay đổi.

    Dùng cho câu hỏi "bản mới có tốt hơn không" — thay vì cảm nhận.
    """
    from collections import Counter

    target = Path(path or METRICS_PATH)
    if not target.exists():
        return {"count": 0, "note": "chưa có dữ liệu đo"}

    rows = []
    for line in target.read_text(encoding="utf-8").splitlines()[-limit:]:
        if line.strip():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return {"count": 0, "note": "chưa có dữ liệu đo"}

    lat = sorted(r.get("latency_ms", 0) for r in rows)
    by_route = Counter(r.get("route", "?") for r in rows)
    n_ok = sum(1 for r in rows if r.get("ok"))
    asked = [r for r in rows if r.get("asked_back") is not None]
    wf = [r for r in rows if r.get("workflow_valid") is not None]

    return {
        "count": len(rows),
        "ok_rate": round(n_ok / len(rows), 4),
        "latency_ms": {
            "p50": lat[len(lat) // 2],
            "p95": lat[int(len(lat) * 0.95)],
            "max": lat[-1],
        },
        "by_route": dict(by_route),
        "ask_back_rate": (
            round(sum(1 for r in asked if r["asked_back"]) / len(asked), 4)
            if asked else None
        ),
        "workflow_valid_rate": (
            round(sum(1 for r in wf if r["workflow_valid"]) / len(wf), 4)
            if wf else None
        ),
    }


__all__ = ["TurnMetric", "Timer", "record", "summarize", "LOG_CONTENT", "METRICS_PATH"]
