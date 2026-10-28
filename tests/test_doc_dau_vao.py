"""
tests/test_doc_dau_vao.py — đọc đầu vào tool từ câu người dùng bằng mã.

Ca trung tâm là lỗi đo được trên vLLM thật (BAO_CAO_BR04 §5.2): hoá đơn hai
dòng 5.000.000 + 500.000, model gửi cho `vat` đúng MỘT dòng, Brain báo "tổng
thực tế 5.500.000đ" kèm "kết quả từ công cụ VAT". Cách B phải bóc đủ hai dòng;
cách A phải bắt được dòng 500.000 bị bỏ khi B không áp dụng được.
"""

import asyncio

import pytest

from src.core.doc_dau_vao import (
    doc_so_tien,
    so_tien_bi_bo_sot,
    so_tien_khong_co_trong_cau,
    tach_hoa_don,
    tach_loi_chao,
    tham_so_chon_nha_xe,
)

HOA_DON_BR04 = (
    'Kiểm tra hoá đơn này giúp tôi: {"Cước vận chuyển HN-HP": 5000000, '
    '"Phụ phí xăng dầu": 500000}, tổng ghi 6.500.000đ có đúng không?'
)


# ---------------------------------------------------------------------------
# Đọc số tiền
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cau,mong", [
    ("12.500.000 đồng", [12_500_000]),
    ("7.450.000đ, chiết khấu", [7_450_000]),
    ("12,500,000 VND", [12_500_000]),
    ("6.500.000d", [6_500_000]),
    ("5 triệu", [5_000_000]),
    ("5,4 triệu", [5_400_000]),
    ("15tr chuyến", [15_000_000]),
    ("500k", [500_000]),
    ("1,2 tỷ", [1_200_000_000]),
    ("1.500 nghìn", [1_500_000]),
    ("28.500 đồng/lít", [28_500]),
    ("giá dầu 21.500", [21_500]),
    ('{"a": 5000000, "b": 500000}', [5_000_000, 500_000]),
])
def test_doc_duoc_cac_cach_viet_so_tien(cau, mong):
    assert doc_so_tien(cau) == mong


@pytest.mark.parametrize("cau", [
    "thuế 8%", "3 cái", "xe 5T", "xe 1.5 tấn", "năm 2026", "ngày 26/10/2026",
    "lấy hàng 20/12", "gọi 0912345678", "email lan@vietcargo247.vn", "cont 40 feet",
])
def test_khong_coi_la_so_tien(cau):
    assert doc_so_tien(cau) == []


# ---------------------------------------------------------------------------
# A — chốt neo đầu vào
# ---------------------------------------------------------------------------

def test_A_bat_dung_dong_bi_bo_cua_BR04():
    model_dien = {"items": [{"name": "Cước", "price": 5_000_000, "qty": 1}],
                  "stated_total": 6_500_000}
    assert so_tien_bi_bo_sot(HOA_DON_BR04, model_dien) == [500_000]


def test_A_khong_bao_khi_du_va_hieu_thanh_tien_cua_dong():
    cau = "Mặt hàng A 4 cái thành tiền 2.400.000 đồng, tổng ghi 2.640.000 đồng"
    args = {"items": [{"name": "A", "price": 600_000, "qty": 4}], "stated_total": 2_640_000}
    assert so_tien_bi_bo_sot(cau, args) == []


def test_A_bat_chep_sai_chu_so():
    cau = "Nhà xe chào 12.500.000 đồng, biên lợi nhuận 8%"
    args = {"carrier_cost": 1_250_000, "pricing_rule": {"base_margin_pct": 8}}
    assert so_tien_bi_bo_sot(cau, args) == [12_500_000]


@pytest.mark.parametrize("cau,mong", [
    ("năm triệu rưỡi", [5_500_000]),
    ("hai trăm nghìn", [200_000]),
    ("hai mươi lăm nghìn", [25_000]),
    ("ba trăm linh năm nghìn đồng", [305_000]),
    ("một tỷ hai trăm triệu", [1_200_000_000]),
    ("mười hai triệu rưỡi", [12_500_000]),
    ("năm triệu hai", [5_200_000]),
    ("hai triệu năm trăm", [2_500_000]),
    ("nam trieu ruoi", [5_500_000]),
    ("5 triệu rưỡi", [5_500_000]),
    ("12tr5", [12_500_000]),
    ("5 triệu 200 nghìn", [5_200_000]),
    ("Nhà xe chào 12 triệu 5, biên 8%", [12_500_000]),
    ("cước năm triệu, phụ phí năm trăm nghìn", [5_000_000, 500_000]),
])
def test_doc_so_viet_bang_chu_va_noi_tat(cau, mong):
    assert doc_so_tien(cau) == mong


