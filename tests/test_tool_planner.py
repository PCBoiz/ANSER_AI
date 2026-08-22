"""
tests/test_tool_planner.py — bảng luật chọn tool.

Đây là thứ THAY THẾ việc model tự chọn tool (đo được 26-33%). Nếu bảng luật này
sai thì cái thay thế còn tệ hơn cái bị thay, nên mỗi luật phải có ít nhất một ca
khớp và một ca KHÔNG được khớp.
"""

from src.core.tool_planner import (
    MAX_PLAN,
    NEEDS_SYSTEM_DATA,
    la_cau_soat_hoa_don,
    needs_system_data,
    plan_tools,
)

TAT_CA = ["quote", "carrier_selection", "forecast_reorder", "vat", "report",
          "inventory_audit", "partner_audit", "vat_catalog_audit"]


def ke_hoach(cau: str) -> list[str]:
    return plan_tools(cau, TAT_CA)


# --------------------------------------------------------------------------
# Câu nhiều bước — lý do vòng agentic tồn tại
# --------------------------------------------------------------------------

def test_cau_nhieu_buoc_ra_nhieu_tool():
    assert ke_hoach(
        "tháng này lãi bao nhiêu, mặt hàng nào lãi nhất, có nên nhập thêm không"
    ) == ["report", "forecast_reorder"]


def test_thu_tu_khong_phu_thuoc_thu_tu_chu_trong_cau():
    """Cùng một ý định thì cùng một đường đi, dù người dùng nói ngược lại."""
    xuoi = ke_hoach("tháng này lãi bao nhiêu, có nên nhập thêm hàng không")
    nguoc = ke_hoach("có nên nhập thêm hàng không, mà tháng này lãi bao nhiêu")
    assert xuoi == nguoc == ["report", "forecast_reorder"]


def test_tran_so_tool():
    cau = ("rà soát tồn kho giúp tôi, quý này lãi hay lỗ, có nên nhập thêm không, "
           "nhà xe nào rẻ nhất, tiền thuế 5 triệu là bao nhiêu")
    assert len(ke_hoach(cau)) == MAX_PLAN


# --------------------------------------------------------------------------
# vat — phân biệt câu TÍNH với câu TRA LUẬT
# --------------------------------------------------------------------------

def test_cau_tinh_thue_co_so_tien_ra_tool_vat():
    assert ke_hoach("bán 10 triệu thì tiền thuế phải nộp là bao nhiêu") == ["vat"]
    assert "vat" in ke_hoach("đơn hàng 3.500.000đ thuế GTGT 8% thì tổng bao nhiêu")


def test_cau_tra_luat_khong_ra_tool():
    """Không có số tiền -> đây là câu hỏi văn bản, thuộc về RAG chứ không phải tool."""
    assert ke_hoach("nghị định 72 quy định thuế suất bao nhiêu") == []
    assert ke_hoach("hộ kinh doanh doanh thu bao nhiêu thì phải đóng thuế") == []


def test_nam_khong_bi_tinh_la_so_tien():
    """
    "2026" là NĂM. Tính nó thành tiền thì câu tổng kết bị kéo thêm tool `vat`
    với tham số vô nghĩa.
    """
    assert ke_hoach("tổng kết kinh doanh năm 2026 và thuế đã nộp") == ["report"]


def test_hoi_mot_con_so_van_thuoc_ve_nhanh_du_lieu():
    """
    "Doanh thu hôm nay bao nhiêu" là MỘT con số, DATA_INTERNAL trả thẳng từ DB.
    Kéo vào vòng agentic chỉ đổi một câu trả lời được thành "chưa nối dữ liệu".
    """
    assert ke_hoach("doanh thu hôm nay là bao nhiêu") == []
    assert ke_hoach("hôm nay bán được mấy đơn") == []


# --------------------------------------------------------------------------
# vat — câu SOÁT HOÁ ĐƠN không được rơi vào inventory_audit (sự cố T4, 23/08)
# --------------------------------------------------------------------------

