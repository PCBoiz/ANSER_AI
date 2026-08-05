"""
src/core/tool_planner.py — CHỌN TOOL BẰNG LUẬT, không để model chọn.

VÌ SAO
------
Benchmark đo khâu "model tự chọn tool" chỉ đúng 26–33%. Nhưng nhìn kỹ thì việc
chọn tool không phải việc cần đến model: "có nên nhập thêm hàng không" luôn ứng
với `forecast_reorder`, không có ngữ cảnh nào làm nó thành tool khác. Đây là ánh
xạ từ ý định sang tên hàm — đúng thứ một bảng luật làm tốt hơn và làm được 100%.

Nên ranh giới P1 dịch thêm một nấc. Model giờ chỉ còn HAI việc:
  1. điền tham số cho tool đã được chọn sẵn   (tiếng Việt -> struct)
  2. viết câu trả lời từ kết quả tool          (struct -> tiếng Việt)
Chọn tool, chạy tool, và lấy dữ liệu đều là code tất định.

TOOL NÀO CẦN DỮ LIỆU HỆ THỐNG
-----------------------------
Chỗ này quan trọng hơn cả bảng luật. `report` cần danh sách dòng bán hàng;
`inventory_audit` cần bảng tổng hợp tồn kho. Model KHÔNG có những thứ đó — bảo
nó điền `arguments` cho `report` là mời nó bịa ra doanh thu rồi hệ thống tính
toán tử tế trên số bịa, cho ra một báo cáo sai mà trông hoàn toàn bình thường.

Vì vậy `NEEDS_SYSTEM_DATA` không phải chú thích: vòng agentic bắt buộc lấy dữ
liệu cho các tool này từ nguồn tất định, và KHÔNG chạy nếu chưa có nguồn.
"""

from __future__ import annotations

import re

# Số tiền: "3 triệu", "3.500.000đ", "500k". Có nó thì câu hỏi thuế là câu TÍNH,
# không có thì là câu TRA LUẬT — hai đường đi khác hẳn nhau.
# Ngưỡng 5 chữ số cho số trần có chủ đích: 4 chữ số là NĂM. "Báo cáo thuế năm
# 2026" mà tính 2026 thành số tiền thì câu đó bị kéo vào tool `vat` với tham số
# vô nghĩa, trong khi nó chỉ là một câu hỏi báo cáo.
_SO_TIEN = re.compile(
    r"\d[\d.,]*\s*(triệu|tri\.?|nghìn|ngàn|tỷ|ty\b|đồng|đ\b|vnd|k\b)"
    r"|\d{1,3}([.,]\d{3}){1,3}\b"
    r"|\b\d{5,}\b",
    re.IGNORECASE,
)