@pytest.mark.parametrize("cau,mong", [
    ("năm 2026", []), ("năm nay", []), ("mười ngày", []), ("hai chuyến", []),
    ("5 triệu 2 chuyến", [5_000_000]),   # "2" là số chuyến, không phải 5,2 triệu
])
def test_so_khong_co_don_vi_tien_khong_bi_doc_nham(cau, mong):
    assert doc_so_tien(cau) == mong


def test_A_chieu_nguoc_bat_so_model_bia():
    cau = "Nhà xe chào 12.500.000 đồng, biên 8%"
    args = {"carrier_cost": 12_500_000,
            "pricing_rule": {"base_margin_pct": 8, "fuel_baseline_price": 26_500,
                             "min_margin_amount": 0}}
    assert so_tien_khong_co_trong_cau(cau, args) == [26_500]


def test_A_chieu_nguoc_chap_nhan_don_gia_tu_thanh_tien():
    cau = "Mặt hàng A 4 cái thành tiền 2.400.000 đồng, tổng ghi 2.640.000 đồng"
    args = {"items": [{"name": "A", "price": 600_000, "qty": 4}], "stated_total": 2_640_000}
    assert so_tien_khong_co_trong_cau(cau, args) == []


def test_A_chieu_nguoc_bo_qua_khoa_do_ma_dien():
    args = {"items": [{"name": "A", "price": 2_000, "qty": 1}], "stated_total": 6_500_000}
    assert so_tien_khong_co_trong_cau("tổng 6.500.000đ", args, bo_qua=("items",)) == []


@pytest.mark.parametrize("cau,mong", [
    ("giá chưa gồm VAT", "chua_gom"),
    ("chua co thue", "chua_gom"),
    ("đơn giá trước thuế", "chua_gom"),
    ("Cước: 5.000.000\nVAT: 500.000\nTổng: 5.500.000", "chua_gom"),
    ("giá đã gồm VAT", "da_gom"),
    ("đã bao gồm thuế GTGT", "da_gom"),
    ("tổng ghi 6.500.000đ có đúng không", None),
    ("thuế suất VAT: 10%", None),
    ("chưa gồm VAT, à mà đã gồm VAT rồi", None),
])
def test_co_so_thue(cau, mong):
    from src.core.doc_dau_vao import co_so_thue
    assert co_so_thue(cau) == mong


def test_noi_tra_loi_hoi_thue_chi_khi_luot_truoc_dung_la_cau_hoi_do():
    from src.core.doc_dau_vao import CAU_HOI_THUE, noi_tra_loi_hoi_thue

    ls = [{"role": "user", "content": "HOÁ ĐƠN"}, {"role": "assistant", "content": CAU_HOI_THUE}]
    assert noi_tra_loi_hoi_thue("chưa gồm VAT", ls) == "HOÁ ĐƠN\nchưa gồm VAT"
    assert noi_tra_loi_hoi_thue("xin chào", ls) is None
    assert noi_tra_loi_hoi_thue("chưa gồm VAT", ls[:1]) is None
    assert noi_tra_loi_hoi_thue("chưa gồm VAT", ls + [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "khác"}]) is None


def test_A_khong_dong_vao_phan_tram_va_ngay():
    cau = "Nhà xe chào 9.100.000 đồng ngày 26/10, biên 10%"
    assert so_tien_bi_bo_sot(cau, {"carrier_cost": 9_100_000}) == []


# ---------------------------------------------------------------------------
# B — hoá đơn dán kèm
# ---------------------------------------------------------------------------

def test_B_boc_du_hai_dong_cua_BR04():
    assert tach_hoa_don(HOA_DON_BR04) == [
        {"name": "Cước vận chuyển HN-HP", "price": 5_000_000, "qty": 1},
        {"name": "Phụ phí xăng dầu", "price": 500_000, "qty": 1},
    ]


def test_B_boc_mang_items_kieu_ocr():
    cau = ('Kiểm tra hoá đơn: {"items": [{"name": "Cước HN-HP", "quantity": 2, '
           '"unit_price": 1500000}], "total_amount": 3300000}')
    assert tach_hoa_don(cau) == [{"name": "Cước HN-HP", "price": 1_500_000, "qty": 2}]


