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

# Câu SOÁT HOÁ ĐƠN: "hoá đơn/invoice" đứng gần một động từ soát (kiểm, soát,
# đối chiếu, xác minh) hoặc cụm nghi vấn ("hợp lệ", "có đúng", "có khớp").
#
# Không nằm trong `_RULES` vì nó không chỉ CHỌN tool mà còn PHỦ QUYẾT tool khác:
# hoá đơn dán kèm (OCR/VLM đọc ra) hay chứa "kho"/"tồn" trong TÊN DÒNG HÀNG
# ("phí kiểm đếm, lưu kho bãi"…) làm luật `inventory_audit` khớp nhầm — sự cố
# benchmark T4 (23/08/2026): người dùng hỏi soát hoá đơn mà nhận "chưa có bảng
# tồn kho". Bảng `_RULES` chỉ biết cộng thêm tool, không biết gạt tool, nên
# luật này sống riêng và được `plan_tools` áp SAU khi quét bảng.
#
# Cửa sổ 0-60 ký tự vì giữa "hoá đơn" và động từ thường chen vài mệnh đề
# ("hóa đơn sau, hãy kiểm tra tính hợp lệ"); DOTALL vì nội dung hoá đơn dán
# kèm hay có xuống dòng.
#
# MỘT MÌNH mẫu này KHÔNG đủ để phủ quyết hay cộng `vat` — nó khớp cả những câu
# soi KHO THẬT có nhắc hoá đơn bằng lời ("kiểm kê kho, đối chiếu với hóa đơn
# nhập hàng"). Điều kiện đủ nằm ở `la_cau_soat_hoa_don`: phải kèm DẤU HIỆU
# hoá đơn dán kèm — đúng đặc trưng của sự cố T4.
_HOA_DON_KIEM = re.compile(
    r"(kiểm|soát|đối chiếu|xác minh|validate|verify)"
    r".{0,60}(hoá đơn|hóa đơn|invoice)"
    r"|(hoá đơn|hóa đơn|invoice).{0,60}"
    r"(kiểm|soát|đối chiếu|xác minh|hợp lệ|có đúng|có khớp|validate|verify)",
    re.IGNORECASE | re.DOTALL,
)

# Dấu hiệu NỘI DUNG HOÁ ĐƠN DÁN KÈM (JSON do OCR/VLM đọc ra, hoặc bảng số
# liệu chép vào): ngoặc nhọn, hoặc tên trường quen thuộc của payload hoá đơn.
# Câu gõ tay bằng lời không chứa những thứ này.
_TU_KHOA_DAN_KEM = re.compile(
    r"[{}]|\b(items|total_amount|unit_price|subtotal)\b",
    re.IGNORECASE,
)

# Khối ngoặc nhọn = phần dán kèm tách được về mặt cấu trúc. Dùng để hỏi "bỏ
# phần dán kèm đi thì câu còn đòi soi kho không". Greedy `.*` cố ý: lấy từ
# '{' đầu đến '}' cuối, vì JSON hoá đơn lồng nhiều tầng ngoặc; nhánh hai vớt
# JSON bị cắt cụt (có mở không có đóng). Thay bằng MỘT khoảng trắng chứ không
# xoá trắng để hai vế câu không bị dính chữ vào nhau tạo match giả.
_KHOI_NGOAC = re.compile(r"\{.*\}|\{.*$", re.DOTALL)


def _co_dau_hieu_dan_kem(cau: str) -> bool:
    """
    Câu có mang theo NỘI DUNG hoá đơn (dán kèm) hay chỉ NHẮC hoá đơn bằng lời?

    Ba dấu hiệu, khớp một là đủ:
      1. ngoặc nhọn / tên trường JSON quen thuộc — VLM đọc hoá đơn ra JSON;
      2. >= 2 số tiền — bảng dòng hàng chép tay cũng có đơn giá lẫn tổng;
      3. dấu hai chấm dẫn vào phần có số tiền ("giúp tôi: tổng 3.500.000đ…")
         — cách người dùng chép số liệu của MỘT tờ hoá đơn cụ thể vào câu.
    Câu chỉ có MỘT số tiền trần và không dẫn nội dung ("kiểm tra hóa đơn tổng
    250 triệu có khớp sổ sách không") là câu hỏi thủ tục/đối chiếu sổ — không
    có dòng hàng nào để tính lại, cộng `vat` chỉ ép model bịa items=[] rồi ra
    "lệch 250 triệu" (sự cố nêu ở phản biện 23/08/2026).
    """
    if _TU_KHOA_DAN_KEM.search(cau):
        return True
    if sum(1 for _ in _SO_TIEN.finditer(cau)) >= 2:
        return True
    _truoc, hai_cham, sau = cau.partition(":")
    return bool(hai_cham) and bool(_SO_TIEN.search(sau))