# Mỗi luật: (tên tool, mẫu nhận diện, có cần số tiền kèm theo không).
#
# Viết CHẶT có chủ đích. Luật bắt hụt thì câu đó đi tiếp vào nhánh cũ — vẫn trả
# lời được. Luật bắt thừa thì một câu chào hỏi bị kéo vào vòng gọi tool và trả
# về thứ chẳng liên quan. Sai kiểu thứ hai đắt hơn nhiều.
_RULES: list[tuple[str, re.Pattern[str], bool]] = [
    (
        "inventory_audit",
        re.compile(
            r"(soi|rà|rà soát|kiểm tra|kiểm|đối chiếu|audit)\s+.{0,12}(kho|tồn|sổ sách)"
            r"|tồn (kho )?âm|sai sổ sách|lệch sổ|hàng chết|hàng tồn lâu"
            r"|giá vốn.{0,15}(sai|lệch|bất thường)",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        # CỐ Ý không bắt "doanh thu"/"doanh số" trần. Hai lý do:
        #  - "hộ kinh doanh DOANH THU bao nhiêu thì phải đóng thuế" là câu hỏi
        #    LUẬT, không phải yêu cầu báo cáo.
        #  - "doanh thu hôm nay bao nhiêu" là một con số, nhánh DATA_INTERNAL
        #    trả thẳng từ DB. Kéo nó vào đây chỉ đổi một câu trả lời được thành
        #    "chưa nối được dữ liệu".
        # Ranh giới: DATA_INTERNAL lo một con số, `report` lo phân tích lãi/lỗ.
        "report",
        re.compile(
            r"báo cáo\s+(tài chính|kinh doanh|lãi|lỗ|lợi nhuận|doanh thu chi phí)"
            r"|lãi (gộp|ròng|hay lỗ)|lỗ hay lãi|lợi nhuận"
            r"|tổng kết (kinh doanh|quý|năm|tháng)"
            r"|(quý|tháng|năm|nửa năm) (này|trước|vừa rồi|qua).{0,20}(lãi|lỗ)"
            r"|mặt hàng nào (lãi|lời) nhất|tuyến nào (lỗ|lãi)"
            r"|so sánh doanh (thu|số) (quý|tháng|năm)",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        "forecast_reorder",
        re.compile(
            r"nên nhập (thêm|hàng)|có nên nhập|cần nhập thêm|đặt hàng lại|đặt thêm hàng"
            r"|dự báo (nhu cầu|bán|tiêu thụ)|tồn an toàn|điểm đặt hàng"
            r"|sắp hết hàng|bao giờ hết hàng|nhập bao nhiêu",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        "carrier_selection",
        re.compile(
            r"(nhà xe|hãng xe|đơn vị vận chuyển|nhà thầu) nào"
            r"|chọn (nhà xe|hãng xe|đơn vị vận chuyển)"
            r"|so sánh (nhà xe|hãng xe)"
            r"|nên (thuê|dùng|giao cho) (nhà xe|hãng xe|ai)",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        "vat",
        re.compile(r"thuế|vat|gtgt", re.IGNORECASE),
        True,   # phải có số tiền, nếu không thì là câu tra luật -> RETRIEVAL
    ),
]

# Thứ tự chạy cố định, KHÔNG theo thứ tự chữ trong câu hỏi. "Có nên nhập thêm
# không, tháng này lãi bao nhiêu" phải chạy `report` trước `forecast_reorder`
# giống hệt câu hỏi ngược lại — cùng một ý định thì cùng một đường đi.
_PIPELINE = ["inventory_audit", "report", "forecast_reorder", "carrier_selection", "vat"]

# Trần số tool một câu hỏi được kích hoạt. `DEFAULT_MAX_STEPS` là 4 và bước cuối
# phải dành cho việc viết câu trả lời.
MAX_PLAN = 3

# Tool -> những TRƯỜNG mà hệ thống cấp, model không được đụng vào.
#
# Không chỉ để chặn bịa dữ liệu. Nó còn quyết định hình dạng JSON Schema đưa vào
# guided decoding: `arguments` bỏ trống hoàn toàn thì model ngồi viết ra nguyên
# mảng `sales` — thứ `data_provider` vứt đi ngay sau đó. Đo được 9/19 ca chạm
# trần 2048 token vì đúng chuyện này (05/08/2026), và cắt cụt thì JSON hỏng,
# `_parse` trả None, vòng lặp gãy -> người dùng nhận "tôi chưa hoàn thành được".
#
# Nghĩa là ta bắt model bịa ra dữ liệu, rồi vứt đi, rồi hỏng vì việc bịa đó.
SYSTEM_DATA_FIELDS: dict[str, tuple[str, ...]] = {
    "report": ("sales", "expenses"),
    "inventory_audit": ("lines",),
    "forecast_reorder": ("items",),
    "carrier_selection": ("carriers", "offers"),
}

# Dẫn xuất, không viết tay lần hai (P4).
NEEDS_SYSTEM_DATA = frozenset(SYSTEM_DATA_FIELDS)


def system_data_fields(tool: str) -> tuple[str, ...]:
    """Trường do hệ thống cấp cho tool này. Rỗng = model điền toàn bộ."""
    return SYSTEM_DATA_FIELDS.get(tool, ())


def plan_tools(question: str, available: list[str] | None = None) -> list[str]:
    """
    Danh sách tool cần chạy, theo thứ tự. Rỗng = không luật nào khớp.

    `available` (thường là tên tool trong manifest) lọc bỏ tool chưa tồn tại —
    bảng luật không được phép nhắc tới một tool đã bị gỡ khỏi manifest (P4).
    """
    q = (question or "").strip()
    if not q:
        return []

    co_so_tien = bool(_SO_TIEN.search(q))
    khop = {
        tool
        for tool, mau, can_so in _RULES
        if mau.search(q) and (co_so_tien or not can_so)
    }
    if available is not None:
        khop &= set(available)

    return [t for t in _PIPELINE if t in khop][:MAX_PLAN]


def needs_system_data(tool: str) -> bool:
    """Tool này có cần dữ liệu từ hệ thống thay vì từ lời người dùng không?"""
    return tool in NEEDS_SYSTEM_DATA


__all__ = [
    "plan_tools",
    "needs_system_data",
    "system_data_fields",
    "NEEDS_SYSTEM_DATA",
    "SYSTEM_DATA_FIELDS",
    "MAX_PLAN",
]