def test_B_boc_dong_ten_so_va_bo_dong_tong():
    cau = "Cước HN-HP: 5.000.000\nPhụ phí xăng: 500.000\nTổng cộng: 6.500.000\nVAT: 650.000"
    assert tach_hoa_don(cau) == [
        {"name": "Cước HN-HP", "price": 5_000_000, "qty": 1},
        {"name": "Phụ phí xăng", "price": 500_000, "qty": 1},
    ]


@pytest.mark.parametrize("cau", [
    "Kiểm tra hoá đơn: tổng 3.500.000 có khớp sổ không",       # một dòng, không phải bảng
    "Mặt hàng A 4 cái giá 600.000 đồng, B 1 cái giá 1.950.000", # câu tự do -> để A lo
    '{"tong": 6500000}',                                         # chỉ có dòng tổng
])
def test_B_khong_nhan_ra_thi_tra_None_khong_doan(cau):
    assert tach_hoa_don(cau) is None


# ---------------------------------------------------------------------------
# Lời chào giá -> carrier_selection
# ---------------------------------------------------------------------------

def test_boc_loi_chao_dang_liet_ke_cham_phay():
    cau = ("Anh vừa nhận báo giá chuyến KCN Quế Võ đi Hà Nội xe 5T: Trường Thịnh "
           "3.100.000 đồng, chiết khấu 8%, công nợ 30 ngày; Đại An 10.700.000 đồng, "
           "chiết khấu 8%, công nợ 45 ngày.")
    assert [(x["ten"], x["gia"], x["chiet_khau_pct"], x["cong_no_ngay"])
            for x in tach_loi_chao(cau)] == [
        ("Trường Thịnh", 3_100_000, 8.0, 30), ("Đại An", 10_700_000, 8.0, 45),
    ]


def test_boc_loi_chao_dang_chao_va_tu_noi():
    cau = ("Đại An chào 9.400.000 đồng chiết khấu 5% công nợ 15 ngày, còn Trường "
           "Thịnh chào 3.450.000 đồng chiết khấu 0% công nợ 15 ngày.")
    assert [x["ten"] for x in tach_loi_chao(cau)] == ["Đại An", "Trường Thịnh"]


def test_ten_rieng_khong_bi_cat_nham():
    """"Phú Gia" không được thành "Phú"; "Bên A" giữ nguyên."""
    assert [x["ten"] for x in tach_loi_chao("Bên A chào 8tr, Phú Gia chào 7,5tr")] == [
        "Bên A", "Phú Gia",
    ]


def test_tham_so_chon_nha_xe_dung_hinh_dang_tool():
    from src.api.routes.tools import CarrierSelectionRequest

    ts = tham_so_chon_nha_xe("Anh A báo 5 triệu chiết khấu 3%, anh B báo 5,4 triệu")
    req = CarrierSelectionRequest(
        **ts, request={"origin": "HN", "destination": "HP", "vehicle_type": "5T"}
    )
    assert [c.name for c in req.carriers] == ["Anh A", "anh B"]
    assert [o.price for o in req.offers] == [5_000_000, 5_400_000]
    assert tham_so_chon_nha_xe("Đại An chào 9.400.000 đồng") is None, "một lời chào thì không so"


# ---------------------------------------------------------------------------
# Nối vào chat.py — `_provide_tool_data`
# ---------------------------------------------------------------------------

def _cung_cap(ten, args, cau):
    from src.api.routes.chat import _provide_tool_data
    return asyncio.run(_provide_tool_data(ten, args, "1", "rid", cau))


def test_vat_B_ghi_de_items_model_chep_thieu():
    args, thieu = _cung_cap("vat", {
        "items": [{"name": "Cước", "price": 5_000_000, "qty": 1}],
        "stated_total": 6_500_000,
    }, HOA_DON_BR04 + " Giá chưa gồm VAT.")
    assert thieu is None
    assert len(args["items"]) == 2, "B phải ghi đè bằng hai dòng bóc từ hoá đơn"
    assert args["prices_include_vat"] is False


def test_vat_khong_noi_ro_gom_vat_thi_hoi_lai():
    from src.core.doc_dau_vao import CAU_HOI_THUE

    _args, thieu = _cung_cap("vat", {
        "items": [{"name": "Cước", "price": 5_000_000, "qty": 1}],
        "stated_total": 6_500_000,
    }, HOA_DON_BR04)
    assert thieu == CAU_HOI_THUE