# Câu T4 nguyên bản: hoá đơn do VLM đọc ra, dán kèm dạng JSON. Chữ "kiểm" và
# "kho" trong TÊN DÒNG HÀNG ("Phí kiểm đếm, lưu kho bãi") từng làm mẫu
# `inventory_audit` khớp nhầm — dữ liệu bên trong hoá đơn bị đọc thành ý định.
CAU_HOA_DON_T4 = (
    'Qwen2-VL đọc được hóa đơn sau, hãy kiểm tra tính hợp lệ: '
    '{"items": [{"name": "Phí kiểm đếm, lưu kho bãi", "price": 500000, '
    '"qty": 2}, {"name": "Cước vận chuyển HN-HP", "price": 2500000, '
    '"qty": 1}], "subtotal": 3500000, "vat_rate": 8, "total_amount": 3780000}'
)


def test_cau_soat_hoa_don_ra_vat_khong_keo_inventory_audit():
    """
    CHỌN THIẾT KẾ: ra đúng ["vat"], KHÔNG phải "vat xếp trước inventory_audit".
    Chỉ xếp lại thứ tự thì inventory_audit vẫn nằm trong kế hoạch, vòng agentic
    vẫn chạm _CHUA_CO_NGUON và "chưa có bảng tồn kho" vẫn đến tay người dùng —
    đúng triệu chứng T4. Ý định của câu là soát MỘT tờ hoá đơn; "kho" ở đây là
    tên dòng hàng, không phải yêu cầu soi kho, nên phải gạt hẳn khỏi kế hoạch.
    """
    assert ke_hoach(CAU_HOA_DON_T4) == ["vat"]


def test_cau_soat_hoa_don_khong_co_chu_vat_van_ra_vat():
    """
    "đối chiếu … có khớp không" không chứa thuế/vat/gtgt nên luật `vat` cũ
    không với tới, còn "hóa đơn lưu kho" thì khớp mẫu kho — trước khi sửa, câu
    này đi thẳng vào inventory_audit (đúng đường hỏng của T4).
    """
    assert ke_hoach(
        "đối chiếu hóa đơn lưu kho này giúp tôi: tổng 3.500.000đ có khớp không"
    ) == ["vat"]


def test_cau_soi_kho_that_van_ve_inventory_audit():
    """Luật phủ quyết chỉ đụng câu có 'hoá đơn' — soi kho thật không bị vạ lây."""
    assert ke_hoach("soi giúp tôi sổ tồn kho") == ["inventory_audit"]


def test_cau_hoi_thu_tuc_hoa_don_khong_kich_hoat_tool():
    """
    Không có số tiền thì không có gì để tính lại — câu hỏi THỦ TỤC về hoá đơn
    thuộc nhánh cũ/RAG (cùng lý do cờ `can_so` của luật `vat`), và cũng không
    được rơi vào inventory_audit.
    """
    assert ke_hoach("hóa đơn hợp lệ cần những thông tin gì") == []


# --------------------------------------------------------------------------
# Phủ quyết hoá đơn KHÔNG được vạ lây câu soi KHO THẬT (phản biện 23/08)
# --------------------------------------------------------------------------

# Bốn câu soi kho thật có NHẮC hoá đơn bằng lời — không dán kèm nội dung nào.
# Trước khi sửa, `_HOA_DON_KIEM` phủ quyết vô điều kiện làm cả bốn ra []:
# người hỏi kiểm kê kho nhận về nhánh router thay vì bảng đối chiếu tồn kho.
CAC_CAU_SOI_KHO_NHAC_HOA_DON = [
    "kiểm kê kho tháng này, đối chiếu với hóa đơn nhập hàng",
    "đối chiếu tồn kho với hóa đơn nhập tháng này",
    "rà soát kho, tiện thể xem hóa đơn nhập",
    "kiểm tra tồn kho rồi xuất hóa đơn cho khách",
]


def test_cau_soi_kho_that_nhac_hoa_don_van_ve_inventory_audit():
    """
    Chỉ NHẮC hoá đơn bằng lời (không có JSON, không có số tiền nào) thì đây là
    yêu cầu soi kho — phủ quyết chỉ dành cho câu CÓ nội dung hoá đơn dán kèm
    (đặc trưng sự cố T4), không dành cho những câu này.
    """
    for cau in CAC_CAU_SOI_KHO_NHAC_HOA_DON:
        assert ke_hoach(cau) == ["inventory_audit"], cau
        assert not la_cau_soat_hoa_don(cau), cau


