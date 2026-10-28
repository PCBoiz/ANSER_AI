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
    }, HOA_DON_BR04)
    assert thieu is None
    assert len(args["items"]) == 2, "B phải ghi đè bằng hai dòng bóc từ hoá đơn"


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