def la_cau_soat_hoa_don(cau: str) -> bool:
    """
    Câu là Ý ĐỊNH SOÁT MỘT TỜ HOÁ ĐƠN CỤ THỂ (có dấu hiệu nội dung dán kèm)?

    Đây là hợp đồng công khai cho tầng trên: `src/api/routes/chat.py` import
    hàm này để rẽ nhánh câu soát hoá đơn. Điều kiện của nó ĐÚNG BẰNG điều kiện
    `plan_tools` cộng tool `vat` theo đường hoá đơn — hai nơi không được lệch
    nhau, nên cùng gọi một hàm.

    True  = có ý định soát (`_HOA_DON_KIEM`) VÀ có nội dung dán kèm
            (`_co_dau_hieu_dan_kem`) — có gì đó để tính lại thật.
    False = câu chỉ nhắc hoá đơn bằng lời (soi kho thật, hỏi thủ tục…) —
            đi đường cũ, không phủ quyết tool nào.
    """
    q = (cau or "").strip()
    return bool(q) and bool(_HOA_DON_KIEM.search(q)) and _co_dau_hieu_dan_kem(q)

# Mẫu SOI KHO tách ra thành hằng riêng vì được dùng ở HAI chỗ: trong `_RULES`
# (chọn tool) và trong `plan_tools` (kiểm lại trên phần câu ĐÃ BỎ khối dán kèm
# — xem chú thích phủ quyết ở đó). Hai chỗ phải cùng một mẫu, viết hai lần thì
# trôi nhau (P4).
_MAU_SOI_KHO = re.compile(
    r"(soi|rà|rà soát|kiểm tra|kiểm|đối chiếu|audit)\s+.{0,12}(kho|tồn|sổ sách)"
    r"|tồn (kho )?âm|sai sổ sách|lệch sổ|hàng chết|hàng tồn lâu"
    r"|giá vốn.{0,15}(sai|lệch|bất thường)",
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
        _MAU_SOI_KHO,
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
        # CỐ Ý không bắt "công nợ" trần — cùng lý do với `report` và "doanh thu".
        # "quy định CÔNG NỢ thanh toán bao nhiêu ngày" và "chính sách CÔNG NỢ bên
        # mình" là câu tra TÀI LIỆU NỘI BỘ, không phải yêu cầu phân tích số dư.
        # Kéo chúng vào đây thì câu trả lời đúng ("30 ngày, theo quy định đã nạp")
        # bị thay bằng "tôi chưa có danh sách công nợ" — đổi một câu trả lời được
        # thành một câu từ chối.
        "partner_audit",
        re.compile(
            r"(soi|rà soát|rà|kiểm tra|kiểm|đối chiếu|phân tích|thống kê|tổng hợp)"
            r"\s+\S{0,15}\s*(công nợ|phải thu|phải trả)"
            r"|tổng (công nợ|phải thu|phải trả)"
            r"|(công nợ|phải thu|phải trả)\s+(hiện (tại|nay|giờ)|bây giờ|đang|còn lại)"
            r"|(công nợ|phải thu|phải trả) (là )?bao nhiêu"
            r"|khách (hàng )?nào (còn |đang )?nợ|ai (đang |còn )?nợ (mình|em|tôi|công ty)"
            r"|nợ (quá hạn|khó đòi|lâu (chưa|không) trả)"
            r"|thu hồi (công )?nợ|đòi nợ|khách nào nợ nhiều"
            r"|dư nợ (của |khách)|vốn lưu động"
            r"|(mã số thuế|mst)\s+\S{0,10}\s*(sai|trùng|không hợp lệ|kiểm)",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        # Đặt TRƯỚC `vat` và viết chặt hơn hẳn: đây là câu về DANH MỤC hàng hoá
        # ("mặt hàng nào 8%"), còn `vat` là tính thuế trên một số tiền cụ thể.
        # Hai luật cùng khớp thì không sao — `_PIPELINE` cho cả hai chạy, và
        # chúng trả lời hai nửa khác nhau của cùng một câu hỏi.
        #
        # Mọi nhánh đều buộc phải có TỪ CHỈ HÀNG HOÁ. Thiếu ràng buộc đó thì
        # "doanh nghiệp nhỏ có được giảm thuế không" — một câu tra luật — bị kéo
        # vào tool đối chiếu danh mục.
        "vat_catalog_audit",
        re.compile(
            r"(thuế suất|thuế gtgt|vat)"
            r".{0,25}(mặt hàng|hàng hoá|hàng hóa|danh mục|mã hàng|sản phẩm)"
            r"|(mặt hàng|hàng hoá|hàng hóa|dầu nhớt|dầu nhờn|mã hàng|sản phẩm)"
            r".{0,30}(được giảm|mấy phần trăm|bao nhiêu phần trăm|8%|10%)"
            r"|8% hay 10%|10% hay 8%"
            r"|gắn cờ thuế|cờ thuế|áp (sai |nhầm )?thuế suất"
            r"|(soi|rà soát|rà|kiểm tra|đối chiếu).{0,15}(thuế suất|cờ thuế)",
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
_PIPELINE = ["inventory_audit", "partner_audit", "vat_catalog_audit", "report",
             "forecast_reorder", "carrier_selection", "vat"]

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
    "partner_audit": ("customers", "suppliers"),
    "vat_catalog_audit": ("products",),
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
    # Soát hoá đơn CÓ NỘI DUNG DÁN KÈM là ý định về MỘT tờ hoá đơn — cộng
    # `vat` và gạt `inventory_audit` (mẫu kho khớp nhờ chữ "kho"/"tồn" trong
    # TÊN DÒNG HÀNG của hoá đơn, không phải nhờ một yêu cầu soi kho — sự cố
    # T4). Gạt hẳn thay vì chỉ xếp `vat` lên trước: còn nằm trong kế hoạch thì
    # vòng agentic vẫn chạm "chưa có bảng tồn kho" và câu đó vẫn đến tay người
    # dùng.
    #
    # Điều kiện là `la_cau_soat_hoa_don` chứ KHÔNG phải `_HOA_DON_KIEM` trần:
    # mẫu trần phủ quyết cả câu soi KHO THẬT có nhắc hoá đơn bằng lời ("kiểm kê
    # kho, đối chiếu với hóa đơn nhập hàng" từng ra [] thay vì inventory_audit
    # — phản biện 23/08/2026). Không có dấu hiệu dán kèm thì không có gì để
    # tính lại, câu đi đường cũ nguyên vẹn.
    if la_cau_soat_hoa_don(q):
        khop.add("vat")
        # CÂU GHÉP "soát hoá đơn <JSON> và rà soát sổ tồn kho": vế kho là yêu
        # cầu THẬT, không được nuốt. Chỉ phân xử được khi phần dán kèm tách ra
        # được về cấu trúc (có ngoặc nhọn): bỏ khối ngoặc đi mà câu VẪN đòi soi
        # kho thì giữ inventory_audit. Không có ngoặc thì không tách nổi trong/
        # ngoài — ưu tiên chống T4, phủ quyết (lựa chọn có chủ đích, có test
        # ghi nhận trong tests/test_tool_planner.py).
        van_doi_soi_kho = "{" in q and _MAU_SOI_KHO.search(_KHOI_NGOAC.sub(" ", q))
        if not van_doi_soi_kho:
            khop.discard("inventory_audit")

    if available is not None:
        khop &= set(available)

    return [t for t in _PIPELINE if t in khop][:MAX_PLAN]


def needs_system_data(tool: str) -> bool:
    """Tool này có cần dữ liệu từ hệ thống thay vì từ lời người dùng không?"""
    return tool in NEEDS_SYSTEM_DATA


__all__ = [
    "la_cau_soat_hoa_don",
    "plan_tools",
    "needs_system_data",
    "system_data_fields",
    "NEEDS_SYSTEM_DATA",
    "SYSTEM_DATA_FIELDS",
    "MAX_PLAN",
]