def test_mot_so_tien_tran_khong_du_de_cong_vat():
    """
    Câu chỉ nêu MỖI số tổng thì không có dòng hàng nào để tính lại: cộng `vat`
    ép model điền items=[] -> calculated_total=0 -> "lệch 250 triệu" — một con
    số sai có nguồn, lọt chốt chặn neo số liệu (tái hiện 23/08/2026). Hai câu
    này phải rơi về nhánh router như câu hỏi thủ tục, KHÔNG ra vat.
    """
    for cau in [
        "kiểm tra hóa đơn tổng 250 triệu có khớp sổ sách không",
        "kiểm tra hóa đơn tổng 3.780.000đ có đúng không",
    ]:
        assert ke_hoach(cau) == [], cau
        assert not la_cau_soat_hoa_don(cau), cau


def test_cau_ghep_hoa_don_dan_kem_va_soi_kho_that_ra_ca_hai():
    """
    CHỌN THIẾT KẾ cho câu ghép: vế kho nằm NGOÀI khối JSON dán kèm là yêu cầu
    thật, không được nuốt. Khi phần dán kèm tách được về cấu trúc (ngoặc nhọn),
    planner bỏ khối ngoặc rồi kiểm lại mẫu soi kho trên phần còn lại — vẫn đòi
    soi kho thì giữ inventory_audit bên cạnh vat. (Không có ngoặc thì không
    tách nổi trong/ngoài, ưu tiên chống T4 — xem test T4 ngay trên.)
    """
    cau = (
        'kiểm tra hóa đơn {"items": [{"name": "Phí kiểm đếm, lưu kho bãi", '
        '"price": 500000, "qty": 2}], "total_amount": 1080000} '
        "và rà soát luôn sổ tồn kho tháng này"
    )
    assert ke_hoach(cau) == ["inventory_audit", "vat"]
    assert la_cau_soat_hoa_don(cau)


def test_hop_dong_la_cau_soat_hoa_don_cho_tang_tren():
    """
    `chat.py` import hàm này để rẽ nhánh — điều kiện của nó phải ĐÚNG BẰNG
    điều kiện planner cộng `vat` theo đường hoá đơn, nếu không hai tầng nhìn
    cùng một câu ra hai ý định khác nhau.
    """
    # Có ý định soát + có nội dung dán kèm -> True, và kế hoạch có vat.
    assert la_cau_soat_hoa_don(CAU_HOA_DON_T4)
    assert "vat" in ke_hoach(CAU_HOA_DON_T4)
    cau_hai_cham = "đối chiếu hóa đơn lưu kho này giúp tôi: tổng 3.500.000đ có khớp không"
    assert la_cau_soat_hoa_don(cau_hai_cham)
    assert "vat" in ke_hoach(cau_hai_cham)

    # Thiếu một trong hai vế -> False.
    assert not la_cau_soat_hoa_don("hóa đơn hợp lệ cần những thông tin gì")  # không dán kèm
    assert not la_cau_soat_hoa_don('{"items": [], "total_amount": 500000}')  # không có ý soát
    assert not la_cau_soat_hoa_don("")
    assert not la_cau_soat_hoa_don("soi giúp tôi sổ tồn kho")


# --------------------------------------------------------------------------
# Không khớp — quan trọng ngang khớp đúng
# --------------------------------------------------------------------------

def test_cau_chao_hoi_khong_kich_hoat_gi():
    for cau in ["xin chào", "cảm ơn bạn nhiều", "bạn làm được những gì",
                "tôi nên bắt đầu từ đâu", ""]:
        assert ke_hoach(cau) == [], cau


def test_cau_bao_gia_van_tai_khong_bi_keo_vao():
    """LOGISTICS có luồng struct riêng — bảng luật không được giành lấy."""
    assert ke_hoach("báo giá xe 5 tấn từ Hà Nội đi Hải Phòng") == []


# --------------------------------------------------------------------------
# Lọc theo manifest (P4)
# --------------------------------------------------------------------------

def test_loc_theo_tool_co_that():
    """Tool bị gỡ khỏi manifest thì bảng luật không được nhắc tới nữa."""
    assert plan_tools("quý này lãi hay lỗ", ["vat"]) == []
    assert plan_tools("quý này lãi hay lỗ", ["report", "vat"]) == ["report"]