def test_vat_da_gom_vat_ma_ghi_de_co_cua_model():
    args, thieu = _cung_cap("vat", {
        "items": [{"name": "Cước", "price": 5_000_000, "qty": 1}],
        "stated_total": 6_500_000, "prices_include_vat": False,
    }, HOA_DON_BR04 + " Giá đã gồm VAT.")
    assert thieu is None
    assert args["prices_include_vat"] is True


def test_quote_model_bia_gia_dau_luc_chot_thi_hoi_lai():
    cau = "Nhà xe chào 12.500.000 đồng, biên lợi nhuận 8%, giá dầu 28.500 đồng/lít"
    _args, thieu = _cung_cap("quote", {
        "carrier_cost": 12_500_000, "current_fuel_price": 28_500,
        "pricing_rule": {"base_margin_pct": 8, "fuel_baseline_price": 26_500},
    }, cau)
    assert thieu and "26.500" in thieu and "không thấy" in thieu


def test_vat_so_viet_bang_chu_bat_duoc_dong_bi_bo():
    cau = ("Soát hoá đơn: cước năm triệu, phụ phí năm trăm nghìn, tổng ghi sáu triệu "
           "rưỡi, giá chưa gồm VAT")
    _args, thieu = _cung_cap("vat", {
        "items": [{"name": "Cước", "price": 5_000_000, "qty": 1}],
        "stated_total": 6_500_000,
    }, cau)
    assert thieu and "500.000" in thieu


def test_vat_gia_da_gom_vat_tinh_dung():
    from src.core.mcp_server import MCPServer

    kq = MCPServer.validate_invoice_total(
        [{"name": "Cước", "price": 5_000_000, "qty": 1},
         {"name": "Phụ phí", "price": 500_000, "qty": 1}],
        6_500_000, prices_include_vat=True,
    )
    assert kq["calculated_total"] == 5_500_000 and kq["difference"] == 1_000_000
    assert kq["lines"][0]["base"] == 4_545_455, "phần trước thuế tách ngược 5.000.000/1,1"


def test_vat_cau_tu_do_A_hoi_lai_dich_danh_so_bi_bo():
    cau = "Hoá đơn có cước 5.000.000 đồng và phụ phí 500.000 đồng, tổng ghi 6.500.000 đồng"
    args, thieu = _cung_cap("vat", {
        "items": [{"name": "Cước", "price": 5_000_000, "qty": 1}],
        "stated_total": 6_500_000,
    }, cau)
    assert thieu and "500.000" in thieu
    assert "hoá đơn" in thieu


def test_quote_A_hoi_lai_khi_bo_gia_dau_luc_chot():
    cau = ("Nhà xe chào 12.500.000 đồng, biên lợi nhuận 8%, giá dầu giờ 28.500 "
           "đồng/lít, lúc chốt bảng giá 26.500 đồng/lít")
    args, thieu = _cung_cap("quote", {
        "carrier_cost": 12_500_000, "pricing_rule": {"base_margin_pct": 8},
        "current_fuel_price": 28_500,
    }, cau)
    assert thieu and "26.500" in thieu and "giá dầu lúc chốt" in thieu


def test_quote_du_so_thi_chay():
    cau = "Nhà xe chào 12.500.000 đồng, biên lợi nhuận 8%, giá dầu 28.500 đồng/lít"
    _args, thieu = _cung_cap("quote", {
        "carrier_cost": 12_500_000, "pricing_rule": {"base_margin_pct": 8},
        "current_fuel_price": 28_500,
    }, cau)
    assert thieu is None


def test_carrier_selection_bom_loi_chao_tu_cau():
    cau = ("Đại An chào 9.400.000 đồng chiết khấu 5% công nợ 15 ngày, Tân Cảng Bắc "
           "chào 10.950.000 đồng chiết khấu 8% công nợ 15 ngày")
    args, thieu = _cung_cap("carrier_selection", {"request": {"origin": "Nội Bài"}}, cau)
    assert thieu is None
    assert [c["name"] for c in args["carriers"]] == ["Đại An", "Tân Cảng Bắc"]
    assert args["request"] == {"origin": "Nội Bài"}, "tuyến do model điền phải giữ nguyên"


def test_carrier_selection_chua_co_loi_chao_thi_van_hoi_lai():
    _args, thieu = _cung_cap("carrier_selection", {}, "nhà xe nào rẻ nhất cho chuyến này")
    assert thieu and "chưa có danh sách nhà xe" in thieu.lower()
