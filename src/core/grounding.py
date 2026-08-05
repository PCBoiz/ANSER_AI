"""
src/core/grounding.py — chốt chặn NEO SỐ LIỆU. Code thuần, không LLM (P1).

VÌ SAO CÓ FILE NÀY
------------------
Phép kiểm "mọi con số trong câu trả lời phải có trong dữ liệu" đã tồn tại từ lâu
ở `offline_training/dgen_common.py`, và nó chạy ở HAI chỗ:

  - lọc dữ liệu huấn luyện (`make_narration_pairs.verify_answer`)
  - chấm điểm benchmark (`benchmark_v3.score_narration`)

Nhưng KHÔNG chạy ở chỗ thứ ba, chỗ quan trọng nhất: **lúc phục vụ người dùng**.
Nghĩa là ta biết rõ model bịa số bao nhiêu phần trăm, và vẫn để nguyên con số bịa
đó đi thẳng ra màn hình chủ doanh nghiệp (05/08/2026).

Buổi đo cho thấy bản fine-tune bịa số ở 8-10 ca trên 27. Nhưng model không cần
giỏi hơn để dùng được: **hệ thống chỉ cần an toàn khi model sai.** Câu trả lời
chứa con số không có trong dữ liệu thì bị TỪ CHỐI, không phải sửa.

Đặt ở `src/core/` vì đây là tầng nghiệp vụ thuần — `offline_training/` giờ import
ngược vào đây, để phép kiểm lúc đo và phép kiểm lúc chạy là MỘT (P4). Hai bản
chép tay sẽ trôi khỏi nhau, và khi đó điểm benchmark không còn nói gì về thực tế.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("projecta.grounding")

_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")

# Từ CẤM trong nội dung soạn cho KHÁCH CUỐI (P2: biên là bí mật kinh doanh).
# So word-boundary CÓ DẤU — bỏ dấu sẽ khiến "lãi" khớp nhầm "lại".
_CUSTOMER_FORBIDDEN_RE = re.compile(
    r"\b(biên|margin|lãi|giá gốc|giá nhà xe|carrier_cost|internal)\b",
    re.IGNORECASE,
)

# Số ngắn (<4 chữ số) bỏ qua: phần trăm, số chuyến, ngày trong tháng, số tấn.
# Loại chúng đi sẽ chặn oan gần hết câu trả lời bình thường.
MIN_DIGITS = 4


def numbers_in(text: str) -> set[str]:
    """Tập các con số đã bỏ dấu phân tách nghìn: '3.450.000đ' -> '3450000'."""
    return {
        m.group(0).replace(".", "").replace(",", "")
        for m in _NUM_RE.finditer(text or "")
    }


def narration_numbers_ok(answer: str, context: str, min_digits: int = MIN_DIGITS):
    """
    Mọi con số >= `min_digits` chữ số trong `answer` PHẢI có trong `context`.

    Trả `(ok, con_số_vi_phạm | None)`.
    """
    ctx_numbers = numbers_in(context)
    for token in numbers_in(answer):
        if len(token) >= min_digits and token not in ctx_numbers:
            return False, token
    return True, None


def customer_leak(answer: str) -> list[str]:
    """Các từ lộ thông tin nội bộ tìm thấy trong nội dung gửi khách cuối."""
    return _CUSTOMER_FORBIDDEN_RE.findall(answer or "")


@dataclass
class GuardVerdict:
    """
    Kết quả soát một câu trả lời trước khi cho ra ngoài.

    `safe_answer` LUÔN dùng được: bằng chính câu model viết khi sạch, hoặc bằng
    lời từ chối khi bẩn. Chỗ gọi không phải nhớ kiểm `ok` mới biết dùng gì —
    quên kiểm là đúng cái lỗi lớp này sinh ra để chặn.
    """
    ok: bool
    safe_answer: str
    reason: str = ""
    offending: str = ""

    @property
    def blocked(self) -> bool:
        return not self.ok


_LOI_TU_CHOI_SO = (
    "Tôi chưa trả lời được câu này một cách chắc chắn.\n\n"
    "Bản nháp vừa tạo có con số {so} không tìm thấy trong dữ liệu, nên tôi đã "
    "chặn lại thay vì đưa ra một câu trả lời nghe hợp lý mà sai. "
    "Bạn xem số liệu gốc bên dưới, hoặc hỏi lại cụ thể hơn."
)

_LOI_TU_CHOI_LO = (
    "Nội dung này gửi cho khách hàng nên tôi đã chặn lại: bản nháp có nhắc tới "
    "{tu} — đó là thông tin nội bộ."
)


def guard_answer(answer: str, context: str, *, for_customer: bool = False) -> GuardVerdict:
    """
    Soát câu trả lời do model viết TRƯỚC KHI cho ra ngoài.

    Hai phép kiểm, cùng một nguyên tắc: thà không trả lời còn hơn trả lời sai mà
    nghe xuôi tai. Con số bịa trong một báo cáo tài chính không lộ ra cho tới
    lúc quyết toán.

    `for_customer=True` bật thêm lớp chặn lộ biên lợi nhuận — dùng cho nội dung
    soạn để gửi thẳng khách hàng cuối.
    """
    if not (answer or "").strip():
        return GuardVerdict(False, "Tôi chưa tạo được câu trả lời cho câu này.",
                            reason="rỗng")

    ok, bad = narration_numbers_ok(answer, context)
    if not ok:
        logger.warning("Chặn câu trả lời: bịa số %s", bad)
        return GuardVerdict(False, _LOI_TU_CHOI_SO.format(so=bad),
                            reason="bịa số", offending=str(bad))

    if for_customer and (leaks := customer_leak(answer)):
        logger.warning("Chặn câu trả lời gửi khách: lộ %s", leaks)
        return GuardVerdict(False, _LOI_TU_CHOI_LO.format(tu=", ".join(sorted(set(leaks)))),
                            reason="lộ nội bộ", offending=", ".join(sorted(set(leaks))))

    return GuardVerdict(True, answer)


__all__ = [
    "GuardVerdict",
    "customer_leak",
    "guard_answer",
    "narration_numbers_ok",
    "numbers_in",
]