def test_khong_truyen_available_thi_khong_loc():
    assert plan_tools("quý này lãi hay lỗ") == ["report"]


# --------------------------------------------------------------------------
# Tool nào cần dữ liệu hệ thống
# --------------------------------------------------------------------------

def test_tool_can_du_lieu_he_thong():
    assert needs_system_data("report")
    assert needs_system_data("inventory_audit")
    assert needs_system_data("partner_audit")
    assert needs_system_data("vat_catalog_audit")
    # `vat` suy được từ chính lời người dùng nên KHÔNG cần bơm dữ liệu.
    assert not needs_system_data("vat")


# --------------------------------------------------------------------------
# partner_audit — phân biệt câu PHÂN TÍCH SỐ DƯ với câu TRA TÀI LIỆU
# --------------------------------------------------------------------------

def test_cau_phan_tich_cong_no_thi_khop():
    for cau in [
        "soi công nợ giúp tôi",
        "rà soát công nợ khách hàng",
        "tổng phải thu hiện tại",
        "công nợ hiện tại bao nhiêu",
        "khách nào còn nợ nhiều nhất",
        "ai đang nợ mình",
        "thu hồi công nợ thế nào",
        "vốn lưu động đang kẹt bao nhiêu",
    ]:
        assert "partner_audit" in ke_hoach(cau), cau


def test_cau_tra_TAI_LIEU_ve_cong_no_thi_KHONG_khop():
    """
    Hai câu này từng làm hỏng test định tuyến thật khi luật còn bắt 'công nợ'
    trần. Chúng hỏi về QUY ĐỊNH đã nạp trong kho tài liệu, và câu trả lời đúng
    là '30 ngày' — kéo vào tool phân tích số dư thì đổi thành 'tôi chưa có
    danh sách công nợ'.
    """
    assert ke_hoach("quy định công nợ thanh toán bao nhiêu ngày") == []
    assert ke_hoach("chính sách công nợ bên mình quy định thế nào") == []
    assert ke_hoach("quy trình đối soát công nợ của công ty là gì") == []


# --------------------------------------------------------------------------
# vat_catalog_audit — phân biệt câu về DANH MỤC với câu tra LUẬT chung
# --------------------------------------------------------------------------

def test_cau_ve_thue_suat_mat_hang_thi_khop():
    for cau in [
        "dầu nhớt được giảm thuế còn mấy phần trăm",
        "mặt hàng nào còn được giảm 8%",
        "thuế suất của mã hàng này là bao nhiêu",
        "hàng hóa bên mình 8% hay 10%",
        "gắn cờ thuế cho danh mục chưa",
        "rà soát thuế suất giúp tôi",
    ]:
        assert "vat_catalog_audit" in ke_hoach(cau), cau


def test_cau_tra_LUAT_chung_ve_thue_thi_KHONG_khop_danh_muc():
    """
    Không có từ chỉ hàng hoá thì đây là câu tra luật — thuộc về RETRIEVAL, chứ
    không phải tool đối chiếu danh mục của riêng doanh nghiệp này.
    """
    assert "vat_catalog_audit" not in ke_hoach("doanh nghiệp nhỏ có được giảm thuế không")
    assert "vat_catalog_audit" not in ke_hoach("thuế thu nhập doanh nghiệp bao nhiêu phần trăm")


def test_cau_TINH_thue_van_ve_vat_chu_khong_ve_danh_muc():
    """`vat` tính trên một số tiền; `vat_catalog_audit` tra diện thuế của mã hàng."""
    assert ke_hoach("tiền thuế của 5.000.000 đồng là bao nhiêu") == ["vat"]


def test_moi_tool_can_du_lieu_deu_co_that_trong_manifest():
    """
    Chống lệch tên. `NEEDS_SYSTEM_DATA` chặn tool chạy khi thiếu nguồn — gõ sai
    một tên ở đây là mở lại đúng cánh cửa nó sinh ra để đóng.
    """
    from src.api.routes.tools import get_tool_defs

    ten_that = {t["name"] for t in get_tool_defs()}
    assert NEEDS_SYSTEM_DATA <= ten_that
